"""Prior-guided thermal belief (the "upload a thermal map + wind before flight"
strategy).

Before flight you upload candidate thermal *source* locations (a thermal map)
and the wind. Thermals drift downwind, so the predicted *current* position of
each candidate is the source shifted downwind (proposal 4). Each candidate
carries a probability. In flight the glider flies to the best candidate, and
its own measurements confirm (found lift) or disconfirm (searched, nothing)
each one — a simple Bayesian update over a fixed candidate set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CandidatePoint:
    x: float                 # predicted current position (source + wind drift)
    y: float
    prob: float              # belief this is a real, usable thermal (0..1)
    strength_guess: float
    visited: bool = False    # we have searched here
    confirmed: bool = False   # we found and used lift here


def build_prior(uploaded_sources, wind, drift_distance: float = 0.0) -> list:
    """Turn uploaded source points into wind-drifted candidates.

    ``uploaded_sources``: list of (x, y, strength_guess[, prob]).
    ``wind``: object with .wx, .wy (or a (wx, wy) tuple); thermals drift the way
    the wind blows. ``drift_distance``: metres to shift downwind.
    """
    wx, wy = (wind.wx, wind.wy) if hasattr(wind, "wx") else (wind[0], wind[1])
    speed = math.hypot(wx, wy)
    ux, uy = (wx / speed, wy / speed) if speed > 1e-6 else (0.0, 0.0)
    cands = []
    for s in uploaded_sources:
        x, y, strength = s[0], s[1], s[2]
        prob = s[3] if len(s) > 3 else 0.6
        cands.append(CandidatePoint(
            x=x + ux * drift_distance,
            y=y + uy * drift_distance,
            prob=prob,
            strength_guess=strength,
        ))
    return cands


class BeliefMap:
    def __init__(self, candidates: list, min_prob: float = 0.12):
        self.candidates = candidates
        self.min_prob = min_prob

    def active(self):
        """Candidates still worth considering (not used up, not ruled out)."""
        return [c for c in self.candidates if c.prob >= self.min_prob and not c.confirmed]

    def _reachable(self, x: float, y: float, usable: float,
                   glide_ratio: float, wind: tuple, airspeed: float) -> list:
        """Candidates reachable from (x, y) with wind-corrected glide range.

        Effective range = usable × L/D × (groundspeed / airspeed).
        Headwind shrinks the circle; tailwind expands it. Clamped at 0 so a
        strong headwind doesn't produce negative range.
        """
        out = []
        for c in self.active():
            dx, dy = c.x - x, c.y - y
            dist = math.hypot(dx, dy)
            if dist < 1e-3:
                out.append(c)
                continue
            wind_along = (wind[0] * dx + wind[1] * dy) / dist  # >0 tailwind, <0 headwind
            eff_rng = usable * glide_ratio * max(0.0, 1.0 + wind_along / airspeed)
            if dist <= eff_rng:
                out.append(c)
        return out

    def _score(self, c: CandidatePoint, from_pos: tuple, goal: tuple,
               wind: tuple, airspeed: float, d_goal_from: float,
               goal_weight: float) -> float:
        """Score a candidate for the primary objective of flying far.

        thermal_value = prob × W* × headwind_factor
          headwind_factor > 1 when flying INTO headwind to reach c: a strong
          thermal is worth more there because the extra altitude directly buys
          more upwind penetration.

        progress_norm = how far toward the goal this hop moves us, in [0, 1],
          so it cannot overwhelm thermal quality regardless of distances.
        """
        dx, dy = c.x - from_pos[0], c.y - from_pos[1]
        dist = math.hypot(dx, dy)
        wind_along = (wind[0] * dx + wind[1] * dy) / dist if dist > 1e-3 else 0.0
        headwind_factor = 1.0 + max(0.0, -wind_along / airspeed)
        d_goal_c = math.hypot(goal[0] - c.x, goal[1] - c.y)
        progress_norm = max(0.0, (d_goal_from - d_goal_c) / max(d_goal_from, 1.0))
        return c.prob * c.strength_guess * headwind_factor + goal_weight * progress_norm

    def best_target(self, x: float, y: float, altitude: float, goal,
                    glide_ratio: float = 22.0, reserve: float = 80.0,
                    wind: tuple = (0.0, 0.0), airspeed: float = 12.0,
                    goal_weight: float = 0.5) -> CandidatePoint | None:
        """Single-step: pick the best reachable candidate toward the goal."""
        usable = max(0.0, altitude - reserve)
        d_goal_now = math.hypot(goal[0] - x, goal[1] - y)
        reach = self._reachable(x, y, usable, glide_ratio, wind, airspeed)
        if not reach:
            return None
        ahead = [c for c in reach if math.hypot(goal[0] - c.x, goal[1] - c.y) < d_goal_now]
        pool = ahead or reach
        return max(pool, key=lambda c: self._score(
            c, (x, y), goal, wind, airspeed, d_goal_now, goal_weight))

    def plan_chain(self, x: float, y: float, altitude: float, goal,
                   plan_alt: float, glide_ratio: float = 22.0,
                   reserve: float = 80.0, wind: tuple = (0.0, 0.0),
                   airspeed: float = 12.0, goal_weight: float = 0.5,
                   depth: int = 2, discount: float = 0.7) -> CandidatePoint | None:
        """Multi-step lookahead: pick the next waypoint by scoring depth steps ahead.

        After each thermal visit ArduSoar is assumed to climb back to plan_alt
        (it circles until SOAR_ALT_MAX). The next-step score is discounted by
        discount to account for the chance the following thermal doesn't work out.

        depth=2 means: score(C1) + discount × score(best C2 reachable from C1).
        """
        usable = max(0.0, altitude - reserve)
        d_goal_now = math.hypot(goal[0] - x, goal[1] - y)
        reach = self._reachable(x, y, usable, glide_ratio, wind, airspeed)
        if not reach:
            return None
        ahead = [c for c in reach if math.hypot(goal[0] - c.x, goal[1] - c.y) < d_goal_now]
        pool = ahead or reach

        if depth <= 1:
            return max(pool, key=lambda c: self._score(
                c, (x, y), goal, wind, airspeed, d_goal_now, goal_weight))

        best_c, best_total = None, -1e9
        for c in pool:
            s1 = self._score(c, (x, y), goal, wind, airspeed, d_goal_now, goal_weight)
            d_goal_c = math.hypot(goal[0] - c.x, goal[1] - c.y)
            c.confirmed = True
            nxt = self.plan_chain(c.x, c.y, plan_alt, goal, plan_alt,
                                  glide_ratio, reserve, wind, airspeed,
                                  goal_weight, depth - 1, discount)
            c.confirmed = False
            s2 = (self._score(nxt, (c.x, c.y), goal, wind, airspeed, d_goal_c, goal_weight)
                  if nxt else 0.0)
            total = s1 + discount * s2
            if total > best_total:
                best_total, best_c = total, c
        return best_c

    def confirm(self, c: CandidatePoint, x: float, y: float, strength: float) -> None:
        c.confirmed = True
        c.visited = True
        c.prob = min(1.0, c.prob + 0.4)
        c.x, c.y, c.strength_guess = x, y, strength   # refine with the real fix

    def disconfirm(self, c: CandidatePoint) -> None:
        c.visited = True
        c.prob *= 0.1                                  # searched, found nothing

    def drift(self, wind, dt: float) -> None:
        """Advect the (unconfirmed) candidates downwind so they track the
        drifting thermals — the map snapshot is only valid at upload time."""
        wx, wy = (wind.wx, wind.wy) if hasattr(wind, "wx") else (wind[0], wind[1])
        for c in self.candidates:
            if not c.confirmed:
                c.x += wx * dt
                c.y += wy * dt

    def decay(self, dt: float, tau: float = 600.0) -> None:
        """The uploaded map ages: unconfirmed candidates get less trustworthy as
        the flight goes on (a thermal predicted from a stale map may be gone)."""
        f = math.exp(-dt / tau)
        for c in self.candidates:
            if not c.confirmed:
                c.prob *= f
