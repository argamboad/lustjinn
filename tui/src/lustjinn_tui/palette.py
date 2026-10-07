"""The command palette: every command of the current screen plus the global ones, found by
typing (``Views/CommandPaletteView.cs``).

Textual ships the palette — the screen, the input, the fuzzy matching, the list — so this is
only its contents: a *provider* that reads the commands a view declares (``View.commands``)
and the few that work everywhere, and yields them as hits. A command run from the palette
behaves as its key would: the palette closes itself first, so a command that pushes a screen
does not leave the palette buried underneath it.

.NET readers: ``ICommandProvider`` in a shell that owns the dialog.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

from textual.app import App
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.screen import Screen


@dataclass(frozen=True, slots=True)
class PaletteCommand:
    """One entry: what the palette shows, what it says under it, and what it does."""

    name: str
    description: str
    run: Callable[[], object]


class HasCommands:
    """What a view that offers commands to the palette provides."""

    def commands(self) -> list[PaletteCommand]:  # pragma: no cover - overridden
        return []


def global_commands(screen: Screen[Any]) -> list[PaletteCommand]:
    """The ones that work on every screen (``Program.cs`` registered them once)."""
    from lustjinn_tui.app import LustjinnApp

    app = cast("App[Any]", screen.app)  # pyright: ignore[reportUnknownMemberType]
    assert isinstance(app, LustjinnApp)
    return [
        PaletteCommand(
            "Search every story", "names and messages, across all of them", app.action_search_all
        ),
        PaletteCommand("Library", "characters, personas and snippets", app.action_library),
        PaletteCommand("Help", "every key, grouped by where it works", app.action_help),
        PaletteCommand("Back", "one screen back", app.go_back),
        PaletteCommand("Quit", "leave the terminal client", app.exit),
    ]


def commands_of(screen: Screen[Any]) -> list[PaletteCommand]:
    """The screen's own commands first, then the global ones."""
    own = screen.commands() if isinstance(screen, HasCommands) else []
    return [*own, *global_commands(screen)]


class LustjinnCommands(Provider):
    """What the palette searches: the current screen's commands and the global ones."""

    async def discover(self) -> Hits:
        for command in commands_of(self.screen):
            yield DiscoveryHit(command.name, partial(self._run, command), help=command.description)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for command in commands_of(self.screen):
            score = matcher.match(f"{command.name} {command.description}")
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(command.name),
                    partial(self._run, command),
                    help=command.description,
                )

    def _run(self, command: PaletteCommand) -> None:
        command.run()
