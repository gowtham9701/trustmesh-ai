# TrustMesh AI Project Memory

## Current state

TrustMesh AI is a locally runnable, tenant-scoped evidence investigation
application. SQLite is the durable source of truth; the default model/retrieval
path requires no credentials or model downloads.

## Current capabilities

- Ingest/version UTF-8 Markdown, text, and JSON evidence.
- Use deterministic retrieval by default; optionally use persisted FAISS,
  Sentence Transformers, and cross-encoder reranking.
- Run typed retrieval/investigation/verification with LangGraph when available.
- Generate extractive claims by default; optionally ask local Ollama for
  structured claims and verify them before returning.
- Check claims with lexical overlap by default or local NLI when enabled.
- Refuse unsupported questions and qualify causal conclusions.
- Persist investigations, feedback, approvals, evaluation reports, and audit
  events in SQLite.
- Use API key roles and tenant isolation when configured.
- Encrypt evidence content at rest with a Fernet key; optional tracing is
  metadata-only and disabled by default.
- Provide an internal approval queue; it does not execute proposed changes.

## Configuration and constraints

- `APP_ENV=development` permits a local admin when no API keys are set.
- `APP_ENV=production` requires bearer tokens in `TRUSTMESH_API_KEYS`.
- Model weight downloads are disabled by default; cache approved model files or
  explicitly opt in.
- `DATA_ENCRYPTION_KEY` must be backed up securely; existing plaintext rows are
  not automatically migrated, and key loss prevents reading encrypted rows.
- SQLite and in-process rate limiting are a pilot-scale baseline. Production
  horizontal scaling requires managed storage and a gateway.
- LangFlow is not embedded; it can call the exposed API as an external client.
- Contextual UCB retrieval routing is a small bandit policy, not deep RL/model
  training.
- Personal deployment uses one combined container: only Streamlit is public;
  FastAPI listens on loopback. Cloud Run/Render filesystem persistence is not
  assumed, and the default deployment database is temporary under `/tmp`.
- The public demo gate uses `TRUSTMESH_PUBLIC_MODE=true` and a
  `TRUSTMESH_DEMO_PASSWORD` of at least 12 characters. It is only a shared
  password barrier, not production authentication.
- Git publishing and cloud deployment are not complete until the owner provides
  a repository remote and configures a cloud account/project.

## Manual test scenarios

- `test_incident_database.md`: deployment/database incident.
- `test_incident_cache.md`: competing hypotheses.
- `test_security_policy.md`: safety and approval boundaries.
- `test_capacity_degradation.json`: queue/worker saturation.
- `test_insufficient_evidence.txt`: out-of-domain refusal.
- `tests/fixtures/adversarial_claims.json`: unsupported claim rejection.

## Next work

See [tasks.md](tasks.md). Remaining scope is real external approval-system
integration, managed identity/KMS, horizontal-scale storage/rate limiting, and
benchmarking local model choices on approved hardware.
