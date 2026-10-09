"""The emoji shortcodes the composer expands: ``:smile:`` becomes the emoji
(``EmojiShortcodes.cs``).

The table is the API's, read once from ``GET /emoji`` and held here for the app (#132): the
client keeps no copy that could drift from the web's. Until it has been read, nothing expands
and nothing is offered — a ``:name:`` stays as typed, which is what it would be anyway for a
name the table lacks. ``suggest`` ranks with the donor's fuzzy matcher and puts an exact name
first.
"""

from __future__ import annotations

from collections.abc import Iterable

from lustjinn_tui.api import Shortcode
from lustjinn_tui.fuzzy import rank

_table: tuple[Shortcode, ...] = ()
_by_name: dict[str, str] = {}


def load(table: Iterable[Shortcode]) -> None:
    """Holds the table the API served, in its order, for every story the app opens."""
    global _table, _by_name
    _table = tuple(table)
    _by_name = {code.name.lower(): code.emoji for code in _table}


def loaded() -> bool:
    return bool(_table)


def table() -> tuple[Shortcode, ...]:
    return _table


def find(name: str | None) -> str | None:
    """The emoji for a name, case folded; None when the table has no such name."""
    return _by_name.get(name.lower()) if name else None


def suggest(query: str | None, limit: int = 8) -> list[Shortcode]:
    """The shortcodes to offer for what was typed after the colon: the table's first few for
    nothing yet, else the fuzzy ranking over names and keywords, an exact name first."""
    if limit <= 0:
        return []
    if not query:
        return list(_table[:limit])
    ranked = rank(_table, query, lambda s: s.search_text)
    exact = next((s for s in ranked if s.name == query.lower()), None)
    if exact is not None:
        return [exact, *[s for s in ranked if s.name != exact.name][: limit - 1]]
    return ranked[:limit]
