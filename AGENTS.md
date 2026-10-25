# AGENTS.md

Local-first, evidence-grounded incident investigation (FastAPI + Streamlit + SQLite).
Advisory only: the system never executes production changes.

## Commands

No lint/typecheck tooling exists (no ruff/mypy/flake8 in `backend/requirements-dev.txt`,
no `pyproject.toml`/`pytest.ini`/`setup.cfg`). `python3 -m compileall -q backend frontend`
is the only static check. There is no CI; run these locally before declaring work done.
- The target is **Python 3.9** (README says 3.9+). `from __future__ import annotations`
  makes `str | None` fine inside function bodies, but FastAPI *evaluates* route
  signatures at import, so a route parameter needs `typing.Optional[str]`. Getting
  this wrong passes `compileall` and fails only when the server starts.

```bash
pip install -r backend/requirements-dev.txt -r frontend/requirements.txt

python3 -m pytest tests -q                              # 23 tests, <1s
python3 -m pytest "tests/test_api.py::test_rate_limit" -q
python3 -m compileall -q backend frontend
docker compose config --quiet

uvicorn backend.app.main:app --reload                   # API :8000
streamlit run frontend/streamlit_app.py                 # UI :8501 (second terminal)
```

- Always `python3 -m pytest` (bare `pytest` is not on PATH) and always from the repo
  root: there is no conftest/src layout, so the module form is what puts the root on
  `sys.path` for `from backend.app import ...` / `from frontend.auth import ...`.
- README quick-start still says `cd "/Users/gautam/personal projects/opspilot"`. The
  repo root is this directory; ignore that path.
- Optional stack (LangGraph, sentence-transformers, FAISS, tracing) lives in
  `backend/requirements-optional.txt` and is never required for the default run.

## Architecture that isn't obvious from filenames

- `backend/app/main.py` builds module-level singletons at import time:
  `store = Store(os.getenv("DATA_DIR", "data"))` and `engine = InvestigationEngine(store)`.
  Endpoints must use these. Tests monkeypatch `main.store` / `main.engine`, so an
  endpoint that constructs its own `Store`/`InvestigationEngine` silently escapes
  test isolation. The rate limiter dict `_request_times` is module-level for the
  same reason (`test_rate_limit` resets it manually).
- `Store.__init__` calls `_load_demo()`: if `<data_dir>/synthetic_incidents.json`
  exists it is auto-ingested into tenant `default`. `Store("data")` is therefore
  **not** empty — it changes retrieval results and evaluation accuracy. Tests use
  `tmp_path` to avoid it; do the same for anything asserting on document counts.
- Default tenant is the literal `"default"` (dev principal in `security.py`, all
  `Store` defaults, unauthenticated local mode).
- Retrieval queries SQLite per request precisely so new uploads are visible across
  processes. Do not add caching without keeping tenant scoping.
- Ingest accepts only `.md`/`.txt`/`.json`, UTF-8, valid JSON, non-empty, within
  `MAX_UPLOAD_BYTES`. Chunks are blank-line-split paragraphs, further split into
  ~1200-char sentence-aligned windows (`CHUNK_TARGET_CHARS`) and capped at 4000
  (`CHUNK_MAX_CHARS`). Without the window split, a large JSON/log upload with no
  blank lines becomes a single 4000-char-truncated chunk. Versions are keyed by
  (tenant, filename) and re-ingesting identical bytes is a no-op, so **changing
  chunking does not re-chunk an existing `data/trustmesh.sqlite3`** — delete it to
  re-index.
- `question_suggestions.py` generates the questions the UI offers. Its
  `_answerable()` deliberately mirrors `ai_workflow.investigation_node`'s overlap
  rule, so suggestions that would return `insufficient_evidence` are dropped.
  Templates are hand-written, so a phrasing change can silently alter which
  questions are offered.
- `combined_server.py` is the single-container deploy: FastAPI pinned to
  `127.0.0.1:$OPSPILOT_INTERNAL_API_PORT`, Streamlit public on `$PORT` (8080), 60s
  health wait, SIGTERM fan-out. Root `Dockerfile` uses it (Cloud Run / `render.yaml`);
  `Dockerfile.api` + `Dockerfile.ui` are the split two-service Compose path.
- `frontend/streamlit_app.py` imports `from auth import ...` (Streamlit puts the
  script dir on `sys.path`) while tests import `frontend.auth`. Both styles must keep
  working — don't "fix" the app to a package-relative import.

## Coupling to be careful with

- Sensitive columns are encrypted with Fernet via `Store._encode_text` /
  `encrypt_bytes` / `_decode_text`, enabled by `DATA_ENCRYPTION_KEY`. Any new
  text-bearing column must use those, and
  `tests/test_api.py::test_encryption_at_rest_when_configured` greps raw SQLite rows
  to assert nothing readable leaks — update that test when you add storage.
- Verification thresholds are load-bearing and duplicated. `engine.py` marks a
  result "enough" only with >=2 hits (or 1 hit scoring >=0.8) **and** non-empty
  claims **and** `citation_coverage >= 0.8`; `verified` requires coverage exactly
  `1.0`, `disputed` is `contradiction_count > 0`. The `0.72` term-overlap support
  threshold appears in both `ai_workflow.verification_node` and
  `claim_verification._lexical_checks`. Changing any of these moves
  `data/evaluation_cases.json` outcomes.
- Four near-duplicate stopword sets exist (`engine.STOPWORDS`,
  `ai_workflow` inline set, `claim_verification.STOPWORDS`, `store.search` — the last
  omits `cause`/`caused`), plus `question_suggestions.TOPIC_STOPWORDS`, which
  imports `engine.STOPWORDS` precisely to stay in sync. Scoring drift hides here;
  keep changes deliberate.
- Optional deps are imported inside functions and must fail **closed** to
  deterministic mode while reporting a reason (`fallback_reason`,
  `verifier_fallback`, surfaced via `GET /api/v1/ai/metadata`). Never swallow a
  fallback silently. `MODEL_DOWNLOADS_ALLOWED=false` sets `HF_HUB_OFFLINE=1`.
- Roles are `viewer < analyst < admin` via `require_role()`. `APP_ENV=production`
  requires `TRUSTMESH_API_KEYS` and disables `/docs`, `/redoc`, `/openapi.json`.
- New config vars use the `TRUSTMESH_*` prefix. `OPSPILOT_API_URL` /
  `OPSPILOT_API_TOKEN` are the legacy UI→API pair; keep reading them.

## Binding product rules (`rules.md` is the authority)

- Never invent evidence, citations, incident IDs, or operational facts; return
  `insufficient_evidence` when the threshold isn't met.
- Never execute rollback, restart, credential rotation, firewall, deletion, or
  capacity changes. There is no remediation executor — approvals are a durable
  internal queue only.
- Treat uploads as untrusted; apply tenant scope to every read and write.
- Never log or trace document bodies, questions, bearer tokens, or model prompts.
  Tracing is metadata-only, disabled by default, and must never need credentials for
  tests. Keep the default run fully offline and deterministic.
- Add a focused test for every behavior change.

## Docs

`rules.md` (binding rules), `architecture.md` (components/persistence flow),
`memory.md` (current capabilities + map of the manual scenario files at repo root),
`INPUT_GUIDE.md`, `CLOUD_DEPLOYMENT.md`, `tasks.md` (deferred scope). Prose docs
drift; trust the code.

`python3 scripts/deploy_cloud_run.py` is interactive and has real side effects
(creates a Secret Manager secret, a service account, IAM bindings, and a publicly
reachable Cloud Run service). Never run it unattended.

## Git

Ask before committing or pushing. Single-commit history, no branch conventions yet.
