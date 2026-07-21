#!/usr/bin/env python3
"""In-flight ground monitor — bidirectional E22 LoRa link.

Connects to the ground-side E22 module (USB-UART adapter).
F405 MAVLink ↔ E22 air link ↔ this module.

What it does:
  - Receives position, altitude, mode, armed state, climb rate from F405
  - Builds a real-time atmospheric map from VFR_HUD climb_rate telemetry
  - Every --eval-interval seconds (default 60), re-runs route_planner and
    uploads only when new route exceeds current score by --upload-threshold (20%)
  - Runs BeliefMap drift + decay locally, reloads belief from new route
  - Writes a status JSON every 5 s for the live dashboard

Replanning approach:
  Event-driven evaluation (AutoSOAR Section 5.1) + improvement threshold.
  AtmoMap fuses observed climb rates at GPS cells (AutoSOAR Section 3.3).
  route_score weights weather prior against observed lift (custom formula).

Usage (real hardware):
    python3 -m companion.ground_monitor --conn /dev/ttyUSB0 --route route.json

Usage (SITL):
    python3 -m companion.ground_monitor --conn tcp:127.0.0.1:5760 \
        --baud 57600 --route planner/routes/route_replanned.json
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from navigation.thermal_prior import BeliefMap, CandidatePoint  # noqa: E402
from pymavlink import mavutil                                     # noqa: E402
from companion import mav as mavlib                              # noqa: E402

REPLAN_OUT  = "/tmp/ground_replan"  # prefix for replanned route files
_ATMO_GRID  = 0.001                 # degrees per cell (~111 m at equator)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class AtmoMap:
    """Real-time atmospheric lift grid built from VFR_HUD climb_rate telemetry.

    Implements M×N independent scalar Kalman filters (AutoSOAR §3.3 Eq. 13–15).
    Each cell: state ŵ (estimated lift m/s) and variance P.
    predict_all() applies the temporal decay (KF predict step, Eq. 13: A×ŵ).
    update() applies a measurement (KF update step, Eq. 14–15).

    Only positive lift (>= min_lift) triggers an update — sinking air is
    glide-phase noise, not a thermal worth routing toward.
    """

    def __init__(self, min_lift: float = 0.3, kf_R: float = 0.5,
                 kf_Q_rate: float = 0.01):
        self._w: dict = {}          # cell key → estimated lift ŵ (m/s)
        self._P: dict = {}          # cell key → KF variance P
        self.min_lift  = min_lift   # m/s threshold: discard weaker obs
        self.R         = kf_R       # measurement noise variance (Eq. 14)
        self.Q_rate    = kf_Q_rate  # process noise variance per second

    def _key(self, lat: float, lon: float):
        return (round(lat / _ATMO_GRID), round(lon / _ATMO_GRID))

    def update(self, lat: float, lon: float, climb_rate: float) -> None:
        if lat == 0.0 and lon == 0.0:
            return
        if climb_rate < self.min_lift:
            return
        k = self._key(lat, lon)
        ŵ = self._w.get(k, climb_rate)   # first obs initialises state
        P = self._P.get(k, 1.0)          # start with high uncertainty
        K = P / (P + self.R)             # Kalman gain
        self._w[k] = ŵ + K * (climb_rate - ŵ)
        self._P[k] = (1.0 - K) * P

    def predict_all(self, dt: float, tau: float = 750.0) -> None:
        """KF predict step: decay all cells toward zero (AutoSOAR §3.3 Eq. 13).

        tau = z_i / W* (Stull 1988: one eddy turnover time).
        A = exp(−dt/tau); Q = kf_Q_rate × dt (process noise grows with time).
        """
        A = math.exp(-dt / tau)
        Q = self.Q_rate * dt
        for k in list(self._P):
            self._w[k] *= A
            self._P[k] = A * A * self._P[k] + Q

    def lookup(self, lat: float, lon: float) -> float:
        """Return KF lift estimate at this position (0.0 if unvisited)."""
        return self._w.get(self._key(lat, lon), 0.0)

    def __len__(self):
        return len(self._w)


def _load_belief(json_path):
    """Load BeliefMap + wind from a route JSON file."""
    if not json_path or not os.path.exists(json_path):
        return None, (0.0, 0.0)
    with open(json_path) as f:
        rj = json.load(f)
    wind = tuple(rj.get("wind") or [0.0, 0.0])
    cands = [CandidatePoint(x=wp["enu_x"], y=wp["enu_y"],
                            prob=wp.get("prob", 0.6),
                            strength_guess=wp.get("w_star", 2.0))
             for wp in rj.get("waypoints", [])]
    return (BeliefMap(cands) if cands else None), wind


def _route_score(json_path: str, atmo_map: AtmoMap, atmo_weight: float = 0.4) -> float:
    """Score a candidate route by combining weather prior with observed lift.

    score_i = prob_i × w_star_i  +  atmo_weight × atmo_map.lookup(wp_i)
    Returns the mean over all waypoints that have lat/lon.

    atmo_weight=0.4 is custom — calibrate from flight data once available.
    """
    if not json_path or not os.path.exists(json_path):
        return 0.0
    try:
        with open(json_path) as f:
            rj = json.load(f)
    except Exception:
        return 0.0
    wps = rj.get("waypoints", [])
    if not wps:
        return 0.0
    total = 0.0
    for wp in wps:
        prior = wp.get("prob", 0.5) * wp.get("w_star", 1.0)
        obs   = atmo_map.lookup(wp.get("lat", 0.0), wp.get("lon", 0.0))
        total += prior + atmo_weight * obs
    return total / len(wps)


def _replan(lat, lon, alt, source="openmeteo"):
    """Re-run route_planner from current aircraft position.

    Returns (waypoints_path, json_path) on success, or (None, None) on failure.
    """
    log(f"Replanning from ({lat:.5f}, {lon:.5f})  alt={alt:.0f} m ...")
    cmd = [
        sys.executable, "-m", "planner.route_planner",
        "--lat",    str(lat),
        "--lon",    str(lon),
        "--source", source,
        "--out",    REPLAN_OUT,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log(f"Replan failed:\n{result.stderr[-400:]}")
            return None, None
        wp  = REPLAN_OUT + ".waypoints"
        jso = REPLAN_OUT + ".json"
        if os.path.exists(wp) and os.path.exists(jso):
            log(f"Replan succeeded → {wp}")
            return wp, jso
        log("Replan ran but output files missing")
        return None, None
    except subprocess.TimeoutExpired:
        log("Replan timed out (>120 s)")
        return None, None
    except Exception as e:
        log(f"Replan error: {e}")
        return None, None


def _upload_route(m, waypoints_path):
    """Upload new mission to F405 through the live MAVLink connection."""
    log(f"Uploading new mission: {os.path.basename(waypoints_path)}")
    for attempt in range(3):
        ok, n = mavlib.upload_qgc_file(m, waypoints_path)
        if ok:
            mavlib.set_current_wp(m, 1)
            log(f"Mission updated: {n} items  (wp reset to 1)")
            return True
        log(f"Upload attempt {attempt + 1} rejected, retrying …")
        time.sleep(3)
    log("Mission upload failed — aircraft continues previous route")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn",   default="/dev/ttyUSB0",
                    help="Ground E22 USB-UART (or tcp:/udp: for SITL)")
    ap.add_argument("--baud",   type=int, default=9600,
                    help="Baud rate — must match E22 module config")
    ap.add_argument("--route",  default=None,
                    help="Initial route JSON for BeliefMap overlay")
    ap.add_argument("--status", default="/tmp/companion_status.json",
                    help="Output status file for live dashboard")
    ap.add_argument("--eval-interval", type=int, default=60,
                    help="Seconds between route evaluations (default 60 s; "
                         "AutoSOAR uses event-driven with similar cadence)")
    ap.add_argument("--upload-threshold", type=float, default=1.20,
                    help="Upload new route only if score > current × threshold "
                         "(default 1.20 = 20%% improvement; AutoSOAR Section 5.1)")
    ap.add_argument("--replan-source",
                    choices=["openmeteo", "soaringmeteo", "terrain"],
                    default="openmeteo",
                    help="Weather source for replanning")
    ap.add_argument("--no-replan", action="store_true",
                    help="Disable automatic replanning (monitor only)")
    args = ap.parse_args()

    # resolve initial route JSON path
    initial_json = None
    if args.route:
        initial_json = (args.route if args.route.endswith(".json")
                        else os.path.splitext(args.route)[0] + ".json")

    belief, wind = _load_belief(initial_json)
    if belief:
        log(f"BeliefMap loaded: {len(belief.candidates)} candidates  wind={wind}")
    else:
        log("No initial route — belief overlay starts empty")

    atmo_map   = AtmoMap()
    curr_score = _route_score(initial_json, atmo_map)

    # connect with auto-retry
    log(f"Connecting to ground E22 at {args.conn} @ {args.baud} …")
    while True:
        try:
            m = mavutil.mavlink_connection(args.conn, baud=args.baud)
            m.wait_heartbeat(timeout=15)
            break
        except Exception as e:
            log(f"Link not up: {e}  retrying in 5 s")
            time.sleep(5)
    log(f"MAVLink link established — aircraft system {m.target_system}")

    if args.no_replan:
        log("Replanning disabled (--no-replan)")
    else:
        log(f"Eval every {args.eval_interval} s  "
            f"upload if score > {args.upload_threshold:.0%}  "
            f"source={args.replan_source}")

    last_status = 0.0
    last_drift  = time.time()
    last_eval   = time.time()
    DRIFT_INTERVAL = 30.0

    alt        = 0.0
    armed      = False
    lat        = 0.0
    lon        = 0.0
    climb_rate = 0.0

    while True:
        try:
            msg = m.recv_match(
                type=["HEARTBEAT", "GLOBAL_POSITION_INT",
                      "VFR_HUD", "SYS_STATUS", "STATUSTEXT"],
                blocking=True, timeout=5)
        except (ConnectionError, KeyboardInterrupt):
            break
        if msg is None:
            pass
        else:
            t = msg.get_type()
            if t == "STATUSTEXT" and "oar" in str(msg.text):
                log(f"AP: {msg.text}")
            elif t == "GLOBAL_POSITION_INT":
                alt   = msg.relative_alt / 1000.0
                lat   = msg.lat / 1e7
                lon   = msg.lon / 1e7
                armed = m.motors_armed()
            elif t == "VFR_HUD":
                climb_rate = msg.climb
                atmo_map.update(lat, lon, climb_rate)

        now = time.time()

        # drift + decay + AtmoMap time-decay
        if armed and now - last_drift >= DRIFT_INTERVAL:
            dt = now - last_drift
            if belief:
                belief.drift(wind, dt)
                belief.decay(dt)
                active = belief.active()
                log(f"drift+decay: {len(active)} active  "
                    f"top_prob={max((c.prob for c in active), default=0):.2f}")
            atmo_map.predict_all(dt)   # KF predict step: decay stale cells
            last_drift = now

        # AutoSOAR §5.2.1 FSM: altitude-critical → force immediate evaluation
        # If below minimum working altitude (400 m AGL, AutoSOAR Table A2),
        # the aircraft is running out of altitude and needs a new route now.
        if armed and lat != 0.0 and alt < 400.0 and not args.no_replan:
            last_eval = 0.0   # force eval on next cycle

        # evaluate + conditional upload (AutoSOAR Section 5.1)
        if (not args.no_replan
                and armed
                and lat != 0.0
                and now - last_eval >= args.eval_interval):
            last_eval = now
            wp_path, json_path = _replan(lat, lon, alt, args.replan_source)
            if wp_path:
                new_score = _route_score(json_path, atmo_map)
                if new_score > curr_score * args.upload_threshold:
                    pct = (new_score / max(curr_score, 1e-9) - 1) * 100
                    log(f"Route improved {curr_score:.3f} → {new_score:.3f} "
                        f"(+{pct:.0f}%)  uploading …")
                    if _upload_route(m, wp_path):
                        belief, wind = _load_belief(json_path)
                        curr_score = new_score
                        if belief:
                            log(f"BeliefMap reloaded: "
                                f"{len(belief.candidates)} candidates  wind={wind}")
                else:
                    log(f"Route score {new_score:.3f} vs current {curr_score:.3f} "
                        f"— below {args.upload_threshold:.0%} threshold, keeping route")

        # status JSON for dashboard
        if now - last_status > 5:
            last_status = now
            belief_snapshot = (
                [{"x": round(c.x), "y": round(c.y),
                  "prob": round(c.prob, 2), "w_star": round(c.strength_guess, 2)}
                 for c in belief.active()]
                if belief else []
            )
            status = {
                "t":          now,
                "mode":       m.flightmode,
                "armed":      bool(armed),
                "alt_m":      round(alt, 1),
                "lat":        lat,
                "lon":        lon,
                "climb_rate": round(climb_rate, 2),
                "soaring":    m.flightmode in ("LOITER", "THERMAL"),
                "belief":     belief_snapshot,
                "atmo_cells": len(atmo_map),
                "curr_score": round(curr_score, 3),
                "next_eval":  round(args.eval_interval
                                    - (now - last_eval)) if not args.no_replan else -1,
            }
            with open(args.status, "w") as f:
                json.dump(status, f)
            eval_in = status["next_eval"]
            log(f"mode={m.flightmode:8s}  alt={alt:6.1f} m  armed={armed}  "
                f"climb={climb_rate:+.1f} m/s  "
                f"belief={len(belief_snapshot)} pts  atmo={len(atmo_map)} cells"
                + (f"  eval_in={eval_in}s" if eval_in >= 0 else ""))

    log("Monitor exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
