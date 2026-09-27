# TrustMesh AI Delivery Plan

## Completed: evidence-first MVP

- [x] FastAPI ingestion, health, investigation, documents, and feedback API.
- [x] Markdown, text, and JSON validation/chunking.
- [x] Streamlit evidence investigation UI.
- [x] Deterministic retrieval and synthetic incident scenarios.
- [x] Typed investigation opinions, citations, uncertainty, and human-safety boundary.

## Completed: AI and grounded retrieval phase

- [x] Typed retrieval → investigation → verification LangGraph workflow with local fallback.
- [x] LangChain Core document adapter.
- [x] Optional local Sentence Transformers embedding path.
- [x] Persist FAISS index and chunk metadata by content/model fingerprint.
- [x] Optional cross-encoder reranking.
- [x] Lexical-vs-semantic retrieval replay report/API.
- [x] Optional Ollama local model for structured claim proposals.
- [x] Optional local NLI entailment verifier; lexical verifier reports its mode/fallback.
- [x] Citation coverage and heuristic contradiction indicators.
- [x] Adversarial unsupported-claim fixture and tests.

## Completed: persistence and learning feedback

- [x] Tenant-scoped SQLite persistence for documents, versions, investigations, and feedback.
- [x] Replayable evaluation corpus and durable evaluation reports.
- [x] Feedback metrics by retrieval route and incident-question context.
- [x] Contextual UCB routing experiment when multiple retrieval routes are available.
- [x] Idempotent duplicate ingestion and database-backed per-request retrieval for workers.

## Completed: local security and operations baseline

- [x] Bearer token authentication and viewer/analyst/admin roles.
- [x] Tenant isolation on reads, retrieval, investigations, feedback, audit, and approvals.
- [x] Per-process rate limit and bounded upload quotas.
- [x] Structured JSON action logs and tenant-scoped audit records.
- [x] Prometheus text metrics endpoint.
- [x] Optional Langfuse and LangSmith metadata tracing, disabled by default.
- [x] Configurable retention and Fernet encryption for document/evidence content.
- [x] Durable internal human approval requests and approval/rejection decisions.
- [x] Docker Compose persistent state volume and deployment configuration.
- [x] Combined Streamlit/FastAPI container for Cloud Run and Render.
- [x] Public demo-password gate with constant-time comparison.
- [x] Deployment guide covering free-tier limits, ephemeral data, secret handling, and Git publishing.

## Deferred: production integrations and scale

- [ ] Connect approval queue to a real ServiceNow/Jira/change-management instance.
- [ ] Replace local single-process API-key configuration with enterprise identity/OIDC and managed RBAC.
- [ ] Use a managed relational DB/vector store and distributed rate limiting for horizontal scale.
- [ ] Use per-tenant KMS envelope encryption and verified key rotation/migration.
- [ ] Add an operationally managed model registry, GPU inference, and NLI/semantic benchmark corpus.
- [ ] Validate privacy/retention policy with deployment owners before production data use.

## Important capability boundary

The contextual UCB component is a small feedback-driven route-selection policy,
not deep reinforcement learning or model weight training. NLI, semantic search,
reranking, LangGraph, LangChain, and Ollama require optional local packages and
cached model weights; the default test/demo profile remains local and
deterministic. External integrations are not represented as complete until
configured and exercised against their target systems.

The Cloud Run script and Render Blueprint are deployment-ready configurations,
not proof of a live cloud deployment. Cloud Run requires the owner's GCP
project/account and billing; publishing requires a Git remote. The shared
password only protects a synthetic-data demo and is not production identity.
