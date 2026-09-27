# TrustMesh AI input guide

## Accepted files

`POST /api/v1/ingest` accepts **UTF-8** files whose filename ends in:

* `.md` — Markdown incident notes, runbooks, and timelines
* `.txt` — plain-text logs, tickets, and operator notes
* `.json` — one valid JSON document (normalized before indexing)

Files with other extensions (including CSV, PDF, DOCX, images, and binary
archives) are rejected. Empty files and invalid JSON are rejected. Upload only
evidence you are allowed to process; uploaded text is untrusted input.
The default upload cap is 10 MiB (`MAX_UPLOAD_BYTES`); an identical filename
and content in the same tenant is idempotent, while changed content creates a
new document version.

## Examples

```text
incident.md
release 2025-01-14

At 14:03 UTC checkout latency increased after the database pool reached 100%.
Rollback at 14:18 UTC restored latency and pool utilization.
```

```json
{
  "incident_id": "INC-42",
  "service": "checkout",
  "started_at": "2025-01-14T14:03:00Z",
  "events": ["database pool exhausted", "rollback restored baseline"]
}
```

## Recommended fields

Include an incident or ticket ID, service/component, UTC timestamps, symptoms
and impact, observed metrics, deployment/change IDs, timeline, hypotheses,
actions already taken, outcome, and links or owners. Keep facts and hypotheses
distinct. Smaller paragraphs produce clearer citations.

The local mode does not call an external LLM. Ask specific questions such as
“What changed before checkout latency increased?” and upload corroborating
timeline, log, and runbook evidence. TrustMesh is advisory: an operator must
approve any production change.

For sensitive evidence, run with production API keys and set
`DATA_ENCRYPTION_KEY` before ingestion. Encryption covers content and free-text
investigation/approval fields, but not all SQLite metadata. Do not upload
credentials, personal data, or material your organization has not approved for
this processing environment.
