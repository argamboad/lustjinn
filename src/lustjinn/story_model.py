"""A model per story: checked before it is saved, fitted to its window, never the reason a turn
is lost.

A story plays on the default model unless it names its own, and it can change at any turn — the
prompt is rebuilt from the store on every send, so nothing already written belongs to the model
that wrote it. Three ways that goes wrong were known before any of it was built: a mistyped id
fails every turn, a model with a smaller window than the budget refuses every full prompt, and a
model that is there today can have no host tomorrow. So a model is saved only if the provider's
list has it and its window can hold the story; the budget shrinks to the window; and a model
that goes missing hands the turn to the default (see `turns`), which is recorded on the reply.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from lustjinn import context, dials
from lustjinn.db import get_session
from lustjinn.library import default_persona
from lustjinn.models import Character, Persona, Story
from lustjinn.openrouter import (
    ModelError,
    ModelInfo,
    OpenRouter,
    catalogue,
    get_openrouter,
    window_of,
)
from lustjinn.settings import Settings, get_settings
from lustjinn.stories import visible_story

ROOM_FOR_A_TURN = 1000
"""The least room a prompt must have for its newest turns, over its fixed layers and the reply,
for a model to be offered a story at all. A floor, not a target: a story whose newest turn is
longer still plays, going over the budget as it always may — but a model with less than this
left would be summarising on every turn and seeing almost none of the scene."""

LEAST_BUDGET = 2048
"""Never fit the budget below a floor where nothing but the newest turn could fit."""


@dataclass(frozen=True)
class Checked:
    """A model the story may be saved on."""

    model: str
    context: int | None
    """The window the story is fitted to; None when nothing says."""
    message: str


def fitted(settings: Settings, story: Story) -> Settings:
    """These settings with the budget made to fit the story's model, or these settings when it
    already fits. One copy, handed to the summariser, the retriever and the builder alike:
    those three disagreeing is what once lost twenty-four turns of a real story."""
    if story.model is None or story.model_context is None:
        return settings
    room = story.model_context - settings.max_tokens
    if room >= settings.context_budget:
        return settings
    return settings.model_copy(update={"context_budget": max(room, LEAST_BUDGET)})


def _fixed_layers(character: Character, persona: Persona | None, directives: str | None) -> int:
    """What every prompt of this story carries whatever is compressed."""
    layers = context.Layers(character=character, persona=persona, directives=directives)
    return context.build(layers, budget=None).estimated_tokens


async def check(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    wanted: str,
    *,
    character: Character,
    persona: Persona | None,
    story_id: uuid.UUID | None,
    keeping: str | None,
) -> Checked | None:
    """Whether `wanted` may be saved. None means the default: the story names nothing.

    Refused — with the story staying on `keeping` — when the list cannot be read, when the
    provider does not list the model, or when its window cannot hold the fixed layers, the reply
    and a turn. A model handed more than it was trained for answers in token soup, so it is
    refused here rather than paid for there.
    """
    name = wanted.strip()
    if not name or name.lower() == settings.model.lower():
        return None
    stays = f"The story stays on {keeping or settings.model}."
    try:
        listed = await catalogue(openrouter)
    except ModelError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{name} could not be checked — the model list could not be read ({error}) — so "
            f"it was not set. {stays}",
        ) from error
    found = next((m for m in listed if m.id.lower() == name.lower()), None)
    if found is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{name} is not available — the provider does not list it — so it was not set. {stays}",
        )
    window = window_of(settings, found.id, found.context_length)
    if window is not None:
        values = {} if story_id is None else await dials.values_of(session, story_id)
        pack = dials.shipped()
        fixed = _fixed_layers(character, persona, dials.directives(pack, values))
        reply = dials.sampler(pack, values).max_tokens or settings.max_tokens
        needed = fixed + reply + ROOM_FOR_A_TURN
        if needed > window:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{found.id} can read {window:,} tokens, and this story needs {needed:,} before "
                f"any of it is said: {fixed:,} for the character, persona and dials, {reply:,} "
                f"for the reply. It cannot be played on it, so it was not set. {stays}",
            )
    fits = window is None or window - settings.max_tokens >= settings.context_budget
    message = f"This story now uses {found.id}."
    if not fits and window is not None:
        message += (
            f" It can read {window:,} tokens, under the {settings.context_budget:,} budget, so "
            "the story's budget shrinks to fit it and older turns compress sooner."
        )
    return Checked(found.id, window, message)


# --- the API --------------------------------------------------------------------------------------

router = APIRouter(tags=["models"])
Session = Annotated[AsyncSession, Depends(get_session)]
Model = Annotated[OpenRouter, Depends(get_openrouter)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]


class Choice(BaseModel):
    """One model to choose from, labelled with the provider's list prices — to compare by only.
    What a call cost is still read from its response."""

    id: str
    is_default: bool
    listed: bool
    """Whether the provider lists it right now. An unlisted choice cannot be set."""
    context_length: int | None
    """The window the story would be fitted to: a correction when one is known, else the list's."""
    prompt_per_million: Decimal | None
    completion_per_million: Decimal | None
    prompt_price_ratio: Decimal | None
    """Its prompt price over the default's: 2 means twice as dear per prompt token."""


class SetModel(BaseModel):
    model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    """A model id, or null (or the default's id) to return the story to the default."""


class StoryModel(BaseModel):
    model: str | None
    """The story's own model; None means the default."""
    context: int | None
    default: str
    message: str | None = None


def _choice(settings: Settings, model: str, listed: list[ModelInfo]) -> Choice:
    found = next((m for m in listed if m.id.lower() == model.lower()), None)
    default = next((m for m in listed if m.id.lower() == settings.model.lower()), None)
    prompt = None if found is None else found.prompt_per_million
    base = None if default is None else default.prompt_per_million
    ratio = None
    if prompt is not None and base:
        ratio = (prompt / base).quantize(Decimal("0.01"))
    return Choice(
        id=found.id if found is not None else model,
        is_default=model.lower() == settings.model.lower(),
        listed=found is not None,
        context_length=window_of(settings, model, None if found is None else found.context_length),
        prompt_per_million=prompt,
        completion_per_million=None if found is None else found.completion_per_million,
        prompt_price_ratio=ratio,
    )


@router.get("/models")
async def list_choices(openrouter: Model, settings: CurrentSettings) -> list[Choice]:
    """The default first, then the configured choices, each with the provider's prices and how
    its prompt price compares with the default's."""
    try:
        listed = await catalogue(openrouter)
    except ModelError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"The model list could not be read: {error}"
        ) from error
    names = [settings.model] + [
        c for c in settings.model_choices if c.lower() != settings.model.lower()
    ]
    return [_choice(settings, name, listed) for name in names]


async def _with_cast(session: AsyncSession, story_id: uuid.UUID) -> Story:
    await visible_story(session, story_id)
    story = await session.scalar(
        select(Story)
        .options(joinedload(Story.character), joinedload(Story.persona))
        .where(Story.id == story_id)
        .execution_options(populate_existing=True)
    )
    assert story is not None  # visible_story just found it
    return story


@router.get("/stories/{story_id}/model")
async def read_model(
    story_id: uuid.UUID, session: Session, settings: CurrentSettings
) -> StoryModel:
    story = await visible_story(session, story_id)
    return StoryModel(model=story.model, context=story.model_context, default=settings.model)


@router.put("/stories/{story_id}/model")
async def set_model(
    story_id: uuid.UUID,
    body: SetModel,
    session: Session,
    openrouter: Model,
    settings: CurrentSettings,
) -> StoryModel:
    """Changes the model the story plays on, from the next turn. Checked before it is saved;
    a refusal leaves the story on what it had."""
    story = await _with_cast(session, story_id)
    persona = story.persona if story.persona is not None else await default_persona(session)
    checked = await check(
        session,
        openrouter,
        settings,
        body.model or "",
        character=story.character,
        persona=persona,
        story_id=story.id,
        keeping=story.model,
    )
    if checked is None:
        story.model = None
        story.model_context = None
        message = f"This story uses the default, {settings.model}."
    else:
        story.model = checked.model
        story.model_context = checked.context
        message = checked.message
    await session.commit()
    return StoryModel(
        model=story.model, context=story.model_context, default=settings.model, message=message
    )
