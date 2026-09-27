# TrustMesh project flow

```text
API key -> tenant/role principal -> request and upload limits
   |
Upload .md/.txt/.json -> SQLite document version -> bounded chunks
   |                                                   |
   |                         Optional FAISS embeddings/index + reranking
   |                                                   |
   +--------------> LangGraph / typed local fallback <-+
                               |
             retrieve -> extract claims -> verify citations
                               |
          optional Ollama proposes claims; verifier still gates output
                               |
       citations + confidence + support/contradiction state + actions
                               |
            SQLite investigation + tenant audit event
                  |                           |
              feedback                 human approval queue
                  |                           |
          contextual route policy      admin decision recorded
```

## Agent contracts

* **Retrieval** reports matching chunks and scores; it cannot create evidence.
* **Investigator** extracts answer claims from cited passages or optionally
  requests structured claims from a local Ollama model. Every claim passes the
  verifier before it is returned.
* **Causal** uses qualified language and never claims causality solely from
  correlation.
* **Policy** forbids autonomous remediation and requires human review.
* **Verifier** checks citation coverage, unsupported claims, and heuristic
  contradictions. An optional local NLI cross-encoder can perform entailment
  scoring; lexical overlap remains the zero-download default.

## Trust boundaries

Uploaded content is treated as untrusted text. No shell/tool execution or
automatic operational changes are available. SQLite persists tenant-scoped
documents, investigations, approvals, evaluations, audit events, and feedback.
Optional tracing receives only investigation metadata. The local limiter is
per-process; use an API gateway for distributed enforcement.
