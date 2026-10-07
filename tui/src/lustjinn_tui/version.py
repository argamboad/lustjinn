"""The client's version, from the installed package metadata (``AppVersion.cs`` in the donor)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def short() -> str:
    """``0.1.0``, or ``dev`` when the package runs from a checkout without being installed."""
    try:
        return version("lustjinn-tui")
    except PackageNotFoundError:  # pragma: no cover - only outside a uv-managed environment
        return "dev"
