"""Small text helpers the views share (``Ui/Draw.cs``): an age, a fit to a width, a count."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.cells import cell_len


def age(when: datetime | None, now: datetime | None = None) -> str:
    """``just now``, ``5m ago``, ``3h ago``, ``12d ago``, then the date; ``—`` when unknown."""
    if when is None:
        return "—"
    now = now or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    elapsed = now - when
    if elapsed.total_seconds() < 0:
        return when.strftime("%Y-%m-%d")
    minutes = int(elapsed.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    return when.strftime("%Y-%m-%d")


def fit(text: str, width: int) -> str:
    """The text cut to ``width`` cells with an ellipsis when it had to be cut."""
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    if width == 1:
        return "…"
    kept: list[str] = []
    used = 0
    for char in text:
        size = cell_len(char)
        if used + size > width - 1:
            break
        kept.append(char)
        used += size
    return "".join(kept) + "…"


def pad(text: str, width: int) -> str:
    """The text fitted to ``width`` and padded to it, so columns line up."""
    fitted = fit(text, width)
    return fitted + " " * (width - cell_len(fitted))


def count(n: int, singular: str, plural: str | None = None) -> str:
    """``1 story``, ``2 stories``."""
    word = singular if n == 1 else (plural or singular + "s")
    return f"{n} {word}"
