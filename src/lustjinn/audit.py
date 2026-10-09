"""`GET /stories/{id}/audit`: what the recent replies and questions were built from and what each
cost, the builder's estimate beside the provider's figure. Moved out of turns.py (#133).

Hidden replies — rerolled away — are listed and marked: "why did it say that" is asked of them
most of all. The reader's own turns are not listed; nothing was built to write them.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from lustjinn.deps import Session
from lustjinn.models import Aside, Message, Role
from lustjinn.stories import visible_story

# What /audit shows: the recent past, not the whole story. The donor's figures.
AUDIT_TURNS = 12
AUDIT_ASIDES = 8


class TurnAudit(BaseModel):
    """What one reply was built from and what it cost — rerolled ones included, marked hidden."""

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


router = APIRouter(prefix="/stories", tags=["audit"])


@router.get("/{story_id}/audit")
async def audit(story_id: uuid.UUID, session: Session) -> Audit:
    """What the recent replies were built from, each estimate beside the provider's figure."""
    await visible_story(session, story_id)
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
