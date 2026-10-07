"""The API client: sign-in and the stored token, refusals as exceptions, a streamed reply."""

import pytest

from lustjinn_tui.api import Api, ApiError, Delta, SignedOutError, TurnDone, UnreachableError
from lustjinn_tui.config import TokenStore
from tui_support import fake_server as fake


async def test_signing_in_stores_the_token_and_sends_it_from_then_on(
    api: Api, server: fake.FakeServer, tokens: TokenStore
) -> None:
    assert not api.signed_in
    issued = await api.sign_in(fake.USERNAME, fake.PASSWORD)
    assert issued.access_token == fake.TOKEN
    assert tokens.read() == fake.TOKEN
    assert api.signed_in
    server.add("First")
    listed = await api.stories()
    assert [s.name for s in listed] == ["First"]
    assert server.requests[-1].headers["Authorization"] == f"Bearer {fake.TOKEN}"


async def test_a_wrong_password_is_a_refusal_with_the_servers_sentence(api: Api) -> None:
    with pytest.raises(ApiError) as refused:
        await api.sign_in(fake.USERNAME, "nope")
    assert refused.value.status == 401
    assert refused.value.detail == "That is not the username and password."
    assert not api.signed_in


async def test_a_401_on_a_call_forgets_the_token(
    api: Api, server: fake.FakeServer, tokens: TokenStore
) -> None:
    tokens.write("stale")
    with pytest.raises(SignedOutError) as out:
        await api.stories()
    assert out.value.detail == "The token is not valid. Sign in again."
    assert tokens.read() is None


async def test_a_server_that_cannot_be_reached_is_unreachable(
    api: Api, server: fake.FakeServer
) -> None:
    server.down = True
    with pytest.raises(UnreachableError):
        await api.health()


async def test_health_needs_no_token(api: Api) -> None:
    assert (await api.health()).status == "ok"


async def test_a_reply_streams_in_pieces_then_says_what_was_stored(
    api: Api, server: fake.FakeServer, tokens: TokenStore
) -> None:
    tokens.write(fake.TOKEN)
    told = server.add("Tale", "An opening.")
    events = [event async for event in api.send(told["id"], "Hello there")]
    deltas = [e.text for e in events if isinstance(e, Delta)]
    assert "".join(deltas) == server.reply
    assert len(deltas) >= 3
    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.sent is not None
    assert done.sent.text == "Hello there"
    assert done.reply.text == server.reply
    assert server.requests[-1].url.path == f"/stories/{told['id']}/send"


async def test_a_refused_stream_raises_before_any_event(
    api: Api, server: fake.FakeServer, tokens: TokenStore
) -> None:
    tokens.write(fake.TOKEN)
    with pytest.raises(ApiError) as refused:
        _ = [e async for e in api.carry_on(fake.uuid.uuid4())]
    assert refused.value.status == 404
