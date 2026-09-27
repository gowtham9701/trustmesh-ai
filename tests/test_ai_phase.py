from backend.app.ai_workflow import run_workflow
from backend.app.retrieval import StoreRetriever
from backend.app.store import Store
from backend.app.tracing import get_tracer
from backend.app.claim_verification import check_claims
from backend.app.providers import OllamaProvider
import io
import json
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
