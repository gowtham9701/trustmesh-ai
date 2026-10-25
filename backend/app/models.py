from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

class Citation(BaseModel):
    document_id: str
    filename: str
    chunk_id: str
    quote: str
    score: float = Field(ge=0)

class AgentOpinion(BaseModel):
    agent: str
    conclusion: str
    confidence: float = Field(ge=0, le=1)
    citations: list[Citation] = []
    rationale: str

class ClaimCheck(BaseModel):
    claim: str
    supported: bool
    citation_ids: list[str] = []
    score: float = Field(ge=0, le=1)

class Verification(BaseModel):
    status: Literal['verified', 'partially_verified', 'insufficient_evidence', 'disputed']
    explanation: str
    supported_claims: list[str] = []
    unsupported_claims: list[str] = []
    claims: list[ClaimCheck] = []
    citation_coverage: float = Field(default=0, ge=0, le=1)
    contradiction_count: int = Field(default=0, ge=0)
    verifier: str = "lexical-overlap"
    verifier_fallback: Optional[str] = None

class InvestigationRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=6, ge=1, le=20)

class InvestigationResponse(BaseModel):
    investigation_id: str
    question: str
    answer: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[Citation]
    agent_opinions: list[AgentOpinion]
    verification: Verification
    recommended_actions: list[str]
    insufficient_evidence: bool
    deadlock: bool
    retrieval_mode: str = "deterministic"
    workflow_engine: str = "local"
    reranker: str = "disabled"

class FeedbackRequest(BaseModel):
    investigation_id: str
    rating: Literal['helpful', 'not_helpful', 'mixed']
    comment: str = Field(default='', max_length=2000)

class ApprovalRequest(BaseModel):
    investigation_id: str
    action: str = Field(min_length=5, max_length=1000)
    rationale: str = Field(min_length=5, max_length=2000)

class ApprovalDecision(BaseModel):
    decision: Literal['approved', 'rejected']
    comment: str = Field(default='', max_length=1000)

class DocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    chunks: int
    characters: int
    version: int = 1

class SuggestedQuestion(BaseModel):
    question: str
    source_document_id: str
    source_filename: str
    source_chunk_id: str
    signals: list[str] = []
    score: float = Field(ge=0)

class SuggestedQuestionsOut(BaseModel):
    items: list[SuggestedQuestion]
    documents: int
    note: str
