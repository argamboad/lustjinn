"""The donor's FuzzyMatcher tests, in Python."""

from lustjinn_tui.fuzzy import Match, match, match_all_terms, rank


def score(query: str, candidate: str) -> int:
    found = match(query, candidate)
    assert found is not None
    return found.score


def test_a_subsequence_matches_case_folded_and_anything_else_does_not() -> None:
    assert match("prof", "Professor") is not None
    assert match("psr", "Professor") is not None
    assert match("PROF", "professor") is not None
    assert match("", "anything") == Match(0, ())
    assert match("xyz", "Professor") is None
    assert match("rp", "Professor") is None
    assert match("professorx", "Professor") is None
    assert match("a", "") is None


def test_positions_are_where_the_characters_were_taken() -> None:
    found = match("pf", "Professor")
    assert found is not None
    assert found.positions == (0, 3)


def test_the_score_prefers_prefixes_word_starts_and_literal_runs() -> None:
    assert score("prof", "Professor") > score("prof", "Purple Roof Of Fame")
    assert score("cap", "Captain") > score("cap", "Escapade")
    assert score("ab", "Alpha Bravo") > score("ab", "Xaxbx")
    assert score("cap", "Escapade") > score("cap", "Cold And Precise")


def test_several_terms_must_all_match_in_any_order() -> None:
    assert match_all_terms("writer story", "Story Writer") is not None
    assert match_all_terms("writer poet", "Story Writer") is None
    assert match_all_terms("prof", "Professor") == match("prof", "Professor")
    assert match_all_terms("   ", "anything") == Match(0, ())


def test_rank_keeps_matches_best_first_and_ties_in_order() -> None:
    names = ["Assistant", "Professor", "Story Ideas", "Captain"]
    ranked = rank(names, "st", lambda n: n)
    assert ranked[0] == "Story Ideas"
    assert "Assistant" in ranked
    assert "Captain" not in ranked
    assert rank(names, "", lambda n: n) == names
    assert rank(["aa", "ab", "ac"], "a", lambda n: n) == ["aa", "ab", "ac"]
