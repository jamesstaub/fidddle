# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/). See "Releases" in the [README](README.md) for what counts as a breaking change.

## [Unreleased]

## [0.1.0-rc.1] - 2026-10-21

### Added
- Polyphonic pitch detector for string instruments (bass, cello, viola, violin, guitar) with up to 6 voices: Python reference, C++17 core and the Max 9 external `fidddle~`.
- Open-string calibration (`calibrate 1`, `calibrate 0`): measures inharmonicity, tuning and partial levels of each string.
- String identification for the guitar profile (`string <slot> <string number> <margin>` on the info outlet).
- `didddle~`: source separator driven by the pitch tracks.
- `python -m fidddle` command line, benchmarks in `tools/`, help files and reference pages for the Max package.

[Unreleased]: https://github.com/jamesstaub/fidddle/compare/v0.1.0-rc.1...HEAD
