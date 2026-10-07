from datetime import UTC, datetime, timedelta

from lustjinn_tui.textfmt import age, count, fit, pad

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_age_reads_as_the_donor_drew_it() -> None:
    assert age(None, NOW) == "—"
    assert age(NOW - timedelta(seconds=30), NOW) == "just now"
    assert age(NOW - timedelta(minutes=5), NOW) == "5m ago"
    assert age(NOW - timedelta(hours=3), NOW) == "3h ago"
    assert age(NOW - timedelta(days=12), NOW) == "12d ago"
    assert age(NOW - timedelta(days=40), NOW) == "2026-08-28"
    assert age(NOW + timedelta(days=1), NOW) == "2026-10-08"  # the future is a date


def test_fit_cuts_with_an_ellipsis_only_when_it_must() -> None:
    assert fit("short", 10) == "short"
    assert fit("a longer name", 8) == "a longe…"
    assert fit("anything", 1) == "…"
    assert fit("anything", 0) == ""
    assert fit("日本語テキスト", 7) == "日本語…"  # wide characters count twice


def test_pad_lines_columns_up() -> None:
    assert pad("ab", 5) == "ab   "
    assert pad("a longer name", 5) == "a lo…"


def test_count_pluralises() -> None:
    assert count(1, "story", "stories") == "1 story"
    assert count(2, "story", "stories") == "2 stories"
    assert count(0, "chat") == "0 chats"
