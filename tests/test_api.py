from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.engine import InvestigationEngine
from backend.app.store import Store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("TRUSTMESH_API_KEYS", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    store = Store(tmp_path / "data", database_path=tmp_path / "trustmesh.sqlite3")
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "engine", InvestigationEngine(store))
    return TestClient(main.app), store


def test_health_and_ai_metadata(workspace):
    client, _ = workspace
    assert client.get("/health").json()["status"] == "ok"
    metadata = client.get("/api/v1/ai/metadata").json()
    assert metadata["workflow"]["nodes"] == ["retrieval", "investigation", "verification"]
    assert metadata["tracing"]["enabled"] is False


def test_persistence_versions_tenant_isolation_and_claim_support(workspace, tmp_path):
    client, store = workspace
    content = (
        b"Incident INC-1 affected payments-api after release 8.1.\n\n"
        b"Database connection pool exhausted and latency reached 900ms.\n\n"
        b"Rollback restored baseline within five minutes."
    )
    first = store.ingest_bytes("incident.md", content, tenant_id="team-a")
    second = store.ingest_bytes("incident.md", content + b"\n\nUpdated owner: payments.", tenant_id="team-a")
    assert first["version"] == 1
    assert second["version"] == 2

    restarted = Store(tmp_path / "data", database_path=tmp_path / "trustmesh.sqlite3")
    assert len(restarted.list_documents("team-a")) == 2
    assert restarted.list_documents("team-b") == []

    # The isolated HTTP app is in the local default tenant; use store/engine to verify team scoping.
    from backend.app.models import InvestigationRequest
    result = InvestigationEngine(restarted).investigate(
        InvestigationRequest(question="What caused payments-api database pool latency after release 8.1?"),
        tenant_id="team-a",
    )
    assert result.evidence
    assert result.verification.citation_coverage > 0
    assert result.verification.claims


def test_insufficient_evidence_and_validation(workspace):
    client, _ = workspace
    unsupported = client.post(
        "/api/v1/investigate", json={"question": "What is the lunar weather forecast?"}
    )
    assert unsupported.status_code == 200
    assert unsupported.json()["verification"]["status"] == "insufficient_evidence"
    assert unsupported.json()["confidence"] == 0
    assert client.post(
        "/api/v1/ingest", files={"file": ("bad.csv", b"x,y", "text/csv")}
    ).status_code == 400


def test_feedback_evaluation_approval_and_audit(workspace, tmp_path, monkeypatch):
    client, store = workspace
    store.ingest_bytes(
        "incident.md",
        b"payments-api database connection pool exhausted after deployment and rollback fixed it",
    )
    result = client.post(
        "/api/v1/investigate",
        json={"question": "What happened to payments-api database connection pool?"},
    ).json()
    assert client.post("/api/v1/feedback", json={
        "investigation_id": result["investigation_id"], "rating": "helpful", "comment": "Citations were useful"
    }).status_code == 200
    assert client.get("/api/v1/feedback/metrics").json()["feedback_count"] == 1

    requested = client.post("/api/v1/approvals", json={
        "investigation_id": result["investigation_id"],
        "action": "Rollback payments-api release 8.1",
        "rationale": "Latency recovered after rollback in the cited incident.",
    })
    assert requested.status_code == 200
    approval = requested.json()
    assert approval["status"] == "pending"
    decision = client.post(f"/api/v1/approvals/{approval['id']}/decision", json={
        "decision": "approved", "comment": "Approved by the service owner."
    })
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    assert len(client.get("/api/v1/audit").json()["events"]) >= 3

    dataset = tmp_path / "evaluation_cases.json"
    dataset.write_text(json.dumps([{
        "id": "unsupported",
        "question": "What is the lunar weather forecast?",
        "expected": "insufficient_evidence",
        "top_k": 4,
    }]))
    monkeypatch.setenv("EVALUATION_DATASET", str(dataset))
    report = client.post("/api/v1/evaluation/run")
    assert report.status_code == 200
    assert report.json()["accuracy"] == 1
    assert client.get("/api/v1/evaluation/latest").status_code == 200


def test_retrieval_comparison_report(workspace, tmp_path, monkeypatch):
    client, store = workspace
    store.ingest_bytes("incident.md", b"orders-api database pool exhausted after release 8.1.")
    dataset = tmp_path / "retrieval-cases.json"
    dataset.write_text(json.dumps([{
        "id": "db-pool",
        "question": "What happened to orders-api database pool?",
        "expected": "verified",
        "expected_terms": ["orders-api", "database", "pool"],
        "relevant_chunks": 1,
        "top_k": 3,
    }]))
    monkeypatch.setenv("EVALUATION_DATASET", str(dataset))
    response = client.post("/api/v1/evaluation/compare-retrieval")
    assert response.status_code == 200
    report = response.json()
    assert "deterministic" in report["retrieval_comparison"]
    assert report["retrieval_comparison"]["deterministic"]["mean_recall_at_k"] == 1
    assert client.get("/api/v1/evaluation/latest").status_code == 200


def test_api_key_roles_and_upload_limit(workspace, monkeypatch):
    client, _ = workspace
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTMESH_API_KEYS", json.dumps([
        {"token": "viewer-token", "tenant_id": "tenant-a", "role": "viewer"},
        {"token": "admin-token", "tenant_id": "tenant-b", "role": "admin"},
    ]))
    assert client.get("/api/v1/documents").status_code == 401
    viewer = {"Authorization": "Bearer viewer-token"}
    assert client.get("/api/v1/documents", headers=viewer).status_code == 200
    assert client.post(
        "/api/v1/ingest",
        files={"file": ("private.md", b"private tenant evidence", "text/markdown")},
        headers=viewer,
    ).status_code == 403
    admin = {"Authorization": "Bearer admin-token"}
    response = client.post(
        "/api/v1/ingest",
        files={"file": ("private.md", b"tenant b only", "text/markdown")},
        headers=admin,
    )
    assert response.status_code == 200
    assert [doc["filename"] for doc in client.get("/api/v1/documents", headers=admin).json()] == ["private.md"]
    assert client.get("/api/v1/documents", headers=viewer).json() == []
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "4")
    assert client.post(
        "/api/v1/ingest",
        files={"file": ("big.md", b"12345", "text/markdown")},
        headers=admin,
    ).status_code == 413


def test_rate_limit(workspace, monkeypatch):
    client, _ = workspace
    monkeypatch.setattr(main, "_request_times", __import__("collections").defaultdict(__import__("collections").deque))
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    assert client.get("/api/v1/documents").status_code == 200
    limited = client.get("/api/v1/documents")
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_encryption_at_rest_when_configured(tmp_path, monkeypatch):
    cryptography = pytest.importorskip("cryptography.fernet")
    key = cryptography.Fernet.generate_key().decode()
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", key)
    db_path = tmp_path / "encrypted.sqlite3"
    store = Store(tmp_path / "encrypted-data", database_path=db_path)
    store.ingest_bytes("private.md", b"secret incident detail")
    store.save_investigation({
        "investigation_id": "private-investigation",
        "question": "secret question",
        "answer": "secret finding",
        "tenant_id": "default",
        "retrieval_mode": "deterministic",
    })
    store.add_feedback({
        "investigation_id": "private-investigation",
        "rating": "helpful",
        "comment": "secret feedback",
        "retrieval_mode": "deterministic",
    })
    approval = store.create_approval(
        "private-investigation", "default", "secret action", "secret rationale", "operator"
    )
    store.decide_approval(approval["id"], "default", "rejected", "secret decision", "reviewer")
    store.save_evaluation({"report": "secret evaluation"})
    import sqlite3
    with sqlite3.connect(db_path) as connection:
        protected_values = [
            row[0] for row in connection.execute("SELECT text FROM chunks")
        ] + [
            row[0] for row in connection.execute("SELECT payload FROM investigations")
        ] + [
            row[0] for row in connection.execute("SELECT comment FROM feedback")
        ] + [
            row[0] for row in connection.execute(
                "SELECT action || rationale || decision_comment FROM approvals"
            )
        ] + [
            row[0] for row in connection.execute("SELECT payload FROM evaluation_runs")
        ]
    assert all("secret" not in value for value in protected_values)
    reopened = Store(tmp_path / "encrypted-data", database_path=db_path)
    assert reopened.get_chunks()[0].text == "secret incident detail"
    assert reopened.get_investigation("private-investigation", "default")["answer"] == "secret finding"
    assert reopened.list_feedback()["items"][0]["comment"] == "secret feedback"
    assert reopened.get_approval(approval["id"], "default")["decision_comment"] == "secret decision"
    assert reopened.latest_evaluation()["report"] == "secret evaluation"


def test_suggested_questions_endpoint(workspace, monkeypatch):
    client, store = workspace
    assert client.get("/api/v1/questions/suggested").json()["items"] == []

    store.ingest_bytes(
        "incident.md",
        b"Incident INC-2001 affected `orders-api` on 2026-09-20. "
        b"Rollback restored the baseline within five minutes.",
        tenant_id="default",
    )
    response = client.get("/api/v1/questions/suggested", params={"limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["documents"] == 1
    assert 0 < len(body["items"]) <= 3
    assert all(item["source_filename"] == "incident.md" for item in body["items"])
    assert client.get("/api/v1/questions/suggested", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/questions/suggested", params={"limit": 99}).status_code == 422
    assert client.get(
        "/api/v1/questions/suggested", params={"document_id": "missing"}
    ).json()["items"] == []

    suggested = body["items"][0]["question"]
    assert client.post(
        "/api/v1/investigate", json={"question": suggested}
    ).json()["verification"]["status"] != "insufficient_evidence"


def test_suggested_questions_do_not_leak_across_tenants(workspace, monkeypatch):
    client, store = workspace
    store.ingest_bytes(
        "secret.md", b"Incident INC-7007 affected `billing-api` on 2026-09-20.", tenant_id="team-a"
    )
    assert client.get("/api/v1/questions/suggested").json()["items"] == []

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTMESH_API_KEYS", json.dumps([
        {"token": "a-token", "tenant_id": "team-a", "role": "analyst"},
        {"token": "b-token", "tenant_id": "team-b", "role": "analyst"},
    ]))
    headers_a = {"Authorization": "Bearer a-token"}
    headers_b = {"Authorization": "Bearer b-token"}
    assert any(
        "billing-api" in item["question"]
        for item in client.get("/api/v1/questions/suggested", headers=headers_a).json()["items"]
    )
    assert client.get("/api/v1/questions/suggested", headers=headers_b).json()["items"] == []
