"""Investigation questions derived from the evidence a tenant has indexed.

Suggestions are built only from chunk text that is already stored, and every
entity a question names (service, incident, symptom) is copied from the source
chunk it is attributed to. A suggestion therefore proposes *what to ask*; it never
asserts a finding.

Each candidate is checked against the same term-overlap rule the workflow uses to
extract answer claims, so a suggested question is one the indexed evidence can
actually answer. Generation is deterministic and needs no model, so the default
offline profile behaves identically with or without the optional stack.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from .engine import STOPWORDS
from .store import Chunk

DEFAULT_LIMIT = 5
MAX_LIMIT = 10

INCIDENT_ID = re.compile(r"\b[A-Z][A-Z0-9]*-\d{2,}\b")
BACKTICKED = re.compile(r"`([^`]{2,40})`")
DASHED_TOKEN = re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b")
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
TERM = re.compile(r"[a-z0-9_'-]+")

SERVICE_SUFFIXES = (
    "-api", "-service", "-worker", "-gateway", "-queue", "-db", "-store",
    "-cache", "-job", "-cluster", "-node", "-proxy", "-shard", "-indexer",
)

# Ordered by specificity: only the first match in a sentence is used as its symptom.
SYMPTOM_PATTERNS = (
    ("connection pool exhaustion", r"connection[- ]pool"),
    ("cache hit rate collapse", r"cache hit rate"),
    ("5xx error rate", r"\b5xx\b"),
    ("error rate", r"\berror rate\b"),
    ("request latency", r"\blatency\b"),
    ("timeouts", r"\btimeouts?\b"),
    ("queue backlog", r"\bbacklog\b"),
    ("queue saturation", r"\bqueues?\b"),
    ("throughput drop", r"\bthroughput\b"),
    ("outage", r"\boutage\b"),
    ("saturation", r"\bsaturat"),
    ("resource exhaustion", r"\bexhaust"),
    ("availability loss", r"\bavailability\b"),
    ("memory pressure", r"\b(memory|oom)\b"),
    ("disk pressure", r"\bdisk\b"),
    ("cpu saturation", r"\bcpu\b"),
)

ACTION_PATTERN = (
    r"roll ?back|restart|remediat|runbook|escalat|next step|approv|patch|"
    r"increase the|add .*alert|rebalance|scale (?:up|out)"
)

SECURITY_PATTERNS = (
    ("credential exposure", r"\bcredentials?\b"),
    ("secret exposure", r"\bsecrets?\b"),
    ("token exposure", r"\btokens?\b"),
    ("data exposure", r"\bexposur"),
    ("unauthorized access", r"\bunauthori[sz]ed"),
    ("security breach", r"\bbreach"),
)

POLICY_PATTERN = r"\b(polic|requir|prohibit|forbidden|must not|do not|shall|approval|approved)\w*"
HYPOTHESIS_PATTERN = (
    r"\b(hypothes\w*|competing|contradict\w*|conflict\w*|root cause|"
    r"candidate cause|contribut\w*|alternative explanation)\b"
)

# Structural/field words are not useful as the subject of a question.
TOPIC_STOPWORDS = STOPWORDS | {
    "was", "were", "been", "being", "has", "had", "did", "does", "are", "not",
    "from", "by", "into", "during", "before", "while", "because", "than",
    "then", "there", "their", "its", "about", "also", "until", "upon",
    "over", "under", "such", "both", "each", "some", "any", "all", "one",
    "other", "another", "only", "still", "even", "much", "more", "most",
    "when", "where", "which", "who", "whom", "whose", "here", "now", "them",
    "they", "using", "used", "use", "via", "per", "via", "seen", "saw",
    "observed", "likely", "scenario", "incident", "service", "services",
    "timestamp", "severity", "symptom", "symptoms", "finding", "findings",
    "action", "actions", "impact", "mitigation", "notes", "summary", "status",
    "description", "details", "evidence", "value", "true", "false", "null",
    "recommended", "response", "reason", "result", "context", "example",
}


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_BOUNDARY.split(text) if part.strip()]


def _content_terms(text: str) -> set[str]:
    return set(TERM.findall(text.lower())) - STOPWORDS


def _answerable(question: str, text: str) -> bool:
    """Mirror the workflow's claim-extraction rule against this chunk's sentences.

    ``ai_workflow.investigation_node`` keeps a sentence as an answer claim only
    when it shares at least ``min(2, len(query_terms))`` terms with the question.
    A question that fails this here would return ``insufficient_evidence``.
    """
    query_terms = _content_terms(question)
    if not query_terms:
        return False
    needed = min(2, len(query_terms))
    return any(
        len(_content_terms(sentence) & query_terms) >= needed
        for sentence in _sentences(text)
    )


def _first_match(patterns: Sequence[tuple[str, str]], text: str) -> str | None:
    for label, pattern in patterns:
        if re.search(pattern, text, re.I):
            return label
    return None


def _matches(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def _entities(text: str) -> tuple[list[str], list[str]]:
    """Services and incident ids that appear verbatim in this text."""
    services: list[str] = []
    for candidate in list(BACKTICKED.findall(text)) + list(DASHED_TOKEN.findall(text)):
        value = candidate.strip("`").lower()
        if value.endswith(SERVICE_SUFFIXES) and value not in services:
            services.append(value)
    incidents: list[str] = []
    for value in INCIDENT_ID.findall(text):
        if value not in incidents:
            incidents.append(value)
    return services, incidents


def _sentence_topics(sentence: str, count: int) -> list[str]:
    """Usable subjects: real words, no field names, no metric values like `90ms`."""
    counts: dict[str, int] = {}
    for token in TERM.findall(sentence.lower()):
        if len(token) < 3 or token in TOPIC_STOPWORDS or any(c.isdigit() for c in token):
            continue
        if len(token) > 4 and token.endswith(("ed", "ing")):
            continue
        counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _ in ordered[:count]]


def _recurring_topics(text: str, count: int) -> list[str]:
    """Content words appearing in more than one sentence: the document's subjects."""
    frequency: dict[str, int] = {}
    for sentence in _sentences(text):
        for topic in _sentence_topics(sentence, 6):
            frequency[topic] = frequency.get(topic, 0) + 1
    ranked = sorted(
        ((topic, n) for topic, n in frequency.items() if n >= 2),
        key=lambda item: (-item[1], -len(item[0]), item[0]),
    )
    return [topic for topic, _ in ranked[:count]]


def _keyword_question(sentence: str, preferred: Sequence[str] = ()) -> str | None:
    """Ask about two topics from one sentence, preferring document-wide subjects."""
    topics = _sentence_topics(sentence, 6)
    ordered = [topic for topic in preferred if topic in topics]
    ordered += [topic for topic in topics if topic not in ordered]
    if len(ordered) >= 2:
        return f"What do the indexed documents say about {ordered[0]} and {ordered[1]}?"
    return None


def _focus_question(sentence: str, focus: str, preferred: Sequence[str] = ()) -> str | None:
    """Name a detected signal plus another term from the same sentence."""
    keywords = [word for word in focus.lower().split() if word not in STOPWORDS]
    topics = [topic for topic in _sentence_topics(sentence, 4) if topic not in keywords]
    if len(keywords) >= 2:
        return f"What do the indexed documents say about {keywords[0]} and {keywords[1]}?"
    if keywords and topics:
        extra = next((topic for topic in preferred if topic in topics), topics[0])
        return f"What do the indexed documents say about {keywords[0]} and {extra}?"
    if keywords:
        return f"What does the indexed evidence say about {keywords[0]}?"
    return None


def _chunk_questions(chunk: Chunk) -> list[tuple[str, list[str], float]]:
    text = chunk.text
    services, incidents = _entities(text)
    service = services[0] if services else None
    recurring = _recurring_topics(text, 12)
    candidates: list[tuple[str, list[str], float]] = []

    for incident in incidents[:2]:
        incident_sentence = next(
            (s for s in _sentences(text) if incident in s), ""
        )
        paired_service = service if service and service in incident_sentence else None
        if paired_service:
            candidates.append(
                (f"What happened during {incident} affecting {paired_service}?",
                 ["incident", "service"], 3.0)
            )
        else:
            local = [
                topic for topic in _sentence_topics(incident_sentence, 4)
                if topic != incident.lower()
            ]
            co_topic = local[0] if local else next(
                (t for t in recurring if t != incident.lower()), None
            )
            if co_topic:
                candidates.append(
                    (f"What happened during {incident}, and what does the evidence say "
                     f"about {co_topic}?", ["incident", "evidence"], 2.4)
                )
    if service:
        symptom = _first_match(SYMPTOM_PATTERNS, text)
        if symptom:
            candidates.append((f"What caused the {symptom} on {service}?", ["service", "symptom"], 2.6))
        candidates.append((f"What caused the incident on {service}?", ["service"], 2.0))
        if _matches(ACTION_PATTERN, text):
            candidates.append((f"What should we do next for {service}?", ["service", "action"], 2.2))
        if _matches(HYPOTHESIS_PATTERN, text):
            candidates.append(
                (f"Which hypothesis about {service} is supported by the evidence?",
                 ["service", "hypothesis"], 2.5)
            )
        if _matches(POLICY_PATTERN, text):
            candidates.append(
                (f"What must be approved before changing {service}?", ["service", "policy"], 2.1)
            )
    for other in services[1:3]:
        candidates.append((f"What happened to {other}?", ["service"], 1.4))

    keyword: list[tuple[str, list[str], float]] = []
    for sentence in _sentences(text):
        if not _entities(sentence)[0]:
            security = _first_match(SECURITY_PATTERNS, sentence)
            if security:
                question = _focus_question(sentence, security, recurring)
                if question:
                    candidates.append((question, ["security"], 2.3))
        if len(keyword) < 2 and len(_sentence_topics(sentence, 4)) >= 3:
            question = _keyword_question(sentence, recurring)
            if question:
                keyword.append((question, ["keywords"], 0.7))
    candidates.extend(keyword)
    if not candidates and len(recurring) >= 2:
        candidates.append(
            (f"What do the indexed documents say about {recurring[0]} and {recurring[1]}?",
             ["keywords"], 0.6)
        )
    return candidates


def _diversify(ranked: list[tuple[int, dict[str, object]]], limit: int) -> list[dict[str, object]]:
    """Prefer a spread of angles over the same template repeated per document.

    A corpus of similar incident files would otherwise fill the list with
    "What happened during INC-XXXX ..." variants, so cap how many suggestions
    share a question shape and how many name the same service, then backfill.
    """
    selected: list[dict[str, object]] = []
    chosen: set[str] = set()
    shapes: dict[tuple[str, ...], int] = {}
    services: dict[str, int] = {}
    for _, item in ranked:
        if len(selected) >= limit:
            break
        question = str(item["question"])
        shape = tuple(str(signal) for signal in item["signals"])  # type: ignore[union-attr]
        service = _entities(question)[0][0] if _entities(question)[0] else None
        if shapes.get(shape, 0) >= 2:
            continue
        if service and services.get(service, 0) >= 2:
            continue
        shapes[shape] = shapes.get(shape, 0) + 1
        if service:
            services[service] = services.get(service, 0) + 1
        chosen.add(question)
        selected.append(item)
    for _, item in ranked:
        if len(selected) >= limit:
            break
        if str(item["question"]) not in chosen:
            selected.append(item)
    return selected


def suggest_questions(
    chunks: Iterable[Chunk], limit: int = DEFAULT_LIMIT
) -> list[dict[str, object]]:
    """Rank questions the indexed evidence can actually answer.

    Candidates that cannot clear the workflow's claim-extraction threshold are
    dropped, and later document versions win over earlier ones for an identical
    question, so re-uploading a corrected incident file refreshes the
    suggestions instead of adding near-duplicates.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    best: dict[str, tuple[int, dict[str, object]]] = {}
    for chunk in chunks:
        for question, signals, score in _chunk_questions(chunk):
            if not _answerable(question, chunk.text):
                continue
            key = " ".join(question.lower().split())
            if key in best and best[key][0] >= chunk.version:
                continue
            best[key] = (chunk.version, {
                "question": question,
                "source_document_id": chunk.document_id,
                "source_filename": chunk.filename,
                "source_chunk_id": chunk.chunk_id,
                "signals": signals,
                "score": score,
            })
    ranked = sorted(
        best.values(),
        key=lambda entry: (
            -float(entry[1]["score"]),         # type: ignore[arg-type]
            str(entry[1]["source_filename"]),  # type: ignore[arg-type]
            str(entry[1]["source_chunk_id"]),  # type: ignore[arg-type]
            str(entry[1]["question"]),         # type: ignore[arg-type]
        ),
    )
    return _diversify(ranked, limit)
