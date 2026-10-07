"""The frame: the app opens on the stories, the footer shows the keys, help opens once, Esc goes
back and then out. Driven with Textual's pilot, headless."""

from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.help import SECTIONS, HelpScreen
from lustjinn_tui.masthead import Masthead
from lustjinn_tui.status import Kind, StatusLine
from lustjinn_tui.stories import StoriesScreen
from lustjinn_tui.theme import NAME
from lustjinn_tui.view import View


def view(app: LustjinnApp) -> View:
    screen = app.screen
    assert isinstance(screen, View)
    return screen


async def test_the_app_opens_on_the_stories_in_the_one_dark_theme() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, StoriesScreen)
        assert app.theme == NAME
        assert app.current_theme.dark
        assert view(app).query_one(Masthead).crumbs == ("Stories",)


async def test_the_legend_shows_the_screens_keys_in_order() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(140, 30)) as pilot:
        await pilot.pause()
        text = view(app).legend.text
        assert text.startswith(" Enter Open the story   N New story   M Library")
        assert text.endswith(" Q Quit")
        assert "All keys" not in text


async def test_a_narrow_legend_ends_with_the_pointer() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(50, 30)) as pilot:
        await pilot.pause()
        text = view(app).legend.text
        assert text.startswith(" Enter Open the story")
        assert text.endswith(" ? All keys")


async def test_help_opens_once_and_esc_closes_it() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert view(app).query_one(Masthead).crumbs == ("Stories", "Help")
        assert view(app).legend.text.startswith(" ↑↓ Scroll")
        await pilot.press("f1")
        await pilot.pause()
        assert len(app.screen_stack) == 2  # not stacked twice
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, StoriesScreen)


async def test_help_lists_every_section() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f1")
        await pilot.pause()
        shown = [str(s.render()) for s in app.screen.query(".section")]
        assert shown == [section.name for section in SECTIONS]


async def test_esc_on_the_last_screen_quits() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("escape")
        await pilot.pause()
    assert app.return_code == 0


async def test_q_quits() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("q")
        await pilot.pause()
    assert app.return_code == 0


async def test_the_status_row_keeps_a_message_until_replaced() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        line = view(app).query_one(StatusLine)
        view(app).status("Refreshed.", Kind.SUCCESS)
        assert (line.text, line.kind) == ("Refreshed.", Kind.SUCCESS)
        await pilot.pause(0.2)
        assert line.text == "Refreshed."
        line.busy("Loading")
        assert line.is_busy
        assert line.text == ""
        assert "Loading…" in str(line.render())
        line.idle()
        assert not line.is_busy


async def test_ctrl_l_redraws_and_says_so() -> None:
    app = LustjinnApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert view(app).status_line.text == "Screen cleared."
