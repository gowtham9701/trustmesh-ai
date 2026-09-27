"""Typed retrieval -> investigation -> verification workflow.

LangGraph is used when installed; the same node functions run sequentially
without it, so the local demo never needs network access or model credentials.
"""
from __future__ import annotations

import os
import re
from typing import Any, TypedDict

from .retrieval import Retriever, RetrievedDocument


class WorkflowState(TypedDict, total=False):
    question: str
    top_k: int
    documents: list[RetrievedDocument]
    finding: str
    claims: list[str]
    verification: dict[str, Any]
    retrieval_mode: str
    workflow_engine: str


def retrieval_node(state: WorkflowState, retriever: Retriever, tenant_id: str = "default") -> WorkflowState:
    state["documents"] = retriever.get_relevant_documents(
        state["question"], state.get("top_k", 6), tenant_id=tenant_id
    )
    state["retrieval_mode"] = retriever.mode
    return state


def investigation_node(state: WorkflowState) -> WorkflowState:
    docs = state.get("documents", [])
    stopwords = {
        "what", "why", "how", "is", "the", "a", "an", "of", "to", "and", "for",
        "in", "on", "did", "do", "we", "should", "can", "could", "would", "likely",
        "next", "take", "action", "after", "this", "that", "with", "cause", "caused",
    }
    query_terms = set(re.findall(r"[a-z0-9_'-]+", state["question"].lower())) - stopwords
    claims = []
    for document in docs:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", document.page_content):
            sentence = sentence.strip()
            sentence_terms = set(re.findall(r"[a-z0-9_'-]+", sentence.lower())) - stopwords
            if sentence_terms and len(sentence_terms & query_terms) >= min(2, len(query_terms)):
                claims.append(sentence)
    state["claims"] = list(dict.fromkeys(claims))[:5]
    state["finding"] = "Extracted answer claims from retrieved evidence." if claims else "No answer claims matched the retrieved evidence."
    return state


def verification_node(state: WorkflowState) -> WorkflowState:
    docs = state.get("documents", [])
    checks = []
    for claim in state.get("claims", []):
        claim_terms = set(re.findall(r"[a-z0-9_'-]+", claim.lower()))
        cited = []
        for document in docs:
            document_terms = set(re.findall(r"[a-z0-9_'-]+", document.page_content.lower()))
            if len(claim_terms & document_terms) / max(1, len(claim_terms)) >= 0.72:
                cited.append(str(document.metadata.get("chunk_id", "")))
        checks.append({"claim": claim, "supported": bool(cited), "citation_ids": cited})
    coverage = sum(bool(check["supported"]) for check in checks) / max(1, len(checks))
    count = len(docs)
    state["verification"] = {
        "status": "verified" if count >= 2 and coverage >= 0.8 else "insufficient_evidence",
        "evidence_count": count,
        "claims": checks,
        "citation_coverage": coverage,
    }
    return state


def _langgraph_runner(retriever: Retriever, tenant_id: str):
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return None
    graph = StateGraph(WorkflowState)
    graph.add_node("retrieval", lambda s: retrieval_node(s, retriever, tenant_id))
    graph.add_node("investigation", investigation_node)
    graph.add_node("verification", verification_node)
    graph.set_entry_point("retrieval")
    graph.add_edge("retrieval", "investigation")
    graph.add_edge("investigation", "verification")
    graph.add_edge("verification", END)
    return graph.compile()


def run_workflow(
    question: str, retriever: Retriever, top_k: int = 6, tenant_id: str = "default"
) -> WorkflowState:
    state: WorkflowState = {
        "question": question,
        "top_k": top_k,
        "workflow_engine": "local",
    }
    if os.getenv("LANGGRAPH_ENABLED", "true").lower() not in {"0", "false", "no"}:
        graph = _langgraph_runner(retriever, tenant_id)
        if graph is not None:
            result = graph.invoke(state)
            result["workflow_engine"] = "langgraph"
            return result
    state = retrieval_node(state, retriever, tenant_id)
    state = investigation_node(state)
    return verification_node(state)


def workflow_metadata() -> dict[str, Any]:
    try:
        import langgraph  # noqa: F401
        available = True
    except ImportError:
        available = False
    enabled = os.getenv("LANGGRAPH_ENABLED", "true").lower() not in {"0", "false", "no"}
    return {
        "nodes": ["retrieval", "investigation", "verification"],
        "langgraph_available": available,
        "langgraph_enabled": enabled,
        "engine": "langgraph" if available and enabled else "local-fallback",
    }
