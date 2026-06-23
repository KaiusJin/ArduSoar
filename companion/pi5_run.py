#!/usr/bin/env python3
"""Pi 5 companion runtime — the real-aircraft counterpart of the SITL demos.

Per the team split, the Pi 5 *interprets the uploaded path* and returns data; it
does NOT plan (the ground does) and does NOT fly (ArduPilot does). So this:

  1. connects to the flight controller over MAVLink serial,
  2. uploads the ground-planned route (a native ArduPilot mission),
  3. arms ArduSoar once the aircraft is airborne (DO_AUX_FUNCTION 88 HIGH),
  4. monitors telemetry and writes a periodic status (a stub for the vision /
     return-data the Pi will add).

By default it does NOT arm or change mode — the pilot arms via RC and the FC flies
the AUTO mission; the companion just delivers the route and manages soaring. Use
--arm only for bench testing.

Example (on the Pi, FC on the primary UART):
    python -m companion.pi5_run --conn /dev/serial0 --baud 921600 \
        --route route.waypoints
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from companion import mav  # noqa: E402
from pymavlink import mavutil  # noqa: E402


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", default="/dev/serial0", help="FC serial device (or tcp:... for SITL)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--route", required=True, help="route .waypoints (or .json; .waypoints sibling is used)")
    ap.add_argument("--arm", action="store_true", help="BENCH ONLY: auto AUTO+arm (default: pilot arms via RC)")
    ap.add_argument("--takeoff-alt", type=float, default=80.0, help="enable soaring once above this (m)")
    ap.add_argument("--status", default="/tmp/companion_status.json", help="periodic status file (return-data stub)")
    args = ap.parse_args()

    waypoints = args.route
    if waypoints.endswith(".json"):
        waypoints = waypoints[:-5] + ".waypoints"

    log(f"Connecting to FC at {args.conn} @ {args.baud}")
    m = mav.connect(args.conn, baud=args.baud)
    log(f"Heartbeat from system {m.target_system}")

    mav.set_param(m, "SOAR_ENABLE", 1)               # ensure soaring is enabled
    # let the FC finish booting (mission subsystem ready) before uploading
    m.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=15)
    ok = False
    for attempt in range(4):
        ok, n = mav.upload_qgc_file(m, waypoints)
        if ok:
            break
        log(f"mission upload attempt {attempt + 1} rejected, retrying…")
        time.sleep(3)
    if not ok:
        log("FAILED: FC rejected the mission")
        return 1
    log(f"Route uploaded to FC: {n} items from {os.path.basename(waypoints)}")

    if args.arm:
        log("BENCH MODE: waiting for GPS fix, then AUTO + arm")
        mav.wait_gps_fix(m)
        mav.set_mode(m, "AUTO")
        if not mav.arm(m):
            log("could not arm")
            return 1
    else:
        log("Waiting for the pilot to arm (RC) and the mission to start…")

    soaring_on = False
    last_status = 0.0
    while True:
        try:
            msg = m.recv_match(type=["HEARTBEAT", "GLOBAL_POSITION_INT", "SYS_STATUS", "STATUSTEXT"],
                               blocking=True, timeout=2)
        except (ConnectionError, KeyboardInterrupt):
            break
        if msg is None:
            continue
        t = msg.get_type()
        if t == "STATUSTEXT" and "oar" in str(msg.text):
            log(f"AP: {msg.text}")
        elif t == "GLOBAL_POSITION_INT":
            alt = msg.relative_alt / 1000.0
            armed = m.motors_armed()
            # arm soaring once safely airborne (enabling during the takeoff climb
            # would suppress throttle and stop the climb-out)
            if armed and alt >= args.takeoff_alt and not soaring_on:
                mav.set_soaring_switch(m, 2)
                soaring_on = True
                log(f"Airborne at {alt:.0f} m — ArduSoar enabled (handed off)")
            if time.time() - last_status > 5:
                last_status = time.time()
                status = {"t": time.time(), "mode": m.flightmode, "armed": bool(armed),
                          "alt_m": round(alt, 1), "lat": msg.lat / 1e7, "lon": msg.lon / 1e7,
                          "soaring": soaring_on}
                json.dump(status, open(args.status, "w"))
                log(f"mode={m.flightmode:8s} alt={alt:6.1f} m armed={armed} soaring={soaring_on}")
    log("Exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
