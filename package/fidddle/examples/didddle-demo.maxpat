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
   960,
   600
  ],
  "gridsize": [
   15,
   15
  ],
  "boxes": [
   {
    "box": {
     "id": "c0",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      8,
      900,
      34
     ],
     "text": "didddle~ - splits a string signal into one signal per sounding note, plus a residual that holds everything else. voices + residual = the input delayed by the reported latency, so the null meter below should read ~0."
    }
   },
   {
    "box": {
     "id": "adc",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      15,
      70,
      50,
      22
     ],
     "text": "adc~ 1",
     "outlettype": [
      "signal",
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "sf",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 2,
     "patching_rect": [
      120,
      100,
      55,
      22
     ],
     "text": "sfplay~",
     "outlettype": [
      "signal",
      "bang"
     ]
    }
   },
   {
    "box": {
     "id": "open",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      120,
      70,
      45,
      22
     ],
     "text": "open",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "play",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      170,
      70,
      25,
      22
     ],
     "text": "1",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "stop",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      200,
      70,
      25,
      22
     ],
     "text": "0",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "sel",
     "maxclass": "newobj",
     "numinlets": 3,
     "numoutlets": 1,
     "patching_rect": [
      15,
      140,
      90,
      22
     ],
     "text": "selector~ 2 1",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "m1",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      110,
      112,
      25,
      22
     ],
     "text": "1",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "m2",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      140,
      112,
      25,
      22
     ],
     "text": "2",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "cin",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      240,
      70,
      380,
      20
     ],
     "text": "input: 1 = adc~, 2 = sfplay~ (open a cello recording first)"
    }
   },
   {
    "box": {
     "id": "d",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 9,
     "patching_rect": [
      15,
      190,
      420,
      22
     ],
     "text": "didddle~",
     "outlettype": [
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "signal",
      "",
      ""
     ]
    }
   },
   {
    "box": {
     "id": "cattr",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      168,
      700,
      20
     ],
     "text": "attributes: @profile cello/bass/viola/violin/guitar  @latency (ms, 0 = shortest)  @transient (ms)  @voices  @minfreq  @maxfreq"
    }
   },
   {
    "box": {
     "id": "lat0",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      460,
      140,
      70,
      22
     ],
     "text": "latency 0",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "lat250",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      535,
      140,
      80,
      22
     ],
     "text": "latency 250",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "tr0",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      620,
      140,
      80,
      22
     ],
     "text": "transient 0",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "tr80",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      705,
      140,
      85,
      22
     ],
     "text": "transient 80",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "info",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      460,
      170,
      40,
      22
     ],
     "text": "info",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "reset",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      505,
      170,
      40,
      22
     ],
     "text": "reset",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "cal",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      550,
      170,
      65,
      22
     ],
     "text": "calibrate",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "cald",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      620,
      170,
      95,
      22
     ],
     "text": "calibrate done",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "v0",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      216,
      30,
      18
     ],
     "text": "v0"
    }
   },
   {
    "box": {
     "id": "v1",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      85,
      216,
      30,
      18
     ],
     "text": "v1"
    }
   },
   {
    "box": {
     "id": "v2",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      155,
      216,
      30,
      18
     ],
     "text": "v2"
    }
   },
   {
    "box": {
     "id": "v3",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      225,
      216,
      30,
      18
     ],
     "text": "v3"
    }
   },
   {
    "box": {
     "id": "v4",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      295,
      216,
      30,
      18
     ],
     "text": "v4"
    }
   },
   {
    "box": {
     "id": "v5",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      365,
      216,
      30,
      18
     ],
     "text": "v5"
    }
   },
   {
    "box": {
     "id": "vr",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      435,
      216,
      30,
      18
     ],
     "text": "res"
    }
   },
   {
    "box": {
     "id": "s1",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      85,
      262,
      30,
      22
     ],
     "text": "+~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "s2",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      155,
      262,
      30,
      22
     ],
     "text": "+~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "s3",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      225,
      262,
      30,
      22
     ],
     "text": "+~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "s4",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      295,
      262,
      30,
      22
     ],
     "text": "+~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "s5",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      365,
      262,
      30,
      22
     ],
     "text": "+~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "dac",
     "maxclass": "ezdac~",
     "numinlets": 2,
     "numoutlets": 0,
     "patching_rect": [
      15,
      330,
      45,
      45
     ]
    }
   },
   {
    "box": {
     "id": "cdac",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      70,
      345,
      260,
      20
     ],
     "text": "left: sum of voices   right: residual"
    }
   },
   {
    "box": {
     "id": "tin",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      480,
      262,
      80,
      22
     ],
     "text": "tapin~ 3000",
     "outlettype": [
      "tapconnect"
     ]
    }
   },
   {
    "box": {
     "id": "tout",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      480,
      296,
      70,
      22
     ],
     "text": "tapout~ 0",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "neg",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      480,
      330,
      40,
      22
     ],
     "text": "*~ -1",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "nsum",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      480,
      364,
      30,
      22
     ],
     "text": "+~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "nres",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      480,
      398,
      30,
      22
     ],
     "text": "+~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "nabs",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      480,
      432,
      40,
      22
     ],
     "text": "abs~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "npk",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      480,
      466,
      90,
      22
     ],
     "text": "peakamp~ 100",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "nnum",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      480,
      500,
      80,
      22
     ],
     "outlettype": [
      "",
      "bang"
     ]
    }
   },
   {
    "box": {
     "id": "cnull",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      575,
      500,
      360,
      20
     ],
     "text": "null test: |delayed input - voices - residual| (peak, linear)"
    }
   },
   {
    "box": {
     "id": "rl",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 2,
     "patching_rect": [
      560,
      232,
      90,
      22
     ],
     "text": "route latency",
     "outlettype": [
      "",
      ""
     ]
    }
   },
   {
    "box": {
     "id": "unp",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      560,
      262,
      80,
      22
     ],
     "text": "unpack 0 0.",
     "outlettype": [
      "int",
      "float"
     ]
    }
   },
   {
    "box": {
     "id": "nlat",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      650,
      296,
      70,
      22
     ],
     "outlettype": [
      "",
      "bang"
     ]
    }
   },
   {
    "box": {
     "id": "clat",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      725,
      297,
      90,
      20
     ],
     "text": "latency (ms)"
    }
   },
   {
    "box": {
     "id": "pinfo",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      700,
      232,
      85,
      22
     ],
     "text": "print didddle"
    }
   },
   {
    "box": {
     "id": "pnote",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      780,
      200,
      70,
      22
     ],
     "text": "print note"
    }
   },
   {
    "box": {
     "id": "lb",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      580,
      140,
      60,
      22
     ],
     "text": "loadbang",
     "outlettype": [
      "bang"
     ]
    }
   }
  ],
  "lines": [
   {
    "patchline": {
     "source": [
      "d",
      0
     ],
     "destination": [
      "s1",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      1
     ],
     "destination": [
      "s1",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "s1",
      0
     ],
     "destination": [
      "s2",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      2
     ],
     "destination": [
      "s2",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "s2",
      0
     ],
     "destination": [
      "s3",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      3
     ],
     "destination": [
      "s3",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "s3",
      0
     ],
     "destination": [
      "s4",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      4
     ],
     "destination": [
      "s4",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "s4",
      0
     ],
     "destination": [
      "s5",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      5
     ],
     "destination": [
      "s5",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "s5",
      0
     ],
     "destination": [
      "dac",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      6
     ],
     "destination": [
      "dac",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "adc",
      0
     ],
     "destination": [
      "sel",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sf",
      0
     ],
     "destination": [
      "sel",
      2
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "m1",
      0
     ],
     "destination": [
      "sel",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "m2",
      0
     ],
     "destination": [
      "sel",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "open",
      0
     ],
     "destination": [
      "sf",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "play",
      0
     ],
     "destination": [
      "sf",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "stop",
      0
     ],
     "destination": [
      "sf",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sel",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sel",
      0
     ],
     "destination": [
      "tin",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "tin",
      0
     ],
     "destination": [
      "tout",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "tout",
      0
     ],
     "destination": [
      "neg",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "neg",
      0
     ],
     "destination": [
      "nsum",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "s5",
      0
     ],
     "destination": [
      "nsum",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "nsum",
      0
     ],
     "destination": [
      "nres",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      6
     ],
     "destination": [
      "nres",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "nres",
      0
     ],
     "destination": [
      "nabs",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "nabs",
      0
     ],
     "destination": [
      "npk",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "npk",
      0
     ],
     "destination": [
      "nnum",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "lat0",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "lat250",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "tr0",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "tr80",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "info",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "reset",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "cal",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "cald",
      0
     ],
     "destination": [
      "d",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      8
     ],
     "destination": [
      "rl",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "rl",
      0
     ],
     "destination": [
      "unp",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "rl",
      1
     ],
     "destination": [
      "pinfo",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "unp",
      1
     ],
     "destination": [
      "nlat",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "nlat",
      0
     ],
     "destination": [
      "tout",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "d",
      7
     ],
     "destination": [
      "pnote",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "lb",
      0
     ],
     "destination": [
      "info",
      0
     ]
    }
   }
  ]
 }
}