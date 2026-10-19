"""didddle: opinionated source separation for string instruments.

Takes the pitch tracks that `fidddle` produces and splits a mono signal into one signal per
sounding voice plus a residual. Outputs are complementary by construction
(sum(voices) + residual == input), so a fixed-latency copy of the input cancels them exactly.
"""
