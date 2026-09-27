# TrustMesh AI Product Requirements

## Product

TrustMesh AI is a local-first, evidence-grounded investigation workspace for
IT and operations teams. It helps users investigate incidents using uploaded
runbooks, incident notes, policies, logs, and structured records.

## Problem

Enterprise AI assistants can produce plausible but unsupported answers, fail to
admit missing evidence, and recommend unsafe operational changes. Engineers
need a faster way to investigate incidents while retaining source citations,
uncertainty, and human approval boundaries.

## Target users

- Site reliability and platform engineers
- IT operations analysts
- Security operations analysts
- Engineering managers reviewing incident evidence

## MVP goals

1. Ingest local Markdown, text, and JSON evidence.
2. Search indexed evidence using a transparent local retrieval baseline.
3. Run a structured multi-agent investigation workflow.
4. Return citations, confidence, agent opinions, verification, and safe actions.
5. Refuse unsupported questions instead of guessing.
6. Capture user feedback for later evaluation.
7. Run without paid APIs or secrets.

## Non-goals

- Autonomous production remediation
- Production authentication or multi-tenancy
- Full causal discovery or model training
- Guaranteed factual correctness
- Persistent enterprise-scale document storage

## Success criteria

- A user can ingest evidence and investigate an incident in under one minute.
- Every non-empty finding includes source citations.
- Unsupported questions return `insufficient_evidence`.
- Recommended actions never execute automatically.
- The demo runs locally with the mock/local provider.

## Functional requirements

### Ingestion

- Accept `.md`, `.txt`, and `.json`.
- Reject unsupported extensions, invalid UTF-8, invalid JSON, and empty files.
- Split documents into citation-preserving chunks.
- Expose indexed document metadata.

### Investigation

- Accept a natural-language question and optional `top_k`.
- Retrieve relevant chunks deterministically.
- Produce retrieval, investigator, causal, and policy opinions.
- Verify evidence sufficiency and detect a deadlock/disputed state.
- Return confidence, citations, recommended actions, and uncertainty.

### Safety

- Never execute remediation.
- Require human review for rollback, credential rotation, capacity changes, or
  other operational interventions.
- Do not claim causation when the evidence only shows correlation.

## API requirements

- `GET /health`
- `POST /api/v1/ingest`
- `GET /api/v1/documents`
- `POST /api/v1/investigate`
- `POST /api/v1/feedback`
- `GET /api/v1/feedback`
