# The donor: what to port from custom-airp, and from where

**custom-airp** (`argamboad/custom-airp`, C#/.NET 10, ~52,000 lines, 70 test files) is the donor
of **logic** for Lustjinn — not of code and not of data. This map says, for every step of the
roadmap, which files carry the rules to port, what those rules are, which tests pin them, and where
a port that only read a summary would go wrong. Read the donor file before building the feature;
read the test names as the specification.

Paths are relative to the donor's root. `LCP` is `src/Airp.Infrastructure/Providers/LocalConversationProvider.cs`
(2,495 lines), which holds almost all the orchestration. `tests/` is `tests/Airp.Tests/`.
Surveyed 2026-10-05 at the donor's commit `71a1470`.

## Two things the donor does not have

- **Streaming.** airp sends `stream: false` and waits for the whole reply. Lustjinn's decision to
  stream replies over SSE (KICKOFF, *Decided*) is new design: the SSE parsing of OpenRouter's
  stream, and reading `usage` from its final chunk, have no donor. Verify against OpenRouter's
  current docs when building #14.
- **A base system prompt.** The character card is the first system message. The only "never write
  the user's words" rules live in the persona frame and the directive frames.

---

## Step 2 · Stories and messages

**Donors:** `src/Airp.Infrastructure/Storage/Local/Entities.cs`, `AirpDbContext.cs` (schema and the
append-only guard), `docs/DATA.md`, ADR 0003 (append-only), ADR 0004 (persist first).

**Schema worth copying** (SQLite through EF Core there; Postgres here)

- `Messages`: `Sequence`, `Role`, `Text`, `SentAtUtc`, `DeletedAtUtc`, `RequestHash`, `Model`,
  `FellBackFrom`, `Provider`, `PromptTokens`, `CompletionTokens`, `EstimatedPromptTokens`,
  `ContextAudit`, `Embedding`. Unique `(ConversationId, Sequence)`; unique **filtered**
  `(ConversationId, RequestHash) WHERE RequestHash IS NOT NULL`; FK to the story `ON DELETE RESTRICT`.
- Roles: User, Assistant, System, Data. **An opening is stored at sequence 1, role Assistant,
  `Model = null`** — null model means "written by a person", and the reroll rule depends on it.
- Only `Messages` has a foreign key in the donor; everything else links by id text. Here, use real
  foreign keys everywhere **except `spend`** — the ledger must survive a purge (step 7).

**Rules**

- **Append-only guard** (`AirpDbContext.GuardAppendOnly`): refuses deleting a message, changing a
  message's `Text`, and deleting a story. Other columns on a message may change: `DeletedAtUtc`,
  `RequestHash`, `Embedding`. A **purge flag** bypasses it, set only inside the purge. → Here: the
  trigger of #12 must allow exactly those updates and have one explicit bypass path for #70.
- **Next sequence** = `MAX(Sequence)` over all rows **including hidden** + 1.
- **Soft delete** by `DeletedAtUtc`; every read filters it. (Donor quirk: fetching a story by id does
  not filter, so a hidden story can still be sent to. Decide deliberately.)
- Donor rule from pain: never order or compare timestamps in SQL (SQLite stored them as text).
  Postgres has real `timestamptz`, so this one does **not** carry over — order by `sequence`
  anyway, it is the truth of a story.

**Tests to port:** `tests/LocalStoreTests.cs` — `Deleting_a_message_is_refused`,
`Rewriting_the_text_of_a_message_is_refused`, `Deleting_a_conversation_is_refused_because_it_would_take_the_messages`,
`Hiding_a_message_is_allowed_and_keeps_the_row`, `The_same_request_hash_cannot_land_twice_in_one_conversation`,
`The_same_request_hash_in_a_different_conversation_is_fine`, `A_sequence_number_cannot_be_reused_within_a_conversation`.

**Pitfall:** the guard rejects a *text edit*, not every update. Clearing `RequestHash` on a hidden
message is legitimate and the retry path needs it (step 3).

---

## Step 3 · One turn against OpenRouter

### The turn and its idempotency (#15)

**Donors:** `LCP.SendAsync` (244–346), `LCP.Hash` (2482–2494), `LCP.ReplyAsync` (745–836),
`src/Airp.Infrastructure/Providers/FrontEndTurn.cs`, ADR 0004.

- **Anchor** = `MAX(Sequence)` of **live Assistant** messages, or 0 — never the next free sequence.
- **Hash** = first 32 hex chars of `SHA256("{conversationId}|{anchor}|{directed}")`, where
  `directed = text` or `text + "\x1f" + instruction.strip()` when a direction accompanies it. The
  instruction hashed is the **fully framed** direction text, so changing frame wording changes hashes.
- **Order:** look up `(conversation, hash)`. Exists and hidden → clear its hash and treat as new
  (this is how re-sending deleted words works). Exists and a live reply came after it → return the
  stored message, **no model call**. Exists and unanswered → reuse the row and call again. Otherwise
  insert the reader's row and **commit before the model call**.
- Model failure → the message is kept; the error says so ("Your message was kept — do not send it
  again"). **No retry inside the reply path**; only background calls retry.
- Memory work (summarise, extract, embed) runs **before** the reply call, inside the same turn.

**Tests:** `tests/LocalProviderTests.cs` — `The_message_survives_a_model_that_fails`,
`Retrying_a_send_the_model_failed_does_not_store_it_twice`, `The_same_words_after_a_reply_landed_are_a_genuinely_new_send`,
`A_send_already_answered_is_returned_rather_than_replayed`, `Resending_words_the_reader_deleted_puts_them_back_in_the_prompt`;
`tests/AsideTests.cs` — `The_same_words_under_two_directions_are_two_different_sends`.

### The OpenRouter client (#14)

**Donors:** `src/Airp.Infrastructure/Providers/OpenRouterClient.cs`, `OpenRouterEmbeddingClient.cs`,
`src/Airp.Application/Options/ModelOptions.cs`, `src/Airp.Application/Context/ModelRouter.cs`, ADR 0008, 0009, 0019.

- **Request:** `POST {base}/chat/completions` with `model, temperature, max_tokens, messages`;
  `frequency_penalty` only when set (0 and absent are different requests); `reasoning: {enabled: bool}`
  only when set; `provider: {order, ignore, allow_fallbacks}` only when something is configured,
  slugs trimmed, never lower-cased. Headers: `Authorization: Bearer`, `HTTP-Referer`, `X-Title`.
- **Response:** `choices[0].message.content`, `model`, `provider` (the host's display name, e.g.
  `DeepInfra`, while request slugs are lower-case), `id` kept as the generation id, `usage.prompt_tokens`,
  `usage.completion_tokens`, `usage.cost`, `usage.prompt_tokens_details.cached_tokens` and
  `.cache_write_tokens`, `finish_reason` (`length` = truncated).
- **A 200 with no content is a failure**, with a message naming the finish reason, the host, and
  "reasoning only" when the model spent everything thinking.
- **Errors:** missing key fails before any request; timeout 180 s (donor bug: .NET's 100 s HttpClient
  default fired first — set one timeout, in one place); non-2xx uses only `error.message` from the
  body, never the whole body; "no such model" = 404, or 400 whose message contains "not a valid model".
- **Defaults:** base `https://openrouter.ai/api/v1`, model `deepseek/deepseek-v4-flash`, temperature
  1.0, max tokens 1024, key from `OPENROUTER_API_KEY`. Shipped alternative models and their
  temperatures (0.3–0.9 for the finetunes) in `ModelOptions.cs`.
- **Temperature per model:** `share = (t − 0.6) / 0.8; mapped = min + share × (max − min)`, clamped to
  `[0.05, max]`, rounded to 3 decimals — applied only to a story's own model.
- **Reasoning off** on Reply and Aside only; Summary and Facts never send the field.
- **Model list:** `GET {base}/models` → `id`, `context_length`, `pricing.prompt/completion` (per token;
  ×1,000,000 for per-million). Describe a choice against the default: ≥1.5× "≈N× the default",
  ≤0.67× "≈1/N of the default", else "about the default".
- **Embeddings:** `POST {base}/embeddings` `{model, input: [...]}`, vectors ordered by `data[].index`;
  default `openai/text-embedding-3-small`, 1536 dimensions (the donor never checks the dimension — do).

**Tests:** `tests/LanguageModelTests.cs` (whole file), `tests/EmbeddingEndpointTests.cs` (routing
tests), `tests/ModelRouterTests.cs`.

### The spend ledger (#16)

**Donors:** `Ledger.cs`, `SpendReports.cs`, `PurgeResults.cs`, `LCP.SpendAsync` (611–710), ADR 0010.

- Row: `Kind` (Reply, Aside, Summary, Facts), `MessageId` (Reply only), `AtUtc`, `Model`, `Provider`,
  `GenerationId`, `PromptTokens`, `CompletionTokens`, `CachedTokens`, `CacheWriteTokens`, `Cost` —
  **decimal, nullable**. Null is "the API gave no price", reported as *unpriced*; zero is a price.
- Written in the **same transaction** as the reply. Summary and Facts rows are written **before**
  the output is judged: a refused summary still bills. A call that throws writes no row.
- Embeddings are never in the ledger.

**Tests:** `tests/SpendTests.cs` (whole file).

### Reroll (#17), slash commands (#18)

- **Reroll:** last live message must be Assistant. Hide it (`DeletedAtUtc`) **before** the call; if
  the call throws, un-hide it. The superseded reply is never in the prompt (a model shown its last
  attempt writes it again). **The opening is not rerolled** until the reader has taken a turn:
  `Model == null` and no live User message → refuse. Reasons and their texts are in step 7 (#61).
  Tests: `tests/OpeningRerollTests.cs`, `tests/RegenerateDirectiveTests.cs`,
  `tests/LocalProviderTests.cs` (`Regenerating_*`).
- **Slash commands:** `src/Airp.Application/Text/SlashCommands.cs`. Trim; not `/` → message; `//` →
  message with one slash stripped; name runs to the first whitespace (a newline counts), argument is
  the rest trimmed; unknown name → **refused, never sent**; a required argument missing → refused with
  the usage line "— nothing was stored." Known commands and their groups: billed `do ask focus`;
  free `card persona facts trackers audit cost search help`; write `fact tracker`; plus web-only
  `/recap [n]` (default 4, 1–20). Tests: `tests/SlashCommandTests.cs`, `tests/ComposerCommandTests.cs`.
- **`/ask`** (`LCP.AskAsync` 503–588, `AskAnswer.cs`, ADR 0011): the same prompt as a turn with the
  ask directive as the instruction; temperature 0.4, 600 tokens, reasoning off, frequency penalty
  forced off; a Spend row of kind Aside and an `asides` row (`Sequence` = max live sequence);
  **nothing in `messages`**. The directive ends "The question: …" and says to answer only from what
  is above and to say when the story does not say. **Pitfall:** asking runs the full compose, so a
  question can trigger compression, extraction and embedding — all billed. Tests: `tests/AsideTests.cs`.

---

## Step 4 · The library

**Donors:** `src/Airp.Infrastructure/TextLibrary.cs`, `LCP.ConversationsUsingAsync` (180–210),
`src/Airp.Web/Shelves.cs`, `src/Airp.Web/Pages/Library*.cshtml.cs`, ADR 0012.

- Four shelves: characters, personas, snippets, openings. **An opening belongs to the character of
  the same name** — here it is a column on the character (KICKOFF), so that rule disappears.
- Name matching is case-insensitive; names starting with `_` are hidden; names with `< > : " / \ | ? *`
  or control characters are refused.
- **Version** = first 16 hex chars of SHA-256 of the text; a save with a stale version is refused
  (`Changed`). Here: `version` integer and `UPDATE … WHERE id = $1 AND version = $2` (KICKOFF).
- **Delete guard:** refused while a live story uses the entry. For personas, every story with no
  persona of its own counts as using the **default persona**. Here `ON DELETE RESTRICT` does the
  first; the default-persona case needs code.
- Resolution rule (inline text → named file → default file) collapses here: stories hold ids.
- **Skeletons:** `CharacterSkeleton` has sections THE WORLD / WHO PLAYS WHOM / THE CHARACTERS and a
  fail-safe line ("stop there and hand the scene back"). Useful shape for the dummy character (#73).
- **Snippets** are expanded at send time (`:name` followed by a word boundary); emoji shortcodes
  `:name:` likewise (`ShortcodeScanner.ExpandAll`, names up to 32 chars of `[A-Za-z0-9_+-]`).

**Tests:** `tests/LibraryManagementTests.cs`, `tests/PersonaTests.cs`, `tests/WebLibraryTests.cs`
(`A_save_over_an_edit_made_elsewhere_is_refused_and_keeps_both_texts`,
`The_default_persona_counts_as_used_by_every_story_that_names_none`).

---

## Step 5 · The context builder

**Donors:** `src/Airp.Application/Context/ContextBuilder.cs`, `TokenEstimator.cs`, `ModelRouter.cs`,
`src/Airp.Infrastructure/Providers/LocalPrompt.cs` (`Build`), `LCP.ComposeAsync` (873–1012), ADR 0005.

- **Tokens:** tiktoken `o200k_base`; **+4 tokens per message** of framing overhead.
- **Layer order** (system messages, empty layers omitted): character, persona, directives, world,
  summaries, history, memories, trackers, instruction. History roles pass through; **the instruction
  is sent as `user` if the last kept history message is `assistant`, otherwise `system`**.
- **Frames:** persona = "The user is playing the following person. Speak to them as this person, and
  never write their words or actions for them.\n\n" + text; summaries joined with blank lines, no
  header; memories under "Earlier in this conversation:" as `[seq] Name: text` lines; world under
  "What is true in this story right now:" one `Subject: text.` line per subject.
- **Budget:** default 32,000 (Development 8,000). Fixed layers always in; `remaining = max(0, budget −
  fixed)`; history filled newest-first; **the newest message is always kept whatever it costs**;
  stop at the first message that would overflow.
- **Story window:** when the story has its own model, `budget = max(window − reply ceiling, 2048)` if
  smaller than the configured budget; when compression failed, budget = window or unlimited.
- **Recall cap:** `budget × RecallPercent(10, 0–50) / 100`; `RecallCount` 4 (0–20); threshold 0.35.
- **Audit:** `"{layer} {tokens}[ ({n} dropped)] · … · total {est}/{budget}"`, plus "; budget N (the
  story's model)" when shrunk. Stored with `EstimatedPromptTokens`.
- **Naming the reader** in background renders: derived from the persona's name (split on `-`, `_`,
  space; title-case), fallback "User" — here, the persona row's name. Live history is sent as roles.
- **Router:** Summary 0.3 / 1200, Facts 0.2 / 4000 (both on `BackgroundModel ?? default`), Aside
  0.4 / 600, Reply dial-or-1.0 / dial-or-1024.

**Tests:** `tests/ContextBuilderTests.cs` — `Framing_is_counted_even_for_a_turn_with_no_text`,
`The_layers_are_sent_least_volatile_first`, `A_persona_is_framed_as_the_user_rather_than_sent_raw`,
`The_transcript_is_what_gives_when_the_budget_binds`, `The_turns_kept_are_the_ones_nearest_the_reply`,
`A_budget_too_small_for_even_the_fixed_layers_still_sends_the_newest_turn`,
`The_accounting_names_every_layer_that_contributed`, `An_instruction_after_a_reply_arrives_as_the_readers_turn`,
`An_instruction_after_the_readers_own_turn_stays_a_system_note`; `tests/ModelRouterTests.cs`.
`Counting_matches_what_the_provider_reported_for_a_real_transcript` needs a real export (25,368
tokens for 95 turns, 10% tolerance) that is not in the repo.

**Pitfall:** three donor bugs came from a positional argument added mid-list to `Build`. Use keyword
arguments only.

---

## Step 6 · The memory

**Donors:** `ConversationSummariser.cs`, `MemoryRetriever.cs`, `FactExtractor.cs`, `Background.cs`,
`Transcript.cs`, `MemoryRebuild.cs`, `src/Airp.Application/Context/Similarity.cs`, ADR 0002, 0006, 0007.

### Summaries (#28)

- Runs synchronously inside the turn, before the prompt is built. **One summary per turn.**
- **Reserved room** = cost of (character, persona frame, directives, world, existing summaries,
  trackers) + a retrieval estimate (`min(min(RecallCount, n) × mean turn tokens, RecallBudget)`) +
  the reply ceiling + **200**. `allowance = max(0, budget − reserved)`.
- Walk newest → oldest over turns not yet covered, costing `tokens + 4`; what does not fit is the
  overflow. **Batch** = `max(overflow, min(10, uncovered − 6))`, capped at **40**, taken from the
  oldest. Constants: `WorthACall = 10`, `AlwaysWhole = 6`, `AtMostPerSummary = 40`.
- **Credible** only if produced tokens ≥ `max(20, sourceTokens / 60)`; otherwise refused.
- The instruction is "compressing part of a roleplay transcript…" with five bullets, ending "Be
  brief." (`ConversationSummariser.cs:52-66`). Transcript rendered `"{Label}: {text}"` joined by
  blank lines, the reader labelled by their persona.
- **Failure** (refused, empty, exception): all history is sent whole and the budget becomes the
  window or unlimited — **over budget rather than discard**. Success inserts the summary and runs
  the fact extractor on the **same stretch**.

**Pitfalls:** `AlwaysWhole = 6` only limits batch *widening* — `max(overflow, …)` can still take
newer turns. The 40 cap with one summary per turn means a big backlog drops un-compressed turns from
*that* prompt until later turns catch up (they stay stored).

### Retrieval (#29)

- Only turns with sequence ≤ `compressedUpTo` (= first recent turn − 1) are embedded; backfill at
  most **128** per call, oldest first. Query = the last **User** message among the recent turns.
- Recall: cosine ≥ 0.35 over live embedded compressed turns, top `RecallCount`, then fit under the
  recall budget (a match that does not fit is skipped, the walk continues), then re-sorted by
  sequence. Any embedding failure other than cancellation degrades to **no memories** — never a
  failed turn. **Donor bug:** an embedding *timeout* surfaced as a cancellation and failed the turn.
- Vectors stored as float32; here `VECTOR(1536)` with an HNSW index (KICKOFF).

### Facts (#30)

- Extractor: 0.2 / 4000. JSON contract `{"facts":[{"subject","text"}],"retired":["<id>"]}`; the
  subject is never "User", "the user" or "the reader". Existing live facts are listed as
  `"{Id[..8]} | {Subject} | {Text}"` before "New transcript:". Parse the substring from the first
  `{` to the last `}` (tolerates fences and prose).
- New facts: `valid_from` = first sequence of the stretch. Retire: first live fact whose id starts
  with the prefix, **skipping pinned**; `valid_to` = last sequence of the stretch.
- Manual add: pinned, `valid_from` = current sequence. Manual retire: the prefix must match
  **exactly one** live fact, else nothing. (The donor's model-driven retire has no ambiguity check.)
- The live-facts snapshot is re-read after compression so new facts reach *this* turn.

### Background retry (#31)

`Background.WorthAnotherGo`: retry **once** when the status is null, 200, 408, 429 or 5xx; never on
401, 402, 404 or other 4xx. Used only by the summariser and the extractor.

### Rebuild (#69)

Delete summaries and **unpinned** facts (embeddings kept); loop the compose up to **200** passes until
the summary count stops growing; report removed / kept / written / extracted / covered.

**Tests:** `tests/SummaryTests.cs`, `tests/CharacterInAFileTests.cs` (the character-file regression:
a 30k-token card, 202 turns, 24 turns lost — build Lustjinn's equivalent with the dummy character
#73), `tests/RetrievalTests.cs`, `tests/WorldStateTests.cs`, `tests/BackgroundRetryTests.cs`,
`tests/RebuildMemoryTests.cs`.

---

## Step 7 · Story features

### Dials (#56)

**Donors:** `src/Airp.Application/Dials/DialPack.cs`, `DialEngine.cs`, `LegacyDials.cs`,
`src/Airp.Infrastructure/Providers/DialService.cs`, `src/Airp.Infrastructure/Dials/default-dials.json`,
ADR 0015, 0016.

- Taxonomy: `kind` scale (exactly 5 levels) / toggle / choice (≥2 options) / list (`{items}`) /
  text (`{value}`); `lever` prompt / sampler / both; `maps` temperature / max_tokens /
  frequency_penalty; `enabled` (default true; **disabled = pinned to default**, stored value
  survives); `default` (null = inject nothing).
- Effective value = `enabled and stored ? stored : default`. Clearing deletes the row.
- Directives render in pack order: scale `"{Title}: {Label} — {Text}."`, choice `"{Title}: {text}."`,
  one-liners joined by newlines as the first block; toggle text, list and text templates as
  separate blocks; blocks joined by blank lines.
- **Shipped pack:** lust (Cold…Unhinged), response-length (both, 200/450/900/1600/2600), creativity
  (sampler, 0.6/0.8/1.0/1.2/1.4), inner-thoughts (toggle), pacing, initiative, consequence,
  prose-balance, register, npc-liveliness, agency-guard (disabled), veils (list), pov (choice),
  ending (choice), language (text), anti-loop (sampler, frequency_penalty 0/0.2/0.4/0.7/1.0). Texts
  in `default-dials.json`.
- **Pitfall:** the response-length dial also shrinks the story window; the summariser's reserve
  uses the configured ceiling instead. Decide one rule.

**Tests:** `tests/DialTests.cs`, `tests/SettingScaleTests.cs`, `tests/InnerThoughtsSettingTests.cs`,
`tests/FakeDialService.cs` (the real pack with in-memory values).

### Meters (#57)

**Donor:** `Trackers.cs`. Header "These meters belong to this story. End every reply with all of
them, each on its own line, in exactly this shape, and nothing else after them:", format line
`[NAME] {bar} {value}/{max} | Δ {change} | {reason in three words}`, movement rules (one to three
points for an ordinary beat, Δ 0 when nothing earned), one line per meter with optional
`measures:` / `scale:` / `rule:` sub-lines. Bar: 10 steps of `#`/`.`. Parse back with the regex at
`Trackers.cs:36`; only existing meters match; value clamped to `[0, max]`; **delta is computed, not
believed**; note trimmed and capped at 200. **Pitfall:** meter lines are not stripped from the stored
reply, so they reach history, summaries and embeddings. Tests: `tests/TrackerTests.cs`.

### Directions: `/do` (#58), carry on (#59), `/focus` (#60)

**Donors:** `src/Airp.Application/Text/LocalDirections.cs`, `LCP.ContinueAsync` (439–443).

- `/do`: the first blank line splits direction from message. Direction alone → a turn with no reader
  message; with a message → the message is stored, the direction is not. Frame: "A direction for
  this reply, from the reader, out of character. It is not something anyone said aloud and nobody
  in the scene knows it was given. Write the next turn following it, and still never write the
  user's words, actions or thoughts.\n\n" + direction.
- Carry on: the directive "Carry the scene forward yourself. Let time pass and let the world act… This
  reply does not hand the scene back and does not wait…". A direction **replaces** it, never joins it.
  Sent as a `user` message because history ends on `assistant`.
- `/focus who`: "…Give this turn to {who}. Let them carry it — what they do, say and notice — and keep
  everyone else to what they need for that. Still never write the user's words, actions or thoughts."

**Tests:** `tests/ComposerCommandTests.cs`, `tests/AsideTests.cs` (`A_direction_replaces_the_carry_on_wording_rather_than_joining_it`,
`Carrying_on_with_no_direction_still_says_not_to_wait`), `tests/FrontEndTurnTests.cs`.

### Regenerate with a reason (#61)

**Donors:** `LCP.RegenerateAsync` (349–414), `LocalPrompt.RegenerateDirective` (110–145),
`src/Airp.Domain/Conversations/RegenerateReason.cs`. The directive: "Your last reply has been
withdrawn and is no longer part of the scene. Write that turn again from the same point, taking the
note below into account. The note is a direction about how to write, not something anyone said and
not something to answer…" + the reason text (+ "Also, from the reader: …" when typed). Reason texts
for Steer, BadMemory, Looping, ActingForUser, TooShort, TooLong, WrongFormat, Refusing and None are
in `RegenerateDirective`; **no directive may contain "previous reply"**; all nine must differ.
Tests: `tests/RegenerateDirectiveTests.cs`.

### A model per story (#62)

**Donors:** `LCP.SetModelAsync` (2224–2322), `LCP.CompleteForStoryAsync` (2394–2446), ADR 0019.
Catalogue cached 10 minutes; a model not listed is refused ("The story stays on X"); the story's
window = configured > shipped > listed; **refuse a model whose window cannot hold the fixed layers +
reply ceiling + 1000**. **Fallback:** if the estimated prompt exceeds the story model's room, or the
model is unknown (404), the default model writes the turn and the message records `FellBackFrom`.
Memory always runs on the configured/background model. Tests: `tests/StoryModelTests.cs`,
`tests/CharacterInAFileTests.cs` (`A_story_on_a_model_with_a_small_window_*`, `A_model_that_cannot_hold_the_character_*`).

### Branch (#63)

**Donor:** `LCP.BranchAsync` (1484–1706). Copied: story fields incl. model; **live** messages ≤ point
(inclusive) with their sequence numbers and embeddings; summaries with `ToSequence ≤ point`; facts
with `ValidFrom ≤ point`, a fact retired after the point **reopened**; all trackers at current values;
all dial values; asides ≤ point. Not copied: spend, request hashes, hidden messages, `FellBackFrom`.
Name: "X" → "X (2)" → "X (3)". Tests: `tests/BranchTests.cs`.

### Delete from (#64), search (#65), export (#66), cost (#67), facts (#68), purge (#70)

- **Delete from:** tombstone every live message with sequence ≥ the target's. Nothing else is
  touched in the donor (summaries over hidden turns remain) — decide here. Test:
  `Deleting_from_a_message_hides_it_and_everything_after`.
- **Search:** cross-story (`SearchService.cs`): story-name hits score fuzzy + 60; message hits are a
  case-insensitive substring over dialogue, score 40 + min(20, occurrences × 5); snippet radius 48;
  limit 200. In-story (`StoryReports.Search`): substring, excerpt ±60. Tests: `tests/SearchServiceTests.cs`.
- **Export** (`ExportService.cs`): JSON per message (index, role, speaker, time, word count, text),
  Markdown with YAML front matter and `## n. Speaker — date`, plain text with `[001] Speaker · stamp`.
  Tests: `tests/TranscriptExportTests.cs`, `tests/ExportServiceTests.cs`.
- **Cost:** window `[from, to)`; **discarded** = rows whose message is hidden, read at report time;
  unpriced counted; by kind, by story (cost desc, then name), by provider with cached share and
  per-call completion; a purged story reports as "(purged)". Tests: `tests/SpendTests.cs`.
- **Facts:** see step 6 (manual add pinned; manual retire needs exactly one match).
  Tests: `tests/WorldStateTests.cs` (`The_model_cannot_retire_a_fact_a_person_stated`, `An_ambiguous_id_retires_nothing`).
- **Purge** (`LCP.PurgeDeletedAsync` 1256–1330): hard-deletes messages, summaries, facts, trackers,
  asides, dial values and the hidden stories; **keeps spend** and reports rows kept and their sum.
  Tests: `Purging_erases_what_was_deleted_and_leaves_the_rest`, `Purging_keeps_the_ledger_and_says_what_it_kept`.

### `/recap` (#78)

Web-only in the donor (`FrontEndTurn.cs`): the latest summary under "Earlier:" plus the last n
dialogue turns (default 4, clamped 1–20), headed "(Recap, out of character — nothing stored, nothing
billed.)". Free; nothing stored.

---

## Steps 8 and 9 · The clients

What both clients share is in the donor's `FrontEndTurn.cs`: one parser, one outcome type
(`Text, Refused, Stored, Answer, Matches`); "stored" outcomes navigate, non-stored answers are shown
once and kept nowhere. Reply rendering: `ProseFormat` turns `*action*`, `**emphasis**` and
`"dialogue"` into styled runs (`ProseHtml` on the web). Composer helpers: snippets (`:name` + Tab),
emoji shortcodes (`EmojiShortcodes.cs`), word completion (`WordList.cs`), grapheme-aware editing
(`Graphemes.cs`, `TextDocument.cs`).

- **Web** (`src/Airp.Web`, Razor Pages, no JavaScript): routes `/`, `/story/{id}` (last 40 turns,
  `?all=true`), `/story/{id}/dials`, `/new`, `/library/…`; handlers Send, Insert, Continue, Pin,
  Reroll, Branch, Export. Response headers worth keeping on the API and the PWA: CSP, `Cache-Control:
  no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex, nofollow`, `nosniff`.
  Tests: `tests/Web*Tests.cs`.
- **Terminal** (`src/Airp.Terminal`): see the step 9 issues for the per-view donors. Key tests:
  `tests/KeyHandlingTests.cs`, `tests/NarrowLayoutTests.cs`, `tests/PhoneBarTests.cs`,
  `tests/IdentityHeaderTests.cs`, `tests/NewChatFlowTests.cs`, `tests/TranscriptScrollingTests.cs`.

---

## Configuration the donor exposes (for #9 and later)

`Airp:Model:` — `Name`, `BackgroundModel`, `EmbeddingModel`, `Temperature` 1.0 (0–2), `MaxTokens`
1024 (1–32768), `ContextBudget` 32000 (1000–900000), `TimeoutSeconds` 180, `RecallCount` 4,
`RecallThreshold` 0.35, `RecallPercent` 10, `IgnoreProviders`, `PreferProviders`,
`AllowProviderFallbacks`, `Choices`, `Windows`, `Temperatures`, `ThinkBeforeReplying`.
`Airp:` — `DefaultPersona`, `MessageCharacterLimit`, `InstructionCharacterLimit`, and the
terminal's `Theme`, `Keyboard`, `TranscriptWidthPercent`, `MouseSupport`, `ExportDirectory`.
Full list with ranges: `docs/CONFIGURATION.md`, `src/Airp.Application/Options/`.

## How the donor's tests are built

- `ScriptedModel` (`tests/LocalProviderTests.cs`): a queue of scripted replies that records every
  call's messages, model, temperature, reasoning flag, ceiling and penalty; helpers `Says`,
  `SaysUnpriced`, `Fails`, `HasNoSuchModel`, `Summarises` (pads the gist so it passes the
  credibility floor), `Truncated`, `Empty`, `Rejected`. → Here: a respx-faked OpenRouter with the
  same vocabulary.
- One in-memory database with the **real migrations** applied. → Here: a throwaway Postgres
  database per test session, migrated by Alembic (#74).
- Seeded conversations: N turns alternating User/Assistant, `"Turn {i}. " + 60 filler words`.
- The realistic character: `"You are Elena. " + 3000 × "detail"` in a file, budget 6000, ceiling 200
  — the guard for the bug KICKOFF names. Other suites put a tiny card inline, which real stories
  never do. **Port the file-backed pattern, with #73's character.**
- `KeywordEmbedder` (`tests/RetrievalTests.cs`): 4-axis vectors over four keywords, with a `Broken`
  flag — a cheap, deterministic embedder for retrieval tests.

## Set aside on purpose

- Import of airp's library and stories (#22, #71 — the owner curates by hand and starts fresh).
- The donor's Tailscale gate (ADR 0018) — replaced by sign-in with a bearer token (#10).
- The Tailscale-only web process, DPAPI secrets (ADR 0013) — Render environment variables and `.env`.
- The retired proxy (ADR 0014, 0017, 0020) and the local Ollama option (ADR 0001).
- `SupersededById` on facts — never set in the donor; not ported.
