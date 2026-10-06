"""Export: the visible transcript as Markdown, JSON or plain text."""

import json
import re
from datetime import UTC, datetime

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.export import slug
from lustjinn.models import Role
from scripts.seed_dummy import Dummy
from tests.factories import a_message
from tests.test_turns import a_played_story


async def a_story_to_export(session: AsyncSession):
    story = await a_played_story(session)
    await a_message(session, story, "I come in from the fog.", Role.USER)
    await a_message(session, story, "She looks up.\n\nAnd does not smile.", Role.ASSISTANT)
    hidden = await a_message(session, story, "A rerolled reply.", Role.ASSISTANT)
    hidden.deleted_at = datetime.now(UTC)
    await session.commit()
    return story


async def test_markdown_has_front_matter_and_one_heading_per_turn(
    client: httpx2.AsyncClient, session: AsyncSession, dummy: Dummy
) -> None:
    story = await a_story_to_export(session)

    response = await client.get(f"/stories/{story.id}/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert re.fullmatch(
        r'attachment; filename="transcript-first-night-\d{8}-\d{6}\.md"',
        response.headers["content-disposition"],
    )
    text = response.text
    head, body = text.split("\n---\n", 1)
    assert head.startswith('---\ntitle: "First night"\n')
    assert 'speaker: "The Gilded Heron"\n' in head
    assert 'reader: "Rowan Hale"\n' in head
    assert "messages: 3\nfrom_reader: 1\nreplies: 2\n" in head
    assert body.startswith("\n# First night\n\n## 1. The Gilded Heron — ")
    assert "\n## 2. Rowan Hale — " in body
    assert "\n## 3. The Gilded Heron — " in body
    assert "I come in from the fog." in body
    assert "She looks up.\n\nAnd does not smile." in body
    assert "rerolled" not in text
    assert dummy.opening.strip() in body


async def test_json_is_one_entry_per_turn_with_a_resolved_speaker(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story_to_export(session)

    response = await client.get(f"/stories/{story.id}/export", params={"format": "json"})

    assert response.headers["content-type"] == "application/json"
    document = json.loads(response.text)
    assert document["title"] == "First night"
    assert document["story_id"] == str(story.id)
    assert (
        document["message_count"],
        document["reader_message_count"],
        document["reply_count"],
    ) == (3, 1, 2)
    assert document["started_at"] <= document["ended_at"] <= document["exported_at"]
    turns = document["messages"]
    assert [t["index"] for t in turns] == [1, 2, 3]
    assert [t["sequence"] for t in turns] == [1, 2, 3]
    assert turns[1] == {
        "index": 2,
        "sequence": 2,
        "role": "user",
        "speaker": "Rowan Hale",
        "sent_at": turns[1]["sent_at"],
        "word_count": 6,
        "text": "I come in from the fog.",
    }
    assert turns[2]["speaker"] == "The Gilded Heron"
    assert turns[2]["word_count"] == 7


async def test_plain_text_numbers_each_turn_with_its_speaker_and_time(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story_to_export(session)

    response = await client.get(f"/stories/{story.id}/export", params={"format": "text"})

    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].endswith('.txt"')
    text = response.text
    assert re.search(r"^\[001\] The Gilded Heron · \d{4}-\d{2}-\d{2} \d{2}:\d{2}\n-{60}\n", text)
    assert "\n\n[002] Rowan Hale · " in text
    assert text.count("\n" + "-" * 60 + "\n") == 3
    assert text.endswith("And does not smile.\n")
    assert "rerolled" not in text


async def test_an_unknown_format_is_refused(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story_to_export(session)

    response = await client.get(f"/stories/{story.id}/export", params={"format": "pdf"})

    assert response.status_code == 422


async def test_a_missing_story_is_a_404(client: httpx2.AsyncClient) -> None:
    missing = "01a10d31-0000-7000-8000-000000000000"

    assert (await client.get(f"/stories/{missing}/export")).status_code == 404


def test_the_file_name_is_a_slug_of_the_title() -> None:
    assert slug("First night") == "first-night"
    assert slug("  La Posada: ¿quién? ") == "la-posada-qui-n"
    assert slug("***") == "export"
    assert len(slug("x" * 100)) == 60
