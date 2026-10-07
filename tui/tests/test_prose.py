"""The prose rules, the same cases the web app's port passes."""

from lustjinn_tui.prose import Run, content, paragraphs, plain, runs


def test_tells_action_emphasis_and_dialogue_from_narration_and_drops_the_markers() -> None:
    assert runs('*She looks up.* "A week," she says, **not** smiling.') == [
        Run("action", "She looks up."),
        Run("narration", " "),
        Run("dialogue", "A week,"),
        Run("narration", " she says, "),
        Run("emphasis", "not"),
        Run("narration", " smiling."),
    ]


def test_keeps_plain_text_as_one_narration_run() -> None:
    assert runs("The fog had come in early.") == [Run("narration", "The fog had come in early.")]
    assert runs("") == []


def test_reads_single_and_double_markers_side_by_side() -> None:
    assert runs("**a** *b*") == [Run("emphasis", "a"), Run("narration", " "), Run("action", "b")]


def test_does_not_close_a_double_run_with_a_lone_asterisk_inside_it() -> None:
    assert runs("**a *b** c") == [Run("emphasis", "a *b"), Run("narration", " c")]


def test_treats_a_star_beside_whitespace_as_a_star() -> None:
    assert runs("2 * 3 * 4") == [Run("narration", "2 * 3 * 4")]
    assert runs("*open but never closed") == [Run("narration", "*open but never closed")]


def test_reads_curly_quotes_and_leaves_an_unclosed_or_multiline_quote_alone() -> None:
    assert runs("“Room seven.”") == [Run("dialogue", "Room seven.")]
    assert runs('She said "and left') == [Run("narration", 'She said "and left')]
    assert runs('"one\ntwo"') == [Run("narration", '"one\ntwo"')]
    assert runs('""') == [Run("narration", '""')]


def test_paragraphs_split_on_blank_lines_whatever_the_line_endings() -> None:
    assert paragraphs('*One.*\r\n\r\n\r\n"Two."\n\n') == [
        [Run("action", "One.")],
        [Run("dialogue", "Two.")],
    ]


def test_plain_drops_the_markers_and_content_styles_the_action() -> None:
    assert plain('*She looks up.* "Yes."') == "She looks up. Yes."
    styled = content("*She looks up.* and [waits]")
    assert styled.plain == "She looks up. and [waits]"  # brackets survive the markup
    assert len(styled.spans) == 1
