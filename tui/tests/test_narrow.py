"""The layout under sixty columns (``NarrowLayoutTests``, ``PhoneBarTests``): one row at the top
and one at the bottom, a one-column story list, the conversation across the whole width with
Enter as a new line and a separate send, the bottom row as buttons with the mouse on — and
all of it back the moment the terminal is wider again."""

from collections.abc import Callable

import pytest

from lustjinn_tui import buttons as phone
from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.config import Config
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.legend import Legend
from lustjinn_tui.masthead import Masthead
from lustjinn_tui.status import StatusLine
from lustjinn_tui.stories import Preview, StoriesScreen
from lustjinn_tui.view import NARROW
from tui_support import fake_server as fake

OPENING = '*The door opens.* "You came," she says.'


def test_sixty_columns_is_where_narrow_begins() -> None:
    assert NARROW == 60


def test_the_bar_fits_from_the_left_and_keeps_the_ellipsis() -> None:
    buttons = (phone.BACK, phone.press("Write", "i"), phone.Button("Reroll", "ctrl+g"))
    content, hits = phone.bar(buttons, 40)
    assert content.plain == " ‹   Write   Reroll   ⋯ "
    assert [h.button.label for h in hits] == ["‹", "Write", "Reroll", "⋯"]
    assert phone.tapped(hits, 0) is phone.BACK
    assert phone.tapped(hits, 3) is None  # between two buttons
    assert phone.tapped(hits, 5) is not None
    assert phone.tapped(hits, 5).label == "Write"  # type: ignore[union-attr]
    content, hits = phone.bar(buttons, 15)  # too narrow for Reroll: dropped from the right
    assert [h.button.label for h in hits] == ["‹", "Write", "⋯"]
    content, hits = phone.bar(buttons, 5)
    assert [h.button.label for h in hits] == ["⋯"]


async def test_the_frame_is_one_row_top_and_bottom_and_comes_back_when_wider(
    app: LustjinnApp, server: fake.FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(StatusLine, "LINGER_SECONDS", 0.05)
    server.add("Tale", OPENING)
    server.add("Other")
    async with app.run_test(size=(50, 24)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, StoriesScreen)
        assert screen.narrow
        masthead = screen.query_one(Masthead)
        assert not masthead.query_one("#brand-row").display
        assert str(masthead.query_one("#crumbs").render()) == "Stories  2 stories"
        assert not screen.query_one(Legend).display
        line = screen.query_one(StatusLine)
        assert line.narrow
        assert line.render().plain.startswith(" Enter Open the story")  # the legend sits here
        assert not screen.query_one(Preview).display
        assert screen.rows.rows_per_item == 2
        drawn = screen.rows.render().plain.splitlines()
        assert drawn[0].startswith("▌ Tale")
        assert "The door opens. You came, she says." in drawn[1]
        assert drawn[3].strip() == "Nothing said yet."
        await pilot.resize_terminal(100, 30)
        await pilot.pause(0.2)
        assert not screen.narrow
        assert masthead.query_one("#brand-row").display
        assert screen.query_one(Legend).display
        assert screen.query_one(Preview).display
        assert screen.rows.rows_per_item == 1
        await pilot.resize_terminal(59, 30)
        await pilot.pause(0.2)
        assert screen.narrow
        await pilot.resize_terminal(60, 30)
        await pilot.pause(0.2)
        assert not screen.narrow


async def test_a_message_borrows_the_phones_row_for_a_few_seconds(
    app: LustjinnApp, server: fake.FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(StatusLine, "LINGER_SECONDS", 0.2)
    server.add("Tale")
    async with app.run_test(size=(50, 24)) as pilot:
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, StoriesScreen)
        line = screen.query_one(StatusLine)
        assert line.render().plain == "1 story loaded."  # the message has the row…
        await pilot.pause(0.4)
        assert line.render().plain.startswith(" Enter Open the story")  # …then the legend
        assert line.render().plain.endswith(" ? All keys")
        screen.status("Hello there.")
        assert line.render().plain == "Hello there."


async def test_on_a_phone_the_conversation_takes_the_width_and_enter_is_a_new_line(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", OPENING, "Hi")
    server.spend[told["id"]] = ("0.0123", "0")
    async with app.run_test(size=(50, 24)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("enter")
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        assert screen.query_one("#column").size.width == 50
        assert str(screen.query_one("#header").render()) == ""  # the position is the masthead's
        crumbs = str(screen.query_one(Masthead).query_one("#crumbs").render())
        assert crumbs == "Tale  2/2 · $0.0123"  # the position and the cost: the phone's header
        rows = screen.transcript.rows
        assert rows[0].body.plain == " Dummy"  # the name alone, no chip, no time
        assert all(r.marker != "none" or r.body.plain == " " for r in rows)  # no rules
        await pilot.press("i", *"one", "enter", *"two")
        await pilot.pause()
        assert screen.composer.text == "one\ntwo"
        assert "POST" not in " ".join(server.paths())
        assert [h.key for h in screen.hints()] == ["Alt+Enter", "Enter", "Esc"]
        await pilot.press("alt+enter")
        await pilot.pause(0.3)
        assert [m.text for m in screen.messages][-2] == "one\ntwo"
        await pilot.resize_terminal(100, 30)
        await pilot.pause(0.2)
        assert not screen.composer.newline_on_enter
        assert screen.transcript.rows[0].body.plain.startswith(" Dummy ")
        assert len(screen.transcript.rows[0].body.plain) > 20  # the chip and the time are back


async def test_with_the_mouse_on_the_bottom_row_is_buttons_that_press_keys(
    make_app: Callable[..., LustjinnApp], server: fake.FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(StatusLine, "LINGER_SECONDS", 0.05)
    server.add("Tale", OPENING)
    app = make_app(config=Config(server="http://api.test", mouse=True))
    async with app.run_test(size=(50, 24)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, StoriesScreen)
        line = screen.query_one(StatusLine)
        assert line.render().plain == " Open   New   Library   ⋯ "
        await pilot.click(StatusLine, offset=(1, 0))  # Open
        await pilot.pause(0.3)
        conversation = app.screen
        assert isinstance(conversation, ConversationScreen)
        line = conversation.query_one(StatusLine)
        await pilot.pause(0.3)
        assert line.render().plain.startswith(" ‹   Write   Reroll ")
        await pilot.click(StatusLine, offset=(6, 0))  # Write
        await pilot.pause()
        assert conversation.composer.display
        assert line.render().plain == " Send   Close   ⋯ "
        await pilot.press(*"Hello")
        await pilot.click(StatusLine, offset=(2, 0))  # Send
        await pilot.pause(0.5)
        assert [m.text for m in conversation.messages][-2] == "Hello"
        await pilot.click(StatusLine, offset=(1, 0))  # ‹ back
        await pilot.pause()
        assert isinstance(app.screen, StoriesScreen)


async def test_without_the_mouse_the_row_stays_a_legend(
    app: LustjinnApp, server: fake.FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(StatusLine, "LINGER_SECONDS", 0.05)
    server.add("Tale")
    async with app.run_test(size=(50, 24)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, StoriesScreen)
        assert "⋯" not in screen.query_one(StatusLine).render().plain
