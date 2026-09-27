# TrustMesh AI Design System

## Product character

TrustMesh should feel like a calm investigation console: transparent,
technical, cautious, and useful under pressure. It should communicate evidence
and uncertainty more prominently than visual decoration.

## Layout

- Sidebar: API status, retrieval/provider mode, and indexed-document count.
- Main column: ingestion, investigation question, and result summary.
- Result sections: finding, confidence, verification, citations, agent opinions,
  claim-level checks, recommended actions, approval queue, and feedback.
- Use expandable sections for long raw evidence and response payloads.

## Visual hierarchy

1. Finding and verification status
2. Confidence and evidence count
3. Citation details
4. Agent opinions and rationale
5. Recommended actions
6. Feedback and raw payload
7. Optional approval queue

## Status semantics

- Verified: green/success treatment.
- Insufficient evidence: amber/warning treatment.
- Disputed/deadlock: red/error treatment.
- Informational provider and mode details: neutral treatment.

## Interaction rules

- Keep the investigation question visible after submission.
- Show loading state while ingesting or investigating.
- Surface API errors explicitly.
- Never hide the fact that actions require human review.
- Make the approval decision auditable and do not imply it executes a change.
- Use plain language alongside technical identifiers.

## Accessibility

- Use headings in workflow order.
- Do not rely on color alone for verification status.
- Provide labels for upload, question, feedback, and comment controls.
- Keep citations readable and expandable.
