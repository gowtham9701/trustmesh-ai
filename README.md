# TrustMesh AI

TrustMesh is a local-first incident investigation system. It indexes Markdown,
text, and JSON evidence; retrieves relevant passages; extracts answer claims;
checks claims against citations; and returns confidence, uncertainty, agent
opinions, and human-reviewed next actions. It does not execute production
changes.

## Quick start

Requirements: Python 3.9+, local SQLite, and (optionally) Docker.

```bash
cd "/Users/gautam/personal projects/opspilot"
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt -r frontend/requirements.txt
uvicorn backend.app.main:app --reload
```

In a second terminal:

```bash
cd "/Users/gautam/personal projects/opspilot"
source .venv/bin/activate
streamlit run frontend/streamlit_app.py
```

Open <http://localhost:8501>. The API docs are at <http://localhost:8000/docs>.
The default `mock/local` mode requires no credentials or model downloads.
SQLite data is written to `data/trustmesh.sqlite3` by default.

## What evidence to upload

UTF-8 `.md`, `.txt`, and valid `.json` files are accepted. Good inputs include
incident timelines, runbooks, ticket notes, policy documents, and sanitized
log excerpts. Include service names, UTC timestamps, deployment IDs, symptoms,
metrics, actions, and outcomes. CSV, PDF, DOCX, images, empty files, and invalid
JSON are rejected. See [INPUT_GUIDE.md](INPUT_GUIDE.md).

## Investigation workflow

1. Validate and version the uploaded document in tenant-scoped SQLite.
2. Split text into citation-preserving chunks.
3. Retrieve evidence using local lexical ranking, optional persisted FAISS
   semantic retrieval, and optional cross-encoder reranking.
4. Run typed retrieval → investigation → verification workflow (LangGraph
   when installed; local implementation otherwise).
5. Extract answer claims and check citation support. An optional local NLI
   cross-encoder can replace lexical-overlap checks.
6. Return an explicit insufficient-evidence or disputed state when checks fail.
7. Store the investigation, audit event, and optional feedback.
8. Put operational changes into the human approval queue; nothing is executed.

## AI and observability options

Optional integrations are deliberately excluded from the default install:

```bash
pip install -r backend/requirements-optional.txt
```

* **LangGraph**: typed workflow orchestration.
* **LangChain Core**: conversion adapter for retrieved documents.
* **Sentence Transformers + FAISS**: semantic embeddings and persisted index.
* **Cross-encoder**: optional reranking (`RERANKER_ENABLED=true`).
* **Local NLI model**: claim entailment (`CLAIM_NLI_ENABLED=true`).
* **Ollama**: local LLM claims (`LLM_PROVIDER=ollama`, then configure
  `OLLAMA_MODEL` and run that model locally).
* **Langfuse or LangSmith**: metadata-only traces, disabled by default.

Model downloads are disabled by default. Pre-cache weights locally or explicitly
set `MODEL_DOWNLOADS_ALLOWED=true` when you approve a download. Missing optional
models fall back to lexical retrieval/verification and report the selected mode.
No paid API is required.

LangFlow is not embedded in the runtime: the HTTP API is the integration seam
for an external LangFlow deployment. Its credentials and network policies should
be configured outside this application.

## API

* `GET /health`
* `GET /api/v1/ai/metadata`
* `POST /api/v1/ingest` — multipart document upload
* `GET /api/v1/documents` — tenant-scoped document versions
* `POST /api/v1/investigate` — `{ "question": "...", "top_k": 6 }`
* `POST /api/v1/feedback`, `GET /api/v1/feedback`
* `GET /api/v1/feedback/metrics`
* `POST /api/v1/evaluation/run`
* `POST /api/v1/evaluation/compare-retrieval`
* `GET /api/v1/evaluation/latest`
* `POST /api/v1/approvals`, `GET /api/v1/approvals`
* `POST /api/v1/approvals/{id}/decision`
* `GET /api/v1/audit`, `GET /metrics`

## Security and deployment configuration

Copy `.env.example` to `.env`. Development mode is open for localhost demos.
Production mode requires bearer API keys and tenant/role assignments:

```dotenv
APP_ENV=production
TRUSTMESH_API_KEYS=[{"token":"a-long-random-secret","tenant_id":"team-a","role":"admin"}]
OPSPILOT_API_TOKEN=a-long-random-secret
```

Roles are `viewer`, `analyst`, and `admin`. Documents and investigations are
tenant-isolated. Configure explicit CORS origins, upload size, rate limit,
retention, and encryption before handling sensitive data. To generate a
Fernet key, install the core `cryptography` dependency and use
`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.
Set it as `DATA_ENCRYPTION_KEY` before ingesting data. This encrypts document
chunks, investigation payloads, feedback comments, approval details, and
evaluation reports at rest; semantic FAISS index data is also encrypted when
the key is configured. Metadata and audit records remain queryable.
Back up the key separately. Changing/loss of the key makes encrypted content
unreadable; existing plaintext rows are not retroactively encrypted.

Run locally in containers:

```bash
docker compose up --build
```

Compose persists SQLite state in a named volume. In a real deployment, use a
managed database/storage service, TLS ingress, distributed rate limiting,
centralized audit retention, secret management, backups, and tenant-specific
encryption keys. The built-in limiter is per process and is not a substitute
for an edge/API gateway. Human approval records are internal; integrations with
ServiceNow/Jira/change-management systems are not included.

For a personal hosted demo, use the single-container root [Dockerfile](Dockerfile)
with Cloud Run or Render. It serves Streamlit publicly and keeps FastAPI on
loopback, with a shared demo-password gate (not production authentication).
The free-tier profile uses ephemeral SQLite; uploaded data can be lost when
the instance stops or restarts. See
[`CLOUD_DEPLOYMENT.md`](CLOUD_DEPLOYMENT.md) for Cloud Run, Render, Git publishing,
Vercel/Netlify fit, and persistence details.

## Validation

```bash
python3 -m pytest tests -q
python3 -m compileall -q backend frontend
docker compose config --quiet
```
