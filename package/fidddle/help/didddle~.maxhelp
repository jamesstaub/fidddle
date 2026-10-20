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
        "rect": [ 134.0, 172.0, 960.0, 600.0 ],
        "boxes": [
            {
                "box": {
                    "id": "c0",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 15.0, 8.0, 1116.0, 20.0 ],
                    "text": "didddle~ - splits a string signal into one signal per sounding note, plus a residual that holds everything else. voices + residual = the input delayed by the reported latency, so the null meter below should read ~0."
                }
            },
            {
                "box": {
                    "id": "adc",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 15.0, 70.0, 50.0, 22.0 ],
                    "text": "adc~ 1"
                }
            },
            {
                "box": {
                    "id": "sf",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 2,
                    "outlettype": [ "signal", "bang" ],
                    "patching_rect": [ 120.0, 100.0, 55.0, 22.0 ],
                    "text": "sfplay~"
                }
            },
            {
                "box": {
                    "id": "open",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 120.0, 70.0, 45.0, 22.0 ],
                    "text": "open"
                }
            },
            {
                "box": {
                    "id": "play",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 170.0, 70.0, 25.0, 22.0 ],
                    "text": "1"
                }
            },
            {
                "box": {
                    "id": "stop",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 200.0, 70.0, 25.0, 22.0 ],
                    "text": "0"
                }
            },
            {
                "box": {
                    "id": "sel",
                    "maxclass": "newobj",
                    "numinlets": 3,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 15.0, 140.0, 90.0, 22.0 ],
                    "text": "selector~ 2 1"
                }
            },
            {
                "box": {
                    "id": "m1",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 110.0, 112.0, 25.0, 22.0 ],
                    "text": "1"
                }
            },
            {
                "box": {
                    "id": "m2",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 140.0, 112.0, 25.0, 22.0 ],
                    "text": "2"
                }
            },
            {
                "box": {
                    "id": "cin",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 240.0, 70.0, 380.0, 20.0 ],
                    "text": "input: 1 = adc~, 2 = sfplay~ (open a cello recording first)"
                }
            },
            {
                "box": {
                    "id": "d",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 9,
                    "outlettype": [ "signal", "signal", "signal", "signal", "signal", "signal", "signal", "", "" ],
                    "patching_rect": [ 15.0, 190.0, 420.0, 22.0 ],
                    "saved_object_attributes": {
                        "confirm": 6,
                        "latency": 0.0,
                        "maxfreq": 1000.0,
                        "minfreq": 60.0,
                        "minlevel": -58.0,
                        "profile": 1,
                        "release": 0.0,
                        "retrigger": 10.0,
                        "transient": 80.0,
                        "voices": 4
                    },
                    "text": "didddle~"
                }
            },
            {
                "box": {
                    "id": "cattr",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 240.0, 101.0, 700.0, 20.0 ],
                    "text": "attributes: @profile cello/bass/viola/violin/guitar  @latency (ms, 0 = shortest)  @transient (ms)  @voices  @minfreq  @maxfreq"
                }
            },
            {
                "box": {
                    "id": "lat0",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 231.0, 129.0, 70.0, 22.0 ],
                    "text": "latency 0"
                }
            },
            {
                "box": {
                    "id": "lat250",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 306.0, 129.0, 80.0, 22.0 ],
                    "text": "latency 250"
                }
            },
            {
                "box": {
                    "id": "tr0",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 475.0, 129.0, 80.0, 22.0 ],
                    "text": "transient 0"
                }
            },
            {
                "box": {
                    "id": "tr80",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 560.0, 129.0, 85.0, 22.0 ],
                    "text": "transient 80"
                }
            },
            {
                "box": {
                    "id": "info",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 460.0, 170.0, 40.0, 22.0 ],
                    "text": "info"
                }
            },
            {
                "box": {
                    "id": "reset",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 505.0, 170.0, 40.0, 22.0 ],
                    "text": "reset"
                }
            },
            {
                "box": {
                    "id": "cal",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 550.0, 170.0, 65.0, 22.0 ],
                    "text": "calibrate 1"
                }
            },
            {
                "box": {
                    "id": "cald",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 620.0, 170.0, 95.0, 22.0 ],
                    "text": "calibrate 0"
                }
            },
            {
                "box": {
                    "id": "v0",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 15.0, 216.0, 30.0, 20.0 ],
                    "text": "v0"
                }
            },
            {
                "box": {
                    "id": "v1",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 85.0, 216.0, 30.0, 20.0 ],
                    "text": "v1"
                }
            },
            {
                "box": {
                    "id": "v2",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 155.0, 216.0, 30.0, 20.0 ],
                    "text": "v2"
                }
            },
            {
                "box": {
                    "id": "v3",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 225.0, 216.0, 30.0, 20.0 ],
                    "text": "v3"
                }
            },
            {
                "box": {
                    "id": "v4",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 295.0, 216.0, 30.0, 20.0 ],
                    "text": "v4"
                }
            },
            {
                "box": {
                    "id": "v5",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 365.0, 216.0, 30.0, 20.0 ],
                    "text": "v5"
                }
            },
            {
                "box": {
                    "id": "vr",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 435.0, 216.0, 30.0, 20.0 ],
                    "text": "res"
                }
            },
            {
                "box": {
                    "id": "s1",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 26.0, 252.0, 35.0, 22.0 ],
                    "text": "+~"
                }
            },
            {
                "box": {
                    "id": "s2",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 96.0, 252.0, 35.0, 22.0 ],
                    "text": "+~"
                }
            },
            {
                "box": {
                    "id": "s3",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 166.0, 252.0, 35.0, 22.0 ],
                    "text": "+~"
                }
            },
            {
                "box": {
                    "id": "s4",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 236.0, 252.0, 35.0, 22.0 ],
                    "text": "+~"
                }
            },
            {
                "box": {
                    "id": "s5",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 306.0, 252.0, 35.0, 22.0 ],
                    "text": "+~"
                }
            },
            {
                "box": {
                    "id": "dac",
                    "maxclass": "ezdac~",
                    "numinlets": 2,
                    "numoutlets": 0,
                    "patching_rect": [ 21.0, 443.0, 45.0, 45.0 ]
                }
            },
            {
                "box": {
                    "id": "cdac",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 70.0, 345.0, 260.0, 20.0 ],
                    "text": "left: sum of voices   right: residual"
                }
            },
            {
                "box": {
                    "id": "tin",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "tapconnect" ],
                    "patching_rect": [ 480.0, 262.0, 80.0, 22.0 ],
                    "text": "tapin~ 3000"
                }
            },
            {
                "box": {
                    "id": "tout",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 480.0, 296.0, 70.0, 22.0 ],
                    "text": "tapout~ 0"
                }
            },
            {
                "box": {
                    "id": "neg",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 480.0, 330.0, 40.0, 22.0 ],
                    "text": "*~ -1"
                }
            },
            {
                "box": {
                    "id": "nsum",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 480.0, 364.0, 30.0, 22.0 ],
                    "text": "+~"
                }
            },
            {
                "box": {
                    "id": "nres",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 480.0, 398.0, 30.0, 22.0 ],
                    "text": "+~"
                }
            },
            {
                "box": {
                    "id": "nabs",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 480.0, 432.0, 40.0, 22.0 ],
                    "text": "abs~"
                }
            },
            {
                "box": {
                    "id": "npk",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "float" ],
                    "patching_rect": [ 480.0, 466.0, 90.0, 22.0 ],
                    "text": "peakamp~ 100"
                }
            },
            {
                "box": {
                    "format": 6,
                    "id": "nnum",
                    "maxclass": "flonum",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": [ "", "bang" ],
                    "parameter_enable": 0,
                    "patching_rect": [ 480.0, 500.0, 80.0, 22.0 ]
                }
            },
            {
                "box": {
                    "id": "cnull",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 575.0, 500.0, 360.0, 20.0 ],
                    "text": "null test: |delayed input - voices - residual| (peak, linear)"
                }
            },
            {
                "box": {
                    "id": "rl",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 2,
                    "outlettype": [ "", "" ],
                    "patching_rect": [ 560.0, 232.0, 90.0, 22.0 ],
                    "text": "route latency"
                }
            },
            {
                "box": {
                    "id": "unp",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": [ "int", "float" ],
                    "patching_rect": [ 560.0, 262.0, 80.0, 22.0 ],
                    "text": "unpack 0 0."
                }
            },
            {
                "box": {
                    "format": 6,
                    "id": "nlat",
                    "maxclass": "flonum",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": [ "", "bang" ],
                    "parameter_enable": 0,
                    "patching_rect": [ 650.0, 296.0, 70.0, 22.0 ]
                }
            },
            {
                "box": {
                    "id": "clat",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 725.0, 297.0, 90.0, 20.0 ],
                    "text": "latency (ms)"
                }
            },
            {
                "box": {
                    "id": "pinfo",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 700.0, 232.0, 85.0, 22.0 ],
                    "text": "print didddle"
                }
            },
            {
                "box": {
                    "id": "pnote",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [ 366.0, 426.0, 70.0, 22.0 ],
                    "text": "print note"
                }
            },
            {
                "box": {
                    "id": "lb",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "bang" ],
                    "patching_rect": [ 725.0, 176.0, 60.0, 22.0 ],
                    "text": "loadbang"
                }
            }
        ],
        "lines": [
            {
                "patchline": {
                    "destination": [ "sel", 1 ],
                    "source": [ "adc", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "source": [ "cal", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "source": [ "cald", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "dac", 1 ],
                    "order": 1,
                    "source": [ "d", 6 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "nres", 1 ],
                    "order": 0,
                    "source": [ "d", 6 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "pnote", 0 ],
                    "source": [ "d", 7 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "rl", 0 ],
                    "source": [ "d", 8 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s1", 1 ],
                    "source": [ "d", 1 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s1", 0 ],
                    "source": [ "d", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s2", 1 ],
                    "source": [ "d", 2 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s3", 1 ],
                    "source": [ "d", 3 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s4", 1 ],
                    "source": [ "d", 4 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s5", 1 ],
                    "source": [ "d", 5 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "source": [ "info", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "source": [ "lat0", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "source": [ "lat250", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "info", 0 ],
                    "source": [ "lb", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "sel", 0 ],
                    "source": [ "m1", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "sel", 0 ],
                    "source": [ "m2", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "npk", 0 ],
                    "source": [ "nabs", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "nsum", 0 ],
                    "source": [ "neg", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "tout", 0 ],
                    "source": [ "nlat", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "nnum", 0 ],
                    "source": [ "npk", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "nabs", 0 ],
                    "source": [ "nres", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "nres", 0 ],
                    "source": [ "nsum", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "sf", 0 ],
                    "source": [ "open", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "sf", 0 ],
                    "source": [ "play", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "source": [ "reset", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "pinfo", 0 ],
                    "source": [ "rl", 1 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "unp", 0 ],
                    "source": [ "rl", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s2", 0 ],
                    "source": [ "s1", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s3", 0 ],
                    "source": [ "s2", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s4", 0 ],
                    "source": [ "s3", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "s5", 0 ],
                    "source": [ "s4", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "dac", 0 ],
                    "order": 1,
                    "source": [ "s5", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "nsum", 1 ],
                    "order": 0,
                    "source": [ "s5", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "order": 1,
                    "source": [ "sel", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "tin", 0 ],
                    "order": 0,
                    "source": [ "sel", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "sel", 2 ],
                    "source": [ "sf", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "sf", 0 ],
                    "source": [ "stop", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "tout", 0 ],
                    "source": [ "tin", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "neg", 0 ],
                    "source": [ "tout", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "source": [ "tr0", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "d", 0 ],
                    "source": [ "tr80", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "nlat", 0 ],
                    "source": [ "unp", 1 ]
                }
            }
        ],
        "autosave": 0
    }
}