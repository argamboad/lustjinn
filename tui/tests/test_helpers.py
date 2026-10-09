"""The composer's helpers as pure functions: the donor's ``GraphemeTests``,
``EmojiShortcodeTests`` and ``WordCompletionTests``, in Python."""

from lustjinn_tui import emoji, graphemes, shortcodes, words

FAMILY = "\U0001f468‍\U0001f469‍\U0001f467"  # four code points joined: one cluster
THUMBS = "\U0001f44d\U0001f3fd"  # a thumbs-up and a skin tone
FLAG = "\U0001f1e8\U0001f1f7"  # two regional indicators


def test_these_fixtures_are_longer_in_chars_than_they_look() -> None:
    assert len(FAMILY) == 5
    assert len(THUMBS) == 2
    assert len(FLAG) == 2


def test_a_cluster_is_stepped_over_whole_in_both_directions() -> None:
    text = f"a{FAMILY}b{THUMBS}{FLAG}c"
    assert list(graphemes.clusters(text)) == [(0, 1), (1, 5), (6, 1), (7, 2), (9, 2), (11, 1)]
    assert graphemes.next_boundary(text, 1) == 6
    assert graphemes.next_boundary(text, 7) == 9
    assert graphemes.previous_boundary(text, 6) == 1
    assert graphemes.previous_boundary(text, 11) == 9
    assert graphemes.next_boundary(text, 12) == 12
    assert graphemes.previous_boundary(text, 0) == 0


def test_an_index_inside_a_cluster_snaps_to_its_start() -> None:
    text = f"a{FAMILY}b"
    assert graphemes.snap(text, 3) == 1
    assert graphemes.snap(text, 1) == 1
    assert graphemes.snap(text, 6) == 6
    assert graphemes.next_boundary(text, 3) == 6  # from inside, to the end of the cluster


def test_combining_marks_keycaps_and_crlf_stay_with_their_base() -> None:
    assert list(graphemes.clusters("éx")) == [(0, 2), (2, 1)]
    assert list(graphemes.clusters("1️⃣")) == [(0, 3)]
    assert list(graphemes.clusters("a\r\nb")) == [(0, 1), (1, 2), (3, 1)]
    assert graphemes.cluster_length("", 0) == 0


def test_every_shortcode_has_a_unique_name_an_emoji_and_a_typeable_name() -> None:
    table = emoji.table()
    names = [s.name for s in table]
    assert len(names) == len(set(names)) == 225
    assert all(s.emoji for s in table)
    assert all(all(shortcodes.is_name_character(c) for c in s.name) for s in table)
    assert all(len(s.name) <= shortcodes.MAX_NAME for s in table)


def test_find_is_case_insensitive_and_suggest_ranks_an_exact_name_first() -> None:
    assert emoji.find("SMILE") == "\U0001f604"
    assert emoji.find("nope") is None
    assert emoji.find("") is None
    assert emoji.suggest("smile")[0].name == "smile"
    assert emoji.suggest("")[:2] == list(emoji.table()[:2])
    assert emoji.suggest("lol")[0].name in {"laughing", "joy"}  # by keyword
    assert len(emoji.suggest("a", 3)) == 3
    assert emoji.suggest("smile", 0) == []


def test_before_the_table_is_read_nothing_expands_and_nothing_is_offered() -> None:
    held = emoji.table()
    emoji.load([])
    try:
        assert not emoji.loaded()
        assert emoji.find("smile") is None
        assert emoji.suggest("smile") == []
        assert shortcodes.expand_emoji("hi :smile:") == "hi :smile:"  # as typed
    finally:
        emoji.load(held)


def test_a_shortcode_being_typed_is_recognised_and_ordinary_prose_is_left_alone() -> None:
    assert shortcodes.at(":smi", 4) == shortcodes.Token(0, 4, "smi")
    assert shortcodes.at("hello :smi", 10) == shortcodes.Token(6, 4, "smi")
    assert shortcodes.at("hello :", 7) == shortcodes.Token(6, 1, "")
    assert shortcodes.at("at 10:30", 8) is None  # a clock time
    assert shortcodes.at("http://x", 8) is None
    assert shortcodes.at("hello :smile and", 16) is None  # the caret left the token
    assert shortcodes.at(":smile", 3) == shortcodes.Token(0, 3, "sm")
    assert shortcodes.at(":" + "a" * 33, 34) is None


def test_a_closed_shortcode_is_substituted_and_the_rest_is_not() -> None:
    assert shortcodes.closed("hi :smile:", 10) == (shortcodes.Token(3, 7, "smile"), "\U0001f604")
    assert shortcodes.closed("hi :nope:", 9) is None
    assert shortcodes.closed("hi ::", 5) is None
    assert shortcodes.closed("note:", 5) is None
    assert shortcodes.closed("hi :smile", 9) is None


def test_expand_all_replaces_emoji_and_snippets_where_they_open_a_word() -> None:
    expanded = shortcodes.expand_all(
        ":smile: at 10:30 see http://x :storm now :nope",
        lambda n: "STORM" if n == "storm" else None,
    )
    assert expanded == "\U0001f604 at 10:30 see http://x STORM now :nope"
    assert shortcodes.expand_emoji("so :heart: you :storm") == "so ❤️ you :storm"


def test_the_dictionary_is_sorted_lower_case_and_long_enough() -> None:
    listed = words.all_words()
    assert len(listed) > 2000
    assert list(listed) == sorted(listed)
    assert all(w == w.lower() and len(w) >= 3 for w in listed)


def test_suggest_offers_prefix_matches_shortest_first_and_never_the_word_itself() -> None:
    found = words.suggest("abso")
    assert found[:2] == ["absolute", "absolutely"]
    assert "abso" not in found
    assert words.suggest("absolute")[0] == "absolutely"
    assert words.suggest("ab") == []
    assert words.suggest("ABSO") == words.suggest("abso")
    assert len(words.suggest("a", 5)) == 0
    assert len(words.suggest("acc", 3)) == 3
    assert words.suggest("zzzz") == []


def test_token_at_finds_the_word_being_finished_and_stays_out_of_the_way() -> None:
    assert words.token_at("the abso", 8) == words.WordToken(4, 4, "abso")
    assert words.token_at("abso", 4) == words.WordToken(0, 4, "abso")
    assert words.token_at("the ab", 6) is None  # not enough to go on
    assert words.token_at("the absolute", 7) is None  # mid-word: an edit, not a write
    assert words.token_at("won't", 3) is None  # inside a contraction
    assert words.token_at("don'tgo", 7) is None
    assert words.token_at("x 10:30", 7) is None


def test_match_case_keeps_the_capitalisation_the_reader_was_using() -> None:
    assert words.match_case("abso", "absolute") == "absolute"
    assert words.match_case("Abso", "absolute") == "Absolute"
    assert words.match_case("ABSO", "absolute") == "ABSOLUTE"
    assert words.match_case("I", "its") == "Its"  # a lone capital is a sentence start
    assert words.match_case("", "its") == "its"
