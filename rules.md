# TrustMesh AI Engineering Rules

## Reliability

- Never invent evidence, citations, incident IDs, or operational facts.
- If the evidence threshold is not met, return `insufficient_evidence`.
- Distinguish correlation from causation in all causal output.
- Do not silently fall back after provider, parsing, or storage failures.
- Preserve explicit error responses at API boundaries.

## Safety

- TrustMesh is advisory only.
- Never execute rollback, restart, credential rotation, firewall changes, message
  deletion, or capacity changes.
- Recommendations involving production changes must state that human approval is
  required.
- Do not include secrets in logs, source files, test fixtures, or documentation.

## Code

- Use Python type hints and Pydantic models for API contracts.
- Keep retrieval, orchestration, storage, and provider concerns separate.
- Prefer existing helpers and repository patterns over duplicate logic.
- Keep agent behavior deterministic in the no-secret demo mode.
- Add focused tests for every changed behavior.
- Use clear, short functions and avoid broad exception handling.

## Data

- Accept only documented file types.
- Validate UTF-8 and JSON before indexing.
- Preserve source text in citations with bounded quote length.
- Treat uploaded evidence as untrusted input.
- Apply tenant scope to every storage read and write.
- Never log document bodies, questions, bearer tokens, or model prompts.
- Enable content encryption before ingesting sensitive data; key rotation and
  retroactive migration require an explicit controlled procedure.
- Use external model weights only when they have been locally cached or download
  permission is explicitly enabled.

## Product behavior

- Show source, score, confidence, verification, and recommended actions.
- Make unsupported questions visibly different from verified findings.
- Explain that deterministic/mock mode does not call an external LLM.
- Optional integrations must fail closed to the deterministic local mode.
- Tracing is disabled by default and must never require credentials for tests.
