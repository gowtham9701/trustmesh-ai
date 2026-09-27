# TrustMesh AI Architecture

## Components

```text
Streamlit UI
  │ authenticated HTTP / multipart
  ▼
FastAPI API ── bearer role + tenant principal ── per-process request limiter
  │
  ├── SQLite/WAL: versioned documents, chunks, investigations, feedback,
  │               evaluation runs, approvals, audit events, bandit outcomes
  ├── Retriever: lexical baseline, optional persisted FAISS semantic index,
  │              optional cross-encoder reranker
  ├── Typed LangGraph workflow (optional) / same local node fallback
  │     └── retrieval → extractive investigation → claim verification
  ├── Claim verifier: lexical overlap / optional local NLI cross-encoder
  ├── Provider: mock local / optional Ollama local model
  └── Observability: structured JSON logs, Prometheus text metrics,
                      optional Langfuse/LangSmith metadata traces
```

## Persistence and tenant isolation

SQLite is the durable source of truth. Document versions are keyed by tenant
and filename; exact duplicate content in the same tenant is idempotent.
Retrieval queries SQLite by tenant at request time so multiple API processes
see newly ingested documents. WAL and a busy timeout support concurrent local
readers/writers. Docker Compose mounts the database directory on a named volume.

At-rest content encryption uses Fernet when `DATA_ENCRYPTION_KEY` is provided.
Document/chunk text, investigation payloads, feedback comments, approval details, evaluation
payloads, and persisted FAISS vector index bytes are encrypted;
routing/tenant metadata remains
plaintext for indexing. Existing plaintext data is not automatically migrated.

## Investigation flow

1. Authenticate bearer token to tenant and role.
2. Apply upload and request limits.
3. Validate file type, UTF-8, JSON, and upload size.
4. Store a versioned document and bounded chunks transactionally.
5. Retrieve tenant-scoped evidence; optional FAISS index is persisted by content
   fingerprint and model ID.
6. The workflow extracts candidate claims from relevant passages.
7. Claim support and citation coverage are measured against source passages.
8. Optionally call local Ollama to propose claims, then run the same verifier.
   Unsupported or malformed output is rejected; no cloud model is contacted.
9. Return cited findings, uncertainty, and human-reviewed action suggestions.
10. Persist investigation/audit state; feedback updates contextual retrieval
    route statistics.

## API security

`TRUSTMESH_API_KEYS` is a JSON array mapping opaque bearer tokens to a role and
tenant ID. Viewer can read/investigate, analyst can ingest and request approvals,
and admin can decide approvals, run evaluations, read audit events, and scrape
metrics. In development only, if no keys are configured, a local admin principal
is used. Production requires explicit token configuration.

CORS defaults to local UI origins, upload bytes are bounded, and an in-process
sliding-window limiter returns HTTP 429. Deploy behind a gateway for
distributed rate limiting and stronger abuse controls.

## Verification and evaluation

Claims are extracted from evidence passages and assigned supporting chunk IDs.
The default verifier measures term overlap (explainable, not semantic entailment).
With a locally cached NLI cross-encoder, entailment probabilities can be used
instead. Verification reports coverage, unsupported claims, and heuristic
polarity conflicts. This is a review signal, not a mathematical guarantee.

`data/evaluation_cases.json` powers replayable status checks and lexical-vs-
semantic retrieval comparison. Feedback metrics and contextual UCB route
selection are available when `BANDIT_ROUTING_ENABLED=true`; this is a small
online bandit policy, not model training or general reinforcement learning.

## Production limitations

- Local SQLite and a per-process rate limiter are suitable for a demo/small
  pilot, not a high-write multi-region deployment.
- A shared Fernet key is a local single-tenant baseline; use per-tenant KMS
  envelope encryption in production.
- Tracing sends metadata only; never add evidence text, questions, secrets, or
  personal data to trace metadata.
- Human approval is an internal durable queue. No external change-management
  provider or remediation executor is connected.
- LangFlow can call the API but is not bundled or embedded.
