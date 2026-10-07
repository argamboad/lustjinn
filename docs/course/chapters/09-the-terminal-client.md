# The terminal client

The second client, and the one closest to home: airp's console client was the thing the owner
built by hand on Spectre.Console, with its own view stack, key map, legend and theme. This
chapter rebuilds it in Python with **Textual**, against the same API the web app uses, dark by
design — one theme, no switch, no approval gate. The kickoff's reason for Textual was that it
ships what airp's shell wrote itself: a screen stack, bindings with a footer legend, a command
palette, themes and mouse support, and it is async, so a streamed reply fits without a thread.

The step is one pull request of ten issues: the skeleton, the API client and the gate, the
stories, the conversation, the composer's commands, the library and the settings, the keys
that work everywhere, the dialects and the phone, the composer's helpers, and this chapter.

## A second package in the workspace

The client is not a module of the API. It lives in `tui/` as its own package, `lustjinn-tui`,
and the root `pyproject.toml` makes the two a **uv workspace**:

```toml
[tool.uv.workspace]
members = ["tui"]

[tool.uv.sources]
lustjinn-tui = { workspace = true }

[dependency-groups]
dev = ["lustjinn-tui", "pyright>=1.1.414", "pytest>=9.1.1", ...]
```

One lock file and one environment, so `uv sync` installs both and `uv run lustjinn-tui` opens
the client. But Textual is a dependency of `tui/pyproject.toml`, not of the API's, and the
client is listed only in the `dev` group: Render installs the API without the terminal, and the
terminal's tests run under the root `uv run pytest` because `testpaths` names `tui/tests` too.
Pyright and ruff cover both packages from the root; isort is told that `lustjinn_tui` and the
test helpers are first-party, so the imports group the way they do in the API.

::: dotnet
A workspace is a solution with two projects and a shared `Directory.Packages.props`. The
`dev` group is the test project's `ProjectReference` to the client: the solution builds it and
tests it, but publishing the API project does not carry it along. `uv run lustjinn-tui` is the
`[project.scripts]` entry, the `dotnet tool`-style command that `app.py`'s `main()` answers.
:::

## Textual's model, mapped to airp's shell

Textual is an **app** that owns a stack of **screens**, each composed of **widgets**, drawn with
a stylesheet (TCSS) and driven by **bindings**, **messages** and **workers**. Every piece of it
has a counterpart in `src/Airp.Terminal`, which is how the port was planned.

| Airp (C#, Spectre.Console) | Textual | Here |
|---|---|---|
| `Shell` — the loop, the view stack, the redraw | `App`, `push_screen` / `pop_screen` | `app.py` |
| `View` — title, keys, `Render` | `Screen`, `compose`, `BINDINGS` | `view.py` |
| `KeyMap` — what a key means | `Binding` + a dialect table | `dialect.py` |
| `Theme` — the Dark palette | a registered `Theme` with variables | `theme.py` |
| `ListState` — cursor, page, selection | the same class, ported | `listing.py` |
| `Run(label, work)` — the spinner | `app.call()` round a worker | `app.py` |

### The app, and the gate

`LustjinnApp` is airp's `Shell`: it owns the API client, the one theme, the dialect and the few
bindings that hold on every screen (`Ctrl+C` quits at once, `Ctrl+P` or `:` opens the palette,
`Ctrl+F` searches every story). Its default screen is the stories, but the first thing it does
is push the lamp on top:

```python
def on_mount(self) -> None:
    self.push_screen(WakingScreen())
```

The waking screen knocks on `/health` in a worker with the waits growing from two to six
seconds, as the web app does, and after two minutes says so more plainly. When something
answers it pops itself and, without a token on disk, pushes the sign-in screen. The app has
one method for the error every screen could meet:

```python
async def call[T](self, label: str, work: Awaitable[T]) -> T | None:
    line.busy(label)
    try:
        return await work
    except SignedOutError as refused:
        self.signed_out(refused.detail)      # forget the token, ask again, say why
    except UnreachableError:
        self.lost(f"The server stopped answering while {label.lower()}.")
    except ApiError as refused:
        screen.status(refused.detail, Kind.ERROR)
    finally:
        line.idle()
    return None
```

A `401` anywhere becomes the sign-in screen with a note; a server that stops answering
becomes the lamp again; a refusal becomes the API's own sentence in red on the status row, and
the caller gets `None` and carries on. That is airp's `Run` with the three outcomes airp learned
to tell apart.

::: dotnet
`async def call[T]` is a generic method, the PEP 695 syntax for `async Task<T?> Call<T>(...)`.
Everything in Textual is `async` on one event loop, so there is no `Dispatcher.Invoke` and no
`ConfigureAwait`; a screen that `await`s the API simply yields to the loop and the redraw
continues around it. The `View.lustjinn` property exists because Textual types `self.app` as
`App[object]`, and pyright in strict mode wants to know it is ours.
:::

### The view, the frame, and the dialect

Every screen extends `View`, which draws airp's frame around whatever the screen composes:
the masthead (the server badge, the model, the breadcrumb of open screens), the body, a
hairline, the legend and the status row.

```python
def compose(self) -> ComposeResult:
    yield Masthead(badge=self.lustjinn.badge, model=self.lustjinn.model_name)
    with Vertical(id="body"):
        yield from self.body()
    yield Hairline(id="footer-rule")
    yield Legend()
    yield StatusLine()
```

A screen declares its `TITLE`, its `HINTS` in the donor's order (the legend fits them to the
width with airp's rule: every hint but the last leaves thirteen cells for *? All keys*) and
its `BINDINGS`. `Esc` is bound here once, to go back one screen and quit from the last. The
frame also follows the width live: under sixty columns — a phone held upright, over SSH, at a
font you can read — the masthead becomes one row, the legend folds into the status row, and
`layout_changed(narrow)` lets a screen lay itself out again. It changes back as soon as the
terminal is wider.

The keyboard dialect is applied in the same class. Airp's `KeyMap` was a table per dialect;
here the screens bind the arrows and the chords once, and the dialect decides what the letters
mean before the bindings see them:

```python
def on_key(self, event: events.Key) -> None:
    if self.typing or event.character is None:
        return
    meant = translate(self.lustjinn.dialect, event.key)
    if meant is None:
        return
    event.stop()
    event.prevent_default()
    if meant != SWALLOW:
        self.lustjinn.post_message(events.Key(meant, None))
```

Vim's `h j k l` become the arrows, `G` the end, `u` undo — only while navigating; inside any
text field every printable key types itself, so there is no mode to be in. Because `G` is the
end in Vim, regenerate is `Ctrl+G` there: a key has to mean one thing whichever dialect is
configured, and the help screen says which.

::: warning
A key translated to itself is not a no-op. The first table mapped `N` to `N` in Vim, and the
synthetic `Key("N")` the view posted never matched the screen's `n,N` binding, while the real
event would have. The letters a dialect does not change must be left out of its table, so the
real event reaches the screen untouched; the test that presses `N` in Vim and expects the
previous match is what caught it.
:::

### Widgets, messages and `@on`

A Textual widget draws itself in `render()` and tells its screen what happened by posting a
**message**, which bubbles up to the first handler that claims it. The list of stories is one
generic widget over the donor's `ListState`:

```python
class Rows[T](Widget):
    class Selected(Message):
        def __init__(self, rows: Rows[Any], index: int) -> None:
            super().__init__()
            self.rows = rows
            self.index = index

        @property
        def control(self) -> Rows[Any]:
            return self.rows
```

The screen handles it by name and, when it has several lists, by selector:

```python
@on(Rows.Selected, "#stories")
def _selected(self, event: Rows.Selected) -> None: ...
```

The `control` property is what makes the selector work: `@on` filters on the message's
`control`, and a message without one matches nothing and raises nothing, which cost an
afternoon. Every message in the client carries it.

::: dotnet
A `Message` is a routed event: it bubbles from the widget to the screen to the app, and
`event.stop()` is `e.Handled = true`. `@on(Rows.Selected, "#stories")` is the XAML
`SelectionChanged="..."` on one named control; `on_key` and `on_mount` are the convention-named
handlers, `OnKeyDown` and `OnLoaded`. `compose()` is the markup: it yields the children, and
`with Vertical(id="body"):` is a `StackPanel` with its children indented beneath it.
:::

### Workers: a stream without a thread

Anything that waits on the network runs in a **worker**, so the screen keeps drawing and the
keys keep working. A turn is the long one: the composer posts `Send`, the screen starts a
worker over the API's event stream, and each event lands in the transcript as it arrives.

```python
self._turn = self.run_worker(partial(self._run, label, stream, replacing), exclusive=True)

async def _run(self, label, stream, replacing) -> None:
    transcript.begin_pending()
    try:
        async for event in stream:
            if isinstance(event, Delta):
                transcript.grow_pending(event.text)
            elif isinstance(event, TurnDone):
                self._arrived(event)
            elif isinstance(event, Failed):
                self._failed(event)
            ...
    finally:
        self._end_turn()
```

`exclusive=True` cancels the previous worker of that group, which is how `Esc` while waiting
stops the stream — the message went, the screen says so, and the reply arrives on the next
refresh. The stream itself is `httpx2.EventSource` over a streaming POST, each event parsed by
pydantic into `Delta`, `TurnDone`, `AsideDone`, `Said` or `Failed`; chapter 8 cut the same
stream by hand in TypeScript, and here the library does it.

::: warning
`run_worker` takes a coroutine *or* a callable. Pass the coroutine of a method you also keep a
reference to and Python warns that it was never awaited when the exclusive group cancels it
before it starts; pass `partial(self._run, ...)` or the bound method and the worker creates
the coroutine itself when it runs. The warning is an error in this repo's pytest, which is how
it was found.
:::

::: dotnet
A worker is `Task.Run` with a cancellation token Textual holds for you; `exclusive=True` is
cancelling the previous token before starting the next. `async for event in stream` is
`await foreach` over an `IAsyncEnumerable<Event>`; `_stream` in `api.py` is an async generator
(`yield` inside `async def`), the Python way of writing one.
:::

### TCSS and the one theme

Textual styles widgets with a CSS dialect. Each widget carries its `DEFAULT_CSS`; the layout
rules are a few lines each (`View > #body { height: 1fr; }`). Colour never appears in them.
Airp's `Theme.cs` named Spectre colours per role; here the roles are a registered Textual
`Theme` and its variables:

```python
DARK: Final = Theme(
    name=NAME,
    primary="#87d7ff",     # heading
    foreground="#dadada",  # text
    background="#0a0d1b",  # the brand's navy
    success="#00d787",     # the character's name
    variables={"muted": "#808080", "selection-bg": "#87d7ff", ...},
)
KEY: Final = "[$accent on $surface]"
```

A view writes `$muted` in TCSS and `[$muted]` in content markup, or one of the openers
`theme.py` exports (`KEY`, `ACTION`, `SELECTION`); it never names a colour, which is the same
rule the web app's tokens enforce. The transcript draws its own lines, and the variables have to
resolve there too:

```python
strips = content.render_strips(
    width, None, self.visual_style,
    RenderOptions(self._get_style, self.styles.get_rules()),
)
```

That is the widget's own style parser, the way Textual draws any widget's content; rendering
to Rich segments directly left `$accent` as literal text.

## The screens

### The stories, and a new one

Newest first, one row each: the name, the character, the age of the last line, a preview in
the donor's prose runs. `/` filters with the fuzzy matcher ported from airp, the match painted
in the highlight role; `F2` renames in place; `Delete` asks first on a confirm screen
that pops itself before it runs the work, so the status lands on the list underneath. On
resume the list reloads quietly whenever the gate is open, which is the one place the app's
`gate_open` is asked: signed in, with neither the lamp nor the sign-in screen on the stack.

A new story is three pickers — character, persona with the default preselected, model — and a
name defaulting to the character and the date. The model list is read in a worker and never
waited for: a picker that has not heard back offers the default, and `Enter` on the last picker
creates.

### The conversation

The screen you live in, and the one with the most donor rules. The transcript is a
`ScrollView` that lays the messages out itself: a row per line, a speaker chip in the role's
colour on the surface tone, the selected turn marked with `▌` in the accent. Opening a story
lands on its newest turn's first row; the arrows step by three rows and the page follows the
selection, as `TranscriptScrollingTests` says it must. The column takes the config's share of
the width (sixty percent by default, centred, never under forty columns) and on a phone all of
it.

`i` or `Enter` writes. The composer is a `TextArea` that posts `Send` on `Enter` and makes a
line break on `Alt+Enter`; on a phone the two swap, because a phone keyboard has no `Alt`. A
paste with line breaks is text, not a send. The reply streams in under a pending row with a
clock in the header; `Esc` keeps the draft, and a failed turn keeps it too. `>` carries on,
`g` regenerates after asking for one of the donor's reasons, `b` branches, `Delete` cuts the
story back to the selected turn after asking and says how many went, `/` searches within the story
with `n`/`N` round the matches, `c` copies the turn, `x` exports.

### The composer's commands and helpers

A leading `/` offers the commands from `GET /commands` in a strip under the draft — one row,
because seven names in a list cost seven rows of the story. `Tab` accepts and `Enter` is never
claimed by the strip: it sends, it spends money, and a key that sends must not quietly mean
something else because a popup is showing. The local commands (`/card`, `/persona`, `/facts`,
`/trackers`, `/audit`, `/cost`, `/help`) open a pane over the conversation, and `/search`
reuses the in-story search; `/ask` opens a pane the reader can pin as a fact; `/recap` comes
back in a pane of its own, a `/fact` or `/tracker` written on the status row, and none of them
stores a turn. What the parser cannot place — an unknown name, a command missing its
argument — is refused on the status row and **nothing is sent**, which the donor's
`SlashCommands` tests insisted on: a mistyped command must never become a line of the story.

The helpers from airp's composer are the last issue: `:name` offers the library's snippets by
name and emoji by name or keyword from the donor's table of 225, `:smile:` becomes 😄 as the
closing colon lands, a word offers completions after three letters in the reader's own
capitalisation, and an emoji is one character to the cursor. That last one is `graphemes.py`,
the part of UAX #29 a chat meets — joiners, skin tones, flags, keycaps — because Textual's text
area moves by code point and a backspace would otherwise take one member of a family.

### The library and the settings

The library is three shelves as tabs over the same `Rows`, the entry's text in a pane beside
it. Editing opens the reader's own `$EDITOR` on a temporary file, with `app.suspend()` handing
the terminal over and taking it back; the tests hand the app an editor that needs no terminal.
A save that meets a `409` shows the conflict screen with their text and *Replace it with mine*
or *Take theirs*, chapter 4's version column again. The story's settings are airp's
`ChatSettingsView`: the model and every dial of the pack, stepped or typed, staged and applied
together, with *Discard* and *Reload*.

### Everywhere: the palette, search, export, the phone

`Ctrl+P` or `:` opens Textual's command palette with the current screen's commands before the
global ones, through one `Provider`:

```python
class LustjinnCommands(Provider):
    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for command in commands_of(self.screen):
            score = matcher.match(f"{command.name} {command.description}")
            if score > 0:
                yield Hit(score, matcher.highlight(command.name), partial(self._run, command))
```

A colon typed into a text field inserts a colon; the app tells the two apart by the last key
it saw. `Ctrl+F` searches every story with a scope that cycles; `x` exports as markdown, JSON
or text to the config's directory, never overwriting. On a phone with `mouse = true` the bottom
row becomes buttons — back, then what the screen does most — which press the key they stand
for, so a button and its key can never drift apart.

## Configuration and the token

The client keeps its own things in the user's config directory: a commented `config.toml`
written with the defaults the first time, and the token beside it in a file only the user can
read. The server can be given on the command line or in `LUSTJINN_SERVER`, which beats the
file. The keyring was the alternative for the token and would have meant a native backend per
platform for a secret the API hands out again on the next sign-in.

::: dotnet
`config.py` is `appsettings.json` and `IOptions<T>` without the layering machinery: one file,
read with the standard library's `tomllib`, into a frozen dataclass; the environment and the
command line applied as explicit `replace()` calls. `platformdirs` answers
`Environment.SpecialFolder.LocalApplicationData` on every OS.
:::

## Testing a terminal

Textual ships a **pilot**: `app.run_test()` runs the app headless at a size you choose, and
the test presses keys, clicks and waits. Against it stands a fake server — httpx2's
`MockTransport` answering the routes the client uses from memory, with switches for the
failures the screens must survive (`asleep_for`, `down`, a revoked token, an unreadable model
list, a model that fails). The tests script a server the way the API's tests script a model.

```python
async def test_a_lost_server_sends_the_reader_back_to_the_lamp(app, server) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        server.down = True
        await app.call("Refreshing", app.api.stories())
        await pilot.pause()
        assert isinstance(app.screen, WakingScreen)
        server.down = False
        await pilot.pause(0.2)
        assert isinstance(app.screen, StoriesScreen)
```

The donor's suites were ported by name: `KeyHandlingTests`, `NarrowLayoutTests`,
`PhoneBarTests`, `NewChatFlowTests`, `TranscriptScrollingTests`, the composer's helper tests.
Resizing is `pilot.resize_terminal(59, 30)` and the frame is asserted to change shape, and
back at sixty.
None of it touches the network, the database or the reader's config directory, so the suite
runs in CI without Postgres and in a second or two.

::: warning
Three things the pilot taught. `AUTO_FOCUS = None` still focuses the first field, because
`None` falls back to the app's `"*"`; a screen that wants no focus says `""`. A `scroll_to`
right after a `virtual_size` change clamps to the *old* maximum, so the transcript remembers
where it wants to be and applies it in `call_after_refresh`. And an attribute named `query`
or a method named `commands` on a widget silently shadows Textual's own; the client's are
`search_query` and `slash`.
:::

::: dotnet
The pilot is a `WebApplicationFactory` for a UI: the real app, in process, driven by a test.
`MockTransport` is the `HttpMessageHandler` you hand `HttpClient` in a test. The fixture that
builds the app for every test is `conftest.py`, the shared `IClassFixture` of pytest, and the
`tmp_path` the token store writes to is a per-test directory pytest deletes.
:::

::: try
Run the API and the client side by side: `uv run uvicorn lustjinn.main:app` and
`uv run lustjinn-tui`. Sign in, open the dummy story, press `i`, type `so :smi` and watch the
strip; `Tab`, then `Enter`. Press `?` for every key. Then set `keyboard = "vim"` in the
config file the first run wrote, restart, and move the list with `j` and `k` — and type a `j`
into the filter to see it stay a letter. Narrow the terminal under sixty columns and watch the
frame fold.
:::

## What step 9 leaves behind

- A terminal client in `tui/`: airp's look, keys and rules on Textual, every feature the API
  has, dark by design, tested headless.
- A second package in the workspace, and a pattern for one: its own `pyproject.toml`, the
  root's gates covering it, its tests collected by the root's pytest.
- Two decisions to note. The `mouse` flag only chooses the phone's button row, since Textual
  reports the mouse regardless; and `/search` from the composer reuses the in-story search
  rather than opening a pane.

**The roadmap ends here.** Two clients, one API, a memory that does not forget. What comes next
is the owner's to choose: the cloud, when it is wanted, is described in `docs/DEPLOYMENT.md`.
