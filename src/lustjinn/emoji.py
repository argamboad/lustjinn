"""The emoji shortcodes both composers expand — `:smile:` becomes 😄 — served from one table.

The donor's 225 shortcodes were ported twice, once per client, and two copies of a table drift
(#132). The table is data in the package, beside `dials.json`, and `GET /emoji` hands it out:
public, because it says nothing about anyone's stories, and cacheable, because it changes only
with a deploy. Each client reads it once and keeps no copy of its own.
"""

import json
from functools import lru_cache
from importlib import resources

from fastapi import APIRouter, Response
from pydantic import BaseModel

CACHE_SECONDS = 24 * 60 * 60
"""How long a browser may keep the table without asking again: it changes only with a deploy."""


class Shortcode(BaseModel):
    name: str
    """What goes between the colons, lower case: `smile`."""
    emoji: str
    keywords: str = ""
    """Words the picker's search also matches, space-separated: `happy joy grin`."""


@lru_cache
def shipped() -> tuple[Shortcode, ...]:
    """The table shipped with the package, in the donor's order. Read once."""
    document = json.loads(
        resources.files("lustjinn").joinpath("emoji.json").read_text(encoding="utf-8")
    )
    return tuple(Shortcode.model_validate(entry) for entry in document["shortcodes"])


router = APIRouter(tags=["emoji"])


@router.get("/emoji")
async def list_emoji(response: Response) -> list[Shortcode]:
    """Every shortcode, in the order a picker offers them before anything is typed."""
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return list(shipped())
