"""Lustjinn in the terminal: the Textual app, which is airp's ``Shell``.

The app owns the screen stack (``push_screen`` / ``pop_screen``), the one theme and the few keys
that work on every screen. ``Esc`` pops a screen and quits from the last one; ``?``/``F1`` opens
the help once, never twice; ``Ctrl+C`` quits at once, as the donor's shell did.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType
from textual.screen import Screen

from lustjinn_tui.help import HelpScreen
from lustjinn_tui.stories import StoriesScreen
from lustjinn_tui.theme import DARK, NAME
from lustjinn_tui.view import View


class LustjinnApp(App[None]):
    TITLE = "lustjinn"
    COMMAND_PALETTE_BINDING: ClassVar[str] = "ctrl+p"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(self, *, badge: str = "Local", model_name: str = "") -> None:
        super().__init__()
        self.badge = badge
        self.model_name = model_name
        self.register_theme(DARK)
        self.theme = NAME

    def get_default_screen(self) -> Screen[None]:
        return StoriesScreen()

    # -- the stack ----------------------------------------------------------------------------

    def crumbs(self) -> tuple[str, ...]:
        """The titles of the open views, bottom first."""
        return tuple(s.TITLE for s in self.screen_stack if isinstance(s, View) and s.TITLE)

    def go_back(self) -> None:
        """One screen back; from the last one, out."""
        if len(self.screen_stack) > 1:
            self.pop_screen()
        else:
            self.exit()

    def action_help(self) -> None:
        if any(isinstance(s, HelpScreen) for s in self.screen_stack):
            return
        self.push_screen(HelpScreen())


def main() -> None:
    LustjinnApp().run()


if __name__ == "__main__":
    main()
