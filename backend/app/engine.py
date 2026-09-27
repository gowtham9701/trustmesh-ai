from __future__ import annotations

import re
import os
import uuid
from typing import Any

from .ai_workflow import run_workflow
from .claim_verification import check_claims
from .models import AgentOpinion, Citation, InvestigationRequest, InvestigationResponse, Verification
from .retrieval import StoreRetriever
from .store import Chunk, Store


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_'-]+", text.lower())) - STOPWORDS


STOPWORDS = {
    "what", "why", "how", "is", "the", "a", "an", "of", "to", "and", "for",
    "in", "on", "did", "do", "we", "should", "can", "could", "would", "likely",
    "next", "take", "action", "after", "this", "that", "with", "cause", "caused",
}


class InvestigationEngine:
    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def citation(chunk: Chunk, score: float) -> Citation:
        return Citation(
            document_id=chunk.document_id,
            filename=chunk.filename,
            chunk_id=chunk.chunk_id,
            quote=chunk.text[:500],
            score=score,
        )

    def _verify_claims(self, claims: list[str], hits: list[tuple[Chunk, float]]) -> dict[str, Any]:
        checks, verifier, verifier_fallback = check_claims(
            claims, [(chunk.chunk_id, chunk.text) for chunk, _ in hits]
        )
        supported = [check["claim"] for check in checks if check["supported"]]
        unsupported = [check["claim"] for check in checks if not check["supported"]]
        # Flag clear polarity conflicts where both statements share most of their content.
        contradiction_count = 0
        for index, left in enumerate(claims):
            for right in claims[index + 1:]:
                left_terms, right_terms = _terms(left), _terms(right)
                shared = len(left_terms & right_terms) / max(1, min(len(left_terms), len(right_terms)))
                opposite_polarity = (bool(re.search(r"\b(no|not|never|without)\b", left, re.I))
                                     != bool(re.search(r"\b(no|not|never|without)\b", right, re.I)))
                if shared >= 0.7 and opposite_polarity:
                    contradiction_count += 1
        coverage = len(supported) / max(1, len(checks))
        return {
            "checks": checks,
            "supported": supported,
            "unsupported": unsupported,
            "citation_coverage": round(coverage, 3),
            "contradiction_count": contradiction_count,
            "verifier": verifier,
            "verifier_fallback": verifier_fallback,
        }

    def investigate(
        self,
        req: InvestigationRequest,
        tenant_id: str = "default",
        retrieval_mode: str | None = None,
        actor: str = "system",
    ) -> InvestigationResponse:
        retriever = StoreRetriever(self.store, mode=retrieval_mode)
        workflow = run_workflow(req.question, retriever, req.top_k, tenant_id=tenant_id)
        hits: list[tuple[Chunk, float]] = [
            (doc.metadata["_chunk"], float(doc.metadata["score"]))
            for doc in workflow.get("documents", [])
        ]
        evidence = [self.citation(chunk, score) for chunk, score in hits]
        avg = sum(score for _, score in hits) / len(hits) if hits else 0
        enough = len(hits) >= 2 or (len(hits) == 1 and hits[0][1] >= 0.8)
        claims = workflow.get("claims", [])
        if enough and os.getenv("LLM_PROVIDER", "mock/local").lower() == "ollama":
            from .providers import get_provider
            claims = get_provider().propose_claims(
                req.question, [chunk.text[:1500] for chunk, _ in hits[:4]]
            )
        checks = self._verify_claims(claims, hits)
        enough = enough and bool(claims) and checks["citation_coverage"] >= 0.8

        retrieval = AgentOpinion(
            agent="retrieval",
            conclusion=f"Retrieved {len(hits)} relevant evidence chunk(s) using {retriever.mode} retrieval.",
            confidence=min(1, avg / 2),
            citations=evidence,
            rationale=f"Workflow engine: {workflow.get('workflow_engine', 'local')}.",
        )
        opinions = [retrieval]
        if not enough:
            opinions.append(AgentOpinion(
                agent="investigator", conclusion="There is not enough verifiable evidence to answer safely.",
                confidence=0.9, citations=evidence, rationale="Evidence and citation-coverage thresholds were not met.",
            ))
            verification = Verification(
                status="insufficient_evidence",
                explanation="The retrieved passages do not support enough specific answer claims.",
                unsupported_claims=[req.question],
                claims=checks["checks"],
                citation_coverage=checks["citation_coverage"],
                contradiction_count=checks["contradiction_count"],
                verifier=checks["verifier"],
                verifier_fallback=checks["verifier_fallback"],
            )
            answer = (
                "Insufficient evidence: I cannot make a reliable claim from the indexed documents. "
                "Add an incident timeline, logs, or runbook evidence and try again."
            )
            actions = ["Upload relevant incident notes or runbook material.",
                       "Validate the question and time window with an operator."]
            deadlock = False
        else:
            opinions.extend([
                AgentOpinion(
                    agent="investigator",
                    conclusion=f"Extracted {len(claims)} answer claim(s), each checked against retrieved evidence.",
                    confidence=checks["citation_coverage"], citations=evidence[:3],
                    rationale="Structured claims are checked against retrieved citations before returning.",
                ),
                AgentOpinion(
                    agent="causal",
                    conclusion="Evidence can show a contributing factor; it does not alone prove causation.",
                    confidence=0.55, citations=evidence[:2],
                    rationale="Causal language remains qualified pending controlled validation.",
                ),
                AgentOpinion(
                    agent="policy",
                    conclusion="Recommendations are advisory; production changes require human approval.",
                    confidence=0.95, citations=evidence[:1],
                    rationale="The system has no remediation execution capability.",
                ),
            ])
            deadlock = checks["contradiction_count"] > 0
            verification = Verification(
                status="disputed" if deadlock else (
                    "verified" if checks["citation_coverage"] == 1 else "partially_verified"
                ),
                explanation=(
                    "Conflicting claims were detected in the evidence."
                    if deadlock else
                    f"Claim-level citation coverage is {checks['citation_coverage']:.0%}; "
                    "causal language remains qualified."
                ),
                supported_claims=checks["supported"],
                unsupported_claims=checks["unsupported"],
                claims=checks["checks"],
                citation_coverage=checks["citation_coverage"],
                contradiction_count=checks["contradiction_count"],
                verifier=checks["verifier"],
                verifier_fallback=checks["verifier_fallback"],
            )
            answer = (
                "Evidence is disputed. Review the cited contradictory passages before acting."
                if deadlock else "Evidence-backed findings:\n\n" + "\n\n".join(f"- {claim}" for claim in claims)
            )
            actions = [
                "Review each citation against the source system.",
                "Have the service owner confirm impact and timeline.",
                "Do not execute remediation automatically; record an approved change first.",
            ]
        confidence = 0 if not enough else round(min(1, 0.45 + avg * 0.12) * checks["citation_coverage"], 2)
        result = InvestigationResponse(
            investigation_id=uuid.uuid4().hex[:12],
            question=req.question,
            answer=answer,
            confidence=confidence,
            evidence=evidence,
            agent_opinions=opinions,
            verification=verification,
            recommended_actions=actions,
            insufficient_evidence=not enough,
            deadlock=deadlock,
            retrieval_mode=retriever.mode,
            workflow_engine=workflow.get("workflow_engine", "local"),
            reranker=retriever.reranker,
        )
        payload = result.model_dump()
        payload["tenant_id"] = tenant_id
        self.store.save_investigation(payload, tenant_id, actor)
        from .tracing import get_tracer
        tracer = get_tracer()
        tracer.trace(
            "investigation.completed",
            {
                "investigation_id": result.investigation_id,
                "tenant_id": tenant_id,
                "retrieval_mode": retriever.mode,
                "verification": result.verification.status,
                "evidence_count": len(evidence),
            },
        )
        tracer.close()
        return result
