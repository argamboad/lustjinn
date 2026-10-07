"""A one-row rule in the border colour (``Draw.Rule`` in the donor). Textual's ``Rule`` carries
margins of its own; this one takes exactly the row it is given."""

from __future__ import annotations

from textual.widget import Widget


class Hairline(Widget):
    DEFAULT_CSS = """
    Hairline { height: 1; width: 1fr; color: $border; }
    """

    def render(self) -> str:
        return "─" * max(1, self.size.width)

    def on_resize(self) -> None:
        self.refresh()
