# ArduPilot config — ArduSoar for our glider

A ready-to-load ArduSoar parameter set for the **~2 m electric powered glider**
(Radian-class) with the **Matek ASPD-4525** airspeed sensor, for the FC team to
start from. It's the *soaring + airspeed* layer only — board/serial/motor/servo
wiring and the basic airframe tune (roll/pitch/TECS) are separate.

## Apply

```
# MAVProxy
param load ardusoar_glider.parm
# Mission Planner: Config > Full Parameter List > Load > (write) > reboot
```

## What's a starting value vs what to tune

`ardusoar_glider.parm` tags every line:

- **[TUNE]** — measure on the real airframe. The **drag polar**
  (`SOAR_POLAR_CD0/B/K`) and the **airspeeds** matter most: ArduSoar predicts sink
  from the polar and calls the difference vs measured descent "air going up", so a
  wrong polar means wrong thermal detection/centring.
- **[SITE]** — depends on the field and airspace, especially `SOAR_ALT_MAX` (your
  legal AGL ceiling).
- **[OK]** — sensible defaults, fine to fly as-is.
- **[WIRE]** — depends on FC wiring (airspeed I2C bus, RC switch channel).

## Tuning checklist (first flights)

1. **Airspeed first.** `ARSPD_USE=1`, calibrate on the ground (zero with the pitot
   covered), confirm `ARSP` in the logs tracks GPS groundspeed in still air.
   Set `AIRSPEED_MIN/CRUISE/MAX` from the airframe's stall and best-glide speeds.
2. **Fly the polar.** With the motor off, do steady glides at ~3 airspeeds across
   the range; log `CTUN.E` (or baro climb) and `ARSP`. Fit sink(V) and adjust
   `SOAR_POLAR_CD0/B/K` until ArduPilot's predicted sink matches the measured sink
   (Mission Planner has a soaring polar helper; or iterate by hand).
3. **Altitude band.** Set `SOAR_ALT_MIN/CUTOFF/MAX` to your field + airspace.
   `SOAR_ALT_MAX` must respect the legal AGL limit.
4. **Trigger.** Start `SOAR_VSPEED=0.7`; lower toward 0.5 if it ignores usable
   lift, raise if it latches onto noise.
5. **Verify in the air** the same way SITL did: cruise → it cuts the motor and
   glides above `SOAR_ALT_CUTOFF` → on lift it switches to LOITER and climbs → on
   weak lift / `SOAR_ALT_MAX` it returns to cruise.

## How the companion uses this

Once these are set and `SOAR_ENABLE=1`, our ground route (`planner/`) is uploaded
as a normal ArduPilot mission and the companion arms soaring with
`MAV_CMD_DO_AUX_FUNCTION(88, HIGH)` once airborne — the same handoff validated in
`sitl/`. Note: enable soaring **after** takeoff (enabling it during the takeoff
climb suppresses throttle).
