"""A turn: the reader's message is kept first, then the reply streams back and is kept too.

The response is a stream of server-sent events: `delta` events carry the reply as it is
written, and one last event says how it ended — `done` with what was stored, or `error` with
why not. The reader's message is committed before the model is asked, so a failed call never
loses what was written, and a retry of the same words finds it instead of storing it twice.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from lustjinn import ledger, prompt
from lustjinn.db import get_session
from lustjinn.models import Message, Role, SpendKind, Story
from lustjinn.openrouter import ModelError, OpenRouter, Reply, get_openrouter, temperature_for
from lustjinn.settings import Settings, get_settings
from lustjinn.sse import format_event
from lustjinn.stories import MessageOut

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


def _choice(story: Story, settings: Settings) -> tuple[str, float]:
    """The model a story plays on, and the temperature mapped onto its range when it has one."""
    if story.model is None:
        return settings.model, settings.temperature
    return story.model, temperature_for(story.model, settings.temperature)


def _reasoning(settings: Settings) -> bool | None:
    """Off unless the settings say otherwise; None sends nothing and leaves it to the model."""
    return None if settings.think_before_replying else False


def _out(message: Message) -> MessageOut:
    return MessageOut.model_validate(message)


def _event(name: str, payload: BaseModel) -> str:
    return format_event(name, payload.model_dump(mode="json"))


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
) -> AsyncIterator[str]:
    """Asks the model for the next reply and streams it; stores it with its ledger row.

    `sent` is the reader's message the reply answers, already committed. `restore` is a reply
    hidden for this call (a reroll), to be shown again if nothing arrives to replace it.
    """
    messages = prompt.build(story.character, story.persona, await _visible(session, story.id))
    model, temperature = _choice(story, settings)
    written: Reply | None = None
    try:
        async for piece in openrouter.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=settings.max_tokens,
            reasoning=_reasoning(settings),
        ):
            if isinstance(piece, Reply):
                written = piece
            else:
                yield format_event("delta", {"text": piece})
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
        prompt_tokens=written.prompt_tokens,
        completion_tokens=written.completion_tokens,
    )
    session.add(stored)
    await session.flush()  # gives it its id, for the ledger row
    # Written whatever becomes of the reply: a reroll a second from now hides the message and
    # leaves this row where it is, which is the only way the total agrees with the invoice.
    session.add(ledger.row(story.id, SpendKind.REPLY, written, message_id=stored.id))
    await session.commit()
    yield _event("done", TurnDone(sent=None if sent is None else _out(sent), reply=_out(stored)))


async def turn(
    session: AsyncSession, openrouter: OpenRouter, settings: Settings, story: Story, text: str
) -> AsyncIterator[str]:
    """Keeps the reader's message — or finds it already kept — and asks for the reply."""
    anchor = await session.scalar(
        select(func.max(Message.sequence)).where(
            Message.story_id == story.id,
            Message.role == Role.ASSISTANT,
            Message.deleted_at.is_(None),
        )
    )
    digest = request_hash(story.id, anchor or 0, text)
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

    async for event in reply(session, openrouter, settings, story, sent=sent):
        yield event


@router.post("/{story_id}/send", responses=STREAMED)
async def send(
    story_id: uuid.UUID,
    body: Send,
    session: Session,
    openrouter: Model,
    settings: CurrentSettings,
) -> StreamingResponse:
    """Sends the reader's message and streams the reply back."""
    story = await _playable(session, story_id)
    return _streamed(turn(session, openrouter, settings, story, body.text))


@router.post("/{story_id}/reroll", responses=STREAMED)
async def reroll(
    story_id: uuid.UUID, session: Session, openrouter: Model, settings: CurrentSettings
) -> StreamingResponse:
    """Writes the newest reply again. The old one is hidden, and kept for the record."""
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
    return _streamed(reply(session, openrouter, settings, story, sent=None, restore=last))
