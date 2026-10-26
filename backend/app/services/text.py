"""Deterministic text analysis helpers for the health checker.

Everything here is pure and deterministic: the same input always produces the
same output. That is a hard requirement — a memory tool whose findings change
between runs cannot be trusted or evaluated.

No model calls. A language model is not needed to notice that two memories say
the same thing, and a deterministic rule gives the user something they can
check by eye.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# --- normalisation ---------------------------------------------------------

_PUNCT_RE = re.compile(r"[^a-z0-9]+")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.+#/-]*")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Used for exact-duplicate detection: "PostgreSQL 15." and "postgresql 15"
    should be recognised as the same statement.
    """
    return " ".join(_PUNCT_RE.sub(" ", text.lower()).split())


# --- tokenisation ----------------------------------------------------------

#: Very common English words that carry no retrieval or comparison signal.
STOPWORDS = frozenset(
    """
    a an the and or but of for to in on at is are was were be been being with by
    as it its this that these those we our us you your they them their he she
    not no do does did have has had will would can could should must may might
    shall all any each every some such than then so if when while from into
    over under again more most other only own same too very just also there here
    what which who whom how why because after before during until against
    between through use uses used using run runs running make makes made take
    takes get gets via per at
    """.split()
)

#: Technology and product names. A token in this set is a "value": the specific
#: thing a memory is talking about, which is what two memories can disagree on.
TECH_LEXICON = frozenset(
    """
    postgres postgresql mysql mariadb sqlite mongodb redis memcached valkey
    kafka rabbitmq celery dramatiq sidekiq duckdb clickhouse elasticsearch
    cassandra dynamodb bigquery snowflake redshift cassandra neo4j
    docker kubernetes k8s helm terraform ansible jenkins github gitlab
    python java golang go rust ruby php typescript javascript node nodejs
    react vue angular svelte django flask fastapi rails spring
    nginx haproxy envoy grpc graphql rest oauth jwt saml ldap
    prometheus grafana datadog sentry openai anthropic
    aws gcp azure s3 lambda sqs sns
    mvc rpc websocket http https json xml yaml csv protobuf
    """.split()
)

#: Unreliable provenance: a source that cannot be checked against anything.
UNRELIABLE_SOURCES = frozenset(
    """
    assistant ai chat gpt llm model unknown n/a na none misc various tbd
    """.split()
)

#: Placeholder namespaces.
PLACEHOLDER_PROJECTS = frozenset(
    """
    unknown default untitled none n/a na misc global common shared temp todo
    """.split()
)

_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")

#: Text that tries to give the memory reader instructions. Memories are
#: untrusted data: a stored memory must never be able to act as a command.
INJECTION_PATTERNS = (
    r"ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules|prompts)",
    r"disregard (?:all |any )?(?:previous|prior|above)",
    r"forget (?:all |everything |your )",
    r"you are now ",
    r"system prompt",
    r"reveal (?:your |the )?(?:prompt|instructions|api key|secret)",
    r"execute (?:the following|this) (?:command|code|script)",
    r"</?(?:system|assistant|user)>",
)


def tokens(text: str) -> list[str]:
    """Meaningful lowercase tokens, in order, without stopwords."""
    result: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip(".-/")
        if not token or token in STOPWORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        result.append(token)
    return result


def token_set(text: str) -> set[str]:
    return set(tokens(text))


def is_value_token(token: str) -> bool:
    """True when the token names a specific thing (a product, a version, a time).

    These are the tokens two memories can legitimately disagree about.
    """
    if token in TECH_LEXICON:
        return True
    return bool(_VERSION_RE.match(token) or _TIME_RE.match(token))


def is_strong_value(token: str) -> bool:
    """A value that is specific enough to signal a real disagreement.

    Bare years are excluded: "migrated in 2025" states *when*, not *what*, so a
    year difference alone is not a contradiction.
    """
    if token in TECH_LEXICON:
        return True
    if _YEAR_RE.match(token):
        return False
    return bool(_VERSION_RE.match(token) or _TIME_RE.match(token))


def value_tokens(text: str) -> set[str]:
    return {token for token in token_set(text) if is_value_token(token)}


def context_tokens(text: str) -> set[str]:
    """Tokens describing *what* the memory is about, ignoring the values.

    Two memories that share a context but disagree on a value are candidates
    for a contradiction. Two memories that share nothing are simply unrelated.
    """
    return {token for token in token_set(text) if not is_value_token(token)}


def dice_coefficient(left: set[str], right: set[str]) -> float:
    """2 * |A ∩ B| / (|A| + |B|). 0.0 when either set is empty."""
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


def overlap_coefficient(left: set[str], right: set[str]) -> float:
    """|A ∩ B| / min(|A|, |B|).

    More forgiving than Jaccard when one memory is much longer than the other.
    A short memory that says "the user service uses PostgreSQL" is still about
    the user service even if the other memory adds three clauses of context.
    """
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def similarity(left: str, right: str) -> float:
    """Combined similarity in [0, 1].

    Two independent views, because they fail in different ways:

    * ``SequenceMatcher`` on normalised text catches rewording that preserves
      character structure ("disabled Redis" vs "Redis was disabled").
    * ``Dice`` on content tokens catches rewording that does not, while
      ignoring filler words.

    The stronger of the two is used, so a pair is not missed because the other
    measure happened to score low.
    """
    normalised_left = normalize_text(left)
    normalised_right = normalize_text(right)
    sequence = SequenceMatcher(None, normalised_left, normalised_right).ratio()
    dice = dice_coefficient(token_set(left), token_set(right))
    return max(sequence, dice)


def contains_instruction_like_text(text: str) -> bool:
    """True when the memory looks like it is trying to give instructions.

    A memory is data about a project. If its content reads like a command, it
    either was captured badly or is a prompt-injection attempt. Either way it
    deserves a human look.
    """
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in INJECTION_PATTERNS)
