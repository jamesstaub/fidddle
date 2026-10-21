# Demo audio

The help file of `fidddle~` plays demo files from this folder:
`cello-open-strings.wav`, `cello-polyphony.wav`, `violin-open-strings.wav`, `violin-polyphony.wav`, `guitar-open-strings.wav`, `guitar-polyphony.wav`.

They are not included, because they are made from the OrchideaSOL library (IRCAM Forum licence, which does not allow passing the audio on).
To make them:

1. Download OrchideaSOL 2020 from https://forum.ircam.fr/projects/detail/orchideasol/ (free IRCAM Forum account).
2. Unpack it to `data/_OrchideaSOL2020_release/` in the source repository.
3. Run `python tools/make_demo_audio.py` there, then copy the WAV files from `package/fidddle/media/` into this folder.

Details: see "Build the C++ core and the Max object" in the README.
