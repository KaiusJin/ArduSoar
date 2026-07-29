# MAVLink companion and ground tools

This directory bridges the strategic planner and ArduPilot/ArduSoar.

The weather and terrain layers produce uncertain **lift-opportunity candidates**,
not observed thermal cores. The planner converts those candidates into an
ArduPilot mission. ArduSoar remains responsible for detecting and centring actual
lift encountered by the aircraft.

```text
weather / terrain prior
          ↓
planner route JSON + QGC mission
          ↓
ground upload or Pi 5 companion
          ↓
MAVLink → ArduPilot / ArduSoar
          ↓
telemetry → ground monitor / dashboard
```

## Current mainline files

| File | Role |
|---|---|
| `mav.py` | Shared pymavlink connection, mission, command, mode, parameter, and position helpers |
| `geo.py` | Local ENU metres ↔ latitude/longitude conversion |
| `ground_upload.py` | Upload a generated QGC mission and configure the initial ArduSoar parameters |
| `pi5_run.py` | Pi 5 runtime for mission upload, telemetry/status, and candidate drift/decay |
| `ground_monitor.py` | Ground telemetry monitor with an experimental atmospheric map and conditional replanning |
| `PI5.md` | Pi 5 serial, power, dependency, and bench-test guidance |

## Operational status

- Route generation and QGC serialization have offline tests.
- MAVLink helpers and companion programs compile, but this checkout has no retained
  Pi 5 bench trace, real-flight-controller session, SITL telemetry log, or flight
  log proving the full operational chain.
- Automatic in-flight mission replacement is experimental and should remain
  disabled on hardware until mission/command ACK handling and fault-injection SITL
  tests pass.
- `GLOBAL_POSITION_INT.relative_alt` is relative to home/origin, not terrain AGL.
- A measured airframe polar and pinned ArduPilot version are required before flight.

## Typical workflow

1. Generate a weather/terrain prior and route with `planner.route_planner`.
2. Review the route, altitude frame, terrain, airspace, energy reserve, and parameter
   file.
3. Validate the exact mission and parameters in a pinned ArduPilot SITL build.
4. Upload with `ground_upload.py` or run the Pi 5 path only after bench validation.
5. Retain `.tlog`, DataFlash `.BIN`, parameter snapshots, route, prior, and software
   versions for every acceptance run.

The independent-truth SITL work required to validate the planner is specified in
[`docs/tasks.md`](../docs/tasks.md).
