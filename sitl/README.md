# SITL experiments — reproducing ArduSoar in pure software

**Milestone 1 of the ArduSoar pivot.** This drives ArduPilot's built-in ArduSoar
thermalling controller in SITL (Software-In-The-Loop) over MAVLink, with zero
hardware. It is also the seed of the step-3 weather companion: the same
connect → upload → command → monitor pattern over `pymavlink` is what the
companion will use to push GUIDED waypoints to the real aircraft.

![ArduSoar in SITL](soaring_demo.png)

## Forecast-conditioned SITL integration demo

`run_weather_truth_demo.sh` connects **real weather → route** with an ArduPilot
mission in SITL:

It plans a route from Open-Meteo W\*, then deliberately places simulated thermals
at the selected route points. This checks the planner-to-mission-to-ArduSoar
integration, but cannot validate whether the forecast predicts real thermal cores:

```
hotspot 1 (43.335,-80.490, W*=2.18): LIFT FOUND, +206 m
hotspot 2 (43.335,-80.310, W*=2.39): LIFT FOUND, +224 m
hotspot 3 (43.245,-80.220, W*=2.69): LIFT FOUND, +248 m
-> 3/3 route points intersected the injected SITL lift
```

This is a circular integration fixture, not atmospheric validation. (The sawtooth between
thermals in the plot is the powered glider motoring along low when the next
forecast thermal is farther than its glide range — a spacing/ceiling tuning knob.)

**SITL patch** (`sitl_thermals_scenario5.patch`): adds `SIM_THML_SCENARI=5`, which
loads thermals from `/tmp/sitl_thermals.txt` (one per line: `x_north y_east w r`),
so thermals can be placed at arbitrary (forecast) positions. Apply with
`cd ../../ardupilot && git apply ../autoglide/sitl/sitl_thermals_scenario5.patch && ./waf plane`.

```bash
sitl/run_weather_truth_demo.sh [lat] [lon]    # plan from real weather + fly it
sitl/plot_weather_truth.py                     # render weather_truth_demo.png
sitl/run_terrain_demo.sh [lat] [lon]           # terrain-trigger hotspots -> thermals there -> fly
```

## Milestone 1 — reproduce ArduSoar

The plane cruises an AUTO mission, ArduSoar detects rising air, switches to
**THERMAL** (LOITER) circling (shaded), climbs toward `SOAR_ALT_MAX`, then
returns to AUTO. Retain telemetry and pin the ArduPilot build when re-running this
as an acceptance test.

## One-time setup

ArduPilot lives **outside** this repo (it's large). Built once with:

```bash
git clone --recurse-submodules --depth 1 https://github.com/ArduPilot/ardupilot.git  # → ../../ardupilot
cd ardupilot && ./waf configure --board sitl && ./waf plane
```

Python tooling is in a venv at `../../soar-venv` (Python **3.12** — ArduPilot's
autotest needs ≥3.10):

```bash
python3.12 -m venv soar-venv
soar-venv/bin/pip install pymavlink "empy==3.3.4" pexpect future numpy MAVProxy matplotlib
```

Paths are hard-coded in `run_demo.sh`; adjust if your layout differs.

## Run

```bash
sitl/run_demo.sh            # launches a fresh plane-soaring SITL, runs the demo, tears it down
sitl/plot_soaring.py        # render soaring_demo.png from soaring_log.csv
```

Expected tail:

```
--> Entered THERMAL at 141 m, t=1s
--> Climbed to 335 m (>= SOAR_ALT_MAX-15)
RESULT: PASS
```

## Files

| File | Role |
|---|---|
| `run_soaring_demo.py` | pymavlink driver: upload mission, enable soaring, arm, monitor mode/altitude |
| `run_demo.sh` | orchestrator: fresh SITL up → demo → SITL down |
| `plot_soaring.py` | altitude-vs-time plot with THERMAL segments shaded |
| `soaring_log.csv` / `soaring_demo.png` | last run's data / figure |

## Why not the stock autotest?

`Tools/autotest/autotest.py test.Plane.Soaring` is the authoritative test, but on
macOS its overlapping fence+mission upload races and aborts with
`MISSION_OPERATION_CANCELLED`. We do a single clean mission upload instead.

## Gotcha: enabling soaring headless

`plane-soaring.parm` binds the soaring-enable switch to **RC7 (`RCx_OPTION=88`)**.
In headless SITL that channel boots **LOW**, which latches
`_pilot_desired_state = SOARING_DISABLED` — the plane then just flies the AUTO
mission under power and **never thermals**. A plain `RC_CHANNELS_OVERRIDE` does
**not** reach the aux-switch logic here. The fix is to invoke the aux function
directly:

```python
MAV_CMD_DO_AUX_FUNCTION(param1=88, param2=2)   # 2 = HIGH = auto mode changes
```

The companion (step 3) will rely on this same command to arm soaring on the real
vehicle once it has delivered the aircraft to a forecast hotspot.
