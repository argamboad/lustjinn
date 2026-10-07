"""The gate: the lamp while the server wakes, sign-in without a token, the stories once in; a
401 later sends the reader back to sign in, a lost server back to the lamp."""

from collections.abc import Callable

from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.config import TokenStore
from lustjinn_tui.signin import SignInScreen
from lustjinn_tui.status import StatusLine
from lustjinn_tui.stories import StoriesScreen
from lustjinn_tui.waking import WakingScreen
from tui_support import fake_server as fake


async def test_the_lamp_shows_until_the_server_answers_then_the_stories(
    make_app: Callable[..., LustjinnApp], server: fake.FakeServer
) -> None:
    server.asleep_for = 1000
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.screen, WakingScreen)
        assert app.screen.query_one(StatusLine).is_busy
        knocked = len([r for r in server.requests if r.url.path == "/health"])
        assert knocked >= 2  # it keeps knocking
        server.asleep_for = 0
        await pilot.pause(0.3)
        assert isinstance(app.screen, StoriesScreen)


async def test_without_a_token_the_reader_signs_in_and_letters_type_into_the_fields(
    make_app: Callable[..., LustjinnApp], tokens: TokenStore
) -> None:
    app = make_app(signed_in=False)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.screen, SignInScreen)
        await pilot.press(*"quit")  # q is quit while navigating, but this is a text field
        assert isinstance(app.screen, SignInScreen)
        await pilot.press("backspace", "backspace", "backspace", "backspace")
        await pilot.press(*fake.USERNAME, "enter")
        await pilot.press(*fake.PASSWORD, "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, StoriesScreen)
    assert tokens.read() == fake.TOKEN


async def test_a_wrong_password_stays_on_the_screen_with_the_servers_sentence(
    make_app: Callable[..., LustjinnApp],
) -> None:
    app = make_app(signed_in=False)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await pilot.press(*fake.USERNAME, "enter", *"wrong", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, SignInScreen)
        assert app.screen.status_line.text == "That is not the username and password."


async def test_a_401_later_sends_the_reader_back_to_sign_in(
    app: LustjinnApp, server: fake.FakeServer, tokens: TokenStore
) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.screen, StoriesScreen)
        server.revoke()
        result = await app.call("Refreshing", app.api.stories())
        await pilot.pause()
        assert result is None
        assert isinstance(app.screen, SignInScreen)
        assert tokens.read() is None
        assert "Sign in again" in str(app.screen.query_one(".note").render())


async def test_a_lost_server_sends_the_reader_back_to_the_lamp(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        server.down = True
        await app.call("Refreshing", app.api.stories())
        await pilot.pause()
        assert isinstance(app.screen, WakingScreen)
        server.down = False
        await pilot.pause(0.2)
        assert isinstance(app.screen, StoriesScreen)


async def test_a_refusal_lands_in_the_status_row(app: LustjinnApp, server: fake.FakeServer) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        await app.call("Opening", app.api.story(fake.uuid.uuid4()))
        await pilot.pause()
        assert isinstance(app.screen, StoriesScreen)
        assert app.screen.status_line.text == "There is no such story."
