# Dragonfly firmware

ESP32 firmware, built with [PlatformIO](https://platformio.org/) and the Arduino framework.

```
firmware/
  lib/dragonfly_core/src/   portable algorithms: no hardware calls, no heap allocation
  src/                      board pins, FreeRTOS tasks, drivers
  test/host/                unit tests for the core, run on a PC
  tools/core_cli.cpp        wrapper used to check the core against the Python reference
```

## Build and flash

```bash
pip install platformio
pio run -d firmware                 # build
pio run -d firmware -t upload       # flash a connected ESP32
pio device monitor -b 460800        # telemetry
```

## Test on a PC

```bash
cmake -S firmware -B build/firmware -DSANITIZE=ON
cmake --build build/firmware
ctest --test-dir build/firmware --output-on-failure
DRAGONFLY_CORE_CLI=build/firmware/core_cli pytest tests/test_parity.py
```

The parity tests feed the same random inputs to the Python reference and to the C++ core, and fail if their answers differ.

## Current state

| Part | Status |
|---|---|
| RD-03D parser | Ported, parity-tested |
| Laser interlock | Ported, parity-tested |
| Aim solver and servo shaping | Ported, unit-tested |
| FFT velocity, Kalman tracker | Not yet ported: the system stays in SEARCH and **the laser cannot switch on** |
| Pins | Placeholders in `src/board.hpp` until the wiring is fixed |

## Safety

The laser output is driven LOW as the very first action after reset, and the interlock starts disarmed. A watchdog resets the chip if a task hangs, which also drives the laser pin LOW. None of this replaces the hardware arm switch, a Class 2 laser, or test T9. See [docs/safety/laser-interlock.md](../docs/safety/laser-interlock.md).
