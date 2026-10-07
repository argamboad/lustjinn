"""The footer legend's fitting rule, as the donor's Legend did it."""

from lustjinn_tui.legend import ALL_KEYS, DEFAULT_HINTS, RESERVE, Hint, fit, markup

HINTS = (
    Hint("Enter", "Open the story"),  # 5 + 14 + 4 = 23 cells
    Hint("N", "New story"),  # 1 + 9 + 4 = 14
    Hint("M", "Library"),  # 1 + 7 + 4 = 12
    Hint("Q", "Quit"),  # 1 + 4 + 4 = 9
)
# Running totals: 23, 37, 49, 58. A hint that is not the last needs its total + 13 to fit.


def test_the_pointer_costs_thirteen_cells() -> None:
    assert ALL_KEYS.key == "?"
    assert ALL_KEYS.label == "All keys"
    assert RESERVE == 13


def test_everything_fits_on_a_wide_screen() -> None:
    kept, dropped = fit(HINTS, 100)
    assert kept == HINTS
    assert not dropped


def test_a_hint_that_does_not_fit_stops_the_loop_and_drops_the_rest() -> None:
    kept, dropped = fit(HINTS, 49)  # the second needs 37 + 13 = 50
    assert kept == HINTS[:1]
    assert dropped
    kept, dropped = fit(HINTS, 50)
    assert kept == HINTS[:2]
    assert dropped


def test_the_last_hint_only_has_to_fit_the_width() -> None:
    # The third needs 49 + 13 = 62; the last only needs its total, 58, within the width.
    kept, dropped = fit(HINTS, 61)
    assert kept == HINTS[:2]
    assert dropped
    kept, dropped = fit(HINTS, 62)
    assert kept == HINTS
    assert not dropped


def test_the_markup_appends_the_pointer_when_something_was_dropped() -> None:
    assert "All keys" not in markup(HINTS, 100)
    assert markup(HINTS, 40).endswith("[$muted]All keys[/]")


def test_the_default_hints_are_the_donors() -> None:
    assert [h.key for h in DEFAULT_HINTS] == ["Enter", "Esc", "Ctrl+P", "F1", "Q"]
