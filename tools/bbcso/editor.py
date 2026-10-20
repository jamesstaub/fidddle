"""Child process for states.capture: open the plugin editor, save the state when the window closes.

Run as `python -m tools.bbcso.editor OUT.state`. It is a separate process because open_editor() blocks inside native
code, where Ctrl-C kills the interpreter; the parent keeps the terminal and can skip by killing this process.
"""
import sys
import dawdreamer as daw
from . import catalog

engine = daw.RenderEngine(44100, 512)
plugin = engine.make_plugin_processor("bbcso", str(catalog.VST3))
plugin.open_editor()
plugin.save_state(sys.argv[1])
