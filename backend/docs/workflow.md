# Backend Workflow Contract

This document is the working contract for PharmaOps backend workflow changes.
It describes the current event-to-review flow and the standards future code
should follow. Keep it short, implementation-focused, and aligned with code.

## Workflow Overview

Current backend flow:

```text
EventNormalized
  -> idempotent ticket creation
  -> inventory match + impact summary
  -> evidence retrieval + sufficiency check
  -> draft generation
  -> draft safety check
  -> policy routing
  -> pharmacist review / report versions / audit trace
```

The main orchestration entrypoint is:

```text
app.orchestration.service.run_ticket_workflow
```

Orchestration coordinates steps. It should not own FDA parsing, inventory
matching quality, RAG scoring, safety pattern policy, or pharmacist UI payload
shape.

## Current Execution Contract

`run_ticket_workflow()` currently:

- creates or reuses a ticket for the same source event
- runs inventory, evidence, draft, safety, and routing steps in order
- persists step outputs on the `tickets` row
- writes step-level audit logs
- persists the generated initial draft as `draft_v1`
- commits workflow success at the end
- commits failure state before re-raising step failures

Current status flow:

```text
CREATED
-> INVENTORY_CHECKED
-> EVIDENCE_RETRIEVED
-> DRAFT_GENERATED
-> SAFETY_CHECKED
-> REVIEW_ROUTED or CLOSED
```

Failure flow:

```text
WORKFLOW_FAILED + PENDING_MANUAL_REVIEW
```

Future standard:

- New workflow steps must have a clear `WorkflowStep` value.
- New statuses should map through `stage_for_status()`.
- Step failures must be visible in ticket state and audit logs.
- Retrying the same source event must not create duplicate tickets.

## Module Boundaries

### Event

Current owner:

- `app.event.normalizer`
- `app.schemas.event.EventNormalized`

Current responsibilities:

- parse/normalize FDA event fields
- normalize FDA NDC values
- preserve FDA source product text as `product_description`
- produce `drug_name`
- track fallback recall numbers with `recall_number_is_fallback`

Future standard:

- Keep `event_id`, `openfda_id`, and `recall_number` distinct.
- Do not infer `product_description` from `drug_name`.
- Do not treat fallback recall numbers as source recall numbers.
- Add tests when event identity rules change because they affect idempotency and
  retrieval filters.

### Inventory

Current owner:

- `app.inventory.matcher`
- `app.inventory.impact`
- `app.schemas.inventory`

Current responsibilities:

- match event drug/NDC/lot against internal inventory
- return match confidence, matched rows, and identity-review signals
- calculate department impact, quantity, urgency, and priority

Future standard:

- `matched=false` must not automatically mean no impact.
- Inventory should explain uncertainty through fields such as confidence,
  `needs_identity_review`, and review reason.
- No-match auto-close should stay conservative, especially for high-risk recall
  events.
- If inventory matching adds brand/generic, RxNorm, freshness, or lot logic,
  keep those semantics inside inventory, not orchestration.

### RAG / Evidence

Current owner:

- `app.rag.*`
- `app.rag.adapter`
- `app.schemas.evidence`
- `app.orchestration.retrieval_identity`

Current responsibilities:

- build/use `RetrievalContext`
- retrieve evidence chunks
- return citations and sufficiency signals
- convert RAG results into ticket state fields

Current orchestration handoff:

- `normalized_drug_name` is resolved with
  `app.event.normalizer.sanitize_drug_name()`
- if `recall_number_is_fallback=True`, orchestration passes
  `recall_number=None` to avoid a false strong filter

Future standard:

- RAG owns filter fallback and scoring. Orchestration only passes context.
- Evidence results should expose enough signals for routing:
  `evidence_status`, `coverage_score`, `missing_sources`, `weak_sources`, and
  `citations_ready`.
- Evidence audit output should include query, context, filters, source coverage,
  chunk count, and citation readiness.

### Draft Generation

Current owner:

- draft generator passed into `run_ticket_workflow`
- `SimpleDraftGenerator` as the local fallback implementation

Current responsibilities:

- generate draft text from ticket context and evidence
- return draft citations
- persist generated draft to `ticket.draft_text`
- persist initial report version as `draft_v1`

Future standard:

- Draft output is never final.
- Drafts must remain evidence-backed and pharmacist-reviewable.
- If draft generation changes citation shape, update report/review handoff tests.

### Draft Safety

Current owner:

- `app.event.safety`
- `app.schemas.event.SafetyCheckResult`

Current responsibilities:

- inspect generated draft text
- return blocked sentence details and revised draft
- set `needs_action_review` when unsafe text is found

Current orchestration handoff:

```text
draft_safety_check(draft_text, lang="both")
```

Future standard:

- Safety check should run on generated pharmacist-facing draft text.
- Source evidence text may contain valid operational instructions; do not apply
  draft safety semantics to evidence text without a separate policy.
- Mixed Korean/English drafts should remain covered.

### Workflow Routing

Current owner:

- `app.workflow.routing`
- `app.workflow.policy`
- `app.schemas.workflow.ReviewDecision`

Current routes:

- `identity_review`
- `evidence_review`
- `action_review`
- `final_approval`
- `no_impact_close`

Future standard:

- Routing should prefer manual review when identity, evidence, or action text is
  uncertain.
- No-inventory-match auto-close must require enough confidence and evidence to
  support closure.
- New routing reasons should be included in policy audit output.

### Review / HITL

Current owner:

- `app.review.router`
- `app.review.approval`
- `app.review.tickets`
- `app.review.payload`

Current responsibilities:

- resolve public ticket IDs from API routes
- approve, reject, or revise reports
- save `final_v1` and `draft_v2` when applicable
- expose report and audit endpoints

Future standard:

- `get_review_payload()` should load real ticket state and build payloads by
  `review_type`.
- `WORKFLOW_FAILED` needs an explicit product decision: operator triage only or
  pharmacist-visible manual review payload.
- Approval actions should keep ticket status, approval rows, report versions,
  and audit logs consistent.

### Report Versioning

Current owner:

- `app.report.versioning`
- `app.db.models.report_version_model`

Current version flow:

```text
draft_v1 -> draft_v2 -> final_v1
```

Current model contract:

- `report_versions.ticket_id` references `tickets.id`
- report body is stored in `report_text`
- `created_by` may be accepted by service functions, but needs a model/migration
  change before persistence

Future standard:

- Keep one `final_v1` per ticket.
- If report metadata such as `created_by` or citations become persistent,
  introduce explicit migrations and tests.

### Audit

Current owner:

- `app.audit.logger`
- `app.db.models.audit_log_model`

Current responsibilities:

- persist workflow and approval traces
- record inputs, outputs, durations, and failure details
- expose traces for debugging and review

Future standard:

- Audit rows must explain why a workflow routed, closed, failed, or retried.
- Failure audit output should include error type, message, duration, and
  retryable flag when available.
- Retrieval and policy audit output should include the context needed to debug
  decision quality.

## Public Ticket ID vs Internal DB ID

Keep these separate in all future code:

```text
Ticket.ticket_id  -> public/business/API id, e.g. "T-..."
Ticket.id         -> internal integer primary key
```

Foreign-key columns use `Ticket.id`:

- `audit_logs.ticket_id`
- `approvals.ticket_id`
- `report_versions.ticket_id`

API routes should accept public `ticket_id` and resolve it with
`get_ticket_by_public_id()` before writing FK rows.

## Rules for Adding Workflow Code

When adding or changing a workflow step:

- define the owning module for domain logic
- keep orchestration as coordination only
- update status/stage transitions if needed
- write audit input/output with useful debugging fields
- decide retry behavior
- preserve idempotency for repeated source events
- add focused tests for success and failure paths
- run DB smoke checks if the change touches models, migrations, or FK handoff

Avoid adding these incidentally:

- seed data
- dashboard-only columns
- scheduler/background polling
- Celery, Redis, LangGraph, or another workflow engine
- broad folder restructuring
- unrelated RAG or inventory algorithm rewrites

## Known Follow-Ups

These are expected future work, not current hidden behavior:

- connect `get_review_payload()` to real ticket state for each `review_type`
- define `WORKFLOW_FAILED` display/triage behavior
- harden retrieval filter fallback and sufficiency scoring
- make inventory no-match confidence semantics explicit
- keep event identity contracts tested
- add workflow attempt/run identifiers if retries need clearer tracing
- revisit transaction boundaries before production external calls grow longer

## Verification

For workflow or handoff changes:

```powershell
pytest
```

For DB/migration-affecting changes:

```powershell
alembic upgrade head
alembic check
```

For manual smoke testing, one workflow should create or update:

- one `tickets` row
- step-level `audit_logs`
- one `draft_v1` row in `report_versions`
- no duplicate ticket when the same source event is processed again
