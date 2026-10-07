"""The composer's commands, decided on the client: the donor's ``SlashCommandTests`` and the
pane builders' lines."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from lustjinn_tui.api import AsideAudit, Audit, ByKind, Fact, Hit, StorySpend, Tracker, TurnAudit
from lustjinn_tui.commands import (
    LOCAL,
    SHIPPED,
    Command,
    Commands,
    Incomplete,
    Prose,
    Unknown,
    audit_report,
    command_being_typed,
    cost_report,
    facts_report,
    page_report,
    search_report,
    trackers_report,
)


def test_prose_is_sent_and_a_doubled_slash_sends_a_literal_one() -> None:
    commands = Commands()
    assert commands.parse("  Hello there  ") == Prose("Hello there")
    assert commands.parse("//ask is a message") == Prose("/ask is a message")


def test_a_known_command_carries_its_argument_and_knows_where_it_runs() -> None:
    commands = Commands()
    parsed = commands.parse("/ask  how old is she?")
    assert parsed == Command(SHIPPED[2], "how old is she?", local=False)
    assert commands.parse("/ASK why") == Command(SHIPPED[2], "why", local=False)
    parsed = commands.parse("/facts")
    assert isinstance(parsed, Command)
    assert parsed.local
    assert parsed.spec.name == "facts"
    parsed = commands.parse("/do\nskip to the evening")  # a newline ends the name too
    assert parsed == Command(SHIPPED[0], "skip to the evening", local=False)


def test_an_unknown_command_is_refused_and_a_missing_argument_too() -> None:
    commands = Commands()
    assert commands.parse("/asl how old") == Unknown("asl")
    assert commands.parse("/") == Unknown("")
    assert commands.parse("/ask") == Incomplete(SHIPPED[2])
    assert commands.parse("/ask   ") == Incomplete(SHIPPED[2])
    assert commands.parse("/help") == Command(LOCAL[-1], "", local=True)


def test_the_servers_list_replaces_the_shipped_one_and_the_local_ones_stay() -> None:
    from lustjinn_tui.api import Spec

    commands = Commands(
        [Spec(name="zap", usage="/zap", summary="New", cost="free", needs_argument=False)]
    )
    assert commands.parse("/zap") == Command(commands.remote[0], "", local=False)
    assert commands.parse("/ask x") == Unknown("ask")
    assert [s.name for s in commands.matching("")][:2] == ["zap", "card"]


def test_matching_is_a_prefix_match_in_the_helps_order() -> None:
    commands = Commands()
    assert [s.name for s in commands.matching("f")] == ["focus", "fact", "facts"]
    assert [s.name for s in commands.matching("tr")] == ["tracker", "trackers"]
    assert commands.matching("zzz") == []


def test_the_command_being_typed_is_only_at_the_very_start() -> None:
    assert command_being_typed("/as", 3, first_line=True) == "as"
    assert command_being_typed("/", 1, first_line=True) == ""
    assert command_being_typed("/ask how", 8, first_line=True) is None  # past the space
    assert command_being_typed("/ask how", 3, first_line=True) == "as"
    assert command_being_typed("//ask", 3, first_line=True) is None
    assert command_being_typed("/ask", 3, first_line=False) is None
    assert command_being_typed("and/or", 4, first_line=True) is None
    assert command_being_typed("/ask", 0, first_line=True) is None


def test_help_lines_group_by_cost_and_end_with_the_doubled_slash() -> None:
    lines = Commands().help_lines()
    assert lines[0] == "Billed — these call the model"
    assert lines[1] == "  /do <direction>"
    assert "These write to the story" in lines
    assert "Free — these only read what is already here" in lines
    assert lines[-1].startswith("A message that genuinely starts with a slash")


def fact(subject: str, text: str, *, since: int = 1, until: int | None = None) -> Fact:
    return Fact(
        id=uuid.uuid4(),
        subject=subject,
        text=text,
        valid_from_sequence=since,
        valid_to_sequence=until,
        pinned=until is None and since == 1,
    )


def test_facts_are_grouped_by_subject_in_order_and_retired_ones_are_counted() -> None:
    report = facts_report(
        [
            fact("Marta", "Owns the bar.", since=4),
            fact("Elena", "Is twenty-nine."),
            fact("Elena", "Moved to the coast.", since=9),
            fact("Elena", "Hates rain.", since=2, until=8),
        ]
    )
    assert report.subtitle == "3 live, 1 retired"
    assert list(report.lines) == [
        "Elena",
        "  · Is twenty-nine.  (pinned)",
        "  · Moved to the coast.",
        "",
        "Marta",
        "  · Owns the bar.",
        "",
    ]
    assert facts_report([]).is_empty
    assert facts_report([]).subtitle.startswith("Nothing is being injected")


def test_trackers_say_where_each_meter_stands() -> None:
    meters = [
        Tracker(id=uuid.uuid4(), name="Trust", value=6, max=10, delta=2, note="she let him in"),
        Tracker(id=uuid.uuid4(), name="Heat", value=3.5, max=10),
    ]
    report = trackers_report(meters)
    assert report.subtitle == "2 meter(s)"
    assert list(report.lines) == [
        "Trust  6 / 10   last moved +2",
        "  she let him in",
        "",
        "Heat  3.5 / 10",
        "",
    ]
    assert trackers_report([]).is_empty


def test_the_audit_lists_turns_newest_first_with_their_context_then_the_questions() -> None:
    when = datetime(2026, 10, 7, tzinfo=UTC)
    audit = Audit(
        turns=[
            TurnAudit(
                sequence=8,
                sent_at=when,
                hidden=True,
                provider="DeepInfra",
                prompt_tokens=2360,
                completion_tokens=180,
                context="character 2000 · history 300 · total 2300/6000",
            ),
            TurnAudit(sequence=6, sent_at=when, prompt_tokens=None, completion_tokens=None),
        ],
        asides=[AsideAudit(sequence=7, asked_at=when, prompt_tokens=100, completion_tokens=20)],
    )
    report = audit_report(audit)
    assert report.subtitle == "2 turn(s), 1 question(s)"
    assert report.lines[0] == "#8  (rolled back)   2,360 in, 180 out   served by DeepInfra"
    assert report.lines[1] == "  character 2000 · history 300 · total 2300/6000"
    assert report.lines[3] == "#6   ? in, ? out   served by unknown"
    assert report.lines[-2] == "Questions asked out of character"
    assert report.lines[-1] == "  · #7   100 in, 20 out   served by unknown"
    assert audit_report(Audit(turns=[])).is_empty


def test_the_cost_pane_breaks_the_bill_down() -> None:
    spend = StorySpend(
        story_id=uuid.uuid4(),
        name="Tale",
        calls=12,
        cost=Decimal("0.0456"),
        discarded_calls=2,
        discarded_cost=Decimal("0.0030"),
        prompt_tokens=50000,
        completion_tokens=4000,
        cached_share=0.42,
        unpriced=1,
        by_kind=[
            ByKind(kind="reply", calls=9, cost=Decimal("0.04")),
            ByKind(kind="summary", calls=3, cost=Decimal("0.0056")),
        ],
    )
    report = cost_report(spend)
    assert report.subtitle == "Tale"
    assert report.lines[0] == "$0.0456   over 12 billed call(s)"
    assert report.lines[2] == "  replies       $0.0400   9 call(s)"
    assert report.lines[3] == "  compression   $0.0056   3 call(s)"
    assert report.lines[5] == "  tokens        50,000 in, 4,000 out"
    assert report.lines[6] == "  cached        42% of the prompt was served from cache"
    assert "went on 2 reply(ies)" in report.lines[8]
    assert "1 call(s) came back with no price" in report.lines[10]
    assert cost_report(None).is_empty


def test_search_and_page_reports() -> None:
    sid = uuid.uuid4()
    hits = [
        Hit(scope="name", story_id=sid, story_name="Tale", snippet="Tale"),
        Hit(
            scope="message",
            story_id=sid,
            story_name="Tale",
            sequence=3,
            role="user",
            snippet="…fog…",
        ),
        Hit(
            scope="message",
            story_id=sid,
            story_name="Tale",
            sequence=4,
            role="assistant",
            speaker="Elena",
            snippet="…the fog…",
        ),
    ]
    report = search_report(hits, " fog ", "Elena")
    assert report.subtitle == '2 turn(s) with "fog"'
    assert list(report.lines) == ["#3 You: …fog…", "#4 Elena: …the fog…"]
    assert search_report([], "fog", "Elena").subtitle == '"fog" is not in this story.'
    page = page_report("Character", "Line one.\nLine two.", "none")
    assert list(page.lines) == ["Line one.", "Line two."]
    assert page_report("Persona", None, "This story has no persona.").subtitle == (
        "This story has no persona."
    )
