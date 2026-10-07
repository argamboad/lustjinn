"""The list state's arithmetic (``Ui/ListState.cs``): selection in range, a scroll margin of
two, a click mapped back to an index."""

from lustjinn_tui.listing import ListState


def test_an_empty_list_selects_nothing_and_a_count_keeps_the_selection_in_range() -> None:
    state = ListState()
    assert state.selected == -1
    state.move(1)
    assert state.selected == -1
    state.set_count(3)
    state.select_last()
    assert state.selected == 2
    state.set_count(2)
    assert state.selected == 1
    state.set_count(0)
    assert state.selected == -1


def test_moving_clamps_at_both_ends() -> None:
    state = ListState()
    state.set_count(5)
    state.move(-3)
    assert state.selected == 0
    state.move(99)
    assert state.selected == 4
    state.select(2)
    state.move(-1)
    assert state.selected == 1
    state.select_first()
    assert state.selected == 0


def test_the_viewport_keeps_a_margin_above_and_below_the_cursor() -> None:
    state = ListState()
    state.set_count(20)
    assert state.viewport(10) == (0, 10)
    state.select(9)  # two rows from the bottom edge: the window must slide
    assert state.viewport(10) == (2, 10)
    state.select(19)
    assert state.viewport(10) == (10, 10)
    state.select(10)  # coming back up: the cursor stays two rows from the top edge
    assert state.viewport(10) == (8, 10)
    state.select(0)
    assert state.viewport(10) == (0, 10)


def test_a_list_that_fits_never_scrolls_and_a_tiny_viewport_has_no_margin() -> None:
    state = ListState()
    state.set_count(3)
    state.select(2)
    assert state.viewport(10) == (0, 3)
    state.set_count(10)
    state.select(5)
    assert state.viewport(1) == (5, 1)


def test_a_row_maps_back_to_an_index_or_to_nothing_past_the_end() -> None:
    state = ListState()
    state.set_count(4)
    assert state.index_at_row(0, 10) == 0
    assert state.index_at_row(3, 10) == 3
    assert state.index_at_row(4, 10) == -1
    assert state.index_at_row(-1, 10) == -1
    state.set_count(20)
    state.select(19)
    state.viewport(10)
    assert state.index_at_row(0, 10) == 10
