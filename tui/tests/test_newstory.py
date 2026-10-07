"""The new-story screen: the pickers read the library, the panels show the card and the
persona, Enter walks the fields, and creating opens the story. The donor's
``NewChatFlowTests``, for the parts the API kept."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from lustjinn_tui.api import Choice
from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.confirm import ConfirmScreen
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.newstory import NewStoryScreen, Panel, Picker, default_name
from lustjinn_tui.status import Kind
from lustjinn_tui.stories import StoriesScreen
from tui_support import fake_server as fake

WORLD = "You are Elena. " + "The resort sits on a cliff. " * 40
PERSONA = "A tall man in his forties, quiet."


def form(app: LustjinnApp) -> NewStoryScreen:
    screen = app.screen
    assert isinstance(screen, NewStoryScreen)
    return screen


def library(server: fake.FakeServer) -> None:
    server.shelve("characters", "Elena", WORLD, opening="*The door opens.*")
    server.shelve("characters", "Marta", "You are Marta.")
    server.default_persona = server.shelve("personas", "Me", PERSONA)
    server.shelve("personas", "Someone else", "A stranger.")


async def test_the_pickers_read_the_library_and_the_panels_show_what_will_be_sent(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    library(server)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("n")
        await pilot.pause(0.2)
        screen = form(app)
        assert screen.picker("character").choices == ["Elena", "Marta"]
        assert screen.picker("persona").choices == ["(default: Me)", "Me", "Someone else"]
        assert screen.picker("model").choices[0] == f"(default: {fake.DEFAULT_MODEL})"
        assert screen.picker("model").choices[1:] == [
            "thedrummer/anubis-70b  ≈2× the default",
            "mistralai/mistral-small  ≈1/2 of the default",
        ]
        # The default persona is on screen before anything is picked, beside the world.
        assert screen.query_one("#world", Panel).text == WORLD
        assert screen.query_one("#persona-text", Panel).text == PERSONA
        assert screen.query_one("#world", Panel).display
        assert screen.query_one("#persona-text", Panel).display
        assert screen.legend.text.startswith(" Tab Next field   ←→ Pick")


async def test_picking_changes_the_panels_and_the_page_keys_follow_the_focus(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    library(server)
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("n")
        await pilot.pause(0.2)
        screen = form(app)
        await pilot.press("tab")  # from the name to the character
        assert screen.focused is screen.picker("character")
        await pilot.press("right")
        await pilot.pause(0.1)
        assert screen.character is not None
        assert screen.character.name == "Marta"
        assert screen.query_one("#world", Panel).text == "You are Marta."
        await pilot.press("right")  # wraps round
        await pilot.pause(0.1)
        assert screen.query_one("#world", Panel).text == WORLD
        world_scroll = screen.query_one("#world", Panel).query_one("VerticalScroll")
        await pilot.press("pagedown")
        await pilot.pause()
        assert world_scroll.scroll_y > 0
        await pilot.press("pageup")
        await pilot.pause()
        assert world_scroll.scroll_y == 0
        await pilot.press("tab", "right", "right")  # the persona
        await pilot.pause(0.1)
        assert screen.persona is not None
        assert screen.persona.name == "Someone else"
        assert screen.query_one("#persona-text", Panel).text == "A stranger."
        await pilot.press("left", "left")
        await pilot.pause(0.1)
        assert screen.persona is None
        assert screen.query_one("#persona-text", Panel).text == PERSONA


async def test_the_whole_flow_creates_a_story_and_opens_it(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    library(server)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.press(*"Cliffs", "enter")  # Enter walks the fields
        screen = form(app)
        assert screen.focused is screen.picker("character")
        await pilot.press("enter", "right", "right", "enter", "right", "enter")  # the last creates
        await pilot.pause(0.2)
        assert isinstance(app.screen, ConversationScreen)
        story = app.screen.story
        assert story.name == "Cliffs"
        assert story.character_name == "Elena"
        assert story.persona_name == "Someone else"
        assert story.model == "thedrummer/anubis-70b"
        assert app.screen.status_line.text == '"Cliffs" started.'
        assert app.screen.status_line.kind == Kind.SUCCESS
        assert [s.__class__ for s in app.screen_stack] == [StoriesScreen, ConversationScreen]
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert isinstance(app.screen, StoriesScreen)
        assert [s.name for s in app.screen.rows.items] == ["Cliffs"]


async def test_ctrl_s_creates_from_anywhere_and_a_nameless_story_is_named_after_the_character(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    library(server)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.press("ctrl+s")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ConversationScreen)
        assert app.screen.story.name.startswith("Elena, ")
        assert app.screen.story.persona_id is None  # the default, left to the server
        assert app.screen.story.model is None


def test_the_default_name_is_the_character_and_the_day() -> None:
    assert default_name("Elena", datetime(2026, 10, 7)) == "Elena, 7 October"


async def test_an_empty_library_is_a_warning_not_a_crash(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("n")
        await pilot.pause(0.2)
        screen = form(app)
        assert screen.status_line.kind == Kind.WARNING
        await pilot.press("ctrl+s")
        await pilot.pause(0.1)
        assert isinstance(app.screen, NewStoryScreen)
        assert "POST /stories" not in server.paths()


async def test_escape_with_nothing_typed_closes_and_with_something_typed_asks_first(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    library(server)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, StoriesScreen)
        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.press(*"Dra", "escape")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("escape")  # keep the form
        await pilot.pause()
        assert isinstance(app.screen, NewStoryScreen)
        await pilot.press("escape", "enter")  # throw it away
        await pilot.pause()
        assert isinstance(app.screen, StoriesScreen)


async def test_a_refused_creation_keeps_the_form_with_the_servers_sentence(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    library(server)
    server.models.append(fake.choice("gone/model"))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("n")
        await pilot.pause(0.2)
        server.models.pop()  # the server stops listing it between the read and the create
        screen = form(app)
        screen.picker("model").index = 3
        await pilot.press("ctrl+s")
        await pilot.pause(0.1)
        assert isinstance(app.screen, NewStoryScreen)
        assert screen.status_line.kind == Kind.ERROR
        assert screen.status_line.text.startswith("gone/model is not available")


async def test_the_model_list_is_never_waited_for(
    make_app: Callable[..., LustjinnApp], server: fake.FakeServer
) -> None:
    library(server)
    server.models_unreadable = True
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("n")
        await pilot.pause(0.2)
        screen = form(app)
        assert screen.picker("model").choices == ["(default)"]
        assert screen.status_line.kind != Kind.ERROR
        await pilot.press("ctrl+s")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ConversationScreen)


def test_a_choice_describes_its_price_against_the_default() -> None:
    assert Choice(id="a", is_default=True).describe() == "a"
    assert Choice(id="a", prompt_price_ratio=None).describe() == "a"
    assert Choice(id="a", prompt_price_ratio=Decimal(2)).describe() == "a  ≈2× the default"
    assert Choice(id="a", prompt_price_ratio=Decimal("0.25")).describe() == "a  ≈1/4 of the default"
    assert Choice(id="a", prompt_price_ratio=Decimal("1.1")).describe() == "a  about the default"


async def test_picker_steps_wrap_and_a_lone_choice_stays_put() -> None:
    picker = Picker("Thing", ["one", "two", "three"], id="p")
    picker.action_step(-1)
    assert picker.value == "three"
    picker.action_step(1)
    assert picker.value == "one"
    picker.set_choices(["only"])
    picker.action_step(1)
    assert picker.value == "only"
