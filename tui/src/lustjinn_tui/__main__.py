"""`python -m lustjinn_tui`: the same as the `lustjinn-tui` command.

The way in for a debugger. Not `python -m lustjinn_tui.app`: that runs app.py as `__main__`, a
second copy of the module beside the `lustjinn_tui.app` the screens import, so the app would not
be the `LustjinnApp` they look for. Importing it here keeps one copy.
"""

from lustjinn_tui.app import main

main()
