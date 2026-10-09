"""`/ask`: a question about the story, answered out of character and kept apart from it.

The prompt is the one the next turn would send, up to the instruction — so the answer is
grounded in exactly what the character can see, and on a caching host it is nearly free.
Nothing goes into `messages`: an asking is not a turn. The answers are kept as asides, listed
here and counted by the audit and the ledger, since they are billed. Moved out of turns.py (#133).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import context, dials, ledger, memory, trackers
from lustjinn.deps import Session
from lustjinn.library import persona_of
from lustjinn.models import Aside, SpendKind, Story
from lustjinn.openrouter import ModelError, OpenRouter, Reply, reasoning
from lustjinn.settings import Settings
from lustjinn.stories import playable_story, visible_messages
from lustjinn.streams import Failed, delta, event

# Sampling for a question: cold, because an answer can be promoted to a pinned fact (step 7),
# so an embellishment would become something the character believes. Short: it is an answer.
ASIDE_TEMPERATURE = 0.4
ASIDE_MAX_TOKENS = 600


class AsideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    question: str
    answer: str
    model: str | None
    provider: str | None
    asked_at: datetime


class AsideDone(BaseModel):
    """The last event of a question that was answered. Nothing of it is in the story."""

    kind: Literal["aside"] = "aside"
    aside: AsideOut


async def ask(
    session: AsyncSession, openrouter: OpenRouter, settings: Settings, story: Story, question: str
) -> AsyncIterator[str]:
    """Answers a question about the story, out of character, and keeps the answer apart."""
    history = await visible_messages(session, story.id)
    # The same compose as a turn — the dials' text and the room their ceiling takes included —
    # so the answer is grounded in exactly what the character can see, and so a question can
    # trigger the same summary a turn would have. The question's own sampling stays cold and
    # short whatever the dials say: it is an answer, not a reply.
    directives, knobs = await dials.of_story(session, story.id)
    built = await memory.compose(
        session,
        openrouter,
        settings,
        story,
        await persona_of(session, story),
        history,
        directives=directives,
        trackers=trackers.render(await trackers.of(session, story.id)),
        instruction=context.ask_directive(question),
        reply_tokens=knobs.max_tokens or settings.max_tokens,
    )
    answered: Reply | None = None
    try:
        async for piece in openrouter.stream(
            built.messages,
            model=settings.model,
            temperature=ASIDE_TEMPERATURE,
            max_tokens=ASIDE_MAX_TOKENS,
            reasoning=reasoning(settings),
        ):
            if isinstance(piece, Reply):
                answered = piece
            else:
                yield delta(piece)
    except ModelError as error:
        # Unlike a send, nothing was stored: this is simply a call that did not happen.
        yield event("error", Failed(detail=f"The question was not answered: {error}", sent=None))
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
    yield event("done", AsideDone(aside=AsideOut.model_validate(aside)))


router = APIRouter(prefix="/stories", tags=["asides"])


@router.get("/{story_id}/asides")
async def list_asides(story_id: uuid.UUID, session: Session) -> list[AsideOut]:
    """The questions asked about a story, newest first."""
    await playable_story(session, story_id)
    rows = await session.scalars(
        select(Aside)
        .where(Aside.story_id == story_id)
        .order_by(Aside.asked_at.desc(), Aside.id.desc())
    )
    return [AsideOut.model_validate(row) for row in rows]
