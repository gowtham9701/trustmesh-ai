from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, PlainTextResponse

from .ai_workflow import workflow_metadata
from .engine import InvestigationEngine
from .models import (
    ApprovalDecision,
    ApprovalRequest,
    DocumentOut,
    FeedbackRequest,
    InvestigationRequest,
    InvestigationResponse,
)
from .providers import ProviderError
from .retrieval import StoreRetriever, retrieval_metadata
from .security import Principal, authentication_required, current_principal, require_role
from .store import Store
from .tracing import tracing_metadata

class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("action", "tenant_id", "subject", "resource_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"))


handler = logging.StreamHandler()
handler.setFormatter(JsonLogFormatter())
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), handlers=[handler])
logger = logging.getLogger("trustmesh.api")
store = Store(os.getenv("DATA_DIR", "data"))
engine = InvestigationEngine(store)
app = FastAPI(
    title="TrustMesh AI",
    version="0.2.0",
    description="Local-first, evidence-grounded incident investigation.",
    docs_url=None if os.getenv("APP_ENV", "development").lower() == "production" else "/docs",
    redoc_url=None if os.getenv("APP_ENV", "development").lower() == "production" else "/redoc",
    openapi_url=None if os.getenv("APP_ENV", "development").lower() == "production" else "/openapi.json",
)


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError):
    logger.error("local_model_unavailable", extra={"action": "model.generate"})
    return JSONResponse(status_code=503, content={"detail": str(exc)})
origins = [origin.strip() for origin in os.getenv(
    "CORS_ALLOWED_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"
).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_rate_lock = Lock()
_request_times: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def protect_request_rate(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    client_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
    with _rate_lock:
        timestamps = _request_times[client_key]
        while timestamps and now - timestamps[0] > 60:
            timestamps.popleft()
        if len(timestamps) >= limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded; retry in a minute."},
                headers={"Retry-After": "60"},
            )
        timestamps.append(now)
        if len(_request_times) > 5000:
            for key, values in list(_request_times.items()):
                while values and now - values[0] > 60:
                    values.popleft()
                if not values and key != client_key:
                    _request_times.pop(key, None)
    return await call_next(request)


def audit_log(action: str, principal: Principal, resource_id: str = "") -> None:
    logger.info(
        "trustmesh_action",
        extra={
            "action": action,
            "tenant_id": principal.tenant_id,
            "subject": principal.subject,
            "resource_id": resource_id,
        },
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "trustmesh-api",
        "retrieval": retrieval_metadata(store)["mode"],
        "llm_provider": os.getenv("LLM_PROVIDER", "mock/local"),
        "auth_required": authentication_required(),
    }


@app.get("/api/v1/ai/metadata")
def ai_metadata(_: Principal = Depends(current_principal)):
    return {
        "workflow": workflow_metadata(),
        "retrieval": retrieval_metadata(store),
        "tracing": tracing_metadata(),
        "claim_verification": {
            "mode": "local-nli" if os.getenv("CLAIM_NLI_ENABLED", "false").lower()
            in {"true", "1", "yes"} else "lexical-overlap",
            "model": os.getenv("CLAIM_NLI_MODEL") if os.getenv("CLAIM_NLI_ENABLED", "false").lower()
            in {"true", "1", "yes"} else None,
        },
    }


@app.post("/api/v1/ingest", response_model=DocumentOut)
async def ingest(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_role("analyst")),
):
    max_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(413, "Document exceeds upload size limit")
    try:
        doc = store.ingest_bytes(
            file.filename or "document.txt",
            content,
            file.content_type or "",
            tenant_id=principal.tenant_id,
            actor=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit_log("document.ingest", principal, doc["id"])
    return doc


@app.get("/api/v1/documents", response_model=list[DocumentOut])
def documents(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(current_principal),
):
    return store.list_documents(principal.tenant_id, limit, offset)


@app.post("/api/v1/investigate", response_model=InvestigationResponse)
def investigate(
    req: InvestigationRequest,
    principal: Principal = Depends(current_principal),
):
    result = engine.investigate(
        req, tenant_id=principal.tenant_id, actor=principal.subject
    )
    audit_log("investigation.run", principal, result.investigation_id)
    return result


@app.post("/api/v1/feedback")
def feedback(
    req: FeedbackRequest,
    principal: Principal = Depends(current_principal),
):
    investigation = store.get_investigation(req.investigation_id, principal.tenant_id)
    if not investigation:
        raise HTTPException(404, "Investigation not found")
    entry = req.model_dump()
    entry["retrieval_mode"] = investigation.get("retrieval_mode", "deterministic")
    entry["actor"] = principal.subject
    store.add_feedback(entry, principal.tenant_id)
    audit_log("feedback.submit", principal, req.investigation_id)
    return {"status": "recorded", "feedback": req.model_dump()}


@app.get("/api/v1/feedback/metrics")
def feedback_metrics(principal: Principal = Depends(require_role("analyst"))):
    return store.feedback_metrics(principal.tenant_id)


@app.post("/api/v1/approvals")
def request_approval(
    req: ApprovalRequest,
    principal: Principal = Depends(require_role("analyst")),
):
    investigation = store.get_investigation(req.investigation_id, principal.tenant_id)
    if not investigation:
        raise HTTPException(404, "Investigation not found")
    approval = store.create_approval(
        req.investigation_id, principal.tenant_id, req.action, req.rationale, principal.subject
    )
    audit_log("approval.request", principal, approval["id"])
    return approval


@app.get("/api/v1/approvals")
def list_approvals(principal: Principal = Depends(current_principal)):
    return {"items": store.list_approvals(principal.tenant_id)}


@app.post("/api/v1/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    principal: Principal = Depends(require_role("admin")),
):
    approval = store.decide_approval(
        approval_id, principal.tenant_id, decision.decision, decision.comment, principal.subject
    )
    if approval is None:
        raise HTTPException(409, "Approval request not found or already decided")
    audit_log(f"approval.{decision.decision}", principal, approval_id)
    return approval


@app.get("/api/v1/audit")
def audit_events(
    limit: int = 100,
    principal: Principal = Depends(require_role("admin")),
):
    if not 1 <= limit <= 500:
        raise HTTPException(400, "limit must be between 1 and 500")
    return {"events": store.audit_events(principal.tenant_id, limit)}


@app.post("/api/v1/evaluation/run")
def run_evaluation(principal: Principal = Depends(require_role("admin"))):
    path = Path(os.getenv("EVALUATION_DATASET", "data/evaluation_cases.json"))
    if not path.exists():
        raise HTTPException(503, "Evaluation dataset is not configured")
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("evaluation_dataset_unavailable")
        raise HTTPException(500, "Could not load evaluation dataset") from exc
    results = []
    for case in cases:
        response = engine.investigate(
            InvestigationRequest(question=case["question"], top_k=case.get("top_k", 6)),
            tenant_id=principal.tenant_id,
            actor=principal.subject,
        )
        expected = case["expected"]
        passed = (
            response.insufficient_evidence == (expected == "insufficient_evidence")
            and (expected != "verified" or response.verification.status == "verified")
        )
        results.append({
            "case_id": case["id"],
            "expected": expected,
            "actual": response.verification.status,
            "passed": passed,
            "confidence": response.confidence,
        })
    report = {
        "cases": len(results),
        "passed": sum(1 for result in results if result["passed"]),
        "accuracy": round(sum(1 for result in results if result["passed"]) / max(1, len(results)), 3),
        "results": results,
    }
    store.save_evaluation(report, principal.tenant_id, principal.subject)
    audit_log("evaluation.run", principal)
    return report


@app.post("/api/v1/evaluation/compare-retrieval")
def compare_retrieval(principal: Principal = Depends(require_role("admin"))):
    path = Path(os.getenv("EVALUATION_DATASET", "data/evaluation_cases.json"))
    if not path.exists():
        raise HTTPException(503, "Evaluation dataset is not configured")
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("evaluation_dataset_unavailable")
        raise HTTPException(500, "Could not load evaluation dataset") from exc
    reports = {}
    modes = ["deterministic", "semantic"]
    semantic_available = retrieval_metadata(store)["semantic_available"]
    if not semantic_available:
        modes = ["deterministic"]
    for mode in modes:
        retriever = StoreRetriever(store, mode=mode)
        case_results = []
        for case in cases:
            hits = retriever.get_relevant_documents(
                case["question"], case.get("top_k", 5), tenant_id=principal.tenant_id
            )
            expected_terms = set(term.lower() for term in case.get("expected_terms", []))
            relevant = []
            for hit in hits:
                words = set(re.findall(r"[a-z0-9_-]+", hit.page_content.lower()))
                if expected_terms and len(expected_terms & words) >= min(2, len(expected_terms)):
                    relevant.append(hit)
            case_results.append({
                "case_id": case["id"],
                "expected": case["expected"],
                "retrieved": len(hits),
                "relevant": len(relevant),
                "recall_at_k": round(len(relevant) / max(1, case.get("relevant_chunks", 1)), 3),
            })
        reports[mode] = {
            "cases": len(case_results),
            "mean_recall_at_k": round(
                sum(item["recall_at_k"] for item in case_results) / max(1, len(case_results)), 3
            ),
            "results": case_results,
        }
    report = {
        "retrieval_comparison": reports,
        "semantic_available": semantic_available,
        "note": "Replay on the current tenant's indexed documents; results are not a production quality guarantee.",
    }
    store.save_evaluation(report, principal.tenant_id, principal.subject)
    return report


@app.get("/api/v1/evaluation/latest")
def latest_evaluation(principal: Principal = Depends(require_role("analyst"))):
    report = store.latest_evaluation(principal.tenant_id)
    if report is None:
        raise HTTPException(404, "No evaluation has been run")
    return report


@app.get("/metrics")
def metrics(principal: Principal = Depends(require_role("admin"))):
    document_count = store.document_count(principal.tenant_id)
    feedback = store.feedback_metrics(principal.tenant_id)
    lines = [
        "# HELP trustmesh_documents Indexed document versions",
        "# TYPE trustmesh_documents gauge",
        f"trustmesh_documents {document_count}",
        "# HELP trustmesh_feedback_submissions Stored feedback records",
        "# TYPE trustmesh_feedback_submissions counter",
        f"trustmesh_feedback_submissions {feedback['feedback_count']}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/api/v1/feedback", include_in_schema=False)
def feedback_list(principal: Principal = Depends(current_principal)):
    return store.list_feedback(principal.tenant_id)
