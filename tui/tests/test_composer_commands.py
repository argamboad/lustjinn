"""Slash commands in the composer, end to end: completion on `/` and Tab, the refusal that
makes no request, the panes, the ask screen and its one key."""

from textual.pilot import Pilot

from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.completion import Strip
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.panes import AskScreen, TextPaneScreen
from lustjinn_tui.status import Kind
from lustjinn_tui.stories import StoriesScreen
from tui_support import fake_server as fake

OPENING = '*The door opens.* "You came," she says.'


def conversation(app: LustjinnApp) -> ConversationScreen:
    screen = app.screen
    assert isinstance(screen, ConversationScreen)
    return screen


async def open_story(app: LustjinnApp, pilot: Pilot[None]) -> ConversationScreen:
    await pilot.pause(0.1)
    assert isinstance(app.screen, StoriesScreen)
    await pilot.press("enter")
    await pilot.pause(0.2)
    return conversation(app)


async def test_a_slash_offers_the_commands_and_tab_completes_the_name(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", "slash")
        await pilot.pause()
        strip = screen.query_one(Strip)
        assert strip.display
        assert strip.offer is not None
        assert [c.display for c in strip.offer.completions][:3] == ["/do", "/focus", "/ask"]
        drawn = strip.render().plain
        assert drawn.startswith(
            "   /do  /focus "
        )  # what fits beside the hint, which keeps its room
        assert drawn.endswith("Tab inserts · ↑↓ chooses · Esc dismisses")
        await pilot.press(*"tr")
        await pilot.pause()
        assert strip.offer is not None
        assert [c.display for c in strip.offer.completions] == ["/tracker", "/trackers"]
        await pilot.press("down", "tab")
        await pilot.pause()
        assert screen.composer.text == "/trackers "
        assert not strip.display
        await pilot.press(*"and/or")  # a slash elsewhere is punctuation
        await pilot.pause()
        assert not strip.display
        await pilot.press("ctrl+u")  # clear the line
        await pilot.press("slash", "escape")  # Esc dismisses the strip first…
        await pilot.pause()
        assert not strip.display
        assert screen.composer.display
        await pilot.press("escape")  # … and the composer only on a second press
        await pilot.pause()
        assert not screen.composer.display


async def test_an_unknown_command_is_refused_and_nothing_is_sent(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        posts = len(server.paths("POST"))
        await pilot.press("i", *"/asl how old", "enter")
        await pilot.pause()
        assert screen.status_line.kind == Kind.WARNING
        assert screen.status_line.text == (
            "There is no /asl command. Type /help for the list, or //asl to send it as a message."
        )
        assert screen.composer.text == "/asl how old"  # kept, to fix
        await pilot.press("ctrl+u", *"/ask", "enter")
        await pilot.pause()
        assert screen.status_line.text == "/ask <question> — nothing has been sent."
        assert len(server.paths("POST")) == posts


async def test_a_doubled_slash_sends_a_message_that_starts_with_one(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"//dance", "enter")
        await pilot.pause(0.3)
        assert [m.text for m in screen.messages][1] == "/dance"


async def test_ask_opens_the_answer_and_f_pins_it_as_a_fact(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", OPENING, "Hi", "Hello.")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"/ask how old is she?", "enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, AskScreen)
        asked = app.screen
        assert asked.aside.question == "how old is she?"
        assert asked.aside.answer == server.answer
        assert asked.legend.text.startswith(" F Pin as a fact")
        assert screen.composer.text == ""  # the draft went once the answer came
        assert len(screen.messages) == 3  # nothing in the story
        await pilot.press("f")
        await pilot.pause(0.2)
        assert asked.pinned
        assert asked.status_line.text.startswith("Pinned under Dummy.")
        assert server.facts[told["id"]][0]["text"] == server.answer
        assert server.facts[told["id"]][0]["subject"] == "Dummy"
        await pilot.press("f")
        await pilot.pause()
        assert asked.status_line.text == "Already pinned."
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)


async def test_a_refused_ask_keeps_the_question(app: LustjinnApp, server: fake.FakeServer) -> None:
    server.add("Tale", OPENING)
    server.commands = [c for c in server.commands if c["name"] != "ask"]  # the server's list wins
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"/ask why", "enter")
        await pilot.pause(0.2)
        assert screen.status_line.text == (
            "There is no /ask command. Type /help for the list, or //ask to send it as a message."
        )
        assert screen.composer.text == "/ask why"


async def test_the_reading_commands_open_panes_or_say_why_not(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", OPENING, "Hi", "Hello.")
    server.shelve("characters", "Dummy", "You are Dummy.\nA test.")
    told["character_id"] = server.library["characters"][0]["id"]
    server.facts[told["id"]] = [
        {
            "id": str(fake.uuid.uuid4()),
            "subject": "Dummy",
            "text": "Is a test.",
            "valid_from_sequence": 1,
            "valid_to_sequence": None,
            "model": None,
            "pinned": False,
        }
    ]
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"/card", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, TextPaneScreen)
        assert app.screen.title == "Character"
        assert list(app.screen.lines) == ["You are Dummy.", "A test."]
        assert app.screen.legend.text.startswith(" ↑↓ PgUp PgDn Scroll")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("i", *"/facts", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, TextPaneScreen)
        assert app.screen.lines[1] == "  · Is a test."
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("i", *"/trackers", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ConversationScreen)  # nothing to show: the status says why
        assert screen.status_line.text.startswith("This story keeps no meters.")
        await pilot.press("i", *"/help", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, TextPaneScreen)
        assert app.screen.title == "Commands"
        assert "  /card" in app.screen.lines
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("i", *"/persona", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ConversationScreen)
        assert screen.status_line.text == "This story has no persona."
        assert screen.composer.text == ""  # a free command's draft goes at once


async def test_search_cost_and_audit_from_the_composer(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", "The fog came in.", "No fog here.", "Clear.")
    server.spend[told["id"]] = ("0.0200", "0")
    server.audits[told["id"]] = {
        "turns": [
            {
                "sequence": 3,
                "sent_at": "2026-10-07T09:00:00Z",
                "hidden": False,
                "model": "m",
                "provider": "Host",
                "estimated_prompt_tokens": 10,
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "context": "character 5 · total 10/100",
            }
        ],
        "asides": [],
    }
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"/search fog", "enter")
        await pilot.pause(0.2)
        assert screen.status_line.text == "2 message(s) match. n for the next one."
        assert screen.transcript.selected == 0
        await pilot.press("i", *"/cost", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, TextPaneScreen)
        assert app.screen.lines[0] == "$0.0200   over 2 billed call(s)"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("i", *"/audit", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, TextPaneScreen)
        assert app.screen.lines[0] == "#3   12 in, 3 out   served by Host"


async def test_recap_opens_a_pane_and_the_writes_say_so(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", OPENING, "Hi", "Hello.")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"/recap", "enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, TextPaneScreen)
        assert app.screen.title == "Recap"
        assert app.screen.lines[0] == "Earlier: the fog came in."
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("i", *"/fact She owns the bar.", "enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConversationScreen)
        assert screen.status_line.text.startswith("Pinned under Dummy.")
        assert server.facts[told["id"]][0]["text"] == "She owns the bar."
        assert screen.composer.text == ""
        assert len(screen.messages) == 3
        await pilot.press("i", *"/tracker Trust 7", "enter")
        await pilot.pause(0.3)
        assert screen.status_line.text == "Trust is now 7."
        await pilot.press("i", *"/tracker Trust lots", "enter")
        await pilot.pause(0.3)
        assert screen.status_line.kind == Kind.ERROR
        assert screen.composer.text == "/tracker Trust lots"  # refused: the draft stays


async def test_do_with_a_message_under_it_stores_the_message_only(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"/do skip to the evening", "alt+enter", "alt+enter", *"Fine.")
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert [m.text for m in screen.messages] == [OPENING, "Fine.", server.reply]
        await pilot.press("i", *"/focus Marta", "enter")
        await pilot.pause(0.3)
        assert [m.role for m in screen.messages][-2:] == ["assistant", "assistant"]
