# Ground path planner (our scope)

Per the team split, **we own the ground-side path planning**: turn today's weather
into an ordered route of thermal waypoints toward a goal, and export it as an
**uploadable path**. The Pi 5 interprets the uploaded path (+ vision, + returns
data) and the flight controller flies it — neither is built here.

```
weather prior  ->  plan_route()  ->  ordered lat/lon waypoints  ->  route.json + route.waypoints
   (ours)          greedy chain        (the path we hand off)         (Pi 5 uploads this)
```

## How it plans

Greedy strategic chain reusing `navigation.thermal_prior.BeliefMap` (same scoring
as the dashboard and companion): from home, pick the best reachable candidate
toward the goal, step to it, repeat until the goal vicinity or candidates run out.

- **Local box** (`--prior` or `--source ... --lat --lon`): candidates are a sampled
  field in a small ±2 km box → usually one best thermal (you can glide anywhere
  locally, so a single waypoint is the right answer).
- **Cross-country** (`--region-km N`): candidates are the **real W\* grid cells**
  over an N-km box → a genuine multi-waypoint route that hops thermal-to-thermal.

## Run

```bash
# cross-country route over a 150 km box from live SoaringMeteo
python -m planner.route_planner --source soaringmeteo --lat 43.47 --lon -80.54 --region-km 150

# local best-thermal route, or from a saved prior, or toward a chosen goal
python -m planner.route_planner --source openmeteo --lat 43.47 --lon -80.54
python -m planner.route_planner --prior weather/data/soaringmeteo_prior_43.47_-80.54.json
python -m planner.route_planner --source soaringmeteo --lat 43.47 --lon -80.54 \
       --region-km 150 --goal-lat 44.2 --goal-lon -79.5
```

Outputs land in `planner/routes/` (gitignored):
- `route_*.json` — our rich format: each waypoint with lat/lon + ENU + forecast W\* + probability, plus goal / wind / cloud base.
- `route_*.waypoints` — **standard QGC WPL 110** (home, takeoff, hotspot waypoints) the Pi 5 / Mission Planner can upload directly.

## Interface to confirm with the Pi 5 / FC team

This is the hand-off boundary — pin these down so the path is consumable as-is:

1. **Path format** — does the Pi 5 want the QGC `.waypoints` file, the rich
   `route.json`, or another shape? Should each waypoint carry extra hints
   (forecast W\*, loiter/dwell, what to do on arrival)?
2. **Return data** — what does the Pi 5 send back (e.g. vision-confirmed thermal
   positions)? If we get it, we can re-plan: feed confirmations into the belief map
   and emit an updated route.
3. **Flight controller** — the hand-off assumes **ArduPilot / ArduSoar** (the
   project pivot). Confirm "we write and tune the FC" means tuning ArduPilot
   params, not custom firmware — the route/handoff interface depends on it.
