"""The stories screen: the list loads and shows the preview, moves, filters as you type, renames
in place, deletes after asking, refreshes, and opens the story on Enter."""

from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.confirm import ConfirmScreen
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.listing import Rows
from lustjinn_tui.masthead import Masthead
from lustjinn_tui.status import Kind
from lustjinn_tui.stories import Preview, StoriesScreen
from tui_support import fake_server as fake


def stories(app: LustjinnApp) -> StoriesScreen:
    screen = app.screen
    assert isinstance(screen, StoriesScreen)
    return screen


def names(app: LustjinnApp) -> list[str]:
    return [s.name for s in stories(app).rows.items]


def drawn(app: LustjinnApp) -> str:
    return stories(app).rows.render().plain


async def test_the_list_loads_newest_first_with_the_selected_storys_preview(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Older", "A dusty opening.", "Hello", '*She looks up.* "A week," she says.')
    server.add("Empty one")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        screen = stories(app)
        assert names(app) == ["Older", "Empty one"]  # the one with a message moved last
        assert screen.status_line.text == "2 stories loaded."
        assert screen.status_line.kind == Kind.SUCCESS
        assert screen.summary() == "2 stories"
        assert drawn(app).startswith("> Older")
        preview = screen.query_one(Preview).render().plain
        assert preview.startswith("Older\n")
        assert "with Dummy" in preview
        assert "She looks up. A week, she says." in preview  # the markers are gone
        await pilot.press("down")
        preview = screen.query_one(Preview).render().plain
        assert preview.startswith("Empty one\n")
        assert "Nothing said yet" in preview
        assert drawn(app).splitlines()[1].startswith("> Empty one")


async def test_the_keys_move_the_cursor_and_the_ends(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    for n in range(40):
        server.add(f"Story {n:02}")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        rows = stories(app).rows
        await pilot.press("down", "down", "down")
        assert rows.state.selected == 3
        await pilot.press("end")
        assert rows.state.selected == 39
        assert drawn(app).splitlines()[-1].startswith("> Story")  # scrolled to the cursor
        await pilot.press("home")
        assert rows.state.selected == 0
        await pilot.press("pagedown")
        assert rows.state.selected > 10
        await pilot.press("pageup")
        assert rows.state.selected == 0
        await pilot.press("up")
        assert rows.state.selected == 0


async def test_the_filter_narrows_as_you_type_and_esc_clears_it(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Professor")
    server.add("Captain")
    server.add("Story Ideas")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        screen = stories(app)
        await pilot.press("slash", *"st")
        await pilot.pause()
        assert screen.legend.text.startswith(" Enter Apply")
        assert names(app) == ["Story Ideas"]
        assert screen.summary() == "1 of 3"
        assert "1 of 3 matching" not in drawn(app)  # the header is the field while typing
        await pilot.press("enter")  # keeps the filter, leaves the field
        await pilot.pause()
        assert names(app) == ["Story Ideas"]
        assert screen.legend.text.startswith(" Enter Open the story")
        assert str(screen.query_one("#header").render()) == '1 of 3 matching "st"'
        await pilot.press("escape")  # the first Esc clears the filter, it does not quit
        await pilot.pause()
        assert names(app) == ["Story Ideas", "Captain", "Professor"]
        assert screen.status_line.text == "Filter cleared."
        assert app.return_code is None
        await pilot.press("slash", *"xyz")
        await pilot.pause()
        assert names(app) == []
        assert "Nothing matches this filter" in drawn(app)
        await pilot.press("escape")
        await pilot.pause()
        assert len(names(app)) == 3


async def test_f2_renames_in_place_and_the_list_is_re_read(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Draft")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        screen = stories(app)
        await pilot.press("f2")
        await pilot.pause()
        assert screen.legend.text.startswith(" Enter Rename")
        assert screen.query_one("#rename").display  # seeded with the name
        await pilot.press("end", *" two", "enter")
        await pilot.pause(0.1)
        assert names(app) == ["Draft two"]
        assert screen.status_line.text == 'Renamed to "Draft two".'
        assert "PATCH /stories/" in " ".join(server.paths())
        assert server.paths("GET")[-1] == "/stories"
        assert screen.legend.text.startswith(" Enter Open the story")


async def test_a_rename_to_nothing_or_to_the_same_name_changes_nothing(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Draft")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        screen = stories(app)
        await pilot.press("f2", "enter")
        await pilot.pause()
        assert screen.status_line.text == "That is already its name."
        await pilot.press("f2", "ctrl+u", "enter")
        await pilot.pause()
        assert screen.status_line.text == "A story needs a name. Nothing was changed."
        await pilot.press("f2", *"x", "escape")
        await pilot.pause()
        assert screen.status_line.text == "Rename cancelled."
        assert names(app) == ["Draft"]
        assert "PATCH" not in " ".join(server.paths())


async def test_delete_asks_first_and_enter_is_the_only_yes(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Keep")
    server.add("Gone")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("delete")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        assert app.screen.query_one(Masthead).crumbs == ("Stories", "Delete")
        await pilot.press("y")  # anything but Enter is no
        await pilot.pause()
        assert isinstance(app.screen, StoriesScreen)
        assert stories(app).status_line.text == "Cancelled."
        assert names(app) == ["Gone", "Keep"]
        await pilot.press("delete")
        await pilot.pause()
        assert 'Delete the story "Gone"?' in str(app.screen.query_one(".question").render())
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, StoriesScreen)
        assert names(app) == ["Keep"]
        assert stories(app).status_line.text == 'Deleted "Gone".'
        assert "DELETE" in " ".join(server.paths())


async def test_r_re_reads_the_list(app: LustjinnApp, server: fake.FakeServer) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        assert "No stories yet" in drawn(app)
        server.add("Arrived")
        await pilot.press("r")
        await pilot.pause(0.1)
        assert names(app) == ["Arrived"]
        assert stories(app).status_line.text == "1 story loaded."


async def test_enter_opens_the_story_and_coming_back_re_reads_quietly(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", "An opening.")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)
        assert app.screen.story.id == fake.uuid.UUID(told["id"])
        assert app.screen.query_one(Masthead).crumbs == ("Stories", "Tale")
        told["name"] = "Tale, renamed elsewhere"
        reads = server.paths("GET").count("/stories")
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert isinstance(app.screen, StoriesScreen)
        assert names(app) == ["Tale, renamed elsewhere"]
        assert server.paths("GET").count("/stories") == reads + 1
        assert stories(app).status_line.text == "1 story loaded."  # the quiet read said nothing


async def test_a_click_selects_and_a_second_click_opens(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("First")
    server.add("Second")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        rows = stories(app).rows
        await pilot.click(Rows, offset=(2, 1))
        await pilot.pause()
        assert rows.state.selected == 1
        assert isinstance(app.screen, StoriesScreen)
        await pilot.click(Rows, offset=(2, 1))
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)
