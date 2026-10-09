# One turn against OpenRouter

Step 2 left a story that could be opened and could not be played. Step 3 plays it: the reader
sends a message, the API asks a model for the reply and streams it back word by word, and both
sides of the exchange are kept — the reader's turn *before* the model is asked, the reply with
the model that wrote it, the host that served it, and what it cost. Around that core, three
pieces of turn mechanics: a retry that cannot store a message twice, a reroll that hides the old
reply and keeps it, and slash commands, where a typo is refused instead of billed.

This chapter is about **async I/O**: an HTTP client that streams, a response that streams, and
the generators that connect the two. It is also where money enters the code, and where a
provider's failure modes get names.

## One endpoint, one key

Every model call goes to **OpenRouter**, which fronts many models behind one OpenAI-compatible
endpoint and one key. Choosing a model is configuration; so is pointing at a different provider
that speaks the same shape. The settings grow accordingly (`src/lustjinn/settings.py`):

```python
openrouter_api_key: SecretStr | None = None
openrouter_base_url: str = "https://openrouter.ai/api/v1"
model: str = "deepseek/deepseek-v4-flash"
temperature: float = Field(default=1.0, ge=0, le=2)
max_tokens: int = Field(default=1024, ge=1, le=32768)
model_timeout_seconds: int = Field(default=180, ge=1, le=3600)
prefer_providers: list[str] = []
ignore_providers: list[str] = []
allow_provider_fallbacks: bool | None = None
think_before_replying: bool = False
```

The key is **optional** here on purpose. The app must start without one — the stories API has
nothing to do with the model — and a model call without a key fails before anything is sent,
with an error naming the variable. `temperature` and `max_tokens` carry ranges, like
`token_days` did. `think_before_replying` is off, which sends OpenRouter's
`reasoning: {enabled: false}` on every reply: without it, the default model came back empty three
times in five, every token spent thinking.

The two provider lists are the one setting that makes a measurable difference to the bill.
OpenRouter spreads a model across hosts, and they are not interchangeable: some cache prompts,
some do not, some return garbage. The lists go out as OpenRouter's `provider` field, trimmed and
otherwise exactly as typed — the router drops a slug it does not know without complaint, so
lower-casing to be helpful would only hide the typo.

## Streaming, in both directions

A reply takes seconds to write. Showing it as it is written is the difference between an app
and a form, so the model is asked to stream — and the API streams to its own clients in turn.
Both use the same format, **server-sent events**: one long HTTP response of `text/event-stream`,
carrying events a few lines at a time, each ended by a blank line.

```
event: delta
data: {"text": "She looks up"}

: a line starting with a colon is a comment — OpenRouter sends these as keep-alives

data: [DONE]
```

`src/lustjinn/sse.py` reads it and writes it, in about forty lines:

```python
async def events(lines: AsyncIterable[str]) -> AsyncIterator[Event]:
    name: str | None = None
    data: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                yield Event("\n".join(data), name)
            name, data = None, []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "data":
                data.append(value)
            elif field == "event":
                name = value
    if data:
        yield Event("\n".join(data), name)
```

This is the first **async generator**: an `async def` with `yield` in it. Calling it runs
nothing; it returns an object that produces one `Event` each time the caller asks with
`async for`, and between two events the function is suspended exactly where its `yield` is,
holding its local variables. The `lines` it reads are themselves produced the same way, by the
HTTP response, as bytes arrive on the socket.

::: dotnet
An async generator is a method returning `IAsyncEnumerable<T>` with `yield return` inside, and
`async for` is `await foreach`. The mental model carries over whole: lazy, pull-based, suspended
between items. One difference — there is no `IAsyncDisposable` on the consumer's side to think
about; leaving the `async for` early is enough, and `aclose()` on the generator is called for
you when it is garbage-collected or the `async with` it lives in ends.
:::

::: warning
The orientation chapter's map said **respx** fakes HTTP in tests. It does not any more: respx
supports `httpx`, and this project moved to **httpx2** in step 1, when Starlette asked for it.
The map is corrected in this edition. The tests fake the network with httpx2's own
`MockTransport` instead, which turns out to be simpler — a function from request to response,
the exact shape of a fake `HttpMessageHandler`.
:::

## The client

`src/lustjinn/openrouter.py` holds one class with three methods: `stream`, which does the work;
`complete`, which gathers a stream into one reply for callers with nothing to show while it is
written; and `models`, which lists what OpenRouter serves. The heart of it:

```python
async def stream(self, messages, *, model=None, temperature=None, max_tokens=None,
                 frequency_penalty=None, reasoning=None) -> AsyncIterator[str | Reply]:
    body: dict[str, object] = {
        "model": model or settings.model,
        "stream": True,
        "temperature": ...,
        "max_tokens": ...,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }
    if frequency_penalty is not None:
        body["frequency_penalty"] = frequency_penalty
    if reasoning is not None:
        body["reasoning"] = {"enabled": reasoning}
    if (routing := self._routing()) is not None:
        body["provider"] = routing

    text: list[str] = []
    async with self._request("POST", "chat/completions", body) as response:
        async for event in sse.events(response.aiter_lines()):
            if event.data == "[DONE]":
                break
            chunk = _parse(event.data)
            ...
            for choice in _objects(chunk, "choices"):
                delta = _object(choice, "delta") or {}
                if piece := _string(delta, "content"):
                    text.append(piece)
                    yield piece
            usage = _object(chunk, "usage") or usage

    yield Reply(text="".join(text), model=..., provider=..., cost=_decimal(usage, "cost"), ...)
```

Things to notice, in the order they appear.

**Keyword-only parameters.** The `*` in the signature means everything after it must be passed
by name: `stream(messages, temperature=0.4)`, never `stream(messages, 0.4)`. The donor project
had three bugs from a positional argument added in the middle of a long list; here that mistake
cannot be typed.

**Fields sent only when asked for.** `frequency_penalty` absent and `frequency_penalty: 0` are
different requests to some backends; only absence means "no opinion". `reasoning` and `provider`
are OpenRouter's own fields, so a backend that refuses unknown keys never sees them unless
something is configured. The walrus `:=` assigns and tests in one expression, the way
`if (Routing() is { } routing)` does in C#.

**The stream yields two kinds of thing.** Pieces of text as they arrive, then — once — a `Reply`
with the whole text and the accounting. The return type says so: `AsyncIterator[str | Reply]`.
The caller tells them apart with `isinstance`, which pyright uses to narrow the type on each
branch.

```python
async for piece in openrouter.stream(messages, ...):
    if isinstance(piece, Reply):
        written = piece
    else:
        yield format_event("delta", {"text": piece})
```

::: dotnet
`str | Reply` is a union type: a value that is one or the other, with the checker tracking which.
C# has no unions; the nearest is a `OneOf<string, Reply>` or a base record with two subtypes
and a type pattern in a `switch`. `isinstance` narrowing is the `is` pattern: after
`if (piece is Reply written)`, `written` is a `Reply` — pyright does the same without the second
name.
:::

**`Reply` is a frozen dataclass.** `@dataclass(frozen=True, kw_only=True)` generates the
constructor, equality and `repr` from the annotated fields, refuses assignment after
construction, and requires every field by name. It is a `record` with `init`-only properties.
Its `cost` field is a `Decimal`.

### Money is a `Decimal`

JSON has one number type, and Python reads it as `float` by default: `0.0002` arrives as the
nearest binary fraction, and a few hundred of those summed give `0.0006000000000000001`. A report
about money that has to apologise for its own arithmetic is not one anybody checks against an
invoice. So the parser reads every number with a decimal point as `Decimal`:

```python
parsed: object = json.loads(text, parse_float=Decimal)
```

and the cost is converted nowhere else. In Postgres it is a `NUMERIC(18, 10)`, and SQLAlchemy
maps that to `Decimal` on the way back.

::: dotnet
`decimal.Decimal` is `System.Decimal`, with one difference that matters here: it is arbitrary
precision rather than 96 bits, and its precision is a context setting rather than fixed. Nothing
in this project is affected; everything is ten decimal places or fewer.
:::

### Reading `Any` without lying to the checker

`json.loads` returns `Any` — a value the checker gives up on. In strict mode every use of it is
an error, which is the point: a key that is not there or a value of the wrong type should be a
decision, not a crash in a log. Four small functions make the decisions, once:

```python
Json = dict[str, object]

def _object(source: Json, key: str) -> Json | None:
    value = source.get(key)
    return value if isinstance(value, dict) else None

def _string(source: Json, key: str) -> str | None:
    value = source.get(key)
    return value if isinstance(value, str) else None
```

Everything the client reads goes through them, so a response shaped differently than expected
produces `None` fields, never an exception — and the one place that must not be `None`, the
text, is checked explicitly.

::: dotnet
`JsonNode` with `?["key"]?.GetValue<string>()` does the same job in the donor, null-conditional
all the way down. The Python version is more explicit because `Any` is the one type the checker
refuses to reason about: it has to be narrowed by hand, with `isinstance`, into something it
can.
:::

### Every failure has one shape

The model can fail in six ways, and the client turns each into one `ModelError` whose message is
fit to show the reader:

| What happened | What the error says |
|---|---|
| No key configured | Names the variable. Fails before any request |
| Timeout, connection refused | "did not answer within 180 s", "could not reach …" |
| A 4xx or 5xx | The status, and `error.message` from the body — never the body, which echoes the prompt |
| A 200 that is not a stream | "not a stream (text/html)": a gateway's error page |
| An error chunk mid-stream | What the chunk said. A host dying mid-reply looks like this |
| A 200 with no text | `finish_reason`, the host, and "reasoning only" when the model spent everything thinking |

The last one is the subtle one. A reply that is an empty string would be stored as though the
model had answered with silence — a turn that never happened, permanent and billed. So no text
is a failure, and the message says which of three different problems it was: a content filter
(`finish_reason: content_filter`), a ceiling hit before the first token (`length`), or a host
with nothing to say (`stop`).

**One timeout, in one place.** The donor had two — its own and `HttpClient`'s 100-second
default — and the wrong one fired first. Here `httpx2.Timeout(settings.model_timeout_seconds)`
is set on the request and nowhere else. For a stream it bounds the connection and the gap between
one chunk and the next: a reply that keeps arriving is alive however long it takes as a whole.

### An `async with` of our own

The request is opened in a class with `__aenter__` and `__aexit__`: enter sends the request,
checks the status and hands back the open response; exit closes it, whether the stream was read
to the end or abandoned at an exception. `async with self._request(...) as response:` is the
whole of the caller's responsibility.

::: dotnet
`__aenter__`/`__aexit__` are `IAsyncDisposable` plus a factory, used with `await using`. Python
splits "acquire" and "release" into two methods on the same object, and the `with` statement
guarantees the second runs — the same `try/finally` a `using` expands to.
:::

## The ledger

Four kinds of call spend money: a reply, a question asked out of character, and (from step 6) a
summary and a fact extraction. Two of those fire without the reader asking for anything, and
were invisible in the donor for as long as spending was inferred from message rows. So every
billed call writes one row to `spend`, in `src/lustjinn/ledger.py`, whatever becomes of what it
produced:

```python
def row(story_id, kind: SpendKind, reply: Reply, message_id=None) -> Spend:
    return Spend(story_id=story_id, kind=kind, message_id=message_id,
                 model=reply.model, provider=reply.provider, generation_id=reply.generation_id,
                 prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens,
                 cached_tokens=reply.cached_tokens, cache_write_tokens=reply.cache_write_tokens,
                 cost=reply.cost)
```

Three decisions are in the table itself:

- **`cost` is nullable.** Null is "the API did not say what it charged"; zero is a price. A
  report that added them together would be confidently wrong instead of honestly incomplete.
- **No foreign keys.** Not to the story, not to the message. Erasing a story for good (step 7)
  takes its messages and keeps its ledger: what the router charged exists nowhere else once the
  response is gone.
- **Insert-only**, by a trigger like the one on messages — but with no purge flag. Migration
  `0003` refuses `UPDATE`, `DELETE` and `TRUNCATE` outright.

A reply's row points at its message, which is how a later cost report will know the reply was
rerolled away: by reading the message's `deleted_at` at report time, never by rewriting the row.

::: note
The ledger is the one table that is not derived from anything. Everything else — summaries,
facts, embeddings — could be rebuilt from the transcript. The bill could not.
:::

## The turn

`POST /stories/{id}/send` with `{"text": "I come in from the rain."}`. What comes back is the
stream: `delta` events while the reply is written, then one last event that says how it ended.

```
event: delta
data: {"text": "She looks up from the ledger"}

event: delta
data: {"text": ", and does not smile."}

event: done
data: {"kind": "turn", "sent": {...}, "reply": {...}, "replayed": false}
```

The last event is `done` with both messages as stored, or `error` with a reason and — this is the
important part — the reader's message, which was kept. Once a response has started streaming its
status code cannot change, so every failure after that point is an event in the stream, not an
HTTP status. A 4xx before the stream (a blank message, an unknown command, a story that does not
exist) is still a plain JSON error.

### Persist first

The order inside `turn()` in `src/lustjinn/turns.py` is the lesson the donor paid for:

1. Compute the request's hash and look it up (next section).
2. If the message is new, **insert it and commit** — before the model is called.
3. Build the prompt, call the model, stream the deltas.
4. On a reply: insert the assistant's message and its ledger row, **one commit**.
5. On a failure: nothing to undo. The event says *"Your message was kept … Do not send it
   again."*

If the send were only stored after a successful reply, a provider outage would silently swallow
what the reader typed — and telling them it failed outright is how the same message gets typed
a second time. A test pins each half: `test_the_message_survives_a_model_that_fails` and
`test_retrying_a_send_the_model_failed_does_not_store_it_twice`.

### Idempotency, anchored on the last reply

A retry must find the message it is a retry of. The message carries a **request hash**:

```python
def request_hash(story_id, anchor, text, instruction=None) -> str:
    directed = text if not instruction else f"{text}\x1f{instruction.strip()}"
    digest = hashlib.sha256(f"{story_id}|{anchor}|{directed}".encode()).hexdigest()
    return digest[:32].upper()
```

The **anchor** is the sequence number of the last visible reply — the state the message
answers — and not the next free position. After a send fails at the model the reader's turn is
already stored, so the next free position has moved; anchoring on it would give the retry a
different hash and store the sentence twice. Anchored on the reply, the retry hashes the same,
finds the unanswered row, and asks again against it. And the same words typed again *after* a
reply has landed anchor differently: saying "Hello." twice in one story is ordinary, not a
retry.

Four cases, in the order the code checks them:

| The lookup finds… | What happens |
|---|---|
| Nothing | Insert the message, commit, call the model |
| A hidden message | Clear its hash, treat as nothing: re-sending words the reader deleted is how a turn is taken back and asked for again |
| A message with a visible reply after it | Return the stored pair, `replayed: true`, **no model call** |
| A message with no reply | Reuse the row and call again |

The third case is reachable only by two copies of one request in flight, since the anchor moves
once a reply lands; the test pins the hash with `monkeypatch.setattr` to simulate it. The second
case came from a real story: the reader deleted their last turn and pasted it again, the hash
matched the tombstone, and the model kept answering the story without that turn.

::: dotnet
`hashlib.sha256(...).hexdigest()` is `Convert.ToHexString(SHA256.HashData(...))`. The `\x1f`
separator between text and instruction is a control character because a pipe or a space can
appear in prose, and a separator the message can contain lets two different sends hash alike.
:::

### The response is a generator too

The endpoint returns a `StreamingResponse` wrapping an async generator; FastAPI iterates it and
writes each string to the socket as it is produced. Two details:

```python
# src/lustjinn/deps.py
StreamingSession = Annotated[AsyncSession, Depends(get_session, scope="request")]
```

**`scope="request"`** keeps the session dependency open until the response has been sent. The
default scope closes a `yield` dependency when the endpoint *function* returns — which, for a
streaming response, is before the stream has run. The generator would find its session closed.
This is one of the few places where FastAPI's model of a request differs from the pipeline you
know, and it is worth remembering whenever a response outlives its handler. It has its own name
for that reason: a streamed route asks for `session: StreamingSession`, and one that finishes
before it returns asks for `session: Session`.

The other is a header, `X-Accel-Buffering: no`, which tells a proxy in front (Render's, nginx)
to pass each event on as it comes instead of collecting the body first.

### The prompt, for now

Step 5 builds the context builder: layers in order, a token budget, the audit. Until then
`src/lustjinn/prompt.py` sends the first two layers and the last, in the order it will keep:
the character's card as a system message, the persona behind its frame ("The user is playing
the following person…"), the visible transcript as `user` and `assistant` turns, and, when there
is one, an instruction for this call only. The instruction goes as `user` when the transcript
ends on a reply and as `system` when it ends on the reader's own turn — two user turns in a row,
and a model tends to answer the second and forget the first.

Every story plays on the configured model. Step 7 let a story name its own, with the
temperature mapped onto that model's range; chapter 7 says why it was taken out again.

## Reroll

`POST /stories/{id}/reroll` writes the newest reply again. The old one is **hidden before the
call** — a model shown its last attempt writes it again — and if nothing arrives to replace it,
shown again, so a failed reroll never leaves the story shorter than it found it. Hidden, not
removed: the row stays, and so does its ledger row. Both calls were charged.

Two refusals, both 409: there is no reply to reroll (the newest visible message is the reader's,
or there is none), and the reply is the **opening**. The opening is a page a person wrote, and it
sits at the top of the story for the rest of its life; a reroll there would trade it for a guess.
It is told apart by two things, because either alone is wrong: no model wrote it (`model` is
null — the reason step 2 stored that null), and the reader has not taken a turn yet. A beat the
model writes after the opening with no reader turn (carry on, step 7) satisfies the first and
not the second, and is rerolled.

## Slash commands, and `/ask`

A message is permanent and billed. `(OOC: skip to the evening)` typed into one reaches the model,
is stored forever, is counted in every later prompt, and may be summarised as something that
happened. A command routes the same words where they belong — or nowhere — and leaves the
transcript alone. The rule that follows: **an unrecognised command is refused, never sent.** A
typo would otherwise cost what the message would have cost and land in the story as nonsense the
character has to react to, and append-only means it could not be taken back.

`src/lustjinn/commands.py` reads what was typed and says what it is:

```python
@dataclass(frozen=True)
class Prose:
    text: str

@dataclass(frozen=True)
class Command:
    spec: Spec
    argument: str

@dataclass(frozen=True)
class Unknown:
    name: str

@dataclass(frozen=True)
class Incomplete:
    spec: Spec

Parsed = Prose | Command | Unknown | Incomplete
```

Four small records and a union of them: the parse result is one of four things, and the caller
has to say what it does with each. The endpoint does so with a `match` statement:

```python
match commands.parse(body.text):
    case commands.Prose(text):
        return _streamed(turn(session, openrouter, settings, story, text))
    case commands.Command(spec=commands.Spec(name="ask"), argument=question):
        return _streamed(ask(session, openrouter, settings, story, question))
    case commands.Incomplete(spec=spec):
        raise HTTPException(422, f"Usage: {spec.usage} — nothing was stored.")
    case commands.Unknown(name=name):
        raise HTTPException(422, f"/{name} is not a command, so nothing was sent ...")
```

::: dotnet
This is a `switch` expression with type patterns and property patterns:
`case Command { Spec.Name: "ask" } c`. Python's version matches on the class, then on positional
fields (`Prose(text)` binds the first field) or named ones (`spec=...`). Dataclasses get the
positional form for free. The union `Parsed` is the closed set of cases a discriminated union
would give you, minus the compiler's exhaustiveness check — pyright does not insist every case is
handled, so the catch-all is the author's job.
:::

The parser itself follows rules the donor arrived at one bug at a time: only a slash in the very
first column counts (a slash mid-sentence is punctuation — `and/or`, a date — and prose is far
more common than commands); `//` sends a line that genuinely begins with one, with the first
slash stripped; the name runs to the first whitespace, a newline included, so a command whose
argument starts on the next line is still that command; a command that needs an argument and has
none is refused quoting its usage. The table of commands holds one entry for now, `ask`; each
later step adds its own as it builds them, and until then `/do` is unknown here, and refused.

### A question is not a turn

`/ask Where does she live?` asks the model a question about the story, out of character. The
rules, each pinned by a test in `tests/test_asides.py`:

- **The same prompt as a turn**, byte for byte, up to the instruction — then the ask directive,
  which says what it is ("Step out of the scene. This is a question from the reader… it is not a
  turn"), what the answer must be (brief, plain, in the author's voice), and that it must come
  only from what was given: "Where it does not say, say that it does not say." Every instruction
  this project sends says what it is; a bare directive gets echoed back as the reply.
- **Cold and short**: temperature 0.4, 600 tokens, reasoning off, no frequency penalty. An
  answer can be promoted to a pinned fact in step 7, so an embellishment would become something
  the character believes.
- **Stored apart.** The answer streams back like a reply and goes into a new table, `asides`
  (migration `0004`), with the model, the host, the token counts and the newest message's
  sequence at the time. Nothing goes into `messages`, so no later prompt — and later, no
  summary, no fact, no embedding — ever sees it. A ledger row of kind `aside` is written, because
  a billed call that left no trace would make the audit quietly stop adding up.

On a caching host the question is nearly free: the prefix is what the next turn is about to send
anyway.

## Testing a stream

The model is faked at the network, not above it. `tests/scripted_model.py` is a queue of answers
in OpenRouter's own stream format — a keep-alive comment, the text split mid-sentence across two
chunks (a client that only handled whole words would pass with one chunk and garble a real
reply), a chunk with `finish_reason`, a last chunk with `usage` and `cost`, then `[DONE]` — behind
an `httpx2.MockTransport`:

```python
def transport(self) -> httpx2.MockTransport:
    def handle(request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        self.calls.append(json.loads(request.content))
        return self._answers.popleft()()
    return httpx2.MockTransport(handle)
```

A test says what the model answers before the call that needs it, then asserts on what was sent:

```python
model.fails().says("I could say the same about you.")

first = await send(client, story.id, "Hello.")
second = await send(client, story.id, "Hello.")

assert first.last[0] == "error"
assert second.done["reply"]["text"] == "I could say the same about you."
assert len(model.calls) == 2
```

`model` is a fixture, and the `client` fixture overrides `get_openrouter` with a client built on
the scripted transport — the same `dependency_overrides` trick as the session. The vocabulary
(`says`, `says_unpriced`, `fails`, `empty`, `truncated`) is the donor's,
because its tests are the specification: every idempotency case in `tests/test_turns.py` has a
namesake in `custom-airp`.

`tests/streaming.py` reads the API's own stream the way a client will — through the same
`sse.events` parser the client uses to read OpenRouter — and answers the three questions a test
asks: what was streamed (`.text`), how it ended (`.done`, `.error`), and with what status.

::: dotnet
`MockTransport` is a fake `HttpMessageHandler`: a function from `HttpRequestMessage` to
`HttpResponseMessage`, injected under the client. The donor's `ScriptedHandler` is the same
thing in thirty lines of C#; here it is a closure. `monkeypatch.setattr(turns, "request_hash",
pinned)` — used once, to simulate a true replay — is the one place a test reaches into a module
and replaces a function, which NSubstitute would need an interface for.
:::

::: try
Play a turn and watch it arrive. Put your OpenRouter key in `.env` as
`LUSTJINN_OPENROUTER_API_KEY`, run the migrations and the seed script again, start the server,
and create a story with the dummy character on `/docs` as in chapter 2. Then, with the token
and the story's id, in a terminal (`-N` keeps curl from buffering):

```
curl -N -X POST http://127.0.0.1:8000/stories/<id>/send \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"text": "I come in from the rain and shake out my coat."}'
```

The `delta` events appear as the model writes; the `done` event ends them. Open the story on
`/docs`: both messages are there. Then:

- Send `/ask What does she make of me so far?` — an answer, and nothing new in the story.
- Send `/aks anything` — refused, with nothing stored and nothing billed.
- Reroll with `POST /stories/<id>/reroll`, then `SELECT sequence, role, deleted_at FROM messages`
  in psql: the old reply is hidden, its number is not reused, and `SELECT kind, cost FROM spend`
  shows every call that was made.

Finally, change the key in `.env` to something wrong, restart, and send again: the `error`
event says the message was kept, and `GET /stories/<id>` agrees.
:::

## What step 3 leaves behind

- A streaming OpenRouter client with one error type, one timeout, provider routing, and money
  read as `Decimal` from the response — never computed from a price list.
- A ledger with a row for every billed call, insert-only, surviving everything.
- A turn that keeps the reader's message before the model is asked, is safe to retry, and
  streams the reply to the client over server-sent events.
- Reroll, and slash commands where a typo costs nothing. `/ask` answers out of character and
  stores nothing in the story.
- A scripted model that speaks OpenRouter's stream format, so every test runs without a network.

**Next — Chapter 4, The library.** Characters with their openings, personas and snippets, with
optimistic concurrency and a history of every saved version — and the first foreign keys the
owner edits through.
