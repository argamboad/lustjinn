"""The transcript's layout and its scroll rules, the donor's ``TranscriptScrollingTests`` in
Python: a turn is a speaker line, wrapped prose, a blank and a rule; the cursor lands on a turn's
first row; the viewport moves only when it loses the turn; the arrows read through a tall turn."""

from collections.abc import Callable
from datetime import UTC, datetime

from textual.app import ComposeResult

from lustjinn_tui.api import Message
from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.transcript import Pending, Transcript, first_row, label_of, last_row, layout
from lustjinn_tui.view import View
from tui_support import fake_server as fake

LONG = "words and *more words* " * 40  # a dozen rows at eighty columns


def turns(*texts: str) -> list[Message]:
    return [
        Message.model_validate(fake.message(i + 1, "assistant" if i % 2 == 0 else "user", text))
        for i, text in enumerate(texts)
    ]


def test_a_turn_is_a_speaker_line_the_wrapped_body_a_blank_and_a_rule() -> None:
    rows = layout(turns('*She looks up.* "Hello."', "Hi"), width=40, speaker="Elena")
    kinds = [(r.turn, r.marker) for r in rows]
    assert kinds == [
        (0, "speaker"),
        (0, "body"),
        (0, "none"),
        (0, "none"),  # the rule between turns
        (1, "speaker"),
        (1, "body"),
        (1, "none"),
    ]
    assert rows[0].body.plain.startswith(" Elena ")
    # The stamp at the far end, in the machine's own zone as the view draws it: the fake
    # message was sent at 09:01 UTC, which is 03:01 on a laptop six hours behind.
    local = datetime(2026, 10, 7, 9, 1, tzinfo=UTC).astimezone().strftime("%H:%M")
    assert rows[0].body.plain.rstrip().endswith(local)
    assert rows[1].body.plain == "She looks up. Hello."  # the markers are gone
    assert rows[4].body.plain.startswith(" You ")
    assert len(rows[0].body.plain) == 40


def test_prose_wraps_to_the_measure_after_the_markers_go() -> None:
    rows = layout(turns(LONG), width=30, speaker="Elena")
    bodies = [r.body.plain for r in rows if r.marker == "body"]
    assert len(bodies) > 5
    assert all(len(b) <= 30 for b in bodies)
    assert "*" not in "".join(bodies)


def test_a_blank_line_in_a_message_stays_a_row_and_no_rule_follows_the_last_turn() -> None:
    rows = layout(turns("One.\n\nTwo."), width=40, speaker="Elena")
    assert [r.body.plain for r in rows if r.marker == "body"] == ["One.", "", "Two."]
    assert rows[-1].marker == "none"
    assert rows[-1].body.plain == " "


def test_a_pending_reply_is_drawn_as_the_newest_turn_with_an_ellipsis_until_text_comes() -> None:
    rows = layout(turns("Hello", "Hi"), width=40, speaker="Elena", pending=Pending(""))
    assert rows[-3].turn == 2
    assert rows[-3].marker == "speaker"
    assert rows[-2].body.plain == "…"
    rows = layout(turns("Hello", "Hi"), width=40, speaker="Elena", pending=Pending("She lo"))
    assert rows[-2].body.plain == "She lo"


def test_the_search_is_painted_through_the_rows_and_the_phone_has_no_rules() -> None:
    rows = layout(turns("The fog came in.", "Fog?"), width=40, speaker="Elena", query="fog")
    painted = [r for r in rows if r.marker == "body" and r.body.spans]
    assert len(painted) == 2
    rows = layout(turns("One", "Two"), width=40, speaker="Elena", rules=False)
    assert sum(1 for r in rows if r.marker == "none") == 2


def test_first_and_last_row_of_a_turn_and_the_labels() -> None:
    rows = layout(turns("a", "b"), width=40, speaker="Elena")
    assert first_row(rows, 1) == 4
    assert last_row(rows, 1) == 6
    assert first_row(rows, 7) == -1
    assert label_of("user", "Elena") == "You"
    assert label_of("assistant", "Elena") == "Elena"
    assert label_of("system", "Elena") == "Scene"


class Bare(View):
    TITLE = "Bare"

    def body(self) -> ComposeResult:
        yield Transcript(speaker="Elena", id="t")


async def test_opening_lands_on_the_newest_turns_first_row_and_the_arrows_read_through_it(
    make_app: Callable[..., LustjinnApp],
) -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app.push_screen(Bare())
        await pilot.pause()
        t = app.screen.query_one(Transcript)
        t.show(turns("short", "short", LONG * 2))
        await pilot.pause()
        assert t.selected == 2
        assert t.top == first_row(t.rows, 2)
        top = t.top
        t.step(1)  # more of the tall turn is off screen: read on, three rows
        await pilot.pause()
        assert t.top == top + 3
        assert t.selected == 2
        t.step(-1)
        await pilot.pause()
        assert t.top == top
        t.step(-1)  # the turn's first row is on screen: move to the previous turn
        await pilot.pause()
        assert t.selected == 1
        t.first()
        await pilot.pause()
        assert (t.selected, t.top) == (0, 0)
        t.last()
        await pilot.pause()
        assert t.selected == 2
        assert t.top == first_row(t.rows, 2)


async def test_paging_inside_a_tall_turn_is_never_dragged_back_and_the_selection_follows(
    make_app: Callable[..., LustjinnApp],
) -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app.push_screen(Bare())
        await pilot.pause()
        t = app.screen.query_one(Transcript)
        t.show(turns(LONG * 3, LONG * 2))
        await pilot.pause()
        t.first()
        await pilot.pause()
        t.page(1)
        await pilot.pause()
        assert t.top > 0
        assert t.selected == 0  # still inside the tall turn
        paged = t.top
        t.refresh()
        await pilot.pause()
        assert t.top == paged  # a redraw leaves the viewport where the reader put it
        t.page(1)
        t.page(1)
        await pilot.pause()
        assert t.selected == 1  # the selection followed the scroll into the next turn
        t.page(-1)
        t.page(-1)
        t.page(-1)
        await pilot.pause()
        assert (t.selected, t.top) == (0, 0)


async def test_a_streamed_reply_follows_its_tail_then_lands_on_its_first_row(
    make_app: Callable[..., LustjinnApp],
) -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app.push_screen(Bare())
        await pilot.pause()
        t = app.screen.query_one(Transcript)
        t.show(turns(LONG, "short"))
        await pilot.pause()
        t.begin_pending()
        for _ in range(6):
            t.grow_pending(LONG)
        await pilot.pause()
        assert t.turns == 3
        assert t.top == len(t.rows) - t.scrollable_content_region.height
        t.end_pending()
        t.show([*t.messages, *turns("x", "y", "z")[2:]], land=True)
        await pilot.pause()
        assert t.selected == 2
        # Its first row, as far as a transcript that short can scroll.
        assert t.top == min(first_row(t.rows, 2), len(t.rows) - t.scrollable_content_region.height)
