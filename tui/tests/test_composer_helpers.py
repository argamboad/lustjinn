"""The helpers in the composer, end to end: `:name` + Tab inserts a snippet, `:name:` becomes
an emoji as the colon lands, a word completes after three letters, a colon token beats a word,
and an emoji is one character to the cursor (the donor's ``EmojiComposerTests`` and
``WordCompletionTests``)."""

from textual.pilot import Pilot

from lustjinn_tui import emoji
from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.completion import Strip
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.stories import StoriesScreen
from tui_support import fake_server as fake

OPENING = "An opening."
SMILE = "\U0001f604"
FAMILY = "\U0001f468‍\U0001f469‍\U0001f467"


async def open_story(app: LustjinnApp, pilot: Pilot[None]) -> ConversationScreen:
    await pilot.pause(0.1)
    assert isinstance(app.screen, StoriesScreen)
    await pilot.press("enter")
    await pilot.pause(0.2)
    screen = app.screen
    assert isinstance(screen, ConversationScreen)
    return screen


def offered(screen: ConversationScreen) -> list[str]:
    strip = screen.query_one(Strip)
    return [c.display for c in strip.offer.completions] if strip.offer else []


async def test_the_first_story_opened_reads_the_emoji_table_from_the_api(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    emoji.load([])  # as the app starts: nothing read yet
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        await open_story(app, pilot)
        await pilot.pause(0.1)
        assert emoji.loaded()
        assert emoji.find("tada") == "🎉"
        assert server.paths("GET").count("/emoji") == 1


async def test_a_colon_offers_emoji_and_tab_inserts_the_glyph(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"so :smi")
        await pilot.pause()
        shown = offered(screen)
        assert len(shown) == 7
        assert f"{SMILE} smile" in shown  # by name; smirk ranks beside it
        await pilot.press(*"le")
        await pilot.pause()
        assert offered(screen)[0] == f"{SMILE} smile"  # an exact name comes first
        await pilot.press("tab")
        await pilot.pause()
        assert screen.composer.text == f"so {SMILE}"
        assert not screen.query_one(Strip).display
        await pilot.press(*" at 10:30")  # a clock time never opens the list
        await pilot.pause()
        assert not screen.query_one(Strip).display


async def test_a_closed_shortcode_becomes_its_emoji_as_the_colon_lands(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"hi :smile:")
        await pilot.pause()
        assert screen.composer.text == f"hi {SMILE}"
        assert screen.status_line.text == f"Inserted {SMILE}  :smile:"
        await pilot.press(*" :nope: x")
        await pilot.pause()
        assert screen.composer.text == f"hi {SMILE} :nope: x"  # not in the table: as typed


async def test_a_snippet_completion_inserts_its_page_still_editable(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    server.shelve("snippets", "storm", "The storm breaks over the bay.\nRain, then hail.\n")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.pause(0.1)
        await pilot.press("i", *"then :st")
        await pilot.pause()
        assert offered(screen)[0] == "» storm"  # the snippet before any emoji
        await pilot.press("tab")
        await pilot.pause(0.3)
        assert screen.composer.text == "then The storm breaks over the bay.\nRain, then hail."
        assert screen.status_line.text == "Expanded :storm — still editable before sending."
        server.library["snippets"].clear()  # gone from the server since the shelf was read
        await pilot.press(*" :sto", "tab")
        await pilot.pause(0.3)
        assert screen.status_line.text == "The snippet 'storm' is empty or gone."


async def test_a_bare_trigger_is_sent_as_typed_and_emoji_names_as_real_text(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i")
        screen.composer.insert("a :heart: and :storm")  # as a paste would land it
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert [m.text for m in screen.messages][1] == "a ❤️ and :storm"


async def test_words_complete_after_three_letters_in_the_readers_case(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"Ab")
        await pilot.pause()
        assert not screen.query_one(Strip).display  # not enough to go on
        await pilot.press("s")
        await pilot.pause()
        assert offered(screen)[:2] == ["absence", "absolute"]
        await pilot.press("down", "tab")
        await pilot.pause()
        assert screen.composer.text == "Absolute"
        await pilot.press(*" wonder")
        await pilot.pause()
        assert screen.query_one(Strip).display
        await pilot.press(*" ")  # typing past the word closes the strip
        await pilot.pause()
        assert not screen.query_one(Strip).display
        await pilot.press(*":smile")
        await pilot.pause()
        assert offered(screen)[0].endswith(" smile")  # the colon token beats the word


async def test_enter_sends_even_with_words_on_offer(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i", *"abso")
        await pilot.pause()
        assert screen.query_one(Strip).display
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert [m.text for m in screen.messages][1] == "abso"


async def test_an_emoji_is_one_character_to_the_cursor(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    server.add("Tale", OPENING)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_story(app, pilot)
        await pilot.press("i")
        screen.composer.insert(f"a{FAMILY}b")
        await pilot.pause()
        assert screen.composer.cursor_location == (0, 7)
        await pilot.press("left")
        assert screen.composer.cursor_location == (0, 6)
        await pilot.press("left")
        assert screen.composer.cursor_location == (0, 1)  # over the whole family
        await pilot.press("right")
        assert screen.composer.cursor_location == (0, 6)
        await pilot.press("backspace")
        assert screen.composer.text == "ab"  # the whole emoji, not one member of it
        screen.composer.insert("\U0001f44d\U0001f3fd")
        await pilot.press("left", "delete")
        assert screen.composer.text == "ab"
