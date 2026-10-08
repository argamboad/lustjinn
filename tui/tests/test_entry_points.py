"""The ways in: `python -m lustjinn_tui` (what the debugger runs) starts the one `LustjinnApp`."""

import runpy
import sys
from pathlib import Path

import pytest

from lustjinn_tui import config as configuration
from lustjinn_tui.app import LustjinnApp


def test_python_dash_m_starts_the_app_class_the_screens_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Started as `python -m lustjinn_tui.app`, the module ran as `__main__` beside its imported
    copy, and every screen's `isinstance(app, LustjinnApp)` failed (found in VS Code,
    2026-10-08). The package's `__main__` imports the app instead, so there is one class."""
    started: list[LustjinnApp] = []

    def run(self: LustjinnApp) -> None:  # the real one would take over the terminal
        started.append(self)

    monkeypatch.setattr(LustjinnApp, "run", run)
    monkeypatch.setattr(configuration, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["lustjinn_tui", "--server", "http://127.0.0.1:8000"])

    runpy.run_module("lustjinn_tui", run_name="__main__")

    assert len(started) == 1
    assert isinstance(started[0], LustjinnApp)
    assert started[0].config.server == "http://127.0.0.1:8000"
    assert (tmp_path / "config.toml").exists()  # the defaults were written, in the test's folder
