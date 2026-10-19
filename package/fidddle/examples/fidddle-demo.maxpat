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
     "text": "fidddle~  -  polyphonic string pitch detector. Mono audio in. Set @profile to bass, cello, viola, violin or guitar (0-4): it sets @voices, @minfreq and @maxfreq, which you can then override for custom tunings. Outlets: 6x voice frequency (signal, Hz, 0 = silent), 6x voice level (signal), note list <midinote> <velocity> <slot> (velocity 0 = note off), info replies. Send [info] for the profile, timing and latency, [reset] to rebuild.",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      10,
      900,
      60
     ]
    }
   },
   {
    "box": {
     "id": "obj-2",
     "maxclass": "newobj",
     "text": "adc~ 1",
     "numinlets": 1,
     "numoutlets": 1,
     "outlettype": [
      "signal"
     ],
     "patching_rect": [
      15,
      80,
      60,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-3",
     "maxclass": "newobj",
     "text": "fidddle~ @profile guitar",
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
      140,
      420,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-20",
     "maxclass": "newobj",
     "text": "unpack 0 0 0",
     "numinlets": 1,
     "numoutlets": 3,
     "outlettype": [
      "int",
      "int",
      "int"
     ],
     "patching_rect": [
      460,
      200,
      100,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-30",
     "maxclass": "newobj",
     "text": "print notes",
     "numinlets": 1,
     "numoutlets": 0,
     "outlettype": [],
     "patching_rect": [
      460,
      310,
      90,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-31",
     "maxclass": "newobj",
     "text": "print info",
     "numinlets": 1,
     "numoutlets": 0,
     "outlettype": [],
     "patching_rect": [
      650,
      200,
      80,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-12",
     "maxclass": "message",
     "text": "info",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      650,
      80,
      40,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-13",
     "maxclass": "message",
     "text": "reset",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      700,
      80,
      44,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-14",
     "maxclass": "message",
     "text": "profile cello",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      760,
      80,
      90,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-15",
     "maxclass": "message",
     "text": "profile guitar",
     "numinlets": 2,
     "numoutlets": 1,
     "outlettype": [
      ""
     ],
     "patching_rect": [
      860,
      80,
      90,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-40",
     "maxclass": "newobj",
     "text": "number~",
     "numinlets": 2,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "float"
     ],
     "patching_rect": [
      15,
      220,
      60,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-41",
     "maxclass": "newobj",
     "text": "number~",
     "numinlets": 2,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "float"
     ],
     "patching_rect": [
      85,
      220,
      60,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-42",
     "maxclass": "newobj",
     "text": "number~",
     "numinlets": 2,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "float"
     ],
     "patching_rect": [
      155,
      220,
      60,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-43",
     "maxclass": "newobj",
     "text": "number~",
     "numinlets": 2,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "float"
     ],
     "patching_rect": [
      225,
      220,
      60,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-44",
     "maxclass": "newobj",
     "text": "number~",
     "numinlets": 2,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "float"
     ],
     "patching_rect": [
      295,
      220,
      60,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-45",
     "maxclass": "newobj",
     "text": "number~",
     "numinlets": 2,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "float"
     ],
     "patching_rect": [
      365,
      220,
      60,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-60",
     "maxclass": "comment",
     "text": "voice slot 0..5 frequency (Hz)",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      250,
      260,
      20
     ]
    }
   },
   {
    "box": {
     "id": "obj-21",
     "maxclass": "number",
     "numinlets": 1,
     "numoutlets": 2,
     "outlettype": [
      "",
      "bang"
     ],
     "parameter_enable": 0,
     "patching_rect": [
      460,
      250,
      50,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-24",
     "maxclass": "comment",
     "text": "midinote",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      460,
      275,
      60,
      20
     ]
    }
   },
   {
    "box": {
     "id": "obj-22",
     "maxclass": "number",
     "numinlets": 1,
     "numoutlets": 2,
     "outlettype": [
      "",
      "bang"
     ],
     "parameter_enable": 0,
     "patching_rect": [
      530,
      250,
      50,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-25",
     "maxclass": "comment",
     "text": "velocity",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      530,
      275,
      60,
      20
     ]
    }
   },
   {
    "box": {
     "id": "obj-23",
     "maxclass": "number",
     "numinlets": 1,
     "numoutlets": 2,
     "outlettype": [
      "",
      "bang"
     ],
     "parameter_enable": 0,
     "patching_rect": [
      600,
      250,
      50,
      22
     ]
    }
   },
   {
    "box": {
     "id": "obj-26",
     "maxclass": "comment",
     "text": "slot",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      600,
      275,
      60,
      20
     ]
    }
   }
  ],
  "lines": [
   {
    "patchline": {
     "source": [
      2,
      0
     ],
     "destination": [
      3,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      12
     ],
     "destination": [
      20,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      20,
      0
     ],
     "destination": [
      21,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      20,
      1
     ],
     "destination": [
      22,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      20,
      2
     ],
     "destination": [
      23,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      12
     ],
     "destination": [
      30,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      13
     ],
     "destination": [
      31,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      12,
      0
     ],
     "destination": [
      3,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      13,
      0
     ],
     "destination": [
      3,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      14,
      0
     ],
     "destination": [
      3,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      15,
      0
     ],
     "destination": [
      3,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      0
     ],
     "destination": [
      40,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      1
     ],
     "destination": [
      41,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      2
     ],
     "destination": [
      42,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      3
     ],
     "destination": [
      43,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      4
     ],
     "destination": [
      44,
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      3,
      5
     ],
     "destination": [
      45,
      0
     ]
    }
   }
  ]
 }
}