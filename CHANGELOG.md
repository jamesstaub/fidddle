# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/). See "Releases" in the [README](README.md) for what counts as a breaking change.

## [Unreleased]

### Added
- WebAudio version (`web/`): the core as WebAssembly in an AudioWorklet. Per voice frequency, level and gate as audio signals, plus note events and Web MIDI output, from one analysis. Demo page with test melody, microphone and file input, a speed test page, a Docker build, and a web zip in each release. Stable releases publish the demo on GitHub Pages.
- `contrabass` profile (profile number 5) for the orchestral double bass, bowed and plucked. The `bass` profile is the plucked 5-string electric bass.
- Harmonics: above the normal range, up to the top of the harmonics of the instrument (cello 2.7 kHz, viola and violin 4 kHz, guitar 1.8 kHz), a pitch is accepted as a near-pure tone only.
- `orchidea_scenes`: a standalone package and command line that builds polyphonic test scenes with exact truth from OrchideaSOL (kinds, mixed techniques and dynamics, stems, JSON truth, MIDI).
- Optional per-stage timing build of the C++ core (`-DFIDDDLE_STAGE_TIMING=ON`).
- Efficient mode (`@efficient 1` in Max, `--efficient` in the command lines, `quality="efficient"` in Python, `Quality::Efficient` in C++): a preset with a 512-sample hop, a 10-cent search grid, 16 candidates, one refinement pass, a noise floor updated every 4th step and a table for the Gaussian peak shape. About one third of the processor time; note-ons a few ms later; the F1 stays within 0.02 of the full mode on the Orchidea scenes. Calibration and string identification are off in this mode. `info` also replies `mode`.
- `FIDDDLE_NO_STRING_ID` build switch: leaves out string identification completely.
- `tools/eval_profile.py` compares settings and presets on groups of Orchidea scenes.

### Changed
- All per-frame constants of the tracker and the onset flux are defined at the 256-sample reference hop and converted to the hop in use. The full mode is unchanged.
- The candidate separation is at least 25 cents on any grid (it was rounded in grid steps).
- Memory for string identification and the calibrator is only allocated when the profile and the mode need it.
- The analysis only uses the bins below the fit band, and the salience, whitening, candidate and fit stages do less work for the same result: 2.4 to 3.1 times less time per hop (cello 1.0 ms to 0.32 ms at 44.1 kHz). Cello bowed and guitar scenes lose up to 0.02 note F1 from ignoring the partials above the fit band in the salience.

## [0.1.0-rc.1] - 2026-10-21

### Added
- Polyphonic pitch detector for string instruments (bass, cello, viola, violin, guitar) with up to 6 voices: Python reference, C++17 core and the Max 9 external `fidddle~`.
- Open-string calibration (`calibrate 1`, `calibrate 0`): measures inharmonicity, tuning and partial levels of each string.
- String identification for the guitar profile (`string <slot> <string number> <margin>` on the info outlet).
- `didddle~`: source separator driven by the pitch tracks.
- `python -m fidddle` command line, benchmarks in `tools/`, help files and reference pages for the Max package.

[Unreleased]: https://github.com/jamesstaub/fidddle/compare/v0.1.0-rc.1...HEAD
