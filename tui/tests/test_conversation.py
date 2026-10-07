"""The conversation screen: a story read, written, streamed, regenerated, searched, branched and
cut, against the fake server."""

from textual import events

from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.composer import Composer
from lustjinn_tui.confirm import ConfirmScreen
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.regenerate import REASONS, RegenerateScreen
from lustjinn_tui.status import Kind
from lustjinn_tui.stories import StoriesScreen
from lustjinn_tui.transcript import Transcript
from tui_support import fake_server as fake

OPENING = '*The door opens.* "You came," she says.'


def conversation(app: LustjinnApp) -> ConversationScreen:
    screen = app.screen
    assert isinstance(screen, ConversationScreen)
    return screen


def header(app: LustjinnApp) -> str:
    return str(conversation(app).query_one("#header").render())


def texts(app: LustjinnApp) -> list[str]:
    return [m.text for m in conversation(app).messages]


async def open_story(app: LustjinnApp, pilot: object) -> ConversationScreen:
    from textual.pilot import Pilot

    assert isinstance(pilot, Pilot)
    await pilot.pause(0.1)
    assert isinstance(app.screen, StoriesScreen)
    await pilot.press("enter")
    await pilot.pause(0.2)
    return conversation(app)


async def test_the_story_opens_on_its_newest_turn_with_the_header_and_the_cost(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", OPENING, "I did.", "She smiles.")
    server.spend[told["id"]] = ("0.0123", "0.0010")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        assert texts(app) == [OPENING, "I did.", "She smiles."]
        assert screen.transcript.selected == 2
        assert screen.status_line.text == "1 from you, 2 replies."
        lines = header(app).splitlines()
        assert lines[0].startswith("message 3/3  ·  1 yours  ·  2 replies  ·  2 words in this one")
        assert lines[1] == "Dummy  ·  as Me"
        assert lines[2] == "$0.0123  ($0.0010 rerolled away)"
        assert screen.summary() == "3/3 · $0.0123"
        assert screen.legend.text.startswith(" I / Enter Write a message")
        column = screen.query_one("#column")
        assert column.size.width == 60  # three fifths of a hundred
        drawn = "\n".join(screen.transcript.render_line(y).text for y in range(6))
        assert " Dummy " in drawn
        assert "The door opens. You came, she says." in drawn  # markers gone, prose styled


async def test_the_arrows_and_pages_move_and_the_header_follows(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING, "One.", "Two.", "Three.")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("up", "up")
        await pilot.pause()
        assert screen.transcript.selected == 1
        assert header(app).startswith("message 2/4")
        await pilot.press("home")
        await pilot.pause()
        assert header(app).startswith("message 1/4")
        await pilot.press("end")
        await pilot.pause()
        assert header(app).startswith("message 4/4")


async def test_writing_sends_on_enter_and_the_reply_streams_in(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    server.reply = "She looks up. *A pause.* Then she laughs."
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i")
        await pilot.pause()
        assert screen.composer.display
        assert screen.focused is screen.composer
        assert screen.legend.text.startswith(" Enter Send   Alt+Enter New line")
        await pilot.press(*"Hello", "alt+enter", *"there")
        await pilot.pause()
        assert screen.composer.text == "Hello\nthere"
        assert "11 characters · 2 words" in str(screen.query_one("Caption").render())
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert texts(app)[-2:] == ["Hello\nthere", server.reply]
        assert screen.composer.text == ""  # the draft went with the send
        assert screen.status_line.text == "Reply received."
        assert screen.status_line.kind == Kind.SUCCESS
        assert screen.transcript.selected == 2
        assert header(app).startswith("message 3/3")
        assert not screen.composer.display
        assert server.paths("POST")[-1].endswith("/send")


async def test_a_paste_with_line_breaks_is_text_not_a_send(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i")
        await pilot.pause()
        app.post_message(events.Paste("line one\nline two\n"))  # as the terminal delivers it
        await pilot.pause()
        assert screen.composer.text == "line one\nline two\n"
        assert "POST" not in " ".join(server.paths())


async def test_esc_keeps_the_draft_and_a_failed_turn_keeps_or_stores_it(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"Draft", "escape")
        await pilot.pause()
        assert not screen.composer.display
        assert screen.status_line.text == "Draft kept. Press I to carry on writing."
        await pilot.press("i")
        await pilot.pause()
        assert screen.composer.text == "Draft"
        server.model_fails = "The model did not answer: timed out. Your message was kept."
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert screen.status_line.kind == Kind.ERROR
        assert screen.status_line.text.startswith("The model did not answer")
        assert texts(app)[-1] == "Draft"  # stored by the server, so it is in the transcript
        assert screen.composer.text == ""  # and the draft went with it
        assert screen.transcript.pending is None


async def test_a_refusal_before_the_stream_keeps_the_draft(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"Keep me")
        server.stories.clear()  # the story is gone: a 404 before anything streams
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert screen.status_line.text == "There is no such story."
        assert screen.composer.text == "Keep me"


async def test_carry_on_needs_a_reply_and_then_streams_one(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("greater_than_sign")
        await pilot.pause()
        assert screen.status_line.text == "There is no reply to carry on from yet."
        server.stories[0]["messages"].append(fake.message(1, "assistant", OPENING))
        await pilot.press("r")
        await pilot.pause(0.2)
        await pilot.press("greater_than_sign")
        await pilot.pause(0.3)
        assert texts(app) == [OPENING, server.reply]
        assert server.paths("POST")[-1].endswith("/continue")


async def test_regenerate_asks_for_a_reason_and_replaces_the_reply(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING, "Hi", "Old reply.")
    server.reply = "New reply."
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("g")
        await pilot.pause()
        assert isinstance(app.screen, RegenerateScreen)
        regen = app.screen
        assert "Old reply." in str(regen.query_one(".replacing").render())
        assert regen.reasons.reason.value == "steer"
        await pilot.press("down", "down")
        assert regen.reasons.reason.value == "looping"
        await pilot.press("i")
        await pilot.pause()
        assert regen.legend.text.startswith(" Esc Done writing")
        await pilot.press(*"less", "enter", *"please", "escape")
        await pilot.pause()
        assert regen.instructions == "less\nplease"
        assert regen.legend.text.startswith(" ↑ ↓ Choose a reason")
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConversationScreen)
        assert texts(app) == [OPENING, "Hi", "New reply."]
        assert server.reroll_bodies == [{"reason": "looping", "instructions": "less\nplease"}]
        assert screen.status_line.text == "Reply received."
        assert REASONS[0].value == "none"


async def test_the_opening_is_not_regenerated(app: LustjinnApp, server: fake.FakeServer) -> None:
    told = server.add("Tale", OPENING)
    told["messages"][0]["model"] = None
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("g")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)
        assert screen.status_line.text.startswith("The opening is not rerolled")
        assert "reroll" not in " ".join(server.paths())


async def test_search_finds_counts_and_steps_round_the_matches(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", "The fog came in.", "No fog here.", "Clear skies.", "Fog again.")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("slash", *"fog", "enter")
        await pilot.pause()
        assert screen.status_line.text == "3 message(s) match."
        assert screen.transcript.selected == 0  # from the last turn, the next match wraps round
        assert 'filter "fog"' in header(app)
        await pilot.press("n")
        await pilot.pause()
        assert screen.transcript.selected == 1
        await pilot.press("N")  # in the Standard dialect both n and N find the next match
        await pilot.pause()
        assert screen.transcript.selected == 3
        await pilot.press("escape")
        await pilot.pause()
        assert screen.status_line.text == "Filter cleared."
        assert "filter" not in header(app)
        await pilot.press("slash", *"dragon", "enter")
        await pilot.pause()
        assert screen.status_line.text == '"dragon" is not in this story.'
        await pilot.press("escape", "n")
        await pilot.pause()
        assert screen.status_line.text == "No active search."


async def test_branch_names_a_copy_and_delete_from_asks_first(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING, "One.", "Two.", "Three.")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("up", "up", "b")
        await pilot.pause()
        assert screen.query_one("#branch").display
        assert screen.legend.text.startswith(" Enter Create the branch")
        await pilot.press("enter")  # the seeded name
        await pilot.pause(0.2)
        assert screen.status_line.text == 'Branched as "Tale (2)": it is in the list of stories.'
        assert [s["name"] for s in server.stories] == ["Tale", "Tale (2)"]
        assert [m["text"] for m in server.stories[1]["messages"]] == [OPENING, "One."]
        await pilot.press("delete")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        question = str(app.screen.query_one(".question").render())
        assert question == "Delete this message and the 2 after it?"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert texts(app) == [OPENING]
        assert screen.status_line.text == "Deleted 3 message(s). 1 remain."


async def test_copy_puts_the_selected_turn_on_the_clipboard(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING, "Mine.")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("c")
        await pilot.pause()
        assert screen.status_line.text == "Message copied to the clipboard."
        assert app.clipboard == "Mine."


async def test_esc_while_waiting_stops_and_says_the_message_went(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        screen._pending_label = "Sending"  # pyright: ignore[reportPrivateUsage]
        screen.transcript.begin_pending()
        screen.status_line.busy("Sending")
        await pilot.pause()
        assert screen.transcript.pending is not None
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)
        assert screen.status_line.text.startswith("Stopped waiting.")
        assert screen.transcript.pending is None


async def test_the_composer_and_transcript_widgets_exist_once(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        assert len(screen.query(Composer)) == 1
        assert len(screen.query(Transcript)) == 1
