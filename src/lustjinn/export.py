"""Export: a story's transcript as a document to keep outside the app.

Three renderings of one projection — Markdown with front matter, JSON, plain text — of the
visible turns, each with a resolved speaker. The API returns the document; each client saves or
copies it. Hidden turns are not in it: an export is the story as it reads, not as it was typed.
"""

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from lustjinn.deps import Session
from lustjinn.library import default_persona
from lustjinn.models import Message, Role, Story
from lustjinn.stories import visible_story

router = APIRouter(prefix="/stories/{story_id}", tags=["export"])


class Format(StrEnum):
    MARKDOWN = "markdown"
    JSON = "json"
    TEXT = "text"


EXTENSIONS = {Format.MARKDOWN: "md", Format.JSON: "json", Format.TEXT: "txt"}
MEDIA_TYPES = {
    Format.MARKDOWN: "text/markdown; charset=utf-8",
    Format.JSON: "application/json",
    Format.TEXT: "text/plain; charset=utf-8",
}


@dataclass(frozen=True)
class Turn:
    index: int
    sequence: int
    role: str
    speaker: str
    sent_at: str
    word_count: int
    text: str


@dataclass(frozen=True)
class Transcript:
    story_id: str
    title: str
    speaker: str
    """The character: who the replies are from."""
    reader: str
    """The persona, or "You"."""
    exported_at: str
    started_at: str | None
    ended_at: str | None
    message_count: int
    reader_message_count: int
    reply_count: int
    messages: list[Turn]


def slug(value: str) -> str:
    """A file-name-safe version of the title: letters and digits, lower-cased, dashes between."""
    cut = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cut[:60] or "export"


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def project(story: Story, reader: str, turns: list[Message], now: datetime) -> Transcript:
    def who(turn: Message) -> str:
        if turn.role is Role.ASSISTANT:
            return story.character.name
        return reader if turn.role is Role.USER else "Note"

    return Transcript(
        story_id=str(story.id),
        title=story.name,
        speaker=story.character.name,
        reader=reader,
        exported_at=now.isoformat(),
        started_at=turns[0].sent_at.isoformat() if turns else None,
        ended_at=turns[-1].sent_at.isoformat() if turns else None,
        message_count=len(turns),
        reader_message_count=sum(1 for t in turns if t.role is Role.USER),
        reply_count=sum(1 for t in turns if t.role is Role.ASSISTANT),
        messages=[
            Turn(
                index=i + 1,
                sequence=turn.sequence,
                role=turn.role.value,
                speaker=who(turn),
                sent_at=turn.sent_at.isoformat(),
                word_count=len(turn.text.split()),
                text=turn.text,
            )
            for i, turn in enumerate(turns)
        ],
    )


def _yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid YAML scalar


def as_markdown(transcript: Transcript) -> str:
    lines = [
        "---",
        f"title: {_yaml(transcript.title)}",
        f"story: {_yaml(transcript.story_id)}",
        f"speaker: {_yaml(transcript.speaker)}",
        f"reader: {_yaml(transcript.reader)}",
        f"messages: {transcript.message_count}",
        f"from_reader: {transcript.reader_message_count}",
        f"replies: {transcript.reply_count}",
    ]
    if transcript.started_at:
        lines.append(f"started: {transcript.started_at}")
    lines += [f"exported: {transcript.exported_at}", "---", "", f"# {transcript.title}"]
    for turn in transcript.messages:
        stamp = _stamp(datetime.fromisoformat(turn.sent_at))
        lines += ["", f"## {turn.index}. {turn.speaker} — {stamp}", "", turn.text]
    return "\n".join(lines) + "\n"


def as_text(transcript: Transcript) -> str:
    blocks: list[str] = []
    for turn in transcript.messages:
        stamp = _stamp(datetime.fromisoformat(turn.sent_at))
        blocks.append(f"[{turn.index:03d}] {turn.speaker} · {stamp}\n{'-' * 60}\n{turn.text}")
    return "\n\n".join(blocks) + "\n"


def as_json(transcript: Transcript) -> str:
    return json.dumps(asdict(transcript), ensure_ascii=False, indent=2) + "\n"


def render(transcript: Transcript, fmt: Format) -> str:
    match fmt:
        case Format.MARKDOWN:
            return as_markdown(transcript)
        case Format.JSON:
            return as_json(transcript)
        case Format.TEXT:
            return as_text(transcript)


@router.get("/export")
async def export_story(
    story_id: uuid.UUID, session: Session, format: Format = Format.MARKDOWN
) -> Response:
    """The visible transcript as a document, with a file name to save it under."""
    await visible_story(session, story_id)
    story = await session.scalar(
        select(Story)
        .options(joinedload(Story.character), joinedload(Story.persona))
        .where(Story.id == story_id)
    )
    assert story is not None
    persona = story.persona if story.persona is not None else await default_persona(session)
    turns = list(
        await session.scalars(
            select(Message)
            .where(Message.story_id == story_id, Message.deleted_at.is_(None))
            .order_by(Message.sequence)
        )
    )
    now = datetime.now(UTC)
    transcript = project(story, persona.name if persona else "You", turns, now)
    filename = f"transcript-{slug(story.name)}-{now.strftime('%Y%m%d-%H%M%S')}.{EXTENSIONS[format]}"
    return Response(
        render(transcript, format),
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
