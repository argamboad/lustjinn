"""GET /emoji: the one table of shortcodes both composers expand (#132)."""

import httpx2

from lustjinn.emoji import CACHE_SECONDS, shipped


def test_the_shipped_table_is_the_donors_whole_list() -> None:
    table = shipped()

    assert len(table) == 225
    assert table[0].name == "smile"
    assert len({code.name for code in table}) == len(table)  # no name twice
    assert all(code.name == code.name.lower() for code in table)
    assert next(code.emoji for code in table if code.name == "tada") == "🎉"


async def test_the_table_is_served_to_anyone_and_may_be_cached(
    anonymous: httpx2.AsyncClient,
) -> None:
    response = await anonymous.get("/emoji")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == f"public, max-age={CACHE_SECONDS}"
    body = response.json()
    assert len(body) == 225
    assert body[0] == {"name": "smile", "emoji": "😄", "keywords": "happy joy grin"}


async def test_every_other_route_stays_private(anonymous: httpx2.AsyncClient) -> None:
    """Letting /emoji choose its caching must not let anything else escape no-store."""
    response = await anonymous.get("/health")

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
