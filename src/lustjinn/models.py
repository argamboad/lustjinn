"""The tables, as SQLAlchemy models.

Schema changes are made here *and* in a migration under `migrations/versions/`; a test fails when
the two disagree. Rules the database enforces by itself — the append-only trigger on messages —
live only in the migrations, because they are not something a model can express.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # One naming rule for every constraint and index, so the names in the database are
    # predictable and a migration can refer to them.
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
        }
    )


def new_id() -> uuid.UUID:
    """A UUID version 7: unique like any UUID, and sortable by the time it was made."""
    return uuid.uuid7()


class Role(StrEnum):
    """Who a message is from."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SpendKind(StrEnum):
    """What a billed call was doing."""

    REPLY = "reply"
    ASIDE = "aside"
    SUMMARY = "summary"
    FACTS = "facts"


def _values(members: type[StrEnum]) -> list[str]:
    """What an enum column holds: the values ("user"), not the member names ("USER")."""
    return [member.value for member in members]


def _stored_as_text(members: type[StrEnum]) -> Enum:
    """An enum stored as plain text, read back as the enum. A CHECK on the table guards it."""
    return Enum(
        members, native_enum=False, create_constraint=False, length=20, values_callable=_values
    )


class Character(Base):
    """A character card. Minimal for now: the library step adds history and editing."""

    __tablename__ = "characters"
    __table_args__ = (Index("uq_characters_name_lower", text("lower(name)"), unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    card: Mapped[str] = mapped_column(Text)
    opening: Mapped[str | None] = mapped_column(Text)
    """The scene a story with this character starts on, written by a person."""
    version: Mapped[int] = mapped_column(server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Persona(Base):
    """Who the reader plays."""

    __tablename__ = "personas"
    __table_args__ = (Index("uq_personas_name_lower", text("lower(name)"), unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Story(Base):
    """One conversation. It points at its character and persona, so editing either reaches it."""

    __tablename__ = "stories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    # RESTRICT: the database refuses to delete a character or persona a story still uses.
    character_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("characters.id", ondelete="RESTRICT"), index=True
    )
    persona_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("personas.id", ondelete="RESTRICT"), index=True
    )
    model: Mapped[str | None] = mapped_column(String(200))
    """The model this story plays on; None means the default."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Set when the story is deleted: it is hidden, and its rows stay."""

    character: Mapped[Character] = relationship(lazy="raise")
    persona: Mapped[Persona | None] = relationship(lazy="raise")
    messages: Mapped[list[Message]] = relationship(
        back_populates="story", order_by="Message.sequence", lazy="raise"
    )


class Message(Base):
    """One turn. Append-only: a trigger refuses deleting a row or changing its text."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("story_id", "sequence", name="uq_messages_story_sequence"),
        # The same request cannot land twice in one story; messages without a hash never collide.
        Index(
            "uq_messages_story_request_hash",
            "story_id",
            "request_hash",
            unique=True,
            postgresql_where=text("request_hash IS NOT NULL"),
        ),
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="role"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stories.id", ondelete="RESTRICT"))
    sequence: Mapped[int]
    """Position in the story, from 1. Never reused, even after a message is hidden."""
    role: Mapped[Role] = mapped_column(_stored_as_text(Role))
    text: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    """Identifies the request that stored a reader's turn, so a retry does not store it twice."""
    model: Mapped[str | None] = mapped_column(String(200))
    """The model that wrote it; None means a person did — the reader's turns, and the opening."""
    provider: Mapped[str | None] = mapped_column(String(200))
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    estimated_prompt_tokens: Mapped[int | None]
    context_audit: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Set when the message is hidden — by a reroll or a delete. The row stays."""

    story: Mapped[Story] = relationship(back_populates="messages", lazy="raise")


class Spend(Base):
    """One row per billed call, whatever became of what it produced. A ledger, not a summary.

    Insert-only, enforced by a trigger — and no foreign keys on purpose: a story erased for good
    takes its messages with it, and its ledger stays. What the router charged exists nowhere
    else once the response is gone.
    """

    __tablename__ = "spend"
    __table_args__ = (
        CheckConstraint("kind IN ('reply', 'aside', 'summary', 'facts')", name="kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[SpendKind] = mapped_column(_stored_as_text(SpendKind))
    message_id: Mapped[uuid.UUID | None]
    """The reply this call produced, for a reply. Whether it was later rerolled away is read
    from that message at report time, never stored here."""
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model: Mapped[str | None] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(200))
    generation_id: Mapped[str | None] = mapped_column(String(200))
    """OpenRouter's id for the call, to reconcile against its own records."""
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    cached_tokens: Mapped[int | None]
    cache_write_tokens: Mapped[int | None]
    cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 10))
    """What the call was charged, as the API reported it. None is "the API did not say", which
    is not zero. Exact decimal, never a float: hundreds of $0.0028 rows must add up."""
