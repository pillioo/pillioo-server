# Pillioo Backend Working Guide

This file is the short working contract for coding agents and contributors.
For the full workflow and future implementation standards, read
`docs/workflow.md`.

## Current Product Shape

Pillioo turns FDA recall/shortage-style events into pharmacist-reviewed
tickets. The backend flow is:

```text
FDA event -> event normalization -> ticket orchestration
-> inventory impact -> evidence retrieval -> draft generation
-> safety check -> routing policy -> pharmacist review/report/audit
```

The system is an MVP. Prefer explicit contracts, focused tests, safe handoff
behavior, and small PRs over adding framework complexity or broad refactors.

## Hard Boundaries

- Do not introduce Celery, Redis, LangGraph, or a new workflow engine unless the
  team explicitly scopes that work.
- Do not add seed data as part of orchestration/retrieval/review PRs.
- Do not add dashboard-only columns unless the PR is specifically about the
  dashboard contract.
- Keep public ticket ids such as `T-...` separate from DB foreign keys.
  `audit_logs.ticket_id`, `approvals.ticket_id`, and `report_versions.ticket_id`
  point to `tickets.id`.
- `product_description` is source FDA product text. Do not silently infer it
  from `drug_name`.
- `recall_number_is_fallback=True` means the value came from `event_id`; do not
  use it as a strong recall-number retrieval filter.
- Drug identity normalization for retrieval should reuse
  `app.event.normalizer.sanitize_drug_name()`.

## Workflow Contracts

- Orchestration coordinates steps; it should not own domain matching or RAG
  scoring logic.
- Workflow routing policy belongs under `app/workflow/`.
- RAG retrieval owns filter fallback, citation readiness, and sufficiency
  scoring.
- Inventory owns match confidence, identity uncertainty, and no-match reasons.
- Review owns pharmacist-facing payloads and approval/revision actions.
- Report versioning persists `draft_v1`, `draft_v2`, and `final_v1`.
- Audit logs should explain why a ticket was routed, failed, or closed.

## Future-Code Standards

- Every new workflow step needs an owner, audit output, failure behavior, and
  tests.
- Public route ids (`T-...`) must be resolved to `Ticket.id` before writing FK
  rows.
- New routing logic belongs in `app/workflow/`, not directly in orchestration
  step code.
- New retrieval quality logic belongs in RAG modules; orchestration only passes
  context.
- New inventory identity logic belongs in inventory modules; orchestration only
  consumes match/confidence/review signals.

## Verification

Run at least:

```powershell
pytest
```

For DB-affecting changes, also run against a local/test Postgres database:

```powershell
alembic upgrade head
alembic check
```

When touching orchestration handoff, verify that one workflow creates:

- one `tickets` row
- step-level `audit_logs`
- `report_versions` row for `draft_v1`
- no duplicate ticket for the same source event
