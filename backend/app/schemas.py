"""Request and response schemas.

These are the API contract, not the database schema. Keeping them separate means
storage can change (adding embedding columns later) without changing what clients
send, and vice versa.
"""

from datetime import datetime
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator, model_validator


class MemoryCategory(str, Enum):
    """What kind of knowledge this memory carries.

    The distinction matters later: a ``decision`` can be superseded, a
    ``failure`` is usually still true even after the bug is fixed, and
    contradiction checks only make sense within comparable categories.
    """

    DECISION = "decision"
    CONSTRAINT = "constraint"
    FAILURE = "failure"
    CONVENTION = "convention"
    FACT = "fact"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class MemoryCreate(BaseModel):
    """What a client may send when adding a memory.

    Deliberately narrower than the stored record: ``id`` and timestamps are
    server-assigned, and ``status``/``superseded_by`` are not writable yet
    because no feature has needed to write them. Adding them here without a
    caller would be untested surface area.
    """

    content: str = Field(min_length=1, max_length=4000)
    category: MemoryCategory
    source: str = Field(min_length=1, max_length=200)
    project: str = Field(min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Optional original timestamp. Real memory systems hold memories that were
    # captured weeks ago, and without that date "stale" can never be detected.
    # When omitted, the server stamps the current time.
    created_at: datetime | None = None

    @field_validator("content", "source", "project", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        """Trim surrounding whitespace so "  " is rejected by min_length.

        We only trim; we do not otherwise normalise content. Normalisation for
        duplicate detection belongs to the analysis layer, which must be free to
        change its rules without rewriting stored memories.
        """
        if isinstance(value, str):
            return value.strip()
        return value


class Memory(BaseModel):
    """A stored memory as returned by the API."""

    id: str
    content: str
    category: MemoryCategory
    source: str
    project: str
    created_at: datetime
    updated_at: datetime
    confidence: float | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    superseded_by: str | None = None


class MemoryUpdate(BaseModel):
    """Partial update. Omitted fields are left untouched.

    Optional-typed fields serve two different meanings in PATCH:
    a field absent from the request is "leave as is", while an explicit ``null``
    on a nullable field is "clear it". Validation below rejects an explicit
    ``null`` for columns that cannot be empty.
    """

    content: str | None = Field(default=None, min_length=1, max_length=4000)
    category: MemoryCategory | None = None
    source: str | None = Field(default=None, min_length=1, max_length=200)
    project: str | None = Field(default=None, min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: MemoryStatus | None = None
    superseded_by: str | None = None

    # Columns that are NOT NULL and therefore cannot be cleared with null.
    REQUIRED_WHEN_PRESENT: ClassVar[tuple[str, ...]] = (
        "content",
        "category",
        "source",
        "project",
        "status",
    )

    @field_validator("content", "source", "project", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def validate_update(self) -> "MemoryUpdate":
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")

        for field in self.REQUIRED_WHEN_PRESENT:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"'{field}' cannot be null")

        return self


class MemoryImportRequest(BaseModel):
    """Bulk import payload.

    Capped at 500 entries: the import runs as a single transaction and looks the
    inserted rows back up with one ``IN (...)`` query, and SQLite's bound
    parameter limit is 999. Validating the whole batch here means a bad row is
    rejected before any write happens.
    """

    memories: list[MemoryCreate] = Field(min_length=1, max_length=500)


class MemoryImportResult(BaseModel):
    imported: int
    ids: list[str]


# --- health check -----------------------------------------------------------


class IssueType(str, Enum):
    """The kind of quality problem a finding describes."""

    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    POTENTIAL_CONTRADICTION = "potential_contradiction"
    POTENTIALLY_STALE = "potentially_stale"
    SUPERSEDED_MEMORY = "superseded_memory"
    MISSING_CONFIDENCE = "missing_confidence"
    LOW_CONFIDENCE = "low_confidence"
    UNRELIABLE_SOURCE = "unreliable_source"
    PLACEHOLDER_PROJECT = "placeholder_project"
    VAGUE_CONTENT = "vague_content"
    SUSPICIOUS_CONTENT = "suspicious_content"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class HealthFinding(BaseModel):
    """One inspectable finding.

    Every finding carries the memories it came from and the evidence that
    produced it, so a developer can check the tool's reasoning instead of
    trusting it.
    """

    id: str
    issue_type: IssueType
    severity: Severity
    title: str
    explanation: str
    evidence: list[str]
    memory_ids: list[str]
    suggested_action: str
    uncertainty: str | None = None


class HealthReport(BaseModel):
    """The result of one health check run."""

    generated_at: datetime
    analyzer: str
    total_memories: int
    projects: list[str]
    summary: dict[str, int]
    findings: list[HealthFinding]
    limitations: list[str]


# --- retrieval --------------------------------------------------------------


class RetrievalStrategy(str, Enum):
    """How memories are ranked.

    Named rather than implicit so every result states which method produced it.
    Comparing two methods is only meaningful if you know which one ran.
    """

    KEYWORD = "keyword"
    SEMANTIC = "semantic"


class RetrievalRequest(BaseModel):
    """A coding task to look memories up for."""

    query: str = Field(min_length=1, max_length=500)
    strategy: RetrievalStrategy = RetrievalStrategy.KEYWORD
    project: str | None = Field(
        default=None,
        max_length=100,
        description="Restrict the search to one namespace.",
    )
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class MatchedTerm(BaseModel):
    """Why one query term contributed to a memory's score."""

    term: str
    idf: float
    term_frequency: int
    contribution: float


class RetrievalMatch(BaseModel):
    memory: Memory
    method: str
    score: float
    matched_terms: list[MatchedTerm]
    explanation: str


class RetrievalResult(BaseModel):
    query: str
    strategy: str
    project: str | None
    considered: int
    returned: int
    matches: list[RetrievalMatch]
    unmatched_query_terms: list[str]
    notes: list[str]


# --- embeddings -------------------------------------------------------------


class IndexRequest(BaseModel):
    """Build vectors for the memories in scope."""

    project: str | None = Field(default=None, max_length=100)
    force: bool = Field(
        default=False,
        description="Re-embed everything, even memories whose vector is current.",
    )


class IndexResult(BaseModel):
    provider: str
    model: str
    dimensions: int
    captures_meaning: bool
    total: int
    indexed: int
    skipped: int
    failed: int
    errors: list[str]


class EmbeddingStatus(BaseModel):
    """What the current provider can do, and how much of the collection is indexed."""

    provider: str
    model: str
    dimensions: int
    captures_meaning: bool
    description: str
    total_memories: int
    indexed_memories: int
    stale_memories: int
