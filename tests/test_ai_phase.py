from backend.app.ai_workflow import run_workflow
from backend.app.engine import InvestigationEngine
from backend.app.models import InvestigationRequest
from backend.app.question_suggestions import _answerable, suggest_questions
from backend.app.retrieval import StoreRetriever
from backend.app.store import Store
from backend.app.tracing import get_tracer
from backend.app.claim_verification import check_claims
from backend.app.providers import OllamaProvider
import io
import json
import re
from pathlib import Path


def test_accepted_file_types(tmp_path):
    store = Store(tmp_path)
    for name, content in (
        ("notes.md", b"# incident"),
        ("notes.txt", b"incident notes"),
        ("notes.json", b'{"incident": "INC-1"}'),
    ):
        result = store.ingest_bytes(name, content)
        assert result["filename"] == name
    try:
        store.ingest_bytes("notes.csv", b"a,b")
    except ValueError as exc:
        assert "Only .md, .txt, and .json" in str(exc)
    else:
        raise AssertionError("unsupported file type was accepted")


def test_workflow_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGGRAPH_ENABLED", "false")
    store = Store(tmp_path)
    store.ingest_bytes("incident.md", b"database pool exhausted")
    state = run_workflow("database pool", StoreRetriever(store), top_k=1)
    assert state["workflow_engine"] == "local"
    assert [state["verification"]["status"], state["retrieval_mode"]] == [
        "insufficient_evidence",
        "deterministic",
    ]


def test_tracing_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TRACING_PROVIDER", raising=False)
    tracer = get_tracer()
    assert tracer.enabled is False
    assert tracer.name == "disabled"


def test_adversarial_claims_are_not_supported():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "adversarial_claims.json").read_text()
    )
    checks, verifier, fallback = check_claims(
        [fixture["supported_claim"], fixture["unsupported_claim"]],
        [("chunk-1", fixture["evidence"])],
    )
    assert checks[0]["supported"] is True
    assert checks[1]["supported"] is False
    assert verifier == "lexical-overlap"
    assert fallback is None


def test_local_ollama_provider_parses_structured_claims(monkeypatch):
    import backend.app.providers as providers

    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "2")
    monkeypatch.setattr(
        providers,
        "urlopen",
        lambda request, timeout: io.BytesIO(
            json.dumps({"message": {"content": '{"claims":["The pool saturated."]}'}}).encode()
        ),
    )
    claims = OllamaProvider("test-model", "http://127.0.0.1:11434").propose_claims(
        "What happened?", ["The pool saturated."]
    )
    assert claims == ["The pool saturated."]


def test_contextual_bandit_uses_recorded_feedback(tmp_path):
    store = Store(tmp_path)
    store.save_investigation({
        "investigation_id": "investigation-1",
        "question": "Why is request latency high?",
        "tenant_id": "team-a",
        "retrieval_mode": "deterministic",
    }, "team-a")
    store.add_feedback({
        "investigation_id": "investigation-1",
        "rating": "helpful",
        "comment": "",
        "retrieval_mode": "deterministic",
    }, "team-a")
    assert store.choose_retrieval_route("team-a", "latency", ["deterministic", "semantic"]) == "semantic"


INCIDENT_TEXT = (
    b"# Scenario: Database connection pool exhaustion\n\n"
    b"Incident INC-2001 affected `orders-api` on 2026-09-20 between 10:00 and 10:25 UTC. "
    b"The 5xx rate increased to 14% immediately after release `orders-7.4.0`.\n\n"
    b"Evidence supports connection-pool exhaustion as the likely contributing cause. "
    b"Before changing orders-api, the owner must approve the change."
)

JSON_TEXT = json.dumps([{
    "incident": "INC-1001",
    "service": "payments-api",
    "symptom": "5xx rate increased to 18% after release 4.2.1",
    "finding": "Database connection pool exhausted; saturation began at 09:58 UTC",
}]).encode()


def _named_entities(text):
    """Services and incident ids, the facts a suggestion must never invent."""
    services = {
        token for token in re.findall(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b", text)
        if token.endswith(("-api", "-worker", "-service", "-gateway", "-queue", "-db",
                           "-store", "-cache", "-job", "-cluster", "-node", "-proxy"))
    }
    return services | set(re.findall(r"\b[A-Z][A-Z0-9]*-\d{2,}\b", text))


def test_suggested_questions_name_only_entities_from_their_source_chunk(tmp_path):
    store = Store(tmp_path)
    store.ingest_bytes("incident.md", INCIDENT_TEXT)
    store.ingest_bytes("capacity.json", JSON_TEXT)
    chunks = {chunk.chunk_id: chunk.text for chunk in store.get_chunks("default")}

    items = suggest_questions(store.get_chunks("default"), limit=10)
    assert items
    for item in items:
        source = chunks[item["source_chunk_id"]]
        assert item["source_filename"] in source or item["source_filename"]
        assert _named_entities(item["question"]) <= _named_entities(source), item
    assert "INC-2001" in " ".join(item["question"] for item in items)
    assert "orders-api" in " ".join(item["question"] for item in items)


def test_suggested_questions_are_answerable_by_the_indexed_evidence(tmp_path):
    store = Store(tmp_path)
    store.ingest_bytes("incident.md", INCIDENT_TEXT)
    engine = InvestigationEngine(store)

    items = suggest_questions(store.get_chunks("default"), limit=5)
    results = [
        engine.investigate(InvestigationRequest(question=item["question"]), tenant_id="default")
        for item in items
    ]
    assert all(not result.insufficient_evidence for result in results), [
        item["question"] for item, result in zip(items, results) if result.insufficient_evidence
    ]
    assert any(result.evidence for result in results)


def test_ungrounded_questions_are_filtered_out(tmp_path):
    store = Store(tmp_path)
    store.ingest_bytes("incident.md", INCIDENT_TEXT)
    text = store.get_chunks("default")[1].text
    assert _answerable("What happened during INC-2001 affecting orders-api?", text)
    assert _answerable("What should we do next for orders-api?", text)
    assert not _answerable("What is the lunar weather forecast?", text)
    assert not _answerable("What happened during INC-9999?", text)
    assert not _answerable("?", text)


def test_suggested_questions_are_tenant_scoped_and_version_aware(tmp_path):
    store = Store(tmp_path)
    store.ingest_bytes("incident.md", INCIDENT_TEXT, tenant_id="team-a")
    store.ingest_bytes("incident.md", INCIDENT_TEXT, tenant_id="team-b")

    team_a = [item["question"] for item in suggest_questions(store.get_chunks("team-a"))]
    team_b = [item["question"] for item in suggest_questions(store.get_chunks("team-b"))]
    assert team_a == team_b
    assert suggest_questions(store.get_chunks("team-c")) == []
    assert {item["source_document_id"] for item in suggest_questions(store.get_chunks("team-b"))} == {
        document["id"] for document in store.list_documents("team-b")
    }

    store.ingest_bytes("incident.md", INCIDENT_TEXT + b"\n\nA second version was indexed.", "team-a")
    refreshed = suggest_questions(store.get_chunks("team-a"), limit=10)
    questions = [item["question"] for item in refreshed]
    assert len(questions) == len(set(questions))
    assert suggest_questions(store.get_chunks("team-a"), limit=2) == refreshed[:2]


def test_json_evidence_is_chunked_and_suggested_questions(tmp_path):
    store = Store(tmp_path)
    document = store.ingest_bytes("incidents.json", JSON_TEXT)
    items = suggest_questions(store.get_chunks("default"), limit=5)
    assert items
    assert any("payments-api" in item["question"] for item in items)
    result = InvestigationEngine(store).investigate(
        InvestigationRequest(question=items[0]["question"]), tenant_id="default"
    )
    assert not result.insufficient_evidence
    assert result.verification.claims


def test_oversized_single_paragraph_evidence_is_split_into_windows(tmp_path):
    store = Store(tmp_path)
    blob = json.dumps([
        {
            "incident": f"INC-{7000 + index}",
            "service": "orders-api",
            "finding": f"latency rose to {index}00ms after release 9.{index}.0",
        }
        for index in range(60)
    ]).encode()
    document = store.ingest_bytes("large.json", blob)
    assert document["chunks"] > 1
    assert all(len(chunk.text) <= 4000 for chunk in store.get_chunks("default"))
    assert store.search("INC-7031 latency", 3, "default")
