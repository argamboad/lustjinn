"""Lustjinn in the terminal: the Textual app, which is airp's ``Shell``.

The app owns the screen stack (``push_screen`` / ``pop_screen``), the one theme, the API client
and the few keys that work on every screen. ``Esc`` pops a screen and quits from the last one;
``?``/``F1`` opens the help once, never twice; ``Ctrl+C`` quits at once, as the donor's shell did.

Before anything else the app knocks on the server (``WakingScreen``) and, without a token, asks
the reader to sign in (``SignInScreen``). A call that meets a ``401`` later sends them back to
sign in with a note saying why; one that cannot reach the server sends them back to the lamp.
"""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable
from typing import ClassVar

from textual import events
from textual.app import App
from textual.binding import Binding, BindingType
from textual.command import Provider
from textual.screen import Screen
from textual.widgets import Input, TextArea

from lustjinn_tui import config as configuration
from lustjinn_tui.api import Api, ApiError, SignedOutError, UnreachableError
from lustjinn_tui.config import Config, TokenStore
from lustjinn_tui.dialect import Dialect, dialect_of
from lustjinn_tui.editor import Editor, edit_in_editor
from lustjinn_tui.help import HelpScreen
from lustjinn_tui.library import LibraryScreen
from lustjinn_tui.palette import LustjinnCommands
from lustjinn_tui.search import SearchScreen
from lustjinn_tui.signin import SignInScreen
from lustjinn_tui.status import Kind
from lustjinn_tui.stories import StoriesScreen
from lustjinn_tui.theme import DARK, NAME
from lustjinn_tui.view import View
from lustjinn_tui.waking import WakingScreen


class LustjinnApp(App[None]):
    TITLE = "lustjinn"
    COMMAND_PALETTE_BINDING: ClassVar[str] = "ctrl+p"

    COMMANDS: ClassVar[set[type[Provider] | Callable[[], type[Provider]]]] = {LustjinnCommands}
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+p,colon", "command_palette", "Commands", show=False, priority=True),
        Binding("ctrl+f", "search_all", "Search every story", show=False, priority=True),
    ]

    def __init__(
        self,
        config: Config,
        api: Api,
        *,
        wake_waits: tuple[float, ...] = WakingScreen.WAITS,
    ) -> None:
        super().__init__()
        self.config = config
        self.api = api
        self.badge = config.badge
        self.model_name = ""
        self.wake_waits = wake_waits
        self.editor: Editor = edit_in_editor  # the tests hand in one that needs no terminal
        self.last_key = ""
        self.dialect: Dialect = dialect_of(config.keyboard)
        self.register_theme(DARK)
        self.theme = NAME

    def get_default_screen(self) -> Screen[None]:
        return StoriesScreen()

    def on_key(self, event: events.Key) -> None:
        self.last_key = event.key

    def on_mount(self) -> None:
        self.push_screen(WakingScreen())

    async def on_unmount(self) -> None:
        await self.api.aclose()

    # -- the gate -----------------------------------------------------------------------------

    @property
    def gate_open(self) -> bool:
        """Signed in, with neither the lamp nor the sign-in screen on the stack: the screens
        may call the API."""
        return self.api.signed_in and not any(
            isinstance(s, WakingScreen | SignInScreen) for s in self.screen_stack
        )

    def woke(self) -> None:
        """The server answered: on to the stories, or to sign in first."""
        if isinstance(self.screen, WakingScreen):
            self.pop_screen()
        if not self.api.signed_in:
            self.push_screen(SignInScreen())

    def signed_in(self) -> None:
        if isinstance(self.screen, SignInScreen):
            self.pop_screen()

    def lost(self, note: str) -> None:
        """The server stopped answering: back to the lamp, unless it is already showing."""
        if not isinstance(self.screen, WakingScreen):
            self.push_screen(WakingScreen(note))

    def signed_out(self, note: str) -> None:
        """A 401 anywhere: forget the token and ask again, saying why."""
        self.api.sign_out()
        if not isinstance(self.screen, SignInScreen):
            self.push_screen(SignInScreen(note))

    async def call[T](self, label: str, work: Awaitable[T]) -> T | None:
        """Run ``work`` behind the spinner (the donor's ``Run``). A refusal becomes a status in
        red, a 401 the sign-in screen, an unreachable server the lamp; those return ``None``."""
        screen = self.screen
        line = screen.status_line if isinstance(screen, View) else None
        if line is not None:
            line.busy(label)
        try:
            return await work
        except SignedOutError as refused:
            self.signed_out(refused.detail)
        except UnreachableError:
            self.lost(f"The server stopped answering while {label.lower()}.")
        except ApiError as refused:
            if isinstance(screen, View):
                screen.status(refused.detail, Kind.ERROR)
        finally:
            if line is not None:
                line.idle()
        return None

    # -- the stack ----------------------------------------------------------------------------

    def crumbs(self) -> tuple[str, ...]:
        """The titles of the open views, bottom first."""
        return tuple(s.title for s in self.screen_stack if isinstance(s, View) and s.title)

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

    def action_search_all(self) -> None:
        """``Ctrl+F`` anywhere past the gate: search across every story, once."""
        if not self.gate_open or any(isinstance(s, SearchScreen) for s in self.screen_stack):
            return
        self.push_screen(SearchScreen())

    def action_library(self) -> None:
        if not self.gate_open or any(isinstance(s, LibraryScreen) for s in self.screen_stack):
            return
        self.push_screen(LibraryScreen())

    def action_command_palette(self) -> None:
        """``Ctrl+P`` or ``:``, but not while a text field would rather have the colon."""
        focused = self.focused
        if isinstance(focused, Input | TextArea) and self.last_key == "colon":
            focused.insert_text_at_cursor(":") if isinstance(focused, Input) else focused.insert(
                ":"
            )
            return
        super().action_command_palette()


def main() -> None:
    parser = argparse.ArgumentParser(prog="lustjinn-tui", description="Lustjinn in the terminal.")
    parser.add_argument("--server", help=f"the API's URL (default: {configuration.DEFAULT_SERVER})")
    args = parser.parse_args()
    directory = configuration.config_dir()
    configuration.write_default(directory / "config.toml")
    config = configuration.load(directory / "config.toml", server=args.server)
    api = Api(config.server, TokenStore(directory / "token"))
    LustjinnApp(config, api).run()

