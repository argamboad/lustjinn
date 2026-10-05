"""Saves are checked against the version they started from, and every version is kept."""

from typing import Any

import httpx2
import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from lustjinn.models import Character, LibraryHistory, LibraryKind, Persona
from tests.factories import a_character, a_persona

Json = dict[str, Any]


async def create(client: httpx2.AsyncClient, shelf: str, **body: object) -> Json:
    response = await client.post(f"/library/{shelf}", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def save(client: httpx2.AsyncClient, shelf: str, entry: Json, **changes: object) -> Json:
    response = await client.patch(
        f"/library/{shelf}/{entry['id']}", json={"version": entry["version"], **changes}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def history(client: httpx2.AsyncClient, shelf: str, entry_id: str) -> list[Json]:
    response = await client.get(f"/library/{shelf}/{entry_id}/history")
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_save_over_an_edit_made_elsewhere_is_refused_and_keeps_both_texts(
    client: httpx2.AsyncClient,
) -> None:
    opened = await create(client, "characters", name="Vardhal", text="A lighthouse.\n")
    laptop = await save(client, "characters", opened, text="Edited on the laptop.\n")

    phone = await client.patch(
        f"/library/characters/{opened['id']}",
        json={"version": opened["version"], "text": "Typed on the phone."},
    )

    assert phone.status_code == 409
    refused = phone.json()["detail"]
    assert "changed somewhere else" in refused["message"]
    assert refused["current"]["text"] == "Edited on the laptop.\n"
    assert refused["current"]["version"] == laptop["version"] == 2
    stored = (await client.get(f"/library/characters/{opened['id']}")).json()
    assert stored["text"] == "Edited on the laptop.\n"

    # Saving again is a decision made with both on the screen, and the laptop's survives it
    # in the history.
    again = await save(client, "characters", refused["current"], text="Typed on the phone.")
    assert (again["text"], again["version"]) == ("Typed on the phone.", 3)
    kept = await history(client, "characters", opened["id"])
    assert [(h["version"], h["text"]) for h in kept] == [
        (3, "Typed on the phone."),
        (2, "Edited on the laptop.\n"),
        (1, "A lighthouse.\n"),
    ]


async def test_every_save_adds_a_history_row_and_counts_the_version(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    created = await create(
        client, "characters", name="Vardhal", text="A lighthouse.", opening="*Rain.*"
    )
    renamed = await save(client, "characters", created, name="The headland")
    reopened = await save(client, "characters", renamed, opening="*Fog.*")

    assert (created["version"], renamed["version"], reopened["version"]) == (1, 2, 3)
    rows = list(
        await session.scalars(
            select(LibraryHistory)
            .where(LibraryHistory.entry_id == created["id"])
            .order_by(LibraryHistory.version)
        )
    )
    assert [(r.version, r.name, r.text, r.opening) for r in rows] == [
        (1, "Vardhal", "A lighthouse.", "*Rain.*"),
        (2, "The headland", "A lighthouse.", "*Rain.*"),
        (3, "The headland", "A lighthouse.", "*Fog.*"),
    ]
    assert all(r.kind is LibraryKind.CHARACTER for r in rows)


async def test_saving_the_text_unchanged_writes_nothing(client: httpx2.AsyncClient) -> None:
    created = await create(client, "snippets", name="rain", text="An older rain.\n")

    same = await save(client, "snippets", created, text="An older rain.\n", name="rain")

    assert same["version"] == 1
    assert same["updated_at"] == created["updated_at"]
    assert len(await history(client, "snippets", created["id"])) == 1


async def test_a_save_must_say_which_version_it_started_from(
    client: httpx2.AsyncClient,
) -> None:
    created = await create(client, "personas", name="Keeper", text="The keeper.")

    response = await client.patch(f"/library/personas/{created['id']}", json={"text": "x"})

    assert response.status_code == 422


async def test_the_history_outlives_the_entry(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    created = await create(client, "personas", name="Keeper", text="The keeper.")
    await save(client, "personas", created, text="The keeper of the light.")

    assert (await client.delete(f"/library/personas/{created['id']}")).status_code == 204

    kept = await history(client, "personas", created["id"])
    assert [h["text"] for h in kept] == ["The keeper of the light.", "The keeper."]
    assert await session.get(Persona, created["id"]) is None


async def test_an_entry_that_never_existed_has_no_history(client: httpx2.AsyncClient) -> None:
    from lustjinn.models import new_id

    assert (await client.get(f"/library/personas/{new_id()}/history")).status_code == 404


async def a_history_row(session: AsyncSession) -> LibraryHistory:
    row = LibraryHistory(
        kind=LibraryKind.SNIPPET,
        entry_id=(await a_persona(session)).id,
        version=1,
        name="x",
        text="t",
    )
    session.add(row)
    await session.flush()
    return row


async def test_a_history_row_cannot_be_changed(session: AsyncSession) -> None:
    await a_history_row(session)

    with pytest.raises(IntegrityError, match="never changed or deleted"):
        await session.execute(update(LibraryHistory).values(text="rewritten"))


async def test_a_history_row_cannot_be_deleted(session: AsyncSession) -> None:
    await a_history_row(session)

    with pytest.raises(IntegrityError, match="never changed or deleted"):
        await session.execute(delete(LibraryHistory))


async def test_the_history_cannot_be_truncated(session: AsyncSession) -> None:
    await a_history_row(session)

    with pytest.raises(IntegrityError, match="never changed or deleted"):
        await session.execute(text("TRUNCATE library_history"))


async def test_the_orm_checks_the_version_on_every_update_it_writes(
    session: AsyncSession,
) -> None:
    """What `version_id_col` buys: a row that moved on between the read and the write is
    noticed by the write itself — UPDATE … WHERE version = 1 touches nothing."""
    character = await a_character(session, name="Elena")
    await session.commit()
    await session.refresh(character)
    assert character.version == 1

    # Meanwhile, somewhere else: a save that does not go through this session.
    await session.execute(
        text("UPDATE characters SET version = version + 1 WHERE id = :id"), {"id": character.id}
    )
    character.card = "Edited here, too late."

    with pytest.raises(StaleDataError):
        await session.flush()


async def test_a_successful_save_moves_the_version_on_by_one(session: AsyncSession) -> None:
    character = await a_character(session, name="Elena")
    await session.commit()
    await session.refresh(character)

    character.card = "A new card."
    await session.commit()
    await session.refresh(character)

    assert character.version == 2
    assert (await session.get(Character, character.id, populate_existing=True)) is character
