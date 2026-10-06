# The context builder

Until now the prompt was three things in a row: the card, the persona, the whole transcript.
That works for a story of twenty turns. It does not work for a story of two hundred, and the
thesis of this project — *you do not need an infinite context window if you have a good retrieval
layer* — needs a place where the prompt is *assembled* rather than concatenated. Step 5 builds
that place: a module of pure functions that takes everything a prompt could hold and returns what
the model is sent, within a budget, with an account of what it did.

Nothing in this step touches the database or the network. That is the point of it, and the
lesson: the most important logic in the app is the easiest to test.

## Why layers, and why this order

A model is sent a list of messages. The order of that list is a cache key: providers keep a
**prefix cache**, and a request whose first *n* messages are byte-for-byte the same as the last
request's gets those *n* messages for a fraction of the price. So the prompt is laid out from the
thing that never changes to the thing that changes every turn:

| Layer | Changes | Here since |
|---|---|---|
| character | when the card is edited | step 3 |
| persona | when the persona is edited | step 3 |
| directives | when a dial is turned | step 7 |
| world | when a fact is extracted or retired | step 6 |
| summaries | every few dozen turns | step 6 |
| **history** | every turn — and it is the layer that *gives way* | step 3 |
| memories | every turn | step 6 |
| trackers | every turn | step 7 |
| instruction | every turn; this turn only | step 3 |

Retrieval goes *after* the history on purpose. Recalled turns change with every message, and
putting them before the transcript would invalidate the cache from that point down, every turn.

## The shape: dataclasses in, dataclasses out

`src/lustjinn/context.py` has one input type and one output type:

```python
@dataclass(frozen=True, kw_only=True)
class Layers:
    character: Character
    persona: Persona | None = None
    directives: str | None = None
    facts: Sequence[Fact] = ()
    summaries: Sequence[str] = ()
    history: Sequence[Message] = ()
    memories: Sequence[Recalled] = ()
    trackers: str | None = None
    instruction: str | None = None


@dataclass(frozen=True)
class Built:
    messages: list[ChatMessage]
    spent: dict[str, Spent]
    budget: int | None
```

A **dataclass** is a class whose `__init__`, `__repr__` and `__eq__` are written for you from the
annotated fields. `frozen=True` makes instances immutable. `kw_only=True` means every field must
be passed by name — `Layers(character=c, history=h)`, never `Layers(c, h)`.

The keyword-only rule is not taste. airp's `Build` took its layers positionally, and three of its
bugs came from the same move: a new layer added in the middle of the parameter list, and one call
site that kept passing the old arguments in the old positions — summaries where the directives
should be, compiling cleanly. Names cannot be shifted.

::: dotnet
`@dataclass(frozen=True)` is a `record` with `init`-only properties; `kw_only=True` is a
constructor you may only call with named arguments. `Sequence[Message]` is `IReadOnlyList<Message>`
— a type that promises you will only read. `Fact` and `Recalled` are small records that steps 6
and 7 will produce; they exist now so the builder's shape does not change when they arrive.
:::

## Counting tokens

A budget is measured in tokens, and there is exactly one honest way to count them: the way the
model does. `src/lustjinn/tokens.py`:

```python
ENCODING = "o200k_base"
PER_MESSAGE = 4


@lru_cache
def encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING)


def count(text: str) -> int:
    return len(encoding().encode(text, disallowed_special=()))


def for_message(text: str) -> int:
    return count(text) + PER_MESSAGE
```

**tiktoken** is OpenAI's tokenizer library; `o200k_base` is the vocabulary of their current
models, and the one airp counted with. Two details:

- **`PER_MESSAGE = 4`**: a message costs more than its text. The role and the separators the API
  wraps around it come to about four tokens — a figure measured against what a provider reported
  for a real transcript, not derived from anything.
- **`disallowed_special=()`**: by default tiktoken refuses to encode text containing a marker like
  `<|endoftext|>`, because in a prompt those mean something. In a card they are just characters.
  A character sheet that quoted one would have crashed the count.

::: warning
A characters-per-token constant is not a count. Spanish runs about 30% more tokens per character
than English in these vocabularies; a budget that holds in one language overflows in the other.
That is why there is a tokenizer in the project and not a division by four.
:::

::: note
tiktoken downloads the vocabulary file (3.6 MB) the first time it is used and keeps it in a cache
directory — `TIKTOKEN_CACHE_DIR` if set, the system's temporary folder otherwise. On this machine
and in CI that happens once and silently. A sandbox that blocks `openaipublic.blob.core.windows.net`
cannot count tokens until the domain is allowed.
:::

## The budget

`build(layers, budget=32_000, recall_percent=10)` does its arithmetic in a fixed order:

1. **Fit the memories under their cap.** The cap is `budget × recall_percent / 100` — a *share*,
   not a count. Four recalled turns once filled a 60,000-token prompt, which is why the rule is not
   "at most four". Memories arrive most relevant first; each is kept if the layer still fits under
   the cap with it, and one that does not fit is **skipped, not fatal** — a shorter one further
   down may still make it. The survivors are then sorted back into story order, so the model reads
   them as a transcript.
2. **Cost every fixed layer.** Character, persona, directives, world, summaries, memories, trackers,
   instruction: these go in whole, whatever they cost. The instruction is counted here too — it is
   never squeezed out by old turns.
3. **Give the history what is left.** `room = max(0, budget − fixed)`. Walk the transcript from the
   newest message backwards, adding each turn while it fits, and **stop at the first that does
   not**. The kept turns are always a contiguous run ending on the newest.
4. **The newest message is always kept**, before the room is even checked. A prompt that leaves out
   the words the reader just typed is a reply to nothing — and a real story once lost the reader's
   own message that way. If the budget cannot hold even the fixed layers, the prompt goes *over*
   budget by one message rather than under it by the one that matters.

```python
def _fit_history(history: Sequence[Message], room: int | None) -> tuple[list[Message], int]:
    if not history:
        return [], 0
    kept = [history[-1]]
    used = tokens.for_message(history[-1].text)
    for turn in reversed(history[:-1]):
        cost = tokens.for_message(turn.text)
        if room is not None and used + cost > room:
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    return kept, len(history) - len(kept)
```

The default budget is 32,000 tokens — far below any current model's window, on purpose. Two
reasons, both measured on real stories: attention thins out as a prompt grows, so a longer
transcript does not make a better reply past a point; and every token in the prompt is paid for on
every turn, so a 100,000-token prompt costs three times what a 32,000-token one does, forever.

::: dotnet
`_fit_history` is the loop you would write with a `for` over `history.Reverse().Skip(1)` and a
running total. Python's `reversed(history[:-1])` is the same `Reverse().Skip(1)` read inside-out:
slice off the last element, then iterate backwards. The tuple return `(kept, dropped)` is a
`(List<Message> Kept, int Dropped)` value tuple; the caller unpacks it as `history, dropped = …`.
:::

## The audit

Every `Built` carries `spent`: per layer, how many tokens it took and how many items were dropped
to fit. `describe()` turns that into one line:

```
character 2755 · persona 412 · history 1830 (12 dropped) · instruction 60 · total 5057/32000
```

That line is stored on every reply, in `messages.context_audit`, with the total in
`estimated_prompt_tokens` — right beside `prompt_tokens`, the figure the provider actually billed.
`GET /stories/{id}/audit` lists the newest twelve replies and eight questions with both numbers.
Rerolled replies are listed too, marked hidden: "why did it say that?" is asked of them more than
of any other.

Having the estimate beside the bill is what made the next paragraph possible.

::: warning
The first real turn of this project was billed at **2,755** prompt tokens. The counter said
**3,163** for the same prompt — 15% high. Not a bug in the arithmetic: `o200k_base` is OpenAI's
vocabulary, and DeepSeek has its own, which happens to spend fewer tokens on this prose. High is
the safe direction (a prompt the counter thinks is at the budget is under it), so the test that
checks the real turn pins the margin at "between the billed figure and 20% above it" rather than
pretending to 10%. Closing the gap is #94, and the audit is collecting the data for it on every
reply.
:::

## Testing pure logic

Thirty-five tests cover this step, and most run in under a millisecond, because the thing under
test is a function from values to values. The tests build their inputs by hand:

```python
def turns(*lines: str) -> list[Message]:
    roles = [Role.USER, Role.ASSISTANT]
    return [Message(sequence=i + 1, role=roles[i % 2], text=line) for i, line in enumerate(lines)]


def test_the_turns_kept_are_the_ones_nearest_the_reply(dummy: Dummy) -> None:
    built = build(
        Layers(character=heron(dummy), history=long_story(100)),
        budget=tokens.for_message(dummy.card) + 500,
    )

    kept = [m.content for m in built.messages[1:]]
    assert kept[-1].startswith("Turn 100.")
    numbers = [int(line.split(".")[0].split()[1]) for line in kept]
    assert numbers == list(range(numbers[0], 101))
```

Three things to notice:

- **`Message(...)` without a database.** A SQLAlchemy model is still a Python object; constructing
  one costs nothing and saves nothing. The test never opens a session.
- **The card is the dummy's**, 1,850 words, through the `dummy` fixture. airp's equivalent tests
  used a four-token card inline, and a bug that only appeared with a real-size card cost a story
  twenty-four turns of memory. Here the fixed layers are big enough to make the budget bind the way
  it does in a real story.
- **`*lines: str`** is `params string[] lines`: `turns("One.", "Two.", "Three.")`.

::: dotnet
These are xUnit `[Fact]`s over a static class, and the fixture is `IClassFixture<Dummy>`. What
has no counterpart is how little ceremony it takes: no `Arrange` helpers to inject, no
`IOptions<ContextOptions>` to fake. `build` takes its budget as an argument, so a test passes a
small number and the rule shows itself.
:::

::: try
Play a turn, then look at what it was built from:

```
GET /stories/{id}/audit
```

Compare `estimated_prompt_tokens` with `prompt_tokens` on the newest reply. Then set
`LUSTJINN_CONTEXT_BUDGET=4000` in `.env`, restart the server, play another turn, and look again:
`history` now shows `(n dropped)`, and the total sits just under 4,000 — unless the card alone is
bigger than that, in which case the total is over and the history is exactly one message. Put the
budget back.

From `psql`, the same comparison across every reply so far:

```sql
SELECT sequence, estimated_prompt_tokens, prompt_tokens,
       round(100.0 * estimated_prompt_tokens / prompt_tokens) AS estimate_pct
FROM messages WHERE prompt_tokens IS NOT NULL ORDER BY sequence;
```
:::

## What step 5 leaves behind

- One place where the prompt is assembled, in a fixed order, with slots for everything steps 6
  and 7 will add.
- A token count in the model's own units, and a budget the transcript yields to — oldest first,
  newest never.
- Recalled memories capped at a share of the budget, ready for retrieval to fill.
- An audit on every reply, estimate beside bill, and the first calibration it produced.

**Next — Chapter 6, The memory.** The three mechanisms that let a story outlive its budget:
summaries of what happened, retrieval of what was said, facts about what is true now — and the
background calls that produce them only when a story needs them.
