# The library

Step 3 played a story with a character that a script had seeded. Step 4 gives the owner the
editor: characters with their openings, personas and snippets, on three shelves behind one set
of endpoints, with the rules that make editing safe — a save that cannot quietly undo another
one, a history that keeps every version, and a delete that the database itself refuses while a
story still needs the entry.

This is the chapter on **constraints**: what the schema enforces on its own, what the ORM
enforces on every write, and the little that is left for code to check. Along the way, the
first mixin, a generic dataclass, and what `UPDATE … WHERE version = …` buys.

## Three shelves, one shape

A character, a persona and a snippet are the same shape of thing: a name, a page of text, a
version, a time of last change. A character also has an opening. In the donor they were four
folders of text files; here they are three tables that share four columns through a **mixin**
(`src/lustjinn/models.py`):

```python
class LibraryEntry:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Character(LibraryEntry, Base):
    __tablename__ = "characters"
    __table_args__ = (Index("uq_characters_name_lower", text("lower(name)"), unique=True),)

    card: Mapped[str] = mapped_column(Text)
    opening: Mapped[str | None] = mapped_column(Text)


class Snippet(LibraryEntry, Base):
    __tablename__ = "snippets"
    __table_args__ = (Index("uq_snippets_name_lower", text("lower(name)"), unique=True),)

    text: Mapped[str] = mapped_column(Text)
```

`LibraryEntry` is not a table. It is a plain class whose annotated attributes SQLAlchemy copies
into each class that inherits it — every table gets its own `id`, `name`, `version` and
`updated_at` columns. The unique index on `lower(name)` stays on each class, because it names
the table.

::: dotnet
A mixin is the abstract base entity that EF Core maps with TPC (table per concrete type): each
derived class gets a full table with the base's columns, and the base itself has none. The
difference is that nothing here is polymorphic — there is no query over "all entries" — which
is why it is a mixin rather than a mapped base. Multiple inheritance, `class Character(
LibraryEntry, Base)`, is ordinary Python; the mixin goes first so its attributes win.
:::

The endpoints are written once, for a **shelf**, and the shelf is a value
(`src/lustjinn/library.py`):

```python
@dataclass(frozen=True)
class Shelf[E: LibraryEntry]:
    slug: Slug
    kind: str
    model: type[E]
    text_of: Callable[[E], str]
    set_text: Callable[[E, str], None]


SHELVES: dict[str, Shelf[Any]] = {
    "characters": Shelf("characters", "character", Character, _card, _set_card),
    "personas": Shelf("personas", "persona", Persona, _text, _set_text),
    "snippets": Shelf("snippets", "snippet", Snippet, _text, _set_text),
}
```

`Shelf[E: LibraryEntry]` is a **generic class** with a bounded type parameter, in the syntax
Python 3.12 introduced: `E` is any subclass of `LibraryEntry`, and `model: type[E]` is the
class itself, used as `select(shelf.model)` and `shelf.model(name=...)`. The two callables
answer the one way the three tables differ — a character's text is its `card`, the others'
is `text` — without a conditional at every use.

The path parameter picks the shelf, and its type is a `Literal` of the three slugs:

```python
Slug = Literal["characters", "personas", "snippets"]


def shelf_named(shelf: Slug) -> Shelf[Any]:
    return SHELVES[shelf]


OnShelf = Annotated[Shelf[Any], Depends(shelf_named)]


@router.get("/{shelf}/{entry_id}")
async def read_entry(shelf: OnShelf, entry_id: uuid.UUID, session: Session) -> EntryOut:
    ...
```

`GET /library/openings` answers 422 before any code runs: FastAPI validated the path against the
`Literal`. And `shelf_named` is a dependency with a parameter of its own, which FastAPI reads from
the path — a dependency that takes a path parameter is nothing special.

::: dotnet
`Shelf[E]` is `Shelf<E> where E : LibraryEntry`, and `type[E]` is `Type` with the generic
argument kept — closer to a `Func<E>` factory plus a `typeof(E)` than to anything C# writes in
one token. The `Literal` on the path is a route constraint, `{shelf:regex(^characters|...$)}`,
with the benefit that pyright knows the three values too.
:::

## Names

Four rules, each with a reason:

- **Unique without regard to case**, by the index on `lower(name)` from step 2. The endpoint
  checks first, to answer 409 with a sentence instead of a constraint name, but the index is
  what holds.
- **Refused:** `< > : " / \ | ? *` and control characters, on every shelf. A name may become a
  file name when a story is exported (step 7), and being refused a colon is a smaller surprise
  than an export that only works on one machine.
- **A snippet's name is one word** of letters, digits, `_`, `+` and `-`, up to 32 characters —
  because it is typed as `:name`, and anything else could not be.
- **A name starting with `_` is kept but not listed** unless asked for. A shelf holds working
  papers as well as things to play — a template, notes towards a character — and they belong
  beside what they are about rather than in every picker.

The last rule met a trap worth a box.

::: warning
`select(Snippet).where(~Snippet.name.startswith("_"))` compiles to `name NOT LIKE '_%'`, and
in SQL's `LIKE`, `_` matches *any one character*. The condition excluded every name. SQLAlchemy
has the fix built in — `startswith("_", autoescape=True)` — but nothing warns when it is left
out. A test that created two entries and listed one caught it; a list that happened to be
tested with no hidden entries would not have.
:::

The same rule had a second trap, and this one only showed on another machine.

::: warning
The shelf is listed alphabetically. The first version said `ORDER BY lower(name)`, and its test
passed where it was written. On the laptop's Postgres the same test failed: `_template` came out
*between* `Elena` and `Zoe`.

`ORDER BY` on text does not have one meaning. Postgres sorts by the **collation** the database
was created with, and collations disagree: the usual `en_US.utf8` ignores punctuation on a first
pass, so a leading underscore vanishes; the `C` collation compares bytes, so `Ángela` lands after
`Zoe`. The fix names the order instead of inheriting it:

```python
def alphabetical(name: InstrumentedAttribute[str]) -> ColumnElement[str]:
    return name.collate("und-x-icu")
```

`und-x-icu` is ICU's language-neutral order — punctuation, digits, then letters without regard to
case, accents beside their base letter — and it is the same on every server. A test now pins
`_template, 9lives, alba, Ángela, Elena, Zoe` exactly.
:::

::: dotnet
SQL Server has the same hazard under another name: a column's collation (`SQL_Latin1_General_CP1_CI_AS`
and friends) decides both ordering and equality, and a query that sorts one way on your machine
sorts another on a server installed with a different default. `.collate(...)` is
`EF.Functions.Collate(x, "...")`.
:::

## What a foreign key does for you

A story points at its character and its persona by id, `ON DELETE RESTRICT`. Two things follow,
and neither needs code:

- **Renaming is free.** The donor stored the character's *name* in each conversation, so a
  rename broke every story using it. Here a `PATCH` with a new name reaches every story at
  once, and a new card reaches them from their next turn — `test_renaming_a_character_a_story_
  uses_reaches_the_story` sends a turn after the rename and reads the new card in the prompt.
- **Deleting one a story uses is refused**, by Postgres, whoever asks.

The code's part is to say *which* stories, so the refusal is useful: `used_by` lists the live
stories using an entry, and `DELETE` answers 409 with their names. It is asked at the moment of
deleting, not trusted from when a screen was drawn — a story could have been started with it
in between.

One case the key cannot express: a **deleted** story (`deleted_at` set) no longer counts as a
user, but its row still points at the character, and the foreign key does not know the
difference. So `used_by` says nobody, the delete goes to the database, the database refuses,
and the endpoint turns that `IntegrityError` into its own 409: *a deleted story still refers to
this character; it can go once that story is erased for good* — which is step 7's purge.

```python
await session.delete(entry)
try:
    await session.commit()
except IntegrityError:
    await session.rollback()
    raise HTTPException(409, "A deleted story still refers to this ...") from None
```

::: dotnet
`IntegrityError` is `DbUpdateException` wrapping a `PostgresException` with SQLSTATE 23503.
The pattern is the same: let the database be the last word, and translate its refusal where
the caller can act on it. `raise ... from None` drops the inner exception from the traceback
— the equivalent of throwing a new exception without an `InnerException`, on purpose, because
the database's message is not the reader's business.
:::

### The default persona

A story that names no persona plays as the **default**, which the owner sets once. It lives in a
new table, `settings`, with one row:

```python
class AppSettings(Base):
    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("id = 1", name="one_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_persona_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("personas.id", ondelete="SET NULL")
    )
```

A `CHECK (id = 1)` is how a table is made to hold one row at most. The foreign key is `SET NULL`
rather than `RESTRICT`: deleting the default persona is allowed, and clears the setting — but
only when nobody plays as it. The default counts as **used by every story that names none**,
and `used_by` says so, so the delete is refused with those stories' names while any exist.
That rule is the one piece of "who uses this" that the schema cannot carry, because the link
runs through a setting rather than a column.

With no default set, a story that names no persona plays as nobody — even when exactly one
persona is on the shelf. Choosing it would be choosing who the reader is playing, and it would
change the day a second one appeared.

## Optimistic concurrency

The owner edits a card on the laptop, then an hour later on the phone, from a page opened before
the laptop's save. Saving the phone's text would silently undo the laptop's. The donor caught
this by hashing the file; here the row has a **version**, and a save names the version it
started from:

```python
class EntryChanges(BaseModel):
    version: int
    name: Name | None = None
    text: Body | None = None
    opening: str | None = None
```

```python
entry = await _one(session, shelf, entry_id)
if changes.version != entry.version:
    raise _changed_elsewhere(shelf, entry)
```

The refusal is a 409 that carries the entry **as it is now**, so a client can show both texts
and let the reader decide — nothing is lost either way, which is the whole point. Saving again
with the current version succeeds, and the overwritten text is in the history.

That check compares the client's version with the row as loaded. Between that load and the
`UPDATE`, another save could still land. The ORM closes that gap by itself, with one mapper
option on the mixin:

```python
@declared_attr.directive
@classmethod
def __mapper_args__(cls) -> dict[str, Any]:
    return {"version_id_col": cls.version}
```

With `version_id_col` set, every `UPDATE` the ORM writes for these tables carries
`WHERE version = <the version it loaded>` and sets `version = version + 1`. If no row matched,
someone saved first, and the flush raises `StaleDataError` — which the endpoint answers with
the same 409. `test_the_orm_checks_the_version_on_every_update_it_writes` bumps the version
behind the session's back with raw SQL and watches the flush fail.

::: dotnet
`version_id_col` is `[ConcurrencyCheck]` on the property, or `IsConcurrencyToken()` in
`OnModelCreating`, and `StaleDataError` is `DbUpdateConcurrencyException`. One difference: EF
compares the *original* value it tracked; SQLAlchemy increments the column itself and compares
the number. Either way the write carries the check, so there is no window.

`@declared_attr.directive` marks a class-level setting a mixin computes per subclass — needed
here because `cls.version` is a different column on each table. In EF the same thing would be
a line in a base `OnModelCreating` helper called for each entity.
:::

A save that changes nothing writes nothing: `session.is_modified(entry)` is false, no `UPDATE`
is issued, the version stays, and no history row is added. The donor's test for this —
`Saving_the_text_unchanged_does_not_replace_the_backup` — has its namesake in
`tests/test_library_history.py`.

## History

The donor kept one `.bak` of the last save. Here every version is kept, in `library_history`:
kind, the entry's id, the version number, the name, text and opening as saved, and when. A row
is written on create (version 1) and on every save that changed something, in the same
transaction as the change:

```python
if session.is_modified(entry):
    session.add(_remembered(shelf, entry, version=entry.version + 1))
    await session.commit()
```

Two decisions carry over from the ledger. **No foreign key**: the history of a deleted entry is
still history, and `GET /library/personas/{id}/history` answers for an id that is no longer on
the shelf. **Insert-only**, by a trigger (migration `0006`) that refuses `UPDATE`, `DELETE` and
`TRUNCATE`. The history is the one thing in the library that cannot be edited.

::: note
Three tables now share the insert-only trigger pattern: `messages` (with a purge door),
`spend` and `library_history` (without). It is the same twelve lines of PL/pgSQL each time,
and that is fine — a trigger is schema, and schema is written out. The course mentions it so
the repetition does not look like an oversight.
:::

## Snippets expand at send time

A snippet is authored prose deployed at the dramatically right moment: written once, typed as
`:storm`, replaced by its text before the message is stored. `src/lustjinn/snippets.py` does the
replacing, and the hard part is not finding a colon but knowing when a colon is *not* a trigger.
Prose is full of them — `10:30`, `https://…`, `note: this` — and a message is permanent, so
guessing is not allowed. The rules:

- The colon must **open a word**: preceded by whitespace or nothing. That excludes clock times
  and URLs.
- The name is letters, digits, `_`, `+`, `-`, up to 32 of them. A longer run is not a name cut
  short; it is not a name.
- A closed `:name:` is an **emoji shortcode**, which the clients handle, and the API passes
  through untouched. This was the open question on the issue; the decision is that emoji are
  presentation, not content, and belong where the typing happens.
- An unknown name is left exactly as typed. One pass: an expansion is not scanned again.

The expansion runs first in `send`, before the line is read for commands — so a trigger works
inside a question too — and before the request hash, so a retry of `:storm` is still one turn.
The stored text is the expanded text; a later edit of the snippet does not reach it, which is
what "copied, never read again" means.

```python
def expand(text: str, snippet: Callable[[str], str | None]) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        opens_word = text[i] == ":" and (i == 0 or text[i - 1].isspace())
        if not opens_word:
            out.append(text[i])
            i += 1
            continue
        end = i + 1
        while end < len(text) and text[end] in NAME_CHARACTERS and end - i <= MAX_NAME_LENGTH:
            end += 1
        name = text[i + 1 : end]
        ...
```

`expand` takes the lookup as a function, `Callable[[str], str | None]`, rather than a table.
The endpoint hands it a closure over the snippets it loaded; the tests hand it a dictionary
through `by_name`. A function parameter is the cheapest seam there is.

::: dotnet
`Callable[[str], str | None]` is `Func<string, string?>`, and the scanner is a line-for-line
port of the donor's `ShortcodeScanner.ExpandAll` with the emoji branch removed. The one Python
idiom worth noticing is `text[i + 1 : end]` — slicing, half-open like `Range` in C#, and the
spaces around the colon are what ruff's formatter does when the bounds are expressions.
:::

## What the tests look like now

The library tests are the first to use the API's own endpoints as the *arrange* step — a
character created through `POST /library/characters` rather than inserted through the
session — because the endpoints are now the natural way to make one. The two styles coexist:
`a_character(session)` where the test is about something else, the endpoint where the test is
about the library.

One test needed a line of care:

```python
character_id = character.id  # the refused delete rolls the shared session back
```

The test and the app share one session, and the app's `rollback()` after the refused delete
expires every object in it — including the test's own `character`. Reading `character.id`
afterwards would try to reload it, which async code cannot do on its own. Capture what you need
before the request; a test that shares a session with the code it tests shares its side
effects too.

::: try
Rebuild the database and seed it, then edit the dummy from `/docs`:

1. `GET /library/characters` — one entry, "The Gilded Heron", `version: 1`.
2. `PATCH` it with `{"version": 1, "name": "The Heron"}`. The response says `version: 2`.
3. `PATCH` it again with `{"version": 1, "text": "x"}` — 409, and `current` is what it says
   now. Send `{"version": 2, "text": "x"}` instead: 200, `version: 3`.
4. `GET …/history` — three rows, newest first, with the card you just overwrote.
5. `DELETE` it: 409, naming the stories that use it. Delete the story first, then try again:
   409 again, from the foreign key — a deleted story still points at it. That is the purge's
   job, in step 7.
6. `POST /library/snippets` with `{"name": "storm", "text": "Rain hammers the glass."}`, then
   send a turn whose text is `I come in. :storm` — the stored message carries the expansion.
   Send `at 10:30 :nothing` — stored as typed.
:::

## What step 4 leaves behind

- Three shelves behind one set of endpoints, with names unique without regard to case, hidden
  working papers, and the default persona that a story without one plays as.
- Renames that reach every story at once, and deletes the database refuses while a story needs
  the entry — with the stories named.
- Saves that carry the version they started from, checked twice: by the endpoint against the
  client's version, and by the ORM on the write itself.
- A history of every version, insert-only, that outlives the entry.
- Snippets that expand where `:name` opens a word, and nowhere else.

**Next — Chapter 5, The context builder.** The prompt, properly: layers in order from least to
most volatile, a token budget counted with the model's own vocabulary, the newest turn always
kept, and an audit of what each layer cost — mostly pure functions, and mostly tests.
