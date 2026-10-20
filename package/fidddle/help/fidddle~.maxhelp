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
     "text": "@profile 0 bass, 1 cello, 2 viola, 3 violin, 4 guitar sets @voices (4, or 6 for guitar), @minfreq and @maxfreq; set those afterwards to override them (custom tunings). Signal outlets 0-5: voice frequency in Hz (0 when silent). 6-11: voice level (linear). Outlet 12: list <midinote> <velocity> <slot>, velocity 0 = note off (a re-attack sends the off, then the on). Outlet 13: replies to [info] (profile, analysis, timing_us, latency_ms) and, on the guitar profile after a calibration, [string <slot> <string number> <margin>] about a quarter second after a note-on (1 = highest string; margin 0 = a guess). Note-ons arrive roughly 70-130 ms after the physical onset depending on the window length.",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      170,
      900,
      90
     ]
    }
   },
   {
    "box": {
     "id": "obj-4",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "text": "HOW TO USE [calibrate 1]. Calibration teaches fidddle~ the real strings of your instrument, which makes chords and plucked notes more reliable, especially on guitar and bass. 1) Turn audio on and make sure your instrument reaches fidddle~. 2) Send the message [calibrate 1]. 3) Pluck each OPEN string on its own and let it ring for about a second: one string at a time, in any order. Do not bow: a bowed string measures no inharmonicity. Chords, overlapping notes and fretted notes are ignored, so only isolated open strings count. Other playing in between does no harm, but it does not help either. 4) Each time a string is captured the right outlet sends [calibrate string <index> <Hz> <cents> <B>] (index 0 is the lowest string). 5) When every string has been captured it finishes by itself ([calibrate complete], then [calibrate applied]) and the result starts working at once. You do not have to play every string: [calibrate 0] finishes early with the strings captured so far, and the others keep the profile's defaults. [calibrate cancel] abandons the session and [calibrate clear] removes a calibration. The result is stored in the @calibration attribute and saved with the patch, so you only calibrate once per instrument. Changing @profile discards it.",
     "patching_rect": [
      15,
      270,
      900,
      110
     ]
    }
   }
  ],
  "lines": []
 }
}