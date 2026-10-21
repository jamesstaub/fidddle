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
   820
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
     "text": "@profile 0 bass, 1 cello, 2 viola, 3 violin, 4 guitar sets @voices (4, or 6 for guitar), @minfreq and @maxfreq; set those afterwards to override them (custom tunings). Signal outlets 0-5: voice frequency in Hz (0 when silent). 6-11: voice level (linear). Outlet 12: list <midinote> <velocity> <slot>, velocity 0 = note off (a re-attack sends the off, then the on). Outlet 13: replies to [info] (version, profile, analysis, timing_us, latency_ms) and, on the guitar profile after a calibration, [string <slot> <string number> <margin>] about a quarter second after a note-on (1 = highest string; margin 0 = a guess). Note-ons arrive roughly 70-130 ms after the physical onset depending on the window length.",
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
   },
   {
    "box": {
     "id": "obj-10",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      395,
      900,
      105
     ],
     "text": "DEMO AUDIO (folder media/ of the package). The audio files are not included: download OrchideaSOL from the IRCAM Forum (link in the README), then run tools/make_demo_audio.py to render them. 1) Click the speaker icon to turn audio on. 2) Calibration demo: click a profile, click its OPEN STRINGS file, send [calibrate 1], then click [1] to play. The object learns the strings (see outlet 13 in the Max console). For cello and violin the open strings are plucked (pizzicato): a bowed string measures no stiffness. 3) Detector demo: click a POLYPHONY file and [1] to play, and watch the notes in the Max console. Do not click the profile again after calibrating (a new profile removes the calibration); [calibrate clear] removes it so you can compare.",
     "linecount": 7
    }
   },
   {
    "box": {
     "id": "obj-11",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      495,
      120,
      20
     ],
     "text": "profile",
     "linecount": 1
    }
   },
   {
    "box": {
     "id": "obj-12",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      120,
      493,
      70,
      22
     ],
     "text": "profile 1"
    }
   },
   {
    "box": {
     "id": "obj-13",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      200,
      493,
      70,
      22
     ],
     "text": "profile 3"
    }
   },
   {
    "box": {
     "id": "obj-14",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      280,
      493,
      70,
      22
     ],
     "text": "profile 4"
    }
   },
   {
    "box": {
     "id": "obj-15",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      360,
      495,
      300,
      20
     ],
     "text": "1 = cello, 3 = violin, 4 = guitar",
     "linecount": 1
    }
   },
   {
    "box": {
     "id": "obj-16",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      530,
      160,
      20
     ],
     "text": "open strings (for calibration)",
     "linecount": 1
    }
   },
   {
    "box": {
     "id": "obj-17",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      190,
      528,
      230,
      22
     ],
     "text": "open cello-open-strings.wav"
    }
   },
   {
    "box": {
     "id": "obj-18",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      430,
      528,
      230,
      22
     ],
     "text": "open violin-open-strings.wav"
    }
   },
   {
    "box": {
     "id": "obj-19",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      670,
      528,
      230,
      22
     ],
     "text": "open guitar-open-strings.wav"
    }
   },
   {
    "box": {
     "id": "obj-20",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      565,
      160,
      20
     ],
     "text": "polyphony",
     "linecount": 1
    }
   },
   {
    "box": {
     "id": "obj-21",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      190,
      563,
      230,
      22
     ],
     "text": "open cello-polyphony.wav"
    }
   },
   {
    "box": {
     "id": "obj-22",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      430,
      563,
      230,
      22
     ],
     "text": "open violin-polyphony.wav"
    }
   },
   {
    "box": {
     "id": "obj-23",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      670,
      563,
      230,
      22
     ],
     "text": "open guitar-polyphony.wav"
    }
   },
   {
    "box": {
     "id": "obj-24",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      605,
      100,
      20
     ],
     "text": "play / stop",
     "linecount": 1
    }
   },
   {
    "box": {
     "id": "obj-25",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      120,
      603,
      40,
      22
     ],
     "text": "1"
    }
   },
   {
    "box": {
     "id": "obj-26",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      170,
      603,
      50,
      22
     ],
     "text": "stop"
    }
   },
   {
    "box": {
     "id": "obj-27",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      250,
      605,
      100,
      20
     ],
     "text": "calibration",
     "linecount": 1
    }
   },
   {
    "box": {
     "id": "obj-28",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      350,
      603,
      100,
      22
     ],
     "text": "calibrate 1"
    }
   },
   {
    "box": {
     "id": "obj-29",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      460,
      603,
      100,
      22
     ],
     "text": "calibrate 0"
    }
   },
   {
    "box": {
     "id": "obj-30",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      570,
      603,
      120,
      22
     ],
     "text": "calibrate clear"
    }
   },
   {
    "box": {
     "id": "obj-31",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "bang"
     ],
     "patching_rect": [
      120,
      660,
      80,
      22
     ],
     "text": "sfplay~ 1"
    }
   },
   {
    "box": {
     "id": "obj-32",
     "maxclass": "ezdac~",
     "numinlets": 2,
     "numoutlets": 0,
     "patching_rect": [
      120,
      700,
      45,
      45
     ]
    }
   },
   {
    "box": {
     "id": "obj-33",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 0,
     "outlettype": [],
     "patching_rect": [
      450,
      660,
      100,
      22
     ],
     "text": "print notes"
    }
   },
   {
    "box": {
     "id": "obj-34",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 0,
     "outlettype": [],
     "patching_rect": [
      570,
      660,
      100,
      22
     ],
     "text": "print info"
    }
   }
  ],
  "lines": [
   {
    "patchline": {
     "destination": [
      "obj-2",
      0
     ],
     "source": [
      "obj-12",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-2",
      0
     ],
     "source": [
      "obj-13",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-2",
      0
     ],
     "source": [
      "obj-14",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-2",
      0
     ],
     "source": [
      "obj-28",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-2",
      0
     ],
     "source": [
      "obj-29",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-2",
      0
     ],
     "source": [
      "obj-30",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-31",
      0
     ],
     "source": [
      "obj-17",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-31",
      0
     ],
     "source": [
      "obj-18",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-31",
      0
     ],
     "source": [
      "obj-19",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-31",
      0
     ],
     "source": [
      "obj-21",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-31",
      0
     ],
     "source": [
      "obj-22",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-31",
      0
     ],
     "source": [
      "obj-23",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-31",
      0
     ],
     "source": [
      "obj-25",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-31",
      0
     ],
     "source": [
      "obj-26",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-2",
      0
     ],
     "source": [
      "obj-31",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-32",
      0
     ],
     "source": [
      "obj-31",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-32",
      1
     ],
     "source": [
      "obj-31",
      0
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-33",
      0
     ],
     "source": [
      "obj-2",
      12
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-34",
      0
     ],
     "source": [
      "obj-2",
      13
     ]
    }
   }
  ]
 }
}