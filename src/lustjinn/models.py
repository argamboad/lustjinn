"""The tables, as SQLAlchemy models.

Schema changes are made here *and* in a migration under `migrations/versions/`; a test fails when
the two disagree. Rules the database enforces by itself — the append-only trigger on messages —
live only in the migrations, because they are not something a model can express.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
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
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship


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


class LibraryEntry:
    """What every shelf of the library shares: a name, a version, a time of last change.

    A mixin, not a table: each class below gets its own copy of these columns. Names are unique
    without regard to case, by an index on `lower(name)` declared on each table.
    """

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(server_default="1")
    """Counts the saves. A save names the version it started from, and is refused when the row
    has moved on: `UPDATE … WHERE id = … AND version = …` touching no row."""
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @declared_attr.directive
    @classmethod
    def __mapper_args__(cls) -> dict[str, Any]:
        # The ORM does the optimistic check itself: every UPDATE it writes carries
        # `WHERE version = <the version it loaded>` and sets `version + 1`; no row matched means
        # someone saved first, and the flush raises StaleDataError.
        return {"version_id_col": cls.version}


class LibraryKind(StrEnum):
    CHARACTER = "character"
    PERSONA = "persona"
    SNIPPET = "snippet"


class LibraryHistory(Base):
    """Every version of every entry ever saved. Insert-only; outlives the entry."""

    __tablename__ = "library_history"
    __table_args__ = (
        CheckConstraint("kind IN ('character', 'persona', 'snippet')", name="kind"),
        Index("ix_library_history_entry", "entry_id", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[LibraryKind] = mapped_column(_stored_as_text(LibraryKind))
    entry_id: Mapped[uuid.UUID]
    """No foreign key: the history of a deleted entry is still history."""
    version: Mapped[int]
    name: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    opening: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Character(LibraryEntry, Base):
    """A character card, with the opening a story with them starts on."""

    __tablename__ = "characters"
    __table_args__ = (Index("uq_characters_name_lower", text("lower(name)"), unique=True),)

    card: Mapped[str] = mapped_column(Text)
    opening: Mapped[str | None] = mapped_column(Text)
    """The scene a story with this character starts on, written by a person."""


class Persona(LibraryEntry, Base):
    """Who the reader plays."""

    __tablename__ = "personas"
    __table_args__ = (Index("uq_personas_name_lower", text("lower(name)"), unique=True),)

    text: Mapped[str] = mapped_column(Text)


class Snippet(LibraryEntry, Base):
    """Authored prose, expanded into a message where `:name` is typed. Copied, never read again."""

    __tablename__ = "snippets"
    __table_args__ = (Index("uq_snippets_name_lower", text("lower(name)"), unique=True),)

    text: Mapped[str] = mapped_column(Text)


class AppSettings(Base):
    """The one row of settings that live in the database rather than the environment.

    One row, by a CHECK on its id. Missing until something is set: readers treat that as every
    value at its default.
    """

    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("id = 1", name="one_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_persona_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("personas.id", ondelete="SET NULL")
    )
    """The persona a story plays as when it names none. Cleared if that persona is deleted."""

    default_persona: Mapped[Persona | None] = relationship(lazy="raise")


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
    model_context: Mapped[int | None]
    """The window that model was checked against when it was set, so the budget can be fitted
    to it on every turn without reading the list again. None when nothing said."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Set when the story is deleted: it is hidden, and its rows stay."""

    character: Mapped[Character] = relationship(lazy="raise")
    persona: Mapped[Persona | None] = relationship(lazy="raise")
    messages: Mapped[list[Message]] = relationship(
        back_populates="story", order_by="Message.sequence", lazy="raise"
    )


class DialValue(Base):
    """One dial a story has set. A story stores only the values it changed; a dial never set
    and a dial cleared are the same state, so clearing deletes the row."""

    __tablename__ = "dial_values"
    __table_args__ = (UniqueConstraint("story_id", "key", name="uq_dial_values_story_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stories.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(100))
    """The dial's key in the pack."""
    value: Mapped[str] = mapped_column(Text)
    """In stored form: a level index, true/false, an option key, a JSON array, or text."""
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tracker(Base):
    """One meter of a story: the model draws it at the end of each reply, and the app reads the
    value back. Off by default — a meter the model can see is a meter it writes towards."""

    __tablename__ = "trackers"
    __table_args__ = (
        Index("uq_trackers_story_name_lower", "story_id", text("lower(name)"), unique=True),
        CheckConstraint("max > 0", name="max_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stories.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    value: Mapped[float] = mapped_column(Float)
    max: Mapped[float] = mapped_column(Float)
    delta: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    """What the last turn was worth: computed from the value read back, never believed."""
    note: Mapped[str | None] = mapped_column(String(200))
    """The model's reason, in a few words; `set by hand` when a person moved it."""
    means: Mapped[str | None] = mapped_column(Text)
    anchors: Mapped[str | None] = mapped_column(Text)
    rule: Mapped[str | None] = mapped_column(Text)
    updated_at_sequence: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    fell_back_from: Mapped[str | None] = mapped_column(String(200))
    """The story's own model, when it could not take this turn and the default wrote it."""
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    estimated_prompt_tokens: Mapped[int | None]
    context_audit: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Set when the message is hidden — by a reroll or a delete. The row stays."""

    story: Mapped[Story] = relationship(back_populates="messages", lazy="raise")


class Aside(Base):
    """A question asked about the story out of character, and its answer.

    Never a turn: nothing that reads a story — the prompt, and later the summariser, the
    extractor, retrieval — reads this table. It exists so that a billed call leaves a trace.
    """

    __tablename__ = "asides"
    __table_args__ = (CheckConstraint("sequence >= 0", name="sequence_not_negative"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int]
    """The newest visible message when it was asked, to place it against the story."""
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model: Mapped[str | None] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(200))
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    estimated_prompt_tokens: Mapped[int | None]
    context_audit: Mapped[str | None] = mapped_column(Text)


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


class Summary(Base):
    """A stretch of the story compressed into prose, carried forward once its turns no longer
    fit. Derived from the transcript: it can always be made again, and deleting one loses
    nothing that is not still in `messages`."""

    __tablename__ = "summaries"
    __table_args__ = (
        UniqueConstraint("story_id", "from_sequence", name="uq_summaries_story_from"),
        CheckConstraint("from_sequence <= to_sequence", name="range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stories.id", ondelete="RESTRICT"))
    from_sequence: Mapped[int]
    to_sequence: Mapped[int]
    """Inclusive: the summary stands for every turn from `from_sequence` to `to_sequence`."""
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(200))
    message_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


EMBEDDING_DIMENSIONS = 1536
"""What openai/text-embedding-3-small produces. The column refuses any other length."""


class Embedding(Base):
    """The vector of one summarised turn, for retrieval. Only turns a summary already covers
    are embedded: the recent ones are in the prompt verbatim and need no recalling."""

    __tablename__ = "embeddings"
    __table_args__ = (
        Index(
            "ix_embeddings_vector",
            "vector",
            postgresql_using="hnsw",
            postgresql_ops={"vector": "vector_cosine_ops"},
        ),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="RESTRICT"), index=True
    )
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    model: Mapped[str] = mapped_column(String(200))
    """The embedding model. Vectors from different models do not compare; if the model changes,
    the rows are made again."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Fact(Base):
    """Something true in the story, from the turn it became true until the turn that made it
    false. Live while `valid_to_sequence` is null. Extracted by a model after each summary, or
    stated by a person — in which case `model` is null and the fact is pinned."""

    __tablename__ = "facts"
    __table_args__ = (
        CheckConstraint(
            "valid_to_sequence IS NULL OR valid_to_sequence >= valid_from_sequence", name="range"
        ),
        Index("ix_facts_story_live", "story_id", "valid_to_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stories.id", ondelete="RESTRICT"))
    subject: Mapped[str] = mapped_column(String(200))
    """Who or what it is about: a name, a place, a pair. Never "User"."""
    text: Mapped[str] = mapped_column(Text)
    valid_from_sequence: Mapped[int]
    valid_to_sequence: Mapped[int | None]
    model: Mapped[str | None] = mapped_column(String(200))
    pinned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    """A person said so; the extractor cannot retire it. A person can."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
