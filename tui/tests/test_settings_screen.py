"""The story's settings: the model row first, the dials stepped and staged, Enter applies,
Esc discards, a refusal leaves the row where the story really is."""

from textual.pilot import Pilot

from lustjinn_tui.api import Dial, DialLevel
from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.masthead import Masthead
from lustjinn_tui.settings import MODEL_KEY, ChatSettingsScreen, describe, level_index
from lustjinn_tui.status import Kind
from lustjinn_tui.stories import StoriesScreen
from tui_support import fake_server as fake


def settings_screen(app: LustjinnApp) -> ChatSettingsScreen:
    screen = app.screen
    assert isinstance(screen, ChatSettingsScreen)
    return screen


async def open_settings(app: LustjinnApp, pilot: Pilot[None]) -> ChatSettingsScreen:
    await pilot.pause(0.1)
    assert isinstance(app.screen, StoriesScreen)
    await pilot.press("enter")
    await pilot.pause(0.2)
    assert isinstance(app.screen, ConversationScreen)
    await pilot.press("s")
    await pilot.pause(0.3)
    return settings_screen(app)


def test_describe_reads_a_value_the_way_the_row_shows_it() -> None:
    scale = Dial(
        key="lust",
        kind="scale",
        title="Lust",
        levels=[DialLevel(label=label, text=label.lower()) for label in ("Cold", "Warm", "Hot")],
    )
    assert describe(scale, None) == ("Not set", "nothing chosen, so the pack's default applies")
    assert describe(scale, "2") == ("Hot", "hot")
    assert describe(scale, "9") == ("9", "")
    assert level_index(scale, " 1 ") == 1
    assert level_index(scale, "x") is None
    toggle = Dial(key="t", kind="toggle", title="T", help="Whether.")
    assert describe(toggle, "true") == ("On", "Whether.")
    assert describe(toggle, "nope") == ("Off", "Whether.")


async def test_the_rows_are_the_model_then_the_enabled_dials(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", "An opening.")
    server.dial_values[told["id"]] = {"lust": "3"}
    async with app.run_test(size=(100, 36)) as pilot:
        screen = await open_settings(app, pilot)
        keys = [row.key for row in screen.settings.rows]
        assert keys == [MODEL_KEY, "lust", "inner-thoughts", "pov", "language"]  # no agency-guard
        assert screen.settings.applied == {MODEL_KEY: fake.DEFAULT_MODEL, "lust": "3"}
        drawn = screen.settings.render().plain
        assert "▌ Model" in drawn
        assert "Default — deepseek/deepseek-v4-flash" in drawn
        assert "○─○─○─●─○  Explicit" in drawn
        assert "Not set" in drawn
        assert screen.legend.text.startswith(
            " ← → Change   ↑ ↓ Choose setting   Del Clear   R Reload"
        )
        assert str(screen.query_one("#foot").render()) == "Nothing changed."


async def test_stepping_stages_and_enter_applies_everything_at_once(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", "An opening.")
    async with app.run_test(size=(100, 36)) as pilot:
        screen = await open_settings(app, pilot)
        await pilot.press("right")  # the model: the first choice after the default
        await pilot.pause()
        assert screen.settings.staged[MODEL_KEY] == "thedrummer/anubis-70b"
        assert screen.settings.is_dirty
        assert screen.legend.text.startswith(
            " ← → Change   ↑ ↓ Choose setting   Del Clear   Enter Apply"
        )
        assert "(was Default" in screen.settings.render().plain
        await pilot.press("down", "right")  # lust: unset starts from the middle, then one up
        await pilot.pause()
        assert screen.settings.staged["lust"] == "3"
        await pilot.press("down", "left")  # inner thoughts: either arrow flips it
        await pilot.pause()
        assert screen.settings.staged["inner-thoughts"] == "true"
        await pilot.press("down", "left")  # pov: unset stepping left lands on the last option
        await pilot.pause()
        assert screen.settings.staged["pov"] == "third-past"
        assert "Press Enter to apply" in str(screen.query_one("#foot").render())
        assert server.dial_values.get(told["id"], {}) == {}  # nothing sent yet
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert server.dial_values[told["id"]] == {
            "lust": "3",
            "inner-thoughts": "true",
            "pov": "third-past",
        }
        assert server.story_models[told["id"]] == "thedrummer/anubis-70b"
        assert not screen.settings.is_dirty
        assert screen.status_line.kind == Kind.SUCCESS
        assert screen.status_line.text.startswith("Applied: Model → thedrummer/anubis-70b")
        assert "Lust → Explicit" in screen.status_line.text
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)
        shown = str(app.screen.query_one(Masthead).query_one("#model").render())
        assert shown.endswith("thedrummer/anubis-70b")
        assert app.model_name == "thedrummer/anubis-70b"


async def test_esc_discards_staged_changes_before_it_leaves_and_del_clears(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", "An opening.")
    server.dial_values[told["id"]] = {"lust": "1"}
    async with app.run_test(size=(100, 36)) as pilot:
        screen = await open_settings(app, pilot)
        await pilot.press("down", "right", "right")
        await pilot.pause()
        assert screen.settings.staged["lust"] == "3"
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ChatSettingsScreen)
        assert screen.settings.staged["lust"] == "1"
        assert screen.status_line.text == "Changes discarded."
        await pilot.press("delete", "enter")
        await pilot.pause(0.3)
        assert "lust" not in server.dial_values[told["id"]]
        assert "Lust → Not set" in screen.status_line.text
        await pilot.press("enter")
        await pilot.pause()
        assert screen.status_line.text == "Nothing to apply."
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)


async def test_a_text_dial_is_typed_and_a_refusal_puts_the_row_back(
    app: LustjinnApp, server: fake.FakeServer
) -> None:
    told = server.add("Tale", "An opening.")
    async with app.run_test(size=(100, 36)) as pilot:
        screen = await open_settings(app, pilot)
        await pilot.press("end", "right")  # language is typed, not stepped
        await pilot.pause()
        assert screen.legend.text.startswith(" Enter Keep")
        await pilot.press(*"Spanish", "enter")
        await pilot.pause()
        assert screen.settings.staged["language"] == "Spanish"
        await pilot.press("home", "right", "right")  # a model the server stops listing
        await pilot.pause()
        server.models.pop()
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert server.dial_values[told["id"]] == {"language": "Spanish"}
        assert screen.settings.staged[MODEL_KEY] == fake.DEFAULT_MODEL  # back to what it has
        assert screen.status_line.kind == Kind.WARNING
        assert "is not available" in screen.status_line.text
        assert not screen.settings.is_dirty
