{
 "patcher": {
  "fileversion": 1,
  "appversion": {
   "major": 9,
   "minor": 1,
   "revision": 3,
   "architecture": "x64",
   "modernui": 1
  },
  "classnamespace": "box",
  "rect": [
   60,
   90,
   1000,
   600
  ],
  "gridsize": [
   15,
   15
  ],
  "boxes": [
   {
    "box": {
     "id": "obj-1",
     "maxclass": "comment",
     "text": "fidddle~ - polyphonic string pitch detector. See examples/fidddle-demo.maxpat for a working patch.",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      10,
      640,
      40
     ]
    }
   },
   {
    "box": {
     "id": "obj-2",
     "maxclass": "newobj",
     "text": "fidddle~",
     "numinlets": 1,
     "numoutlets": 14,
     "outlettype": [
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "",
      ""
     ],
     "patching_rect": [
      15,
      130,
      420,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-3",
     "maxclass": "comment",
     "text": "@profile 0 bass, 1 cello, 2 viola, 3 violin, 4 guitar sets @voices (4, or 6 for guitar), @minfreq and @maxfreq; set those afterwards to override them (custom tunings). Signal outlets 0-5: voice frequency in Hz (0 when silent). 6-11: voice level (linear). Outlet 12: list <midinote> <velocity> <slot>, velocity 0 = note off (a re-attack sends the off, then the on). Outlet 13: replies to [info] (profile, analysis, timing_us, latency_ms). Note-ons arrive roughly 70-130 ms after the physical onset depending on the window length. CALIBRATION: send [calibrate], then pluck each OPEN string on its own and let it ring for about a second (any order, one at a time). Other playing is ignored; chords and fretted notes do not count. The learned per-string inharmonicity, tuning and harmonic balance are applied at once and saved in @calibration. [calibrate done] uses what has been captured, [calibrate cancel] abandons, [calibrate clear] removes it. Progress arrives on the right outlet.",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      170,
      900,
      130
     ]
    }
   }
  ],
  "lines": []
 }
}