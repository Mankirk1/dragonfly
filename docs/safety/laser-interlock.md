# Laser interlock: hazard analysis

Dragonfly's only effector is a visible laser indicator of **1 mW or less (IEC 60825-1 Class 2)**. This page lists what could go wrong and which layer stops it. The software interlock (`src/dragonfly/control/interlock.py`) is one layer. It never replaces the hardware arm switch.

## Layers of protection

1. **Laser class.** Only a module with a marked output of 1 mW or less is fitted. Common 5 mW (Class 3R) modules are not used.
2. **Hardware arm switch** in series with the laser supply. Off means no power to the laser, whatever the software does.
3. **Software interlock**, which allows the laser only when every rule holds (below).
4. **Aim-height cap** at or below 1.2 m, enforced in the aim solver and checked again by the interlock.
5. **Procedure:** a matte backstop, no reflective surfaces in the beam path, a briefing for everyone present, and test T9 passed with nobody present before any trial with a person.

## Software interlock rules

The laser may be on only when **all** of these hold. Anything else means off.

| Rule | Limit | Why |
|---|---|---|
| Switch re-armed | off then on since start-up or since the last fault | The system always starts disarmed |
| No latched fault | fault, watchdog or stale telemetry (> 0.5 s) latches off until re-arm | A transient fault can't be forgotten silently |
| Tracking | LOCKED, or COAST for ≤ 0.5 s | No emission without a confirmed target |
| Range | 0.5 to 6 m | Nothing very close to the unit, nothing beyond the tested area |
| Pan | within ±60° | Inside the radar's field of view only |
| Height | aim height and beam height at the target ≤ 1.2 m | The beam stays below adult shoulder height |
| Valid input | all numbers finite | NaN or infinity is treated as a fault |

## Hazards

| Hazard | Cause | Controls |
|---|---|---|
| Beam at eye height | Bad tilt, wrong aim height in config, bad calibration | Height cap in config validation, the solver and the interlock; tilt servo travel limit; T9 check |
| Laser on with no target | Tracker bug, false track | Requires LOCKED (3 of 5 hits); COAST limited to 0.5 s; HOLD and SEARCH are off |
| Laser on after a crash | Firmware hang | Watchdog latches off; arm switch; telemetry age check |
| Laser on at power-up | Switch left on | Re-arm required after start-up |
| Beam outside the test area | Target at the edge, wrong pan | Pan limit ±60°; range limit 6 m; backstop |
| Reflection | Mirror, glass or shiny surface | Procedure: clear the beam path |
| Wrong laser fitted | 5 mW module bought | Procurement check of the marked output; T9 checks the label |

## Verification

- Unit tests cover every rule and every latch path, with property tests over random input sequences. CI requires 100% branch coverage of the interlock.
- **T9 on the real unit** (arm switch, lock loss, fault, watchdog reset and height cap, with nobody present) must pass and be signed off before any trial with a person. Software tests do not replace T9.
