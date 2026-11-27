# Dragonfly schematic, Rev B: verification

Sheet: `dragonfly_schematic.pdf` (A3, also `.svg` and `.png`).
Source of truth: `dragonfly_netlist.py`, which lists every pin of every part and the net it joins.

## Three layers of checking

1. **Electrical rule checks on the netlist** (`dragonfly_netlist.py`): the circuit-level rules in the table below.
2. **The drawing is checked against the netlist** (`dragonfly_schematic.py`). While it draws, the script records every wire, pin, net label and ground symbol. It then rebuilds the connections from the drawing alone: wires join at shared end points and T-junctions, and wires that only cross do not join. If any net differs from the netlist, or two differently named nets touch, the render stops with an error. To test the check itself, I swapped the RD_TX and RD_RX labels, swapped PAN_PWM and TILT_PWM, broke the wire between the two amplifier stages, and lifted one ground symbol by 0.2 mm. The check caught all four.
3. **CI runs both** in the "Schematic and netlist checks" job on every pull request, so the sheet, the netlist and `firmware/src/board.hpp` can't drift apart unnoticed.

Component values on the sheet are read from the netlist, not typed twice.

## How to re-check by hand

```bash
pip install "schemdraw==0.23" "matplotlib==3.11.2"
cd docs/hardware
python dragonfly_netlist.py . ../../firmware/src/board.hpp   # rule checks; writes netlist + BOM
python dragonfly_schematic.py .                              # redraws the sheet and checks it against the netlist
```

## Rule checks

| Check | Result |
|---|---|
| No single-pin (dangling) nets | PASS, 31 nets |
| Every pin connected | PASS |
| At most one driver per net | PASS |
| Every input has a DC path to a driver (through resistors, switch, trimmer) | PASS |
| Every supply pin has a source (LASER_PWR through S1A) | PASS |
| No ESP32 GPIO sees more than 3.3 V | PASS |
| Doppler ADC on ADC1 (works with Wi-Fi on) | PASS, GPIO36 |
| No ESP32 strapping pins (0, 2, 5, 12, 15) used | PASS |
| GPIO14 protected: it toggles at boot, so R11 sits between it and the arm switch | PASS |
| RD-03D UART series resistors, 10 to 100 Ω per its datasheet | PASS, R12 and R13 |
| Electrolytic polarity (C1, C2) | PASS |
| Laser powered only through S1A, Q1 gate pulled down | PASS |
| Servos on their own supply (J1), not USB | PASS |
| ESP32 pin map equals `firmware/src/board.hpp` (7 pins) | PASS |
| 0.2 to 5 m/s Doppler (32 to 805 Hz) inside the passband (16 Hz to 1.6 kHz) | PASS |
| LM358 bandwidth (needs about 161 kHz, has about 1 MHz) | PASS |
| VREF 1.65 V inside the LM358 input range on 5 V | PASS |
| USB 5 V average load below 500 mA | PASS, about 254 mA (peaks about 530 mA) |

The analog figures are first-order (ideal op-amp) calculations, not a SPICE simulation. Bench measurements on the built board are still the final proof.

## Datasheet facts used

| Part | Fact | Source |
|---|---|---|
| RD-03D | 4 pins: 5V, GND, TX, RX. Supply 4.5 to 5.5 V. IO is 3.3 V. Default 256 000 Bd. Average 92 mA, peak above 200 mA. Ripple under 100 mV. Put 10 to 100 Ω in series on the IO lines | Ai-Thinker Rd-03D Specification V1.0.0 (Tables 1, 2, 4, 5; sections 7.3, 7.4) |
| ESP32 | GPIO36 is input-only, ADC1_CH0. GPIO14 outputs a PWM signal at boot. GPIO16/17 are UART2 | Random Nerd Tutorials ESP32 pinout reference |
| BAT54S | Pin 1 anode of D1, pin 2 cathode of D2, pin 3 common | Standard SOT-23 series pair pinout |
| LM358 | Pins 1 to 3 amp A, 4 GND, 5 to 7 amp B, 8 V+. Input and output reach about V+ minus 1.5 V | Standard dual op-amp pinout |

## Changes in Rev B (after a second review)

| Change | Why |
|---|---|
| R11, 1 kΩ in series with GPIO14 | GPIO14 drives a PWM signal during boot. With the key switch closed it would push straight into ground |
| R12 and R13, 100 Ω on the RD-03D TX and RX | The RD-03D datasheet asks for 10 to 100 Ω in series on its IO |
| C12, 10 µF at the RD-03D supply | The datasheet asks for under 100 mV ripple, with peaks above 200 mA |
| USB current budget added | The average fits a USB 2.0 port; peaks are close to 500 mA, so use a USB 3 port or a supply of at least 1 A if the board browns out |
| Drawing-vs-netlist check and a CI job | So "the sheet is correct" is something a machine checks, not only a claim |
| S1B ground stub | The new sheet check found the stub stopping 0.15 units short of the switch contact. Fixed |

## Changes from the Tinkercad "test #1 DRAGONFLY" circuit

| Tinkercad | Now | Why |
|---|---|---|
| Arduino Uno (U2) | ESP32-WROOM-32 DevKit (U1) | The firmware targets the ESP32; pins follow `board.hpp` |
| No radar | RD-03D (M1) on UART2, GPIO16/17 | Primary tracking sensor |
| Function generator, 160 Hz sine | CDM324 (M2) | 160 Hz is what the CDM324 gives for 1 m/s, so the test signal stood in for the real sensor |
| Generator wired only to C1, not to the amplifier | CDM324 IF → C3 → amplifier | In Tinkercad the signal never reached the op-amp |
| 741 op-amp, V+ unconnected, V− on GND | LM358 on a single 5 V supply | A 741 needs about ±5 V or more and cannot run from one 5 V rail |
| 100 kΩ feedback to pin ON1 (offset null), OUT unconnected | Feedback to OUT through R3 ∥ C4 | ON1 is not the output; the amplifier had no output |
| Filtered output (10 kΩ) to Uno RX (D0) | R6 10 kΩ + C8 10 nF to GPIO36 (ADC) | RX is a serial pin, not an analog input. The 10 kΩ / 10 nF low-pass (1.6 kHz) is kept |
| CFILT_CAP and CCAP_1 each had one lead floating | All capacitors have both ends connected | A floating part does nothing |
| 10 kΩ / 10 kΩ bias from 5 V (2.5 V) | Buffered 1.65 V VREF from 3.3 V (R7, R8, C9, U3A) | Centres the signal in the ESP32 ADC range |
| One gain stage (gain 11 intended) | Two stages, gain about 2 200 to 4 400 | The CDM324 IF is micro- to millivolts; a gain of 11 is too small |
| Servos on D9 and D10, powered from the Uno 5 V | GPIO25 / GPIO26, powered from J1 with C1 and C2 | MG996R stall current (about 2.5 A each) would reset the board on USB power |
| Pots RPOT1 / RPOT2 on A1 / A2 (manual aim) | Removed | The RD-03D now supplies the target position |
| LED + 220 Ω on D2 (laser stand-in) | Class 2 laser M5 switched by Q1 from GPIO27, through key switch S1 | Matches the safety design in `docs/safety/laser-interlock.md` |
| micro:bit, RPOT3 not connected | Removed | Unused |
| No display | SSD1306 OLED (M6) on I²C, GPIO21/22 | In the procurement list; GPIO21/22 still need adding to `board.hpp` |

## Open items

- Add the I²C pins (GPIO21, GPIO22) to `firmware/src/board.hpp`.
- Buy D1 (BAT54S) and R11 to R13 and C12; they are small parts not yet on the procurement list.
- Check that the laser module you buy runs on 5 V (some 1 mW modules are 3 V parts) and draws about 30 mA or less.
- The CDM324 pin order (VCC, IF, GND) is labelled by name. Check it against the silkscreen of the module you receive.
- Set RV1 on the bench: the ESP32 ADC is most linear between about 0.15 V and 2.45 V at 11 dB attenuation, so keep the signal within about ±0.8 V of VREF.
