# Story features

Step 7 adds no new mechanism. Everything the memory needed is in place; what this step adds is
what airp does *beyond* the core loop — eighteen features, each a few rules on top of chapters
2 to 6 — and the thing it teaches is how an API grows feature by feature without growing a
tangle. It shipped as two pull requests: the features that steer a turn, then the features
that manage a story, with this chapter.

| Steering the turn | Managing the story |
|---|---|
| dials, meters | branch, delete from a message |
| carry on, `/do`, `/focus` | search, export |
| regenerate with a reason | cost reports |
| a model per story — taken out again | facts by hand |
| `/recap` | rebuild the memory, purge |

## One module per feature

Every feature here is one file under `src/lustjinn/` with the same shape: pure functions at the
top, the few `async def` that touch the database under them, and a thin `APIRouter` at the
bottom. `main.py` adds one line per module, behind the sign-in guard:

```python
app.include_router(dials.router, dependencies=[Depends(auth.require_user)])
app.include_router(trackers.router, dependencies=[Depends(auth.require_user)])
app.include_router(editing.router, dependencies=[Depends(auth.require_user)])
```

A router with a prefix (`/stories/{story_id}/trackers`) is the feature's own namespace; the
`story_id` in the prefix becomes a parameter of every handler under it. The one thing they all
share is `stories.visible_story(session, story_id)`: the story, or a 404 that does not say
whether it was deleted or never existed.

::: dotnet
An `APIRouter` is an ASP.NET Core controller, or a minimal-API `MapGroup`, with the route
prefix and the `[Authorize]` attribute applied where it is *included* rather than where it is
*declared*. The module-per-feature layout is the vertical slice: the request model, the rules
and the handler for one feature next to each other, instead of a Controllers folder, a Services
folder and a Models folder each holding a slice of every feature.
:::

## Dials: a pack of data

"Be more varied", written into a prompt, is the weakest way to move a model. Temperature moves
it; so does the token ceiling. So each dial declares its **lever**: `prompt` puts the chosen text
in the directives layer, `sampler` sets an API parameter and injects nothing, `both` does one of
each per level. The sixteen shipped dials are a JSON file inside the package — Render has no
disk to put a reader's own file on — read once and validated **whole**:

```python
@lru_cache
def shipped() -> Pack:
    return parse(resources.files("lustjinn").joinpath("dials.json").read_text(encoding="utf-8"))
```

A scale has exactly five levels, read by index — a four-level scale would make the top of the
dial quietly mean the bottom — a sampler lever names its parameter, a template carries its
placeholder, or the dial is skipped with its reason recorded. A story stores only the values it
changed (`dial_values`, one row per dial), and the value in force is:

```python
def effective(dial: Dial, values: Mapping[str, str]) -> str | None:
    stored = values.get(dial.key)
    return stored if dial.enabled and stored is not None else dial.default
```

Disabled is *pinned*, not off: the default still applies on every prompt, and a stored value
survives to resurface the day the dial is re-enabled. Rendering walks the pack in order — the
one-line dials as a block, the paragraph-shaped ones after — which is cache-stable until a dial
moves:

```python
match dial.kind:
    case Kind.SCALE if (index := level_index(dial, value)) is not None:
        level = dial.levels[index]
        lines.append(f"{dial.title}: {level.label} — {level.text}.")
    case Kind.TOGGLE if is_on(value) and dial.on_text:
        blocks.append(dial.on_text.strip())
    case _:
        pass  # a value the pack cannot read says nothing rather than something wrong
```

::: dotnet
`match … case Kind.SCALE if …` is a `switch` expression with a `when` guard; the walrus
`(index := …)` binds inside the guard the way a pattern's designation does. `importlib.resources`
is `Assembly.GetManifestResourceStream` — a file that ships inside the package and is read by
name, not by path. `StrEnum` is an enum whose members *are* their strings, which is what you want
when the values live in JSON and in a database column.
:::

Two decisions worth knowing. Summaries stay at 0.3 whatever Creativity says. And the
response-length dial's ceiling is also the room the summariser reserves (`reply_tokens`), so the
memory and the builder agree about how much room the transcript has — the donor left that one
open, and two components disagreeing about room is how it once lost twenty-four turns.

### Saying what the dials are

The rendered lines first went out bare, as airp sent them: `Lust: Unhinged — no limits, no
pacing, maximum intensity every message.`, right after a card thousands of tokens long. Nothing
said whether that was an order, a mood or a note, nor which side wins when the card describes
someone reserved. The model split the difference, and the card mostly won — where the reader
expected what other apps do, a character who *adapts* to the dial in their own way. So the layer
now goes under a frame, as the persona always has (#142):

```python
DIRECTIVES_FRAME = (
    "The reader has set how this story is told. These settings outrank anything in the "
    "character's description that disagrees with them. The character stays who they are, in "
    "voice, history and manner, and acts the settings out through that: a shy character at the "
    "highest heat is shy and losing that fight, not suddenly someone else.\n\n"
)
```

It is chapter 3's rule again — every instruction sent to the model says what it is — applied to
the one layer that had escaped it. The frame is constant text, so it costs sixty-seven tokens a
turn and nothing in cache: it changes only when a dial does, which is when the layer changed
anyway. It is sent only when a dial says something; a story with no dials set gets no frame.

::: dotnet
`layers.directives and DIRECTIVES_FRAME + layers.directives` is a null-and-empty guard in one
expression: `and` returns its left side when that is falsy (`None`, `""`) and its right side
otherwise — `string.IsNullOrEmpty(d) ? d : Frame + d` in C#. Python's `and`/`or` return an
operand, not a `bool`, which is why the idiom works.
:::

## Meters: a value the model draws and the app reads back

A meter is a number the story keeps — trust, heat, suspicion — with a name, a range and, if the
reader wants, what it measures, what the numbers mean and what constrains it. Each turn the
stored value is rendered into the prompt with the shape the model must draw it back in, the
model ends its reply with the meter moved, and the line is read back:

```python
RENDERED = re.compile(
    r"\[\s*(?P<name>[^\]\n]{1,120}?)\s*\]\s*(?P<bar>[^\n\d]*?)\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)\s*/\s*(?P<max>\d+(?:\.\d+)?)\s*\|\s*"
    r"(?:Δ|delta)?\s*(?P<delta>[+\-]?\d+(?:\.\d+)?)\s*\|\s*(?P<note>[^\n|]{0,200})",
    re.IGNORECASE,
)
```

Deliberately loose about the bar — models draw hearts, blocks or nothing — and strict about
three things: only a meter the story *has* is touched (a model that invents one is writing
fiction, not configuration), the value is clamped to the range rather than trusted, and the
**delta is computed, never believed**. That round trip is what keeps a meter honest three hundred
turns later, when the turn that last drew it has been compressed away: the value lives in the
table, not in the transcript.

::: warning
A meter the model can see is a meter it writes towards. Meters are off by default for that
reason, and the drawn lines stay in the stored reply as the donor left them — they reach history,
summaries and embeddings. Stripping them would be a change to a reply the model wrote.
:::

`/tracker <name> <value>` moves one by hand; the value is the last word, so a two-word name
needs no quoting. Python's `rpartition(" ")` does the split in one call.

## Directions: turns the reader asks for without writing one

Three commands call the model with nothing from the reader. **Carry on** (`POST
/stories/{id}/continue`) sends the donor's directive that the reader's silence is not a cue to
stop. **`/do <direction>`** frames a direction; alone it is a turn under that direction, over a
message (after a blank line) the message is stored and the direction steers the reply.
**`/focus <who>`** hands the turn to a named character. None of them puts a word into
`messages`: the direction is the prompt's *last layer*, and a direction replaces the carry-on
wording rather than joining it — two answers to "what should this turn be" in one prompt is how
a reply comes back trying to satisfy neither.

A direction is part of what is asked for, so it is part of the request's identity:
`request_hash(story_id, anchor, text, instruction)` — the same words under a new direction are
a new ask, and a retry under the same one finds the stored message.

One small trick made the commands that answer *without* a model call fit the streaming
endpoint. `/recap`, `/tracker` and `/fact` answer in a single `said` event, so a client has one
code path for everything `/send` returns; but a refusal (a word where a number should be) must
be a 4xx, not a stream of one. So the generator is run up to its first event *before* the
response opens:

```python
async def _started(events: AsyncIterator[str]) -> AsyncIterator[str]:
    first = await anext(events)  # a refusal raises here, as an HTTPException

    async def rest() -> AsyncIterator[str]:
        yield first
        async for event in events:
            yield event

    return rest()
```

::: dotnet
An `async def` with `yield` is an `IAsyncEnumerable<T>` method, and `anext()` is
`await enumerator.MoveNextAsync()` for the first item. The pattern — pull one item to surface
early failures, then hand the rest on — is the same one you would write to make a streaming
action return `400` instead of a broken stream.
:::

## Regenerate with a reason

The reason is the only thing that makes the second attempt differ from the first. Nine reasons,
nine notes under one frame, and a rule enforced as written: **no directive may contain "previous
reply"**, because the withdrawn attempt is hidden from the prompt before the call and the model
cannot see what it is being asked to differ from. The reader's own words are framed as a
direction under the note, never read as the latest message.

```python
@router.post("/{story_id}/reroll", responses=STREAMED)
async def reroll(story_id: uuid.UUID, ..., body: Reroll | None = None) -> StreamingResponse:
```

A body typed `Reroll | None = None` is optional on a POST: the chapter 4 clients that send
nothing still work, and one that sends `{"reason": "looping"}` gets its note.

## A model per story — built, then taken out

Step 7 shipped a model per story, ported from airp: a story could name its own model, checked
against the provider's list before it was saved; its budget was fitted to that model's window;
its temperature was mapped onto the model's range; and the default wrote any turn the story's
model could not take, with the reply saying so.

It was taken out again (#140), once airp had shown what the choice was worth. The model billed as
the most explicit wrote about like the default, and the larger ones cost several times as much
for no difference a reader could name. What changes a reply is the card, the dials and the host
serving the model — all of which work on the default. Every rule the choice needed (a
temperature map, window corrections, a fitted budget, a fallback, a cached model list) existed
only to keep the choice from breaking a story. Every story now plays on `LUSTJINN_MODEL`;
changing it is one variable.

Taking a feature out is a migration like any other, read backwards:

```python
def upgrade() -> None:
    op.drop_column("messages", "fell_back_from")
    op.drop_column("stories", "model_context")
    op.drop_column("stories", "model")


def downgrade() -> None:
    op.add_column("stories", sa.Column("model", sa.String(length=200), nullable=True))
    op.add_column("stories", sa.Column("model_context", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("fell_back_from", sa.String(length=200), nullable=True))
```

The downgrade brings the columns back empty, not their values: a dropped column's data is gone.
That is why the data was checked first — no story on staging had named a model, and no reply had
ever fallen back.

::: dotnet
`op.drop_column` is EF Core's `migrationBuilder.DropColumn`, and `downgrade` is `Down`. Deleting
the attributes from the SQLAlchemy model without a migration fails the schema test from chapter 2
— the models and the migrations must agree — exactly as an EF model change without a migration
leaves `PendingModelChangesWarning`. An API field removed from a Pydantic body is ignored, not
refused, when an old client still sends it: `BaseModel` drops unknown fields by default, as
`System.Text.Json` does.
:::

## Branch, and delete from a message

Both edit a story's shape without rewriting a row. **Branch** (`POST /stories/{id}/branch`)
copies the story up to a chosen turn under a new name, with the memory those turns built, by
four rules worth stating because each one is a wrong answer avoided:

- live messages keep their sequence numbers, and their **embeddings are carried**, not recomputed
  — the text is identical, so the vector is too, and retrieval in the branch works from turn one;
- only **summaries wholly inside** the branch: one that straddles the point describes turns the
  copy does not have;
- **facts true at the point**: a fact retired *after* it was retired by turns this copy lacks, so
  here it never stopped being true (`valid_to_sequence = None`);
- **meters at the value they hold now**, the one thing that cannot be rewound; dial choices as
  they stand; and never spend — the branch starts at zero.

**Delete from** (`DELETE /stories/{id}/messages/{message_id}`) hides the turn and everything
after it; the rows stay, as the trigger insists. What to do with the memory of the hidden turns
was a decision the donor left open, and it is the branch rules run backwards: a summary that
reaches the cut goes, a fact extracted at or after it goes (a pinned one stays — a person said
it), and a fact those turns had retired is true again. The next sequence number is never reused.

## Search, export, cost

**Search** (`GET /search?q=`) is a case-insensitive *phrase* search over visible turns of visible
stories — `ILIKE` with the pattern's own `%` and `_` escaped — because the question is almost
always "where were these words said", and stemming would answer a different one. Postgres
full-text search was weighed and set aside: one reader's stories are small enough to scan. Story
names score 60, turns 40 plus five per further occurrence up to twenty, newest first among
equals; inside one story the excerpt is longer.

**Export** (`GET /stories/{id}/export?format=`) is one projection rendered three ways —
Markdown with front matter and a heading per turn, JSON with one entry per turn and a resolved
speaker, plain text with a numbered stamp line — and never the hidden turns. The response
carries a `Content-Disposition` with a file name; each client saves or copies it.

**Cost reports** (`GET /spend`, `GET /stories/{id}/spend`) are sums over the ledger from
chapter 3, read at report time: by kind, by story (dearest first; an erased story under
"(purged)") and by provider, with the cached share and what went on replies since rerolled or
cut away. Two rules the tests pin against hand-made totals: **a call with no price is counted as
unpriced, never as zero**, and the window is `[from_at, to_at)`. Embeddings are not in the
ledger and are not counted, and the report says so.

::: dotnet
The tally is a mutable `@dataclass` with a method, built up in one pass over the rows — the
Python equivalent of a `GroupBy` followed by `Aggregate`, written out because the same row feeds
five tallies (the whole, its kind, its story, its story's kind, its provider). `Decimal` sums
stay exact; the JSON carries them as strings, which is why the tests wrap them in `Decimal()`.
:::

## Facts by hand

A wrong fact is injected into every prompt until something contradicts it — and since the
character acts on it, nothing does. So `GET/POST/DELETE /stories/{id}/facts` let a person see what
the story believes, state a fact (pinned from the current turn, so the extractor cannot retire
it) and retire one — pinned or not; a person can do what the extractor cannot. `/fact
<statement>` pins under the character's name without a model call, and an `/ask` answer worth
keeping is one `POST` away from becoming something the character believes.

## Rebuild, and purge

The memory is derived and the transcript is never deleted, so **memory made badly by an earlier
version can be made again**. `POST /stories/{id}/memory/rebuild` throws away the summaries and the
extracted facts and replays `memory.compose` — the same function a turn calls, dials and meters
and fitted budget included, retrieval off since nothing is asked — until a pass writes nothing:

```python
for _ in range(MOST_PASSES):
    before = await _summaries(session, story.id)
    await memory.compose(..., retrieval=False)
    if await _summaries(session, story.id) == before:
        break
```

A rebuild that used rules of its own would produce a memory the application never would. The
bound is the transcript itself; the loop only ends early if something is wrong, and then the
report says what it managed. Pinned facts stay. The old calls stay in the ledger and the new ones
are added beside them. A dry run only says what it would replace.

**Purge** (`POST /stories/{id}/purge`) is the real erasure: delete only hides. It erases a story
*already deleted* — two deliberate acts, not one — with every row that carries its text, in one
transaction, on the one path where chapter 2's append-only trigger stands aside:

```python
await session.execute(text("SELECT set_config('lustjinn.purging', 'on', true)"))
```

The third argument makes the setting local to the transaction; the trigger reads it and lets the
`DELETE` through, and still refuses an `UPDATE` of a message's text. The spend rows stay — they
carry no text, the money left the account whatever became of the story, and dropping them would
make every report for that month wrong.

## Testing eighteen features

Nothing new in kind, and one habit worth naming: **a fixture that builds a story with everything
in it**. `tests/test_branching.py` makes the dummy story with a summary, a straddling summary,
facts of every kind, embeddings, a meter, a dial, two questions, a hidden reply and a bill — and
branch, delete-from and purge all test against it, each asserting the rules on the same rows.
Cost reports are tested against totals worked out by hand in the test file, including an
unpriced call and a purged story.

::: note
Step 7 made no real calls. Dials and meters are deterministic through the API, and the one thing
worth watching against a real model — whether it draws the meter line back in the shape asked —
is best seen in a client, which the next two steps build.
:::

::: try
Set a dial and watch it reach the request: `PUT /stories/{id}/dials/creativity` with
`{"value": "4"}`, send a turn, then read `GET /stories/{id}/audit` — the `directives` layer is in
the context line only for prompt levers, and the ledger row shows the model that answered.

Add a meter — `POST /stories/{id}/trackers` with `{"name": "Trust", "value": 40}` — play three
turns and read it back: the value moved by what the model drew, the note in its words, the delta
computed. Then `/recap` to see the story so far for free, and `GET /stories/{id}/spend` to see
what the three turns cost, discarded replies apart.
:::

## What step 7 leaves behind

- An API that does everything airp's two clients did, feature by feature, each in its own module
  behind the guard.
- Two more tables (`dial_values`, `trackers`) and no new mechanism. (Two columns came and went
  with the model per story.)
- Every endpoint and all six slash commands tested, so the clients can be built against a
  contract that does not move.

**Next — Chapter 8, The SvelteKit PWA.** A design system in dark and light, approved by the
owner before the screens are built: sign-in, the stories list, the conversation with its
composer and commands, dials, meters, the library, and the audit — all against this API.
