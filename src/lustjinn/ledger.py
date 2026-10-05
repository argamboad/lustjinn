"""Turns a model's answer into the one row that says what it cost.

One place, because the calls that spend money are easy to forget — two of them (summaries and
facts, step 6) fire without the reader asking for anything. Every billed call writes a row,
including one whose output is thrown away a second later: the charge happened.
"""

import uuid

from lustjinn.models import Spend, SpendKind
from lustjinn.openrouter import Reply


def row(
    story_id: uuid.UUID, kind: SpendKind, reply: Reply, message_id: uuid.UUID | None = None
) -> Spend:
    return Spend(
        story_id=story_id,
        kind=kind,
        message_id=message_id,
        model=reply.model,
        provider=reply.provider,
        generation_id=reply.generation_id,
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
        cached_tokens=reply.cached_tokens,
        cache_write_tokens=reply.cache_write_tokens,
        cost=reply.cost,
    )
