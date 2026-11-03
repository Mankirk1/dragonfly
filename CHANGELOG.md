# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- RD-03D frame decoder, encoder and stream parser
- `dragonfly-log` recorder for raw and decoded radar output
- RD-03D simulator with scenarios S1 to S6 and the T1 grid (`dragonfly-sim`)
- ESP32 firmware skeleton (PlatformIO, FreeRTOS radar and 50 Hz control tasks, watchdog, laser driven LOW at reset)
- Portable C++ core: RD-03D parser, laser interlock and aim solver, with host tests under sanitizers and Python/C++ parity tests
- Laser safety interlock: arm-switch re-arm on start-up and after faults, latched faults, lock/coast, range, pan and height-cap rules; 100% branch coverage enforced in CI
- Aim solver with parallax and height cap, servo calibration tables and command shaping (clamp, dead band, smoothing, rate limit)
- Constant-velocity Kalman filter with polar measurement noise, and a multi-target tracker: optimal gated association, SEARCH/TENTATIVE/LOCKED/COAST/HOLD states, sticky primary selection, maneuver adaptation, coast velocity decay, duplicate-track merging
- Simulated A/B pointing evaluation for scenarios S1 to S6, with regression thresholds
- FFT velocity estimator for the CDM324 channel with learned background (hum rejection), log-parabolic interpolation and a walking-speed smoother
- Velocity scoring against ground truth (B2, T4)
- CDM324 Doppler channel simulator: walker micro-Doppler, rigid targets, mains hum, analog band-pass and 12-bit ADC
- Initial project structure, documentation, CI and security tooling
