"""Claim-to-evidence entailment with an offline lexical fallback."""
from __future__ import annotations

import math
import os
import re
from functools import lru_cache
from typing import Any


STOPWORDS = {
    "what", "why", "how", "is", "the", "a", "an", "of", "to", "and", "for",
    "in", "on", "did", "do", "we", "should", "can", "could", "would", "likely",
    "next", "take", "action", "after", "this", "that", "with", "cause", "caused",
}


def terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_'-]+", text.lower())) - STOPWORDS


@lru_cache(maxsize=2)
def _nli_model(name: str):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(name)


def _lexical_checks(claims: list[str], passages: list[tuple[str, str]]) -> list[dict[str, Any]]:
    result = []
    for claim in claims:
        claim_terms = terms(claim)
        supporting = []
        best_score = 0.0
        for citation_id, text in passages:
            overlap = len(claim_terms & terms(text)) / max(1, len(claim_terms))
            if overlap >= 0.72:
                supporting.append(citation_id)
            best_score = max(best_score, overlap)
        result.append({
            "claim": claim, "supported": bool(supporting),
            "citation_ids": supporting, "score": round(best_score, 3),
        })
    return result


def check_claims(claims: list[str], passages: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], str, str | None]:
    if os.getenv("CLAIM_NLI_ENABLED", "false").lower() not in {"true", "1", "yes"}:
        return _lexical_checks(claims, passages), "lexical-overlap", None
    try:
        if os.getenv("MODEL_DOWNLOADS_ALLOWED", "false").lower() not in {"true", "1", "yes"}:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        model = _nli_model(os.getenv(
            "CLAIM_NLI_MODEL", "cross-encoder/nli-deberta-v3-base"
        ))
        labels = model.model.config.id2label
        label_index = next(
            int(index) for index, label in labels.items() if "entail" in str(label).lower()
        )
        pairs = [(text, claim) for claim in claims for _, text in passages]
        logits = model.predict(pairs, apply_softmax=True)
        result = []
        for claim_index, claim in enumerate(claims):
            citations = []
            best_score = 0.0
            for passage_index, (citation_id, _) in enumerate(passages):
                score = float(logits[claim_index * len(passages) + passage_index][label_index])
                if score >= float(os.getenv("CLAIM_NLI_THRESHOLD", "0.72")):
                    citations.append(citation_id)
                best_score = max(best_score, score)
            result.append({
                "claim": claim, "supported": bool(citations),
                "citation_ids": citations, "score": round(best_score, 3),
            })
        return result, "local-nli", None
    except (ImportError, OSError, RuntimeError, ValueError, StopIteration) as exc:
        return (
            _lexical_checks(claims, passages),
            "lexical-overlap",
            f"Local NLI unavailable ({type(exc).__name__}); lexical verifier used.",
        )
