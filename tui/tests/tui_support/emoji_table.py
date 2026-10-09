"""The API's emoji table, read from its data file, as test data: the client keeps no copy of
its own (#132), so the tests take the real one rather than inventing a smaller one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lustjinn_tui.api import Shortcode

SOURCE = Path(__file__).resolve().parents[3] / "src" / "lustjinn" / "emoji.json"


def served() -> list[dict[str, Any]]:
    """What ``GET /emoji`` answers."""
    return json.loads(SOURCE.read_text(encoding="utf-8"))["shortcodes"]


def shortcodes() -> list[Shortcode]:
    return [Shortcode.model_validate(entry) for entry in served()]
