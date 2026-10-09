"""A turn: the reader's message is kept first, then the reply streams back and is kept too.

The response is a stream of server-sent events: `delta` events carry the reply as it is
written, and one last event says how it ended — `done` with what was stored, or `error` with
why not. The reader's message is committed before the model is asked, so a failed call never
loses what was written, and a retry of the same words finds it instead of storing it twice.

This module is the turn pipeline — send, carry on, reroll — and `/send`'s dispatch. The commands
that answer without a turn live with their nouns (#133): `/ask` in `asides`, `/recap` in
`recap`, `/fact` in `facts`, `/tracker` in `trackers`; the audit in `audit`.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import (
    asides,
    commands,
    dials,
    directions,
    facts,
    ledger,
    memory,
    recap,
    regenerate,
    snippets,
    streams,
    trackers,
)
from lustjinn.deps import CurrentSettings, Model, StreamingSession
from lustjinn.library import persona_of
from lustjinn.models import Message, Role, Snippet, SpendKind, Story
from lustjinn.openrouter import ModelError, OpenRouter, Reply, reasoning
from lustjinn.settings import Settings
from lustjinn.stories import MessageOut, playable_story, visible_messages

router = APIRouter(prefix="/stories", tags=["turns"])


class Send(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Reroll(BaseModel):
    """Why the reply is being asked for again. Optional, and so is the body: a bare reroll asks
    for the turn afresh."""

    reason: regenerate.Reason = regenerate.Reason.NONE
    instructions: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None
    ) = None
    """The reader's own guidance, framed as a direction — never read as the latest message."""


class TurnDone(BaseModel):
    """The last event of a turn that was answered."""

    kind: Literal["turn"] = "turn"
    sent: MessageOut | None
    """The reader's message; None for a reply written without one (a reroll)."""
    reply: MessageOut
    replayed: bool = False
    """True when this exact request had already been answered: the stored reply is returned and
    the model is not called again."""


def request_hash(
    story_id: uuid.UUID, anchor: int, text: str, instruction: str | None = None
) -> str:
    """What identifies a request, so a retry is harmless.

    Anchored on the last reply — the state the message answers — and not on the next free
    position: after a send fails at the model the reader's turn is already stored, and the next
    position would hash differently on the retry. The same words typed again after a reply has
    landed anchor differently, and are a genuinely new send.

    A direction (step 7) is part of what is asked for, so it is part of the identity. The
    separator is a control character: a pipe or a space can appear in prose.
    """
    directed = (
        text if not instruction or not instruction.strip() else f"{text}\x1f{instruction.strip()}"
    )
    digest = hashlib.sha256(f"{story_id}|{anchor}|{directed}".encode()).hexdigest()
    return digest[:32].upper()


async def _expanded(session: AsyncSession, text: str) -> str:
    """The text with its `:name` triggers replaced by the snippets of those names."""
    if ":" not in text:
        return text
    rows = await session.execute(select(Snippet.name, Snippet.text))
    return snippets.expand(text, snippets.by_name({name: body for name, body in rows}))


async def _next_sequence(session: AsyncSession, story_id: uuid.UUID) -> int:
    """One past the highest ever used, hidden rows included: a number is never reused."""
    highest = await session.scalar(
        select(func.max(Message.sequence)).where(Message.story_id == story_id)
    )
    return (highest or 0) + 1


def _out(message: Message) -> MessageOut:
    return MessageOut.model_validate(message)


async def reply(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    *,
    sent: Message | None,
    restore: Message | None = None,
    instruction: str | None = None,
) -> AsyncIterator[str]:
    """Asks the model for the next reply and streams it; stores it with its ledger row.

    `sent` is the reader's message the reply answers, already committed. `restore` is a reply
    hidden for this call (a reroll), to be shown again if nothing arrives to replace it.
    `instruction` is this turn's direction, if the reader gave one: the last layer of the
    prompt, and never a message.
    """
    # The dials first: their text is a layer of the prompt, and their ceiling is room the memory
    # must reserve. Then the memory — a summary if the story no longer fits — then the prompt.
    directives, knobs = await dials.of_story(session, story.id)
    ceiling = knobs.max_tokens or settings.max_tokens
    meters = await trackers.of(session, story.id)
    built = await memory.compose(
        session,
        openrouter,
        settings,
        story,
        await persona_of(session, story),
        await visible_messages(session, story.id),
        directives=directives,
        trackers=trackers.render(meters),
        instruction=instruction,
        reply_tokens=ceiling,
    )
    written: Reply | None = None
    try:
        async for piece in openrouter.stream(
            built.messages,
            model=settings.model,
            temperature=settings.temperature if knobs.temperature is None else knobs.temperature,
            max_tokens=ceiling,
            frequency_penalty=knobs.frequency_penalty,
            reasoning=reasoning(settings),
        ):
            if isinstance(piece, Reply):
                written = piece
            else:
                yield streams.delta(piece)
    except ModelError as error:
        if restore is not None:
            restore.deleted_at = None
            await session.commit()
        # The send is not undone: it is stored, it is the reader's, and telling them it failed
        # outright is how the same message gets typed a second time.
        detail = (
            f"Your message was kept, but the model did not answer: {error} Do not send it again."
            if sent is not None
            else f"The model did not answer: {error}"
        )
        yield streams.event(
            "error", streams.Failed(detail=detail, sent=None if sent is None else _out(sent))
        )
        return
    if written is None:  # the client always ends its stream with a Reply
        raise RuntimeError("The stream ended without a reply.")

    stored = Message(
        story_id=story.id,
        sequence=await _next_sequence(session, story.id),
        role=Role.ASSISTANT,
        text=written.text.strip(),
        model=written.model,
        provider=written.provider,
        prompt_tokens=written.prompt_tokens,
        completion_tokens=written.completion_tokens,
        # The estimate beside the figure the provider reported: the one way to know whether the
        # budget is measuring what it thinks it is.
        estimated_prompt_tokens=built.estimated_tokens,
        context_audit=built.describe(),
    )
    session.add(stored)
    await session.flush()  # gives it its id, for the ledger row
    # The meters the model drew at the end of the reply, read back into the table. The lines
    # stay in the stored text, as the donor left them: they reach history, summaries and
    # embeddings, and stripping them would be a change to a reply the model wrote.
    trackers.absorb(meters, stored.text, stored.sequence)
    # Written whatever becomes of the reply: a reroll a second from now hides the message and
    # leaves this row where it is, which is the only way the total agrees with the invoice.
    session.add(ledger.row(story.id, SpendKind.REPLY, written, message_id=stored.id))
    await session.commit()
    yield streams.event(
        "done", TurnDone(sent=None if sent is None else _out(sent), reply=_out(stored))
    )


async def turn(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    text: str,
    instruction: str | None = None,
) -> AsyncIterator[str]:
    """Keeps the reader's message — or finds it already kept — and asks for the reply.

    `instruction` is a direction sent with the message: part of what is asked for, so part of
    the request's identity, and the prompt's last layer — never a message of its own.
    """
    anchor = await session.scalar(
        select(func.max(Message.sequence)).where(
            Message.story_id == story.id,
            Message.role == Role.ASSISTANT,
            Message.deleted_at.is_(None),
        )
    )
    digest = request_hash(story.id, anchor or 0, text, instruction)
    existing = await session.scalar(
        select(Message).where(Message.story_id == story.id, Message.request_hash == digest)
    )

    # A match the reader has since deleted is not a retry of anything: sending the same words
    # again after deleting them is how a turn is taken back and asked for again. The tombstone
    # keeps its text; only the hash goes, since idempotency is all it was for.
    if existing is not None and existing.deleted_at is not None:
        existing.request_hash = None
        await session.commit()
        existing = None

    if existing is not None:
        answered = await session.scalar(
            select(Message)
            .where(
                Message.story_id == story.id,
                Message.sequence > existing.sequence,
                Message.role == Role.ASSISTANT,
                Message.deleted_at.is_(None),
            )
            .order_by(Message.sequence)
            .limit(1)
        )
        if answered is not None:
            # Already sent and already answered. Asking again would charge for a second reply
            # and leave the transcript saying the reader typed twice.
            yield streams.event(
                "done", TurnDone(sent=_out(existing), reply=_out(answered), replayed=True)
            )
            return
        # Stored, never answered: the previous attempt died at the model. Ask again against
        # the message that is already there.
        sent = existing
    else:
        sent = Message(
            story_id=story.id,
            sequence=await _next_sequence(session, story.id),
            role=Role.USER,
            text=text,
            request_hash=digest,
        )
        session.add(sent)
        await session.commit()  # before the model is called: a failed call loses nothing

    async for event in reply(
        session, openrouter, settings, story, sent=sent, instruction=instruction
    ):
        yield event


@router.post("/{story_id}/send", responses=streams.STREAMED)
async def send(
    story_id: uuid.UUID,
    body: Send,
    session: StreamingSession,
    openrouter: Model,
    settings: CurrentSettings,
) -> StreamingResponse:
    """Sends what the reader typed: a message, or a slash command.

    A message becomes a turn and streams the reply back. `/ask <question>` streams an answer
    out of character and stores nothing in the story. Anything else that starts with a slash is
    refused before anything is stored or sent; `//` sends a line that begins with one.
    """
    story = await playable_story(session, story_id)
    # Snippets expand first, before the line is read for commands, so a trigger works inside
    # a question too; and before the hash, so a retry of `:storm` is still one turn.
    match commands.parse(await _expanded(session, body.text)):
        case commands.Prose(text):
            return streams.streamed(turn(session, openrouter, settings, story, text))
        case commands.Command(spec=commands.Spec(name="do"), argument=argument):
            steer, message = directions.split(argument)
            framed = directions.direction(steer)
            if not message:
                # The direction alone: a turn with nothing from the reader, written under it.
                return streams.streamed(
                    reply(session, openrouter, settings, story, sent=None, instruction=framed)
                )
            # The message is stored; the direction steers the reply and is stored nowhere.
            return streams.streamed(turn(session, openrouter, settings, story, message, framed))
        case commands.Command(spec=commands.Spec(name="focus"), argument=who):
            framed = directions.focus(who)
            return streams.streamed(
                reply(session, openrouter, settings, story, sent=None, instruction=framed)
            )
        case commands.Command(spec=commands.Spec(name="ask"), argument=question):
            return streams.streamed(asides.ask(session, openrouter, settings, story, question))
        case commands.Command(spec=commands.Spec(name="recap"), argument=argument):
            return streams.streamed(await streams.started(recap.recap_of(session, story, argument)))
        case commands.Command(spec=commands.Spec(name="fact"), argument=statement):
            return streams.streamed(facts.pin_fact(session, story, statement))
        case commands.Command(spec=commands.Spec(name="tracker"), argument=argument):
            # Checked before the stream opens, so a refusal is a 4xx and not a stream of one.
            return streams.streamed(
                await streams.started(trackers.set_tracker(session, story, argument))
            )
        case commands.Command(spec=spec):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{spec.usage} is not available yet."
            )
        case commands.Incomplete(spec=spec):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Usage: {spec.usage} — nothing was stored.",
            )
        case commands.Unknown(name=name):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"/{name} is not a command, so nothing was sent and nothing was stored. To send "
                "a line that begins with a slash, begin it with two.",
            )


@router.post("/{story_id}/continue", responses=streams.STREAMED)
async def carry_on(
    story_id: uuid.UUID, session: StreamingSession, openrouter: Model, settings: CurrentSettings
) -> StreamingResponse:
    """The model writes the next beat with nothing from the reader. Billed and stored as a
    reply like any other, so it can be rerolled like any other."""
    story = await playable_story(session, story_id)
    return streams.streamed(
        reply(session, openrouter, settings, story, sent=None, instruction=directions.CARRY_ON)
    )


@router.post("/{story_id}/reroll", responses=streams.STREAMED)
async def reroll(
    story_id: uuid.UUID,
    session: StreamingSession,
    openrouter: Model,
    settings: CurrentSettings,
    body: Reroll | None = None,
) -> StreamingResponse:
    """Writes the newest reply again, with a reason. The old one is hidden, and kept for the
    record; the reason becomes the prompt's last layer, which is the only thing that makes the
    second attempt differ from the first."""
    story = await playable_story(session, story_id)
    visible = await visible_messages(session, story.id)
    last = visible[-1] if visible else None
    if last is None or last.role is not Role.ASSISTANT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "There is no reply to write again: a reroll applies to the newest reply. "
            "Send a message first.",
        )
    # The opening is a page a person wrote, and it sits at the top of the story for the rest
    # of its life; a reroll there would trade it for a guess. Told apart by two things, since
    # either alone is wrong: no model wrote it, and the reader has not taken a turn yet.
    if last.model is None and not any(m.role is Role.USER for m in visible):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The opening is not rerolled: a person wrote it. Write your first turn; the reply "
            "to it can be rerolled.",
        )
    # Hidden before the call, or the prompt would end on the very reply being rewritten and
    # invite the model to write it again. Hidden, not removed: it is still something the model
    # wrote, and the ledger row for it stays.
    last.deleted_at = datetime.now(UTC)
    await session.commit()
    asked = body or Reroll()
    return streams.streamed(
        reply(
            session,
            openrouter,
            settings,
            story,
            sent=None,
            restore=last,
            instruction=regenerate.directive(asked.reason, asked.instructions),
        )
    )
