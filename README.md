# ArduSoar

A readable autonomous thermal-soaring simulation & research platform, aligned with
**ArduPilot's ArduSoar controller** ([docs](https://ardupilot.org/plane/docs/soaring.html)).
See [`proposal.md`](proposal.md) for the direction. (Originally inspired by
`sahil-kale/autoglide`; see Attribution below.)

It started as a single-thermal demo (cruise → detect lift → circle → climb) and
has grown into a cross-country soarer that **searches** for off-route thermals,
**captures** them, **hops** between them to a goal, and can fly a **prior-guided**
search from an uploaded thermal map + wind — all behind a **sensor abstraction
layer** ready for real hardware.

## Core idea

```
net climb:        h_dot   = w - v_s        (thermal lift minus sink rate)
reconstructed w:  w_meas  = h_dot + v_s    (what the estimator fits)
thermal model:    w(r)    = W_0 * exp(-r^2 / R_th^2)
```

## Capabilities (in the order they were built)

1. **Single-thermal tracking** — online least-squares Gaussian estimator +
   `Cruise / Probe / Thermal` state machine + L1 guidance + circling. Climbs
   ~300 → 936 m on the nominal thermal.
2. **Figure-8 search** — cruise flies straight, then a periodic figure-8 to sweep
   ~±90 m off the route, so it finds thermals that aren't on the cruise line.
3. **Capture hysteresis** — once it touches a thermal it latches on long enough
   for circling to spiral into the core (no more "drive-by" misses).
4. **Cloud-base departure + cross-country** — climbs to a ceiling, leaves, and
   (refusing to re-enter the *same* thermal) hops to the next one across a
   multi-thermal map to reach a goal.
5. **Sensor + estimation interfaces** — guidance reads `VehicleState` / `Wind` /
   `ThermalMap`, never raw sensors; swap simulated sensors for hardware later.
6. **Prior-guided search** — upload a thermal map + wind → wind-drifted candidate
   points with probabilities → fly to the best reachable one, validate by flying
   (bounded expanding figure-8), **confirm/disconfirm**, and hop to the goal.

## Layout

```
config.py              all tunable constants
main.py                run the basic sim + save plots
glider_model/          kinematic glider (coordinated turn, bank-dependent sink)
thermal_model/         Gaussian thermal + ThermalField (multi-thermal world)
thermal_estimator/     rolling window + regularized least-squares fit
controller/            state machine (capture hysteresis + cloud base),
                       L1 guidance, cruise (figure-8 search), probe, circling
simulator/             simulation loop + plotting + 3D animation
sensors/               sensor abstraction (interfaces + simulated)  -> sensors/README.md
estimation/            state fusion (proposal 5) + wind estimation (proposal 4)
navigation/            thermal map, prior belief, contact detector (proposal 2)
monte_carlo/           randomised robustness analysis  -> monte_carlo/readme.md
tests/                 unit tests
output/                saved figures / animations
```

## Run

```bash
pip install -r requirements.txt

python main.py                       # single-thermal sim + plots
python main.py --video               # also render the 3D soaring GIF
python cross_country.py              # multi-thermal cross-country (hop to a goal)
python prior_guided_search.py        # upload-map + wind, prior-guided search
python -m monte_carlo.run_monte_carlo  # randomised robustness analysis

python -m pytest tests               # run the unit tests
```

## Architecture: from sensors to a plan

The guidance brain never touches a raw sensor. Data flows:

```
sensors (sim or hardware)
   -> SensorSnapshot          raw accel/gyro/GPS/compass/pitot/baro
   -> StateFusion  -> VehicleState   (proposal 5)
   -> WindEstimator -> Wind          (proposal 4)
   -> ThermalMap / BeliefMap         (proposal 2: map, score, reachability, planning)
```

So when the real GPS/IMU/pitot arrive, only the bottom layer changes — guidance,
the map, and the planners are untouched. See [`sensors/README.md`](sensors/README.md).

## Prior-guided search (the upload-map strategy)

Before flight: upload candidate thermal *source* locations + the wind. Thermals
drift downwind, so each candidate's predicted position = source + wind drift. In
flight the glider:

1. flies **straight** to the highest-probability **reachable** candidate (toward the goal),
2. runs a **bounded expanding figure-8** there (3 loops, 35° → 28° → 22°, reach
   ~75 → 130 m, ~120 s) and watches the variometer,
3. on contact → captures, circles, climbs, and **confirms** the candidate,
4. if the search boundary is hit with no lift → **disconfirms** and the map sends
   it straight to the next point (no wasted circling = saves energy).

```bash
python prior_guided_search.py
```

## Scope / what's idealised

Constant airspeed; the prior-guided demo runs on **clean** sensor data (realistic
sensor noise currently fools the `1/(1+mse)` confidence metric into false
captures — the next algorithm task is the chi-squared confidence upgrade).
Thermals are **static** in time; a thermal lifecycle model (grow/shrink/vanish)
is the next world-model task. See `proposal.md` §16–17 for non-goals and the
roadmap.

## Attribution
This project is derived from the original AutoGlide repository by Sahil Kale. The original author is not affiliated with, endorsing, collaborating on, or currently involved in this derivative project.

Original repository: [AutoGlide](https://github.com/sahil-kale/autoglide)
