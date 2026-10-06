"""Search: the turn where something was actually said, across every story or inside one.

For "did this happen", search beats asking the model. It is a phrase search — a case-insensitive
substring over the visible turns of visible stories — because the question is almost always
"where were these words said", and stemming would answer a different one. Postgres full-text
search was weighed and set aside for now: one reader's stories are small enough to scan, and an
exact phrase is what the donor's readers asked for.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.db import get_session
from lustjinn.library import default_persona
from lustjinn.models import Character, Message, Persona, Role, Story
from lustjinn.stories import visible_story

router = APIRouter(tags=["search"])
Session = Annotated[AsyncSession, Depends(get_session)]

SNIPPET_RADIUS = 48
"""Characters shown around the first match in a list of hits across stories."""
EXCERPT_RADIUS = 60
"""Around the match inside one story, where there is room for more."""
NAME_SCORE = 60
"""A story named for the phrase outranks any turn that merely contains it."""
MESSAGE_SCORE = 40
"""Plus five per further occurrence, up to twenty: a turn that says it more than once is the
more likely one to have been looking for."""
MOST_HITS = 200


class Hit(BaseModel):
    scope: Literal["name", "message"]
    story_id: uuid.UUID
    story_name: str
    message_id: uuid.UUID | None
    sequence: int | None
    role: Role | None
    speaker: str | None
    """The character's name, the reader's persona, or "You"."""
    sent_at: str | None
    snippet: str
    score: int
    occurrences: int


class Results(BaseModel):
    hits: list[Hit]
    searched: int
    """How many stories were looked through."""


def snippet(text: str, index: int, radius: int = SNIPPET_RADIUS) -> str:
    """One line around the match: a turn carries its own line breaks, a list of hits wants one
    line per hit."""
    flat = " ".join(text.split())
    if len(flat) <= radius * 2:
        return flat.strip()
    # The index was found in the original text; the flattened one is never longer, and the
    # shift from collapsed whitespace before the match is what this corrects.
    shifted = len(" ".join(text[:index].split()))
    if text[:index] and text[:index][-1].isspace():
        shifted += 1
    start, end = max(0, shifted - radius), min(len(flat), shifted + radius)
    slice_ = flat[start:end].strip()
    return ("…" if start > 0 else "") + slice_ + ("…" if end < len(flat) else "")


def occurrences(text: str, phrase: str) -> int:
    return text.lower().count(phrase.lower())


def _escaped(phrase: str) -> str:
    """The phrase as a LIKE pattern, with its own `%` and `_` meaning themselves."""
    return phrase.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _speaker(role: Role, character: str, persona: str | None) -> str:
    if role is Role.ASSISTANT:
        return character
    if role is Role.USER:
        return persona or "You"
    return "Note"


async def search(
    session: AsyncSession, phrase: str, *, story_id: uuid.UUID | None, limit: int
) -> Results:
    pattern = f"%{_escaped(phrase)}%"
    fallback = await default_persona(session)
    stories = (
        select(Story, Character.name, Persona.name)
        .join(Character, Story.character_id == Character.id)
        .outerjoin(Persona, Story.persona_id == Persona.id)
        .where(Story.deleted_at.is_(None))
    )
    if story_id is not None:
        stories = stories.where(Story.id == story_id)
    rows = list(await session.execute(stories))
    hits: list[Hit] = []

    if story_id is None:
        for story, _character, _persona in rows:
            if phrase.lower() in story.name.lower():
                hits.append(
                    Hit(
                        scope="name",
                        story_id=story.id,
                        story_name=story.name,
                        message_id=None,
                        sequence=None,
                        role=None,
                        speaker=None,
                        sent_at=None,
                        snippet=story.name,
                        score=NAME_SCORE,
                        occurrences=1,
                    )
                )

    names = {story.id: (story.name, character, persona) for story, character, persona in rows}
    radius = SNIPPET_RADIUS if story_id is None else EXCERPT_RADIUS
    found = await session.scalars(
        select(Message)
        .where(
            Message.story_id.in_(list(names)),
            Message.deleted_at.is_(None),
            Message.text.ilike(pattern, escape="\\"),
        )
        .order_by(Message.sent_at.desc(), Message.sequence.desc())
    )
    for message in found:
        story_name, character, persona = names[message.story_id]
        index = message.text.lower().find(phrase.lower())
        count = occurrences(message.text, phrase)
        hits.append(
            Hit(
                scope="message",
                story_id=message.story_id,
                story_name=story_name,
                message_id=message.id,
                sequence=message.sequence,
                role=message.role,
                speaker=_speaker(
                    message.role, character, persona or (fallback.name if fallback else None)
                ),
                sent_at=message.sent_at.isoformat(),
                snippet=snippet(message.text, index, radius),
                score=MESSAGE_SCORE + min(20, count * 5),
                occurrences=count,
            )
        )

    # Highest score first; among equals, the newest first. Two stable sorts, the tie-break
    # applied before the key that matters.
    hits.sort(key=lambda hit: (hit.sent_at or "", hit.sequence or 0), reverse=True)
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return Results(hits=hits[: max(1, limit)], searched=len(rows))


@router.get("/search")
async def search_everywhere(
    session: Session,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    story_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=MOST_HITS)] = MOST_HITS,
) -> Results:
    """Finds the phrase in story names and visible turns, the best hits first. With `story_id`,
    inside that story only, with a longer excerpt around each match."""
    if story_id is not None:
        await visible_story(session, story_id)
    return await search(session, q.strip(), story_id=story_id, limit=limit)
