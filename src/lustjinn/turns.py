"""A turn: the reader's message is kept first, then the reply streams back and is kept too.

The response is a stream of server-sent events: `delta` events carry the reply as it is
written, and one last event says how it ended — `done` with what was stored, or `error` with
why not. The reader's message is committed before the model is asked, so a failed call never
loses what was written, and a retry of the same words finds it instead of storing it twice.
"""

import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from lustjinn import (
    commands,
    context,
    dials,
    directions,
    ledger,
    memory,
    recap,
    regenerate,
    snippets,
    story_model,
    trackers,
)
from lustjinn.db import get_session
from lustjinn.library import default_persona
from lustjinn.models import Aside, Message, Persona, Role, Snippet, SpendKind, Story
from lustjinn.openrouter import ModelError, OpenRouter, Reply, get_openrouter, temperature_for
from lustjinn.settings import Settings, get_settings
from lustjinn.sse import format_event
from lustjinn.stories import MessageOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/stories", tags=["turns"])

# scope="request": the session stays open until the response has been sent. The default would
# close it when the endpoint function returns — before the stream below has run.
Session = Annotated[AsyncSession, Depends(get_session, scope="request")]
Model = Annotated[OpenRouter, Depends(get_openrouter)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]

# How the stream is described on /docs: FastAPI cannot read it off a StreamingResponse.
STREAMED: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {
        "content": {"text/event-stream": {}},
        "description": "Server-sent events: `delta` while the reply is written, then `done` or "
        "`error`.",
    }
}


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


class Failed(BaseModel):
    """The last event when the model did not answer."""

    kind: Literal["error"] = "error"
    detail: str
    sent: MessageOut | None
    """The reader's message, which was kept. Do not send it again."""


class AsideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    question: str
    answer: str
    model: str | None
    provider: str | None
    asked_at: datetime


class TurnAudit(BaseModel):
    """What one reply was built from and what it cost — rerolled ones included, marked hidden."""

    model_config = ConfigDict(from_attributes=True)

    sequence: int
    sent_at: datetime
    hidden: bool
    model: str | None
    provider: str | None
    estimated_prompt_tokens: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    context: str | None
    """The layers and their tokens, as `context.Built.describe()` wrote them."""


class AsideAudit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    asked_at: datetime
    model: str | None
    provider: str | None
    estimated_prompt_tokens: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    context: str | None


class Audit(BaseModel):
    turns: list[TurnAudit]
    """The newest replies first, up to AUDIT_TURNS."""
    asides: list[AsideAudit]
    """The newest questions first, up to AUDIT_ASIDES. Billed, and they leave no message behind,
    so leaving them out is how a story's cost quietly stops adding up."""


# What /audit shows: the recent past, not the whole story. The donor's figures.
AUDIT_TURNS = 12
AUDIT_ASIDES = 8


class AsideDone(BaseModel):
    """The last event of a question that was answered. Nothing of it is in the story."""

    kind: Literal["aside"] = "aside"
    aside: AsideOut


class Said(BaseModel):
    """The last — and only — event of a command that answers in words and stores no turn:
    shown once, kept nowhere."""

    kind: Literal["said"] = "said"
    text: str


# Sampling for a question: cold, because an answer can be promoted to a pinned fact (step 7),
# so an embellishment would become something the character believes. Short: it is an answer.
ASIDE_TEMPERATURE = 0.4
ASIDE_MAX_TOKENS = 600


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


async def _playable(session: AsyncSession, story_id: uuid.UUID) -> Story:
    """A visible story with its character and persona loaded: what a prompt is built from."""
    story = await session.scalar(
        select(Story)
        .options(joinedload(Story.character), joinedload(Story.persona))
        .where(Story.id == story_id, Story.deleted_at.is_(None))
    )
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no story with that id.")
    return story


async def _expanded(session: AsyncSession, text: str) -> str:
    """The text with its `:name` triggers replaced by the snippets of those names."""
    if ":" not in text:
        return text
    rows = await session.execute(select(Snippet.name, Snippet.text))
    return snippets.expand(text, snippets.by_name({name: body for name, body in rows}))


async def _persona(session: AsyncSession, story: Story) -> Persona | None:
    """The story's own persona, or the default for a story that names none, or nobody."""
    return story.persona if story.persona is not None else await default_persona(session)


async def _dialled(session: AsyncSession, story: Story) -> tuple[str | None, dials.Sampler]:
    """The story's dials: rendered for the directives layer, and resolved for the sampler."""
    pack = dials.shipped()
    values = await dials.values_of(session, story.id)
    return dials.directives(pack, values), dials.sampler(pack, values)


async def _visible(session: AsyncSession, story_id: uuid.UUID) -> list[Message]:
    rows = await session.scalars(
        select(Message)
        .where(Message.story_id == story_id, Message.deleted_at.is_(None))
        .order_by(Message.sequence)
    )
    return list(rows)


async def _next_sequence(session: AsyncSession, story_id: uuid.UUID) -> int:
    """One past the highest ever used, hidden rows included: a number is never reused."""
    highest = await session.scalar(
        select(func.max(Message.sequence)).where(Message.story_id == story_id)
    )
    return (highest or 0) + 1


def _choice(story: Story, settings: Settings, temperature: float) -> tuple[str, float]:
    """The model a story plays on, and the temperature mapped onto its range when it has one."""
    if story.model is None:
        return settings.model, temperature
    return story.model, temperature_for(story.model, temperature)


def _reasoning(settings: Settings) -> bool | None:
    """Off unless the settings say otherwise; None sends nothing and leaves it to the model."""
    return None if settings.think_before_replying else False


def _out(message: Message) -> MessageOut:
    return MessageOut.model_validate(message)


def _event(name: str, payload: BaseModel) -> str:
    return format_event(name, payload.model_dump(mode="json"))


async def _started(events: AsyncIterator[str]) -> AsyncIterator[str]:
    """Runs a stream up to its first event, so what it refuses is refused with a status code
    before the response has begun, and what it says is still said as a stream."""
    first = await anext(events)

    async def rest() -> AsyncIterator[str]:
        yield first
        async for event in events:
            yield event

    return rest()


def _streamed(events: AsyncIterator[str]) -> StreamingResponse:
    # X-Accel-Buffering: a proxy in front (Render's, nginx) must pass each event on as it comes.
    return StreamingResponse(
        events, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


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
    # The budget fits the story's model, if it has one with a smaller window. Then the dials:
    # their text is a layer of the prompt, and their ceiling is room the memory must reserve.
    # Then the memory — a summary if the story no longer fits — then the prompt is built.
    settings = story_model.fitted(settings, story)
    directives, knobs = await _dialled(session, story)
    ceiling = knobs.max_tokens or settings.max_tokens
    meters = await trackers.of(session, story.id)
    built = await memory.compose(
        session,
        openrouter,
        settings,
        story,
        await _persona(session, story),
        await _visible(session, story.id),
        directives=directives,
        trackers=trackers.render(meters),
        instruction=instruction,
        reply_tokens=ceiling,
    )
    asked = settings.temperature if knobs.temperature is None else knobs.temperature
    model, temperature = _choice(story, settings, asked)
    fell_back_from: str | None = None
    # A story's model with a smaller window than this prompt cannot take the turn: handed more
    # than it was trained for, it answers in token soup. The default writes it instead, before
    # anything is sent, and the reply says so.
    if (
        story.model is not None
        and story.model_context is not None
        and built.estimated_tokens > story.model_context - ceiling
    ):
        log.warning(
            "%s cannot read this prompt (%d tokens against %d); the default wrote the turn.",
            story.model,
            built.estimated_tokens,
            story.model_context - ceiling,
        )
        fell_back_from, model, temperature = story.model, settings.model, asked
    written: Reply | None = None

    async def relay(model: str, temperature: float) -> AsyncIterator[str]:
        nonlocal written
        async for piece in openrouter.stream(
            built.messages,
            model=model,
            temperature=temperature,
            max_tokens=ceiling,
            frequency_penalty=knobs.frequency_penalty,
            reasoning=_reasoning(settings),
        ):
            if isinstance(piece, Reply):
                written = piece
            else:
                yield format_event("delta", {"text": piece})

    try:
        try:
            async for event in relay(model, temperature):
                yield event
        except ModelError as error:
            # A model with no host today — and only that — hands the turn to the default; the
            # story keeps its model and tries it again next turn. Anything else is reported,
            # not retried: a rejected key or an empty account would refuse the default too.
            if fell_back_from is not None or model == settings.model or not error.no_such_model:
                raise
            log.warning("%s is not available (%s); the default wrote the turn.", model, error)
            fell_back_from, model, temperature = model, settings.model, asked
            async for event in relay(model, temperature):
                yield event
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
        yield _event("error", Failed(detail=detail, sent=None if sent is None else _out(sent)))
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
        fell_back_from=fell_back_from,
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
    yield _event("done", TurnDone(sent=None if sent is None else _out(sent), reply=_out(stored)))


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
            yield _event("done", TurnDone(sent=_out(existing), reply=_out(answered), replayed=True))
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


async def ask(
    session: AsyncSession, openrouter: OpenRouter, settings: Settings, story: Story, question: str
) -> AsyncIterator[str]:
    """Answers a question about the story, out of character, and keeps the answer apart.

    The prompt is the one the next turn would send, up to the instruction — so the answer is
    grounded in exactly what the character can see, and on a caching host it is nearly free.
    Nothing goes into `messages`: an asking is not a turn.
    """
    settings = story_model.fitted(settings, story)
    history = await _visible(session, story.id)
    # The same compose as a turn — the dials' text and the room their ceiling takes included —
    # so the answer is grounded in exactly what the character can see, and so a question can
    # trigger the same summary a turn would have. The question's own sampling stays cold and
    # short whatever the dials say: it is an answer, not a reply.
    directives, knobs = await _dialled(session, story)
    built = await memory.compose(
        session,
        openrouter,
        settings,
        story,
        await _persona(session, story),
        history,
        directives=directives,
        trackers=trackers.render(await trackers.of(session, story.id)),
        instruction=context.ask_directive(question),
        reply_tokens=knobs.max_tokens or settings.max_tokens,
    )
    model, temperature = _choice(story, settings, ASIDE_TEMPERATURE)
    answered: Reply | None = None
    try:
        async for piece in openrouter.stream(
            built.messages,
            model=model,
            temperature=temperature,
            max_tokens=ASIDE_MAX_TOKENS,
            reasoning=_reasoning(settings),
        ):
            if isinstance(piece, Reply):
                answered = piece
            else:
                yield format_event("delta", {"text": piece})
    except ModelError as error:
        # Unlike a send, nothing was stored: this is simply a call that did not happen.
        yield _event("error", Failed(detail=f"The question was not answered: {error}", sent=None))
        return
    if answered is None:
        raise RuntimeError("The stream ended without a reply.")

    aside = Aside(
        story_id=story.id,
        sequence=history[-1].sequence if history else 0,
        question=question,
        answer=answered.text.strip(),
        model=answered.model,
        provider=answered.provider,
        prompt_tokens=answered.prompt_tokens,
        completion_tokens=answered.completion_tokens,
        estimated_prompt_tokens=built.estimated_tokens,
        context_audit=built.describe(),
    )
    session.add(aside)
    session.add(ledger.row(story.id, SpendKind.ASIDE, answered))
    await session.commit()
    yield _event("done", AsideDone(aside=AsideOut.model_validate(aside)))


async def recap_of(session: AsyncSession, story: Story, argument: str) -> AsyncIterator[str]:
    """`/recap [turns]`: the latest summary and the last turns. Nothing stored, nothing billed."""
    try:
        count = recap.count_from(argument)
    except ValueError as why:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{why} — nothing was stored."
        ) from None
    summaries = await memory.summaries_of(session, story.id)
    latest = summaries[-1].text if summaries else None
    turns = await _visible(session, story.id)
    yield _event("done", Said(text=recap.format_recap(story.character.name, latest, turns, count)))


async def set_tracker(session: AsyncSession, story: Story, argument: str) -> AsyncIterator[str]:
    """`/tracker <name> <value>`: moves a meter by hand and says so. No model call."""
    split = trackers.split_command(argument)
    if split is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "/tracker <name> <value> — the value has to be a number, so nothing was stored.",
        )
    name, value = split
    tracker = await trackers.named(session, story.id, name)
    if tracker is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"This story has no meter called {name}, so nothing was stored.",
        )
    await trackers.set_value(session, tracker, value)
    await session.commit()
    yield _event("done", Said(text=f"{tracker.name} is now {trackers.shown(value)}."))


@router.post("/{story_id}/send", responses=STREAMED)
async def send(
    story_id: uuid.UUID,
    body: Send,
    session: Session,
    openrouter: Model,
    settings: CurrentSettings,
) -> StreamingResponse:
    """Sends what the reader typed: a message, or a slash command.

    A message becomes a turn and streams the reply back. `/ask <question>` streams an answer
    out of character and stores nothing in the story. Anything else that starts with a slash is
    refused before anything is stored or sent; `//` sends a line that begins with one.
    """
    story = await _playable(session, story_id)
    # Snippets expand first, before the line is read for commands, so a trigger works inside
    # a question too; and before the hash, so a retry of `:storm` is still one turn.
    match commands.parse(await _expanded(session, body.text)):
        case commands.Prose(text):
            return _streamed(turn(session, openrouter, settings, story, text))
        case commands.Command(spec=commands.Spec(name="do"), argument=argument):
            steer, message = directions.split(argument)
            framed = directions.direction(steer)
            if not message:
                # The direction alone: a turn with nothing from the reader, written under it.
                return _streamed(
                    reply(session, openrouter, settings, story, sent=None, instruction=framed)
                )
            # The message is stored; the direction steers the reply and is stored nowhere.
            return _streamed(turn(session, openrouter, settings, story, message, framed))
        case commands.Command(spec=commands.Spec(name="focus"), argument=who):
            framed = directions.focus(who)
            return _streamed(
                reply(session, openrouter, settings, story, sent=None, instruction=framed)
            )
        case commands.Command(spec=commands.Spec(name="ask"), argument=question):
            return _streamed(ask(session, openrouter, settings, story, question))
        case commands.Command(spec=commands.Spec(name="recap"), argument=argument):
            return _streamed(await _started(recap_of(session, story, argument)))
        case commands.Command(spec=commands.Spec(name="tracker"), argument=argument):
            # Checked before the stream opens, so a refusal is a 4xx and not a stream of one.
            return _streamed(await _started(set_tracker(session, story, argument)))
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


@router.post("/{story_id}/continue", responses=STREAMED)
async def carry_on(
    story_id: uuid.UUID, session: Session, openrouter: Model, settings: CurrentSettings
) -> StreamingResponse:
    """The model writes the next beat with nothing from the reader. Billed and stored as a
    reply like any other, so it can be rerolled like any other."""
    story = await _playable(session, story_id)
    return _streamed(
        reply(session, openrouter, settings, story, sent=None, instruction=directions.CARRY_ON)
    )


@router.get("/{story_id}/audit")
async def audit(story_id: uuid.UUID, session: Session) -> Audit:
    """What the recent replies were built from, each estimate beside the provider's figure.

    Hidden replies — rerolled away — are listed and marked: "why did it say that" is asked of
    them most of all. The reader's own turns are not listed; nothing was built to write them.
    """
    await _playable(session, story_id)
    replies = await session.scalars(
        select(Message)
        .where(Message.story_id == story_id, Message.role == Role.ASSISTANT)
        .order_by(Message.sequence.desc())
        .limit(AUDIT_TURNS)
    )
    asides = await session.scalars(
        select(Aside)
        .where(Aside.story_id == story_id)
        .order_by(Aside.asked_at.desc(), Aside.sequence.desc())
        .limit(AUDIT_ASIDES)
    )
    return Audit(
        turns=[
            TurnAudit(
                sequence=m.sequence,
                sent_at=m.sent_at,
                hidden=m.deleted_at is not None,
                model=m.model,
                provider=m.provider,
                estimated_prompt_tokens=m.estimated_prompt_tokens,
                prompt_tokens=m.prompt_tokens,
                completion_tokens=m.completion_tokens,
                context=m.context_audit,
            )
            for m in replies
        ],
        asides=[
            AsideAudit(
                sequence=a.sequence,
                asked_at=a.asked_at,
                model=a.model,
                provider=a.provider,
                estimated_prompt_tokens=a.estimated_prompt_tokens,
                prompt_tokens=a.prompt_tokens,
                completion_tokens=a.completion_tokens,
                context=a.context_audit,
            )
            for a in asides
        ],
    )


@router.get("/{story_id}/asides")
async def list_asides(story_id: uuid.UUID, session: Session) -> list[AsideOut]:
    """The questions asked about a story, newest first."""
    await _playable(session, story_id)
    rows = await session.scalars(
        select(Aside)
        .where(Aside.story_id == story_id)
        .order_by(Aside.asked_at.desc(), Aside.id.desc())
    )
    return [AsideOut.model_validate(row) for row in rows]


@router.post("/{story_id}/reroll", responses=STREAMED)
async def reroll(
    story_id: uuid.UUID,
    session: Session,
    openrouter: Model,
    settings: CurrentSettings,
    body: Reroll | None = None,
) -> StreamingResponse:
    """Writes the newest reply again, with a reason. The old one is hidden, and kept for the
    record; the reason becomes the prompt's last layer, which is the only thing that makes the
    second attempt differ from the first."""
    story = await _playable(session, story_id)
    visible = await _visible(session, story.id)
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
    return _streamed(
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
