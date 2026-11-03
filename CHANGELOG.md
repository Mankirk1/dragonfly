# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- RD-03D frame decoder, encoder and stream parser
- `dragonfly-log` recorder for raw and decoded radar output
- RD-03D simulator with scenarios S1 to S6 and the T1 grid (`dragonfly-sim`)
- FFT velocity estimator for the CDM324 channel with learned background (hum rejection), log-parabolic interpolation and a walking-speed smoother
- Velocity scoring against ground truth (B2, T4)
- CDM324 Doppler channel simulator: walker micro-Doppler, rigid targets, mains hum, analog band-pass and 12-bit ADC
- Initial project structure, documentation, CI and security tooling
