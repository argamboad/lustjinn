"""The two keyboard dialects (``KeyHandlingTests``): Vim's letters move while navigating and
type inside a field; Standard's ``N`` finds the next match too; ``G`` is the end in Vim and
regenerate in Standard, with ``Ctrl+G`` in both."""

from collections.abc import Callable

from textual.widgets import Input

from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.config import Config
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.dialect import SWALLOW, dialect_of, translate
from lustjinn_tui.regenerate import RegenerateScreen
from lustjinn_tui.stories import StoriesScreen
from tui_support import fake_server as fake


def test_the_tables_say_what_a_letter_means() -> None:
    assert dialect_of("Vim") == "vim"
    assert dialect_of("anything else") == "standard"
    assert translate("vim", "j") == "down"
    assert translate("vim", "G") == "end"
    assert translate("vim", "g") == SWALLOW
    assert translate("vim", "N") is None  # the screen's own binding: previous match
    assert translate("vim", "x") is None
    assert translate("standard", "N") == "n"
    assert translate("standard", "j") is None


async def test_vim_letters_move_the_list_and_still_type_in_a_field(
    make_app: Callable[..., LustjinnApp], server: fake.FakeServer
) -> None:
    for name in ("One", "Two", "Three"):
        server.add(name)
    app = make_app(config=Config(server="http://api.test", keyboard="vim"))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, StoriesScreen)
        await pilot.press("j", "j")
        await pilot.pause()
        assert screen.rows.state.selected == 2
        await pilot.press("k")
        await pilot.pause()
        assert screen.rows.state.selected == 1
        await pilot.press("slash", *"jk")  # the letters type into the filter
        await pilot.pause()
        assert screen.query_one("#filter", Input).value == "jk"
        await pilot.press("escape")
        await pilot.pause()
        assert len(screen.rows.items) == 3
        await pilot.press("l")  # right opens, as the arrow does
        await pilot.pause(0.2)
        assert isinstance(app.screen, ConversationScreen)
        await pilot.press("h")  # left means nothing here; nothing happens
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)


async def test_in_vim_g_is_the_end_and_regenerate_is_ctrl_g(
    make_app: Callable[..., LustjinnApp], server: fake.FakeServer
) -> None:
    server.add("Tale", "An opening.", "Hi", "Hello.", "More.", "Yes.")
    app = make_app(config=Config(server="http://api.test", keyboard="vim"))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("enter")
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        await pilot.press("k", "k", "k")
        await pilot.pause()
        assert screen.transcript.selected == 1
        await pilot.press("G")
        await pilot.pause()
        assert screen.transcript.selected == 4
        assert isinstance(app.screen, ConversationScreen)  # no regenerate screen opened
        await pilot.press("g")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert isinstance(app.screen, RegenerateScreen)


async def test_in_standard_n_and_shift_n_both_find_the_next_match_and_g_regenerates(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", "fog one", "fog two", "clear", "fog four", "a reply")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("enter")
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        await pilot.press("slash", *"fog", "enter")
        await pilot.pause()
        assert screen.transcript.selected == 0  # wrapped round from the last turn
        await pilot.press("N")
        await pilot.pause()
        assert screen.transcript.selected == 1  # forward, not back
        await pilot.press("n")
        await pilot.pause()
        assert screen.transcript.selected == 3
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("G")
        await pilot.pause()
        assert isinstance(app.screen, RegenerateScreen)


async def test_in_vim_shift_n_goes_back(
    make_app: Callable[..., LustjinnApp], server: fake.FakeServer
) -> None:
    server.add("Tale", "fog one", "fog two", "clear", "fog four")
    app = make_app(config=Config(server="http://api.test", keyboard="vim"))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("enter")
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        await pilot.press("slash", *"fog", "enter")
        await pilot.pause()
        assert screen.transcript.selected == 0
        await pilot.press("N")
        await pilot.pause()
        assert screen.transcript.selected == 3  # back, wrapping round
        await pilot.press("n")
        await pilot.pause()
        assert screen.transcript.selected == 0
