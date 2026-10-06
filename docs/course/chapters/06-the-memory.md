# The memory

This is the chapter the project exists for. Everything before it was a chat client with good
habits; what this step adds is the reason a story can run to its five-hundredth turn and the
character still knows what was said on the tenth.

> You do not need an infinite context window if you have a good retrieval layer.

The memory is three mechanisms, each answering one question, and a rule about when they run:

| Mechanism | Answers | Produces | When |
|---|---|---|---|
| **Summaries** | what happened | prose, one per stretch of turns | when the transcript no longer fits the budget |
| **Retrieval** | what was said | the few old turns nearest to the reader's last words | once something has been summarised |
| **Facts** | what is true now | one sentence each, with a validity range | right after each summary |

The rule: **a story that fits its budget costs no extra call.** Nothing here fires until the
context builder from chapter 5 would otherwise start dropping turns.

## One entry point

`memory.compose` is what a turn (and a question) now calls instead of `context.build`:

```python
built = await memory.compose(
    session, openrouter, settings, story, persona, history, instruction=...
)
```

It does five things in order, and each is a section below:

1. Loads the story's summaries and works out which turns they already **cover**. Covered turns
   are not sent; the summaries stand in for them. The rest are the *recent* turns.
2. If the recent turns no longer fit, **compresses** the oldest of them into one new summary.
3. If that worked, **extracts facts** from the same stretch.
4. **Retrieves** the compressed turns nearest to the reader's last message.
5. Builds the prompt with chapter 5's builder — summaries, world, history, memories all in their
   layers — and returns it with the audit.

Steps 2, 3 and 4 are each a model call, and each can fail. The design decision that shapes the
whole module is what happens then: **the reader never pays for a background failure with their
reply.** A failed summary sends the turns whole and sets the budget aside; a failed extraction
leaves the summary standing; a failed retrieval sends no memories. The reply is asked for
regardless.

::: dotnet
`compose` is an orchestration method the way an application service in a clean-architecture .NET
project is: it owns the order of operations and the transaction boundaries, and delegates the
work. There is no mediator and no handler per step; the five steps are five function calls on
one page, because being able to read the whole algorithm top to bottom is worth more here than
pluggability.
:::

## Summaries: what happened

### When, and how much

The builder decides what fits; the summariser has to decide *before* the builder runs, so it
estimates the same thing: the fixed layers, plus the reply's ceiling, plus the room retrieval
will take, plus 200 tokens of slack. What is left is the **allowance** for the recent turns.

```python
def batch_to_compress(recent: Sequence[Message], allowance: int) -> list[Message]:
    overflow = overflowing(recent, allowance)
    if overflow <= 0:
        return []
    size = min(max(overflow, WORTH_A_CALL), len(recent) - ALWAYS_WHOLE, AT_MOST_PER_SUMMARY)
    return list(recent[:size]) if size > 0 else []
```

Three constants, each a lesson airp paid for:

- **`WORTH_A_CALL = 10`.** The first version compressed only what overflowed. On a long story that
  was two messages, every single turn — a model call per turn for a summary of two lines. A batch
  of at least ten buys several turns of room per call.
- **`ALWAYS_WHOLE = 6`.** The newest six turns are the scene in progress and stay verbatim,
  **whatever the overflow**. The first version of this step treated six as a limit on *widening*
  the batch only, as the donor does, and `max(overflow, …)` could reach past them. The real
  playtest caught it on the thirteenth turn of a story squeezed into a 6,000-token budget: the
  reader's own newest message was summarised, the prompt had no history layer at all, and the
  character answered a message it had never been shown. That is the exact failure the kickoff
  lesson forbids, so the newest six are now a hard cap (#96). What still does not fit among them
  is the context builder's problem — dropped from that prompt, the newest never — not the
  summariser's. In practice the case needs a budget that leaves almost no room for turns; at
  32,000 the newest six never overflow.
- **`AT_MOST_PER_SUMMARY = 40`.** One call over ninety-nine messages came back as `##`. A model
  asked to compress too much compresses it to nothing.

### What is asked, and what is accepted

The stretch is rendered as `Name: text` lines — the character by name, **the reader by their
persona's name, never "User"** — and sent with an instruction that asks for a factual account:
what happened in order, what was established, what changed between people, what was promised or
left unresolved, where the scene was left. Temperature 0.3, because a creative summariser invents
history the character then believes forever. A ceiling of 1,200 tokens.

The answer is judged before it is kept:

```python
def credible(summary: str, source: Sequence[Message]) -> bool:
    produced = tokens.count(summary)
    source_tokens = sum(tokens.count(turn.text) for turn in source)
    return produced >= max(LEAST_SUMMARY_TOKENS, source_tokens // LEAST_COMPRESSION)
```

A summary shorter than one sixtieth of what it replaces cannot have kept it. Working summaries
compress 3× to 19×; `##` compresses 600×. A refused summary is **still billed** — the call
happened — and the turns go to the model whole this time. Over budget rather than discard.

::: warning
Where a story is compressed matters as much as whether. The summary layer sits *before* the
history in the prompt, so a model reads "earlier, this happened" and then the live turns — the
same order a reader would. And one summary per call: a long backlog is worked through over
several turns, not in one heroic request that comes back as `##`.
:::

## Facts: what is true now

A summary is prose, and prose is a poor place to keep "she is allergic to shellfish". So right
after each summary, the same stretch is read once more by an **extractor**, which answers JSON:

```json
{
  "facts": [ { "subject": "Isaure", "text": "owes Derrow & Sons four hundred and ten marks." } ],
  "retired": [ "01a111c5" ]
}
```

- **Subject** is always a name — a character, a place, a pair. The instruction forbids "User",
  "the user" and "the reader" as subjects: a story does not know who the user is.
- **New facts** begin at the first turn of the stretch; the world layer shows them from the very
  turn they were extracted on, because `compose` reads the live facts *after* the extraction.
- **Retiring** is the interesting half. The extractor is shown the existing facts with a short
  id each, and names the ones the stretch made false — a change of heart, a healed wound, a kept
  promise. A retired fact gets `valid_to` = the last turn of the stretch and leaves the prompt. A
  world state that only accumulated would end up asserting both that she distrusts the reader and
  that she trusts them, and the model would believe whichever it read last.
- **A pinned fact cannot be retired by the model.** When a person states a fact (step 7's
  `/fact`, or pinning an `/ask` answer), it has no `model` and `pinned` is true. It is not derived
  from the transcript — it may be about something the story never mentioned — so nothing in the
  transcript can prove it wrong.

The parsing is deliberately generous: the JSON is read from the first `{` to the last `}`, so a
model that wraps its answer in a code fence or a sentence does no harm. Anything that is not the
agreed shape is skipped rather than guessed at, and an answer with no object in it records
nothing — billed, like the refused summary. Temperature 0.2, colder still: an invented fact is
injected into every prompt from then on.

::: dotnet
`parse` is the kind of function `System.Text.Json` would make you write with a `JsonDocument`
and a dozen `TryGetProperty` calls. Python's `json.loads` gives back nested `dict`s and `list`s,
and `isinstance` checks do the rest. pyright strict insists on those checks: a value out of
`json.loads` is `Any`, and the `# pyright: ignore` comments mark exactly where the untyped world
is being read.
:::

## Retrieval: what was said

A summary keeps what happened; it does not keep *how it was said*, and three hundred turns later
the character should still be able to echo the reader's own words from the tenth. That is
retrieval: each compressed turn is turned into a **vector** — a list of 1,536 numbers that places
its meaning in a space where similar texts are near — and the reader's last message is used to
find the nearest few.

### pgvector

The vectors live in Postgres, in a column of type `vector(1536)` that the **pgvector** extension
provides, with an HNSW index for approximate nearest-neighbour search by cosine distance.

```python
distance = Embedding.vector.cosine_distance(wanted).label("distance")
rows = await session.execute(
    select(Message.sequence, Message.role, Message.text, distance)
    .join(Embedding, Embedding.message_id == Message.id)
    .where(Message.story_id == story.id, Message.sequence <= covered, Message.deleted_at.is_(None))
    .order_by(distance)
    .limit(settings.recall_count)
)
```

`cosine_distance` compiles to pgvector's `<=>` operator; `1 − distance` is the similarity, and
anything below the threshold (0.35) is not recalled. The column refuses a vector of any other
length — a test proves it with a three-number vector.

### The rules

- **Only compressed turns are embedded.** The recent ones are in the prompt verbatim; recalling
  them would send them twice. Embedding is done lazily, oldest first, at most 128 per call — a long
  story meeting retrieval for the first time catches up over a few turns.
- **The query is the reader's last message** among the recent turns. What they just said is the
  best signal of what they are reaching back for.
- **At most `recall_count` turns** (4), most relevant first. Then chapter 5's builder applies the
  real limit — the recall *share* of the budget — and puts the survivors back in story order.
- **Any failure costs the reader nothing but the memories.** The embedding host down, a wrong
  dimension, a timeout: the reply goes out without recalled turns. airp had a bug here — an
  embedding *timeout* surfaced as a cancellation and failed the whole turn — so the test for it is
  explicit.
- **Embeddings are not in the ledger.** The whole corpus of a story costs under a cent; airp's
  cost report said so rather than pretend to completeness, and so does this one.

::: note
DeepSeek has no embeddings endpoint, so the embedding model stays on OpenRouter
(`openai/text-embedding-3-small`) whatever writes the replies. Setting
`LUSTJINN_EMBEDDING_MODEL` to empty switches retrieval off entirely — summaries and facts keep
working.
:::

## Background calls: once more, only if it could help

Summaries and extractions are the story's own calls, with nobody waiting on them. A refusing
summariser is a character that forgets, so they are asked once more — but only for a failure a
second attempt could fix:

```python
def worth_another_go(error: ModelError) -> bool:
    status = error.status
    if status is None:  # a timeout, a dropped connection, a body that was not JSON
        return True
    return status in RETRYABLE_STATUSES or status >= 500   # 200 with nothing in it, 408, 429
```

A 401 or a 404 is not retried: a rejected key is rejected twice, and the second call would bill
for the same refusal. Two failures running give up. **A reply to the reader is never retried
here**: the reader sees the failure and decides.

::: dotnet
`once_more_if_worth_it[T](call: Callable[[], Awaitable[T]]) -> T` is a generic method taking a
`Func<Task<T>>` — Python 3.12's syntax for type parameters on a function, `def f[T](...)`, is
new enough that many examples online still use `TypeVar`. The policy itself is a one-retry
Polly policy with a predicate; written out, it is six lines.
:::

## Testing the memory

Every memory test plays on the dummy character. That is not a convenience: airp's memory tests
set a four-token card inline, and a bug that only showed with a real-size card — the summariser
not counting the character file when deciding what fit — cost a real story twenty-four turns of
memory. Here the fixed layers are the size they will be in production, and the budget binds the
way it will.

The scripted model from chapter 3 grew three verbs for this step:

- **`summarises(gist)`** answers a summary padded past the credibility floor — a test that wants
  a *refused* summary scripts `says("##")` instead.
- **`extracts(facts, retired)`** answers the extractor's JSON, optionally in a code fence.
- **The embeddings endpoint** answers with a *keyword embedder*: a text's vector says which of
  four words it contains, so "the knife" and "a knife on the table" are near, and two unrelated
  texts are orthogonal rather than identical. Deterministic, and no network.

And a `tune()` fixture changes a setting for one test — `tune(context_budget=…)` — so a story of
thirty turns can be made to overflow without being three hundred turns long.

::: warning
Every summary is followed by an extraction. When the summariser was first wired in, nine
summary tests broke at once: each had scripted a summary and a reply, and the extractor quietly
ate the reply. The fix was one line per test (`.summarises(…).extracts().says(…)`), but the
lesson is the one from chapter 3's spend ledger: a call that fires on its own is a call that is
easy to forget — in the budget, in the bill, and in the tests.
:::

::: try
Make the memory work in front of you. Set a small budget so compression starts early:

```
LUSTJINN_CONTEXT_BUDGET=6000
```

Run `uv run python scripts/seed_dummy.py` once more if you have not since chapter 4, so the
dummy persona is the default. Restart the server, start a story on the dummy character and play
fifteen or twenty short turns.
Then look at what happened:

```sql
SELECT from_sequence, to_sequence, message_count, left(text, 80) FROM summaries;
SELECT subject, text, valid_from_sequence, valid_to_sequence FROM facts ORDER BY created_at;
SELECT count(*) FROM embeddings;
SELECT kind, count(*), sum(cost) FROM spend GROUP BY kind;
```

Then ask the character about something from the first few turns — a name, an object — and read
`GET /stories/{id}/audit`: the newest reply's `context` line names a `memories` layer, and its
`summaries` and `world` layers carry the tokens that replaced the turns you no longer see. Put
the budget back.
:::

## A real run

Before this chapter was finished, the memory played a real story: twelve short turns on the
dummy character, then a question about the first night, with the budget forced down to 6,000
tokens so that compression would start within the hour instead of within the week. DeepSeek V4
Flash wrote the replies and the summaries; `text-embedding-3-small` made the vectors. What the
tables held afterwards:

| What | Count | Cost |
|---|---|---|
| Replies | 13 | $0.0086 |
| Summaries | 5 | $0.0024 |
| Fact extractions | 4 billed (one failed, cost nothing) | $0.0029 |
| Facts kept | 21, none retired yet | |
| Embeddings | 21 at the time; the five turns just compressed join on the next turn | |

The first summary covered turns 1–10, as designed. The next four covered 4, 5, 2 and 5 turns:
with a budget that tight, fewer than ten turns are ever to spare beyond the newest six, and the
batch shrinks to what there is. At 32,000 the batches stay at ten. The facts were the right kind
— *Rowan Hale is a surveyor for the Meridian Assurance Company* from turn 1, *Mags deals
left-handed* from turn 6 — and included details the character had invented itself, such as
which way the bolt on room seven throws, which is exactly what facts are for: once said, it is
true. The estimate for the last prompt was 4,716 tokens; DeepSeek billed 4,720.

And the run found the bug described above under `ALWAYS_WHOLE`: the thirteenth turn, the
question itself, was summarised, and the audit line read `character 2360 · world 417 ·
summaries 1939 · total 4716/6000` — no history. After the fix the same question gave `history 32
(1 dropped) · memories 530 · total 5278/6000`: the question kept, the previous reply dropped by
the builder because nothing else could give, and five recalled turns brought back for it.

One more thing it showed. The story had been created without a persona, and the local database
had no default persona set — it was seeded before the default existed — so the recalled turns
named the reader *the reader*. The rule held (never "User"), but a story with nobody to play as
is a weaker prompt than it needs to be. The try box below starts by making sure the seed has
run.

## What step 6 leaves behind

- A story can run past its budget without forgetting: summaries carry what happened, facts carry
  what is true, retrieval brings back what was said.
- Nothing fires for a story that fits, and nothing that fires can cost the reader their reply.
- Three new tables (`summaries`, `embeddings`, `facts`), pgvector enabled, and a ledger that
  shows every background call beside the replies.

**Next — Chapter 7, Story features.** What airp does beyond the core loop, as API features both
clients will use: directions with `/do`, dials, meters, regenerating with a reason, branching a
story, search, export, cost reports, editing facts by hand, and rebuilding a story's memory from
its transcript.
