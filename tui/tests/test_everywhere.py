"""The keys that work everywhere: the command palette with each screen's commands, search
across every story, and the export of a story."""

from pathlib import Path

from textual.command import CommandPalette
from textual.pilot import Pilot

from lustjinn_tui.api import Export
from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.config import Config
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.export import ExportScreen, write_export
from lustjinn_tui.library import LibraryScreen
from lustjinn_tui.palette import commands_of
from lustjinn_tui.search import SearchScreen
from lustjinn_tui.status import Kind
from lustjinn_tui.stories import StoriesScreen
from tui_support import fake_server as fake


async def open_story(app: LustjinnApp, pilot: Pilot[None]) -> ConversationScreen:
    await pilot.pause(0.1)
    assert isinstance(app.screen, StoriesScreen)
    await pilot.press("enter")
    await pilot.pause(0.2)
    screen = app.screen
    assert isinstance(screen, ConversationScreen)
    return screen


async def test_the_palette_lists_the_screens_commands_then_the_global_ones(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", "An opening.")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        names = [c.name for c in commands_of(app.screen)]
        assert names[:2] == ["Open the story", "New story"]
        assert names[-5:] == ["Search every story", "Library", "Help", "Back", "Quit"]
        await open_story(app, pilot)
        names = [c.name for c in commands_of(app.screen)]
        assert names[0] == "Write a message"
        assert "Export the transcript" in names
        assert names[-1] == "Quit"


async def test_ctrl_p_opens_the_palette_and_a_command_runs_as_its_key_would(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", "An opening.")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("ctrl+p")
        await pilot.pause(0.2)
        assert isinstance(app.screen, CommandPalette)
        await pilot.press(*"librar")
        await pilot.pause(0.5)
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert isinstance(app.screen, LibraryScreen)
        assert [type(s).__name__ for s in app.screen_stack] == ["StoriesScreen", "LibraryScreen"]
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("colon")  # the donor's other key for it
        await pilot.pause(0.2)
        assert isinstance(app.screen, CommandPalette)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, StoriesScreen)


async def test_a_colon_in_a_text_field_is_a_colon(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", "An opening.")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"a", "colon", *"b")
        await pilot.pause()
        assert screen.composer.text == "a:b"
        assert isinstance(app.screen, ConversationScreen)


async def test_ctrl_f_searches_every_story_and_enter_opens_a_hit(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Fog Tale", "The fog came in.", "No fog here.")
    server.add("Other", "Clear skies.")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        search = app.screen
        assert search.focused is search.query_one("#query")
        await pilot.press(*"fog", "enter")
        await pilot.pause(0.3)
        assert len(search.rows.items) == 3  # the name and two messages
        assert search.status_line.text == "3 result(s) in 2 story(ies)."
        drawn = search.rows.render().plain
        assert drawn.startswith("> Fog Tale")
        assert "name" in drawn.splitlines()[0]
        assert "Fog" in drawn.splitlines()[1]  # the snippet of a name hit is the name
        await pilot.press("tab")  # the scope: names only
        await pilot.pause()
        assert search.status_line.text == "Scope: story names"
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("enter")  # the query is the same, the scope changed: a new search
        await pilot.pause(0.3)
        assert [h.scope for h in search.rows.items] == ["message", "message"]
        assert "scope: messages   ·   2 result(s)" in str(search.query_one("#where").render())
        await pilot.press("down", "enter")  # the same query again: open the selected hit
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConversationScreen)
        assert app.screen.story.name == "Fog Tale"
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        await pilot.press("ctrl+u", *"dragon", "enter")
        await pilot.pause(0.3)
        assert search.status_line.text == 'Nothing matches "dragon".'
        assert search.status_line.kind == Kind.WARNING


async def test_e_exports_with_a_preview_per_format_and_writes_the_file(
    app: LustjinnApp, server: fake.FakeServer, tmp_path: Path
) -> None:
    server.add("Tale", "An opening.", "Hi")
    app.config = Config(server="http://api.test", export_directory=str(tmp_path / "out"))
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("e")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ExportScreen)
        export = app.screen
        assert export.fmt == "markdown"
        assert export.export is not None
        assert export.export.filename == "transcript-tale-20261007-120000.md"
        assert str(export.query_one("#preview").render()).startswith("# Tale")
        await pilot.press("right")
        await pilot.pause(0.3)
        assert export.fmt == "json"
        assert str(export.query_one("#preview").render()).startswith("{")
        await pilot.press("right")
        await pilot.pause(0.3)
        assert export.fmt == "text"
        assert str(export.query_one("#preview").render()).startswith("[001]")
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConversationScreen)
        written = tmp_path / "out" / "transcript-tale-20261007-120000.txt"
        assert written.read_text(encoding="utf-8").startswith("[001]")
        assert screen.status_line.text == f"Written to {written}"
        await pilot.press("e")
        await pilot.pause(0.3)
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)
        assert app.clipboard.startswith("# Tale")
        assert screen.status_line.text == "Copied to the clipboard."


def test_write_export_never_overwrites(tmp_path: Path) -> None:
    export = Export(filename="transcript.md", text="one")
    first = write_export(tmp_path, export)
    second = write_export(tmp_path, Export(filename="transcript.md", text="two"))
    assert first.name == "transcript.md"
    assert second.name == "transcript (2).md"
    assert first.read_text() == "one"
    assert second.read_text() == "two"
