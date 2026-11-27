# Dragonfly schematic, Rev A: verification

Sheet: `dragonfly_schematic.pdf` (A3, also `.svg` and `.png`).
Source of truth: `dragonfly_netlist.py`. The drawing script takes every component value and net label from it and stops with an error if the sheet shows a net that is not in the netlist, or misses one that is.

## How to re-check

```bash
pip install schemdraw matplotlib
cd docs/hardware
python dragonfly_netlist.py . ../../firmware/src/board.hpp   # rule checks; writes netlist + BOM
python dragonfly_schematic.py .                              # redraws the sheet (uses the Inter font if installed)
```

## What the checks cover

| Check | Result |
|---|---|
| No single-pin (dangling) nets | PASS, 28 nets |
| Every pin connected | PASS |
| At most one driver per net | PASS |
| Every input has a DC path to a driver (through resistors, switch, trimmer) | PASS |
| Every supply pin has a source (LASER_PWR through S1A) | PASS |
| No ESP32 GPIO sees more than 3.3 V | PASS |
| Doppler ADC on ADC1 (works with Wi-Fi on) | PASS, GPIO36 |
| No ESP32 strapping pins (0, 2, 5, 12, 15) used | PASS |
| Electrolytic polarity (C1, C2) | PASS |
| Laser powered only through S1A, Q1 gate pulled down | PASS |
| Servos on their own supply (J1), not USB | PASS |
| ESP32 pin map equals `firmware/src/board.hpp` (7 pins) | PASS |
| 0.2 to 5 m/s Doppler (32 to 805 Hz) inside the passband (16 Hz to 1.6 kHz) | PASS |
| LM358 bandwidth (needs about 161 kHz, has about 1 MHz) | PASS |
| VREF 1.65 V inside LM358 input range on 5 V | PASS |

These are rule checks on the netlist, not a SPICE simulation. The analog numbers are first-order (ideal op-amp) calculations. Bench measurements on the built board are still the final proof.

## Changes from the Tinkercad "test #1 DRAGONFLY" circuit

| Tinkercad | Rev A | Why |
|---|---|---|
| Arduino Uno (U2) | ESP32-WROOM-32 DevKit (U1) | Firmware targets the ESP32; pins follow `board.hpp` |
| No radar | RD-03D (M1) on UART2, GPIO16/17 | Primary tracking sensor |
| Function generator, 160 Hz sine | CDM324 (M2) | 160 Hz is what the CDM324 gives for 1 m/s, so the test signal stands in for the real sensor |
| Generator wired only to C1, not to the amplifier | CDM324 IF → C3 → amplifier | In Tinkercad the signal never reached the op-amp |
| 741 op-amp, V+ unconnected, V− on GND | LM358 on 5 V single supply | A 741 needs about ±5 V or more and cannot work from one 5 V rail |
| 100 kΩ feedback to pin ON1 (offset null), OUT unconnected | Feedback to OUT through R3 ∥ C4 | ON1 is not the output; the amplifier had no output |
| Filtered output (10 kΩ) to Uno RX (D0) | R6 10 kΩ + C8 10 nF to GPIO36 (ADC) | RX is a serial pin, not an analog input. The 10 kΩ / 10 nF low-pass (1.6 kHz) is kept |
| CFILT_CAP and CCAP_1 each had one lead floating | All capacitors have both ends connected | Floating parts do nothing |
| 10 kΩ / 10 kΩ bias from 5 V (2.5 V) | Buffered 1.65 V VREF from 3.3 V (R7, R8, C9, U3A) | Centres the signal in the ESP32 ADC range |
| One gain stage (gain 11 intended) | Two stages, gain about 2 200 to 4 400 | The CDM324 IF is micro- to millivolts; gain 11 is too small |
| Servos on D9 and D10, powered from Uno 5 V | GPIO25 / GPIO26, powered from J1 with C1, C2 | MG996R stall current (about 2.5 A each) would reset the board on USB power |
| Pots RPOT1 / RPOT2 on A1 / A2 (manual aim) | Removed | The RD-03D now supplies the target position |
| LED + 220 Ω on D2 (laser stand-in) | Class 2 laser M5 switched by Q1 from GPIO27, through key switch S1 | Matches the safety design in `docs/safety/laser-interlock.md` |
| micro:bit, RPOT3 not connected | Removed | Unused |
| No display | SSD1306 OLED (M6) on I²C, GPIO21/22 | In the procurement list; GPIO21/22 still need adding to `board.hpp` |

## Open items

- Add the I²C pins (GPIO21, GPIO22) to `firmware/src/board.hpp`.
- D1 (BAT54S) is not on the procurement list yet; it is a small, cheap addition.
- Check the laser module you buy runs on 5 V (some 1 mW modules are 3 V parts).
- Set RV1 on the bench: the ESP32 ADC is most linear between about 0.15 V and 2.45 V at 11 dB attenuation, so keep the signal within about ±0.8 V of VREF.
