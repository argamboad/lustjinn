"""The library screen: shelves, the text beside the names, creating in the editor, renaming,
the default persona, removing, and a save over an edit made elsewhere."""

from collections.abc import Callable

from textual.pilot import Pilot

from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.confirm import ConfirmScreen
from lustjinn_tui.library import ConflictScreen, LibraryScreen
from lustjinn_tui.status import Kind
from lustjinn_tui.stories import StoriesScreen
from tui_support import fake_server as fake

CARD = "You are Elena.\n\n=== THE WORLD ===\n\nA resort on a cliff."


def library(app: LustjinnApp) -> LibraryScreen:
    screen = app.screen
    assert isinstance(screen, LibraryScreen)
    return screen


def names(app: LustjinnApp) -> list[str]:
    return [e.name for e in library(app).rows.items]


def prose(app: LustjinnApp) -> str:
    return str(library(app).query_one("#prose").render())


async def open_library(app: LustjinnApp, pilot: Pilot[None]) -> LibraryScreen:
    await pilot.pause(0.1)
    assert isinstance(app.screen, StoriesScreen)
    await pilot.press("m")
    await pilot.pause(0.2)
    return library(app)


def scripted_editor(replies: list[str | None]) -> Callable[..., str | None]:
    """An editor that answers from a script and records what it was handed."""
    handed: list[str] = []

    def edit(app: LustjinnApp, text: str, suffix: str) -> str | None:
        handed.append(text)
        return replies.pop(0) if replies else None

    edit.handed = handed  # type: ignore[attr-defined]
    return edit


async def test_the_shelves_list_their_entries_with_the_text_beside(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    elena = server.shelve("characters", "Elena", CARD, opening="*The door opens.*")
    server.shelve("characters", "Marta", "You are Marta.")
    server.shelve("personas", "Me", "A tall man.")
    told = server.add("Tale", character="Elena", character_id=elena["id"])
    assert told
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_library(app, pilot)
        assert names(app) == ["Elena", "Marta"]
        assert screen.summary() == "2 characters"
        assert screen.status_line.text == "2 characters on the shelf."
        assert "You are Elena." in prose(app)
        assert "=== THE OPENING ===" in prose(app)
        assert "The door opens." in prose(app)
        assert "used by Tale" in str(screen.query_one("#caption").render())
        assert "Characters" in str(screen.query_one("#tabs").render())
        await pilot.press("down")
        await pilot.pause(0.1)
        assert prose(app).startswith("You are Marta.")
        await pilot.press("right")
        await pilot.pause(0.2)
        assert screen.shelf == "personas"
        assert names(app) == ["Me"]
        assert "A tall man." in prose(app)
        await pilot.press("right")
        await pilot.pause(0.2)
        assert screen.shelf == "snippets"
        assert names(app) == []
        assert "No snippets yet" in screen.rows.render().plain
        await pilot.press("left", "left")
        await pilot.pause(0.2)
        assert screen.shelf == "characters"


async def test_n_names_a_new_entry_and_opens_the_editor_on_its_skeleton(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    editor = scripted_editor(["You are Sofia. The rest.\n"])
    app.editor = editor
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_library(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        assert screen.legend.text.startswith(" Enter Create and edit")
        await pilot.press(*"Sofia", "enter")
        await pilot.pause(0.3)
        assert names(app) == ["Sofia"]
        assert editor.handed[0].startswith("You are the narrator")  # type: ignore[attr-defined]
        assert server.library["characters"][0]["text"] == "You are Sofia. The rest.\n"
        assert server.library["characters"][0]["version"] == 2
        assert screen.status_line.text.startswith("Saved. Every story using 'Sofia'")
        assert "You are Sofia." in prose(app)


async def test_enter_edits_and_an_unchanged_text_saves_nothing(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.shelve("characters", "Elena", CARD)
    app.editor = scripted_editor([None, CARD + "\nMore.\n"])
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_library(app, pilot)
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert screen.status_line.text == "Nothing changed."
        assert server.library["characters"][0]["version"] == 1
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert server.library["characters"][0]["text"].endswith("More.\n")
        assert server.library["characters"][0]["version"] == 2
        assert "PATCH" in " ".join(server.paths())


async def test_o_edits_the_opening_and_only_a_character_has_one(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.shelve("characters", "Elena", CARD)
    server.shelve("personas", "Me", "A tall man.")
    app.editor = scripted_editor(['"You came," she says.'])
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_library(app, pilot)
        await pilot.press("o")
        await pilot.pause(0.3)
        assert server.library["characters"][0]["opening"] == '"You came," she says.'
        assert "You came" in prose(app)
        await pilot.press("right")
        await pilot.pause(0.2)
        await pilot.press("o")
        await pilot.pause()
        assert screen.status_line.text == "A persona has no opening."


async def test_a_save_over_an_edit_made_elsewhere_shows_theirs_and_asks(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    elena = server.shelve("characters", "Elena", CARD)
    app.editor = scripted_editor(["Mine.\n", "Mine again.\n"])
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_library(app, pilot)
        elena["text"], elena["version"] = "Theirs, from the phone.", 2  # changed in between
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConflictScreen)
        assert app.screen.theirs.version == 2
        assert "Theirs, from the phone." in str(app.screen.query_one(".theirs").render())
        await pilot.press("escape")  # keep theirs
        await pilot.pause()
        assert isinstance(app.screen, LibraryScreen)
        assert screen.status_line.text == "Kept the server's text. Yours was not saved."
        assert elena["text"] == "Theirs, from the phone."
        await pilot.press("r")
        await pilot.pause(0.2)
        elena["text"], elena["version"] = "Theirs once more.", 3
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConflictScreen)
        await pilot.press("enter")  # save mine over it
        await pilot.pause(0.3)
        assert isinstance(app.screen, LibraryScreen)
        assert elena["text"] == "Mine again.\n"
        assert elena["version"] == 4
        assert screen.status_line.text == "Saved over version 3."


async def test_f2_renames_and_d_makes_a_persona_the_default(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.shelve("personas", "Me", "A tall man.")
    server.shelve("personas", "Someone", "A stranger.")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_library(app, pilot)
        await pilot.press("right")
        await pilot.pause(0.2)
        await pilot.press("f2", "end", *" too", "enter")
        await pilot.pause(0.3)
        assert names(app) == ["Me too", "Someone"]
        assert screen.status_line.text.startswith('Renamed to "Me too".')
        await pilot.press("d")
        await pilot.pause(0.2)
        assert server.default_persona is not None
        assert server.default_persona["name"] == "Me too"
        assert screen.rows.render().plain.startswith("★ Me too")
        assert screen.status_line.kind == Kind.SUCCESS
        await pilot.press("d")  # again clears it
        await pilot.pause(0.2)
        assert server.default_persona is None
        await pilot.press("left")
        await pilot.pause(0.2)
        await pilot.press("d")
        await pilot.pause()
        assert screen.status_line.text == "Only a persona can be the default."


async def test_del_asks_and_the_server_refuses_while_a_story_uses_it(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    elena = server.shelve("characters", "Elena", CARD)
    server.shelve("characters", "Spare", "Unused.")
    server.add("Tale", character="Elena", character_id=elena["id"])
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_library(app, pilot)
        await pilot.press("delete")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        consequences = [str(c.render()) for c in app.screen.query(".consequence")]
        assert consequences[0].startswith("The server will refuse")
        assert consequences[1].strip() == "Tale"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, LibraryScreen)
        assert (
            screen.status_line.text == "This character is used by Tale. It stays until they do not."
        )
        assert names(app) == ["Elena", "Spare"]
        await pilot.press("down", "delete")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert names(app) == ["Elena"]
        assert screen.status_line.text == "Removed 'Spare'."
