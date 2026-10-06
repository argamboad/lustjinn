"""The reading of a composed line into a command.

The stakes are asymmetric, and every test here is about the expensive direction. Reading a
command as prose sends it: it is billed, it lands in an append-only transcript as a line the
character has to react to, and nothing can take it back. Reading prose as a command only costs
a re-typed message.
"""

import httpx2

from lustjinn.commands import COMMANDS, Command, Incomplete, Prose, Unknown, find, parse


def test_ordinary_prose_is_a_message() -> None:
    assert parse("She looks up and/or laughs. 10:30 on the dot.") == Prose(
        "She looks up and/or laughs. 10:30 on the dot."
    )


def test_a_command_is_recognised_with_its_argument() -> None:
    parsed = parse("/ask what has Nicole not said out loud yet?")

    assert isinstance(parsed, Command)
    assert parsed.spec.name == "ask"
    assert parsed.argument == "what has Nicole not said out loud yet?"


def test_the_case_of_the_name_does_not_matter() -> None:
    parsed = parse("/ASK who is she")

    assert isinstance(parsed, Command)
    assert parsed.spec.name == "ask"


def test_an_unknown_command_is_refused_rather_than_sent() -> None:
    """The whole reason commands are parsed before anything is sent. A typed /aks would
    otherwise cost what the message would have cost and stay in the transcript for good."""
    assert parse("/aks what has she not said") == Unknown("aks")
    assert parse("/sak") == Unknown("sak")


def test_a_doubled_slash_sends_prose_with_one_slash_left() -> None:
    assert parse("//ask is what I would type on the other site") == Prose(
        "/ask is what I would type on the other site"
    )


def test_only_the_first_column_opens_a_command() -> None:
    """A slash mid-sentence is punctuation. Opening a command there would make half the
    messages in this application unsendable."""
    assert parse("She said /do it and left.") == Prose("She said /do it and left.")


def test_a_command_whose_argument_starts_on_the_next_line_is_still_that_command() -> None:
    parsed = parse("/ask\nwhere is the lighthouse?")

    assert isinstance(parsed, Command)
    assert parsed.argument == "where is the lighthouse?"


def test_a_command_that_needs_an_argument_is_incomplete_without_one() -> None:
    parsed = parse("/ask")

    assert isinstance(parsed, Incomplete)
    assert parsed.spec.usage == "/ask <question>"
    assert parse("/ask   \n ") == parsed


def test_surrounding_whitespace_is_trimmed_everywhere() -> None:
    assert parse("  Hello.  ") == Prose("Hello.")
    parsed = parse("  /ask   who?  ")
    assert isinstance(parsed, Command)
    assert parsed.argument == "who?"


def test_a_lone_slash_is_an_unknown_command_with_no_name() -> None:
    assert parse("/") == Unknown("")


def test_every_command_has_a_usage_line_starting_with_its_own_name() -> None:
    """The usage strings are what a missing argument quotes back. One that named a different
    command would send the reader to the wrong place."""
    for spec in COMMANDS:
        assert spec.usage.startswith(f"/{spec.name}")
        assert spec.summary


def test_no_two_commands_share_a_name() -> None:
    names = [spec.name for spec in COMMANDS]

    assert len(set(names)) == len(names)
    assert find("ask") is not None
    assert find("ASK") is find("ask")
    assert find("do") is not None


async def test_the_api_lists_the_commands_it_enforces(client: httpx2.AsyncClient) -> None:
    """A composer builds its palette from this, so it never shows a command the API refuses."""
    response = await client.get("/commands")

    assert response.status_code == 200
    listed = response.json()
    assert [c["name"] for c in listed] == [spec.name for spec in COMMANDS]
    recap = next(c for c in listed if c["name"] == "recap")
    assert recap == {
        "name": "recap",
        "usage": "/recap [turns]",
        "summary": recap["summary"],
        "cost": "free",
        "needs_argument": False,
    }
    assert {c["cost"] for c in listed} == {"free", "billed", "write"}


async def test_the_list_needs_a_token(anonymous: httpx2.AsyncClient) -> None:
    assert (await anonymous.get("/commands")).status_code == 401
