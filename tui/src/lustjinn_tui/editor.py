"""Long text is written in the reader's own editor (``Ui/EditorLauncher.cs``).

A character's card runs to pages, and a terminal composer is not where pages are written. So
the text goes to a temporary file, the app steps aside (``App.suspend``: Textual hands the
terminal back, as the donor's shell did), ``$VISUAL`` or ``$EDITOR`` opens it — ``notepad`` on
Windows, ``nano`` elsewhere when neither is set — and whatever is in the file when the editor
closes comes back. The file is deleted either way.

The launcher is a function the app holds, so the tests hand it one that edits without a
terminal.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lustjinn_tui.app import LustjinnApp

Editor = Callable[["LustjinnApp", str, str], str | None]
"""Edits ``text`` in a file named with ``suffix``; the text after, or None when unchanged."""


def editor_command() -> list[str]:
    chosen = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if chosen:
        return shlex.split(chosen, posix=sys.platform != "win32")
    return ["notepad"] if sys.platform == "win32" else ["nano"]


def editor_name() -> str:
    return Path(editor_command()[0]).name


def edit_in_editor(app: LustjinnApp, text: str, suffix: str) -> str | None:
    """Runs the editor on ``text`` with the app suspended. The donor waited the same way."""
    handle, name = tempfile.mkstemp(prefix="lustjinn-", suffix=suffix, text=True)
    path = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        with app.suspend():
            subprocess.run([*editor_command(), str(path)], check=False)
        after = path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)
    return None if after == text else after
