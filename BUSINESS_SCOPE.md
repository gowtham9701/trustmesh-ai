# TrustMesh AI business scope

## Users and input

SREs, support engineers, incident commanders, service owners, and auditors
upload UTF-8 Markdown, plain text, or valid JSON. See [INPUT_GUIDE.md](INPUT_GUIDE.md)
for the exact contract and recommended fields.

## Business use cases

* Triage incidents and identify the most relevant timeline and runbook passages.
* Prepare evidence-backed handoffs, post-incident reviews, and customer updates.
* Compare competing hypotheses without silently inventing facts.
* Find operational patterns across tickets, logs, and service notes.
* Give auditors traceable citations and an explicit insufficient-evidence state.

## Value, efficiency, and innovation

TrustMesh reduces time spent searching fragmented incident records, makes
handoffs repeatable, and keeps confidence and source quotes visible. A
deterministic local baseline provides explainability and zero-cost demos.
Optional sentence-transformers/FAISS semantic retrieval can improve
paraphrase recall; optional LangGraph gives an explicit typed workflow.
Neither option is required for local operation.

## Workflow

1. Validate the extension, UTF-8 encoding, and JSON syntax.
2. Split source text into bounded paragraph chunks with stable metadata.
3. Retrieve relevant chunks (deterministic by default; semantic is optional).
4. Investigate only from retrieved citations.
5. Verify evidence thresholds and return confidence, uncertainty, and safe
   recommended actions.
6. Record optional human feedback. No remediation is executed automatically.

## Current deployment baseline and limits

The project now has tenant-scoped SQLite persistence, versioned inputs, bearer
roles, per-process rate limits, upload quotas, audit events, configurable
retention, and optional Fernet encryption. This is suitable for a controlled
local pilot, not a certified production service. Deterministic lexical retrieval
can miss paraphrases. Optional semantic/NLI models are not installed or
downloaded by default. SQLite and per-process rate limits are not horizontal
scale primitives. Causal language is qualified; this is not causal discovery.
Internal approvals are recorded but do not update ServiceNow/Jira or execute
changes.

## Security and scalability

Treat uploads as untrusted: validate type and encoding, bound upload size and
citation quotes, avoid secrets in fixtures/logs, encrypt content at rest when
configured, and keep the human approval boundary. Optional Langfuse/LangSmith
tracing is disabled by default and sends metadata only. For scale, replace
SQLite with managed tenant-scoped storage, use a distributed gateway limiter,
and manage vector-index lifecycle and key rotation.
