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
   900,
   520
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
     "text": "cellostop~ - polyphonic string pitch detector. See examples/cellostop-demo.maxpat for a working patch.",
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
     "numinlets": 1,
     "numoutlets": 10,
     "outlettype": [
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
      330,
      22
     ],
     "text": "cellostop~"
    }
   },
   {
    "box": {
     "id": "obj-3",
     "maxclass": "comment",
     "text": "Signal outlets 0-3: voice frequency in Hz (0 when silent). 4-7: voice level (linear). Outlet 8: list <midinote> <velocity> <slot>, velocity 0 = note off (a re-attack sends the off, then the on). Outlet 9: replies to [info] (analysis, timing_us, latency_ms). Note-ons arrive roughly 70-90 ms after the physical onset.",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      15,
      170,
      760,
      60
     ]
    }
   }
  ],
  "lines": []
 }
}