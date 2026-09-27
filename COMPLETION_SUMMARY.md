# TrustMesh AI implementation status

## Implemented

- FastAPI and Streamlit application with local mock mode and a local Ollama
  provider option.
- UTF-8 Markdown, text, and JSON ingestion with size limits, tenant-scoped
  document versions, SQLite persistence, and idempotent re-ingestion.
- Deterministic retrieval plus optional local Sentence Transformers/FAISS
  semantic retrieval, persisted indexes, and optional cross-encoder reranking.
- Typed LangGraph workflow with local fallback and LangChain Core document
  adapter.
- Extractive evidence claims, citation coverage and unsupported claim checks;
  optional local NLI entailment model.
- Feedback metrics and optional context-aware UCB retrieval routing.
- Bearer API-key roles, tenant isolation, bounded uploads, per-process request
  rate limiting, structured logs, Prometheus text metrics, and audit events.
- Optional Fernet at-rest encryption for document/chunk text, investigations,
  feedback comments, approval details, evaluation reports, and semantic vector
  index bytes.
- Configurable retention, replayable evaluation, retrieval comparison reports,
  and a durable human-approval queue. The queue records decisions; it does not
  execute production changes.
- Docker Compose with persistent SQLite state.
- Combined, non-root Cloud Run/Render demo image; FastAPI stays on loopback and
  Streamlit is the only public process.
- Shared demo-password gate, secure secret injection instructions, and a
  Cloud Run deployment helper with Secret Manager access for its runtime
  service account.
- Render Blueprint and deployment guidance covering free-tier sleep, ephemeral
  storage, privacy boundaries, and the limits of Vercel/Netlify for this
  Streamlit architecture.

## Required user input

Upload UTF-8 `.md`, `.txt`, or valid `.json` with incident IDs, service names,
UTC timestamps, deployment/change IDs, observed symptoms and metrics, timelines,
actions, and outcomes. CSV, PDF, DOCX, image, and binary uploads are not
accepted. See [INPUT_GUIDE.md](INPUT_GUIDE.md) for examples.

## Validation

Latest checks before the deployment-profile changes:

```text
python3 -m pytest -q
14 passed
```

After deployment-profile changes, `python3 -m pytest -q` passes **15 tests**,
and `python3 -m compileall -q backend frontend scripts tests` passes. A local
combined-server smoke test returned healthy API and Streamlit endpoints; the
browser successfully authenticated with a test-only password, displayed the
demo corpus, refused an unsupported question, then produced a verified
incident result at 86% confidence with 100% citation coverage for the
scenario-matching question. The test server remains available locally at
`http://127.0.0.1:18721` (test password: `smoke-test-password-123`).

Container build and Compose validation could not be performed in this session:
the Docker CLI is installed, but the Docker daemon socket is unavailable.
Cloud deployment was not executed because `gcloud` is not installed and no
cloud project was provided. The directory is not a Git repository and has no
remote, so no commit or push was made.

## Important limits

Semantic/NLI models, FAISS, LangGraph, LangChain, Langfuse, LangSmith, and Ollama
are optional; their integrations were not all exercised against live model or
tracing services. Weights are not downloaded by default. The contextual UCB
policy is not deep reinforcement learning. The rate limiter is per process,
SQLite is pilot scale, the approval queue is not integrated with an external
change-management platform, and this is not a production-certified system.
See [tasks.md](tasks.md) for remaining external/scale work.
