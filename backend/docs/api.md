# API Reference

Quick reference for every mounted HTTP endpoint. For the full request/response
JSON schema, always prefer the live Swagger UI at `/docs` (or `/openapi.json`) —
this file is a map of what exists and how the pieces connect, not a schema
dump.

See [workflow.md](workflow.md) for how the orchestration steps behave
internally.

## Typical local test flow

```text
POST /events/upload                      -> creates ticket (status=CREATED)
POST /tickets/{ticket_id}/run             -> runs the workflow (inventory, evidence, draft, safety, routing)
GET  /tickets/{ticket_id}                 -> consolidated status + per-step progress + can_rerun
GET  /tickets/{ticket_id}/evidence-trace  -> inspect evidence retrieval / gate / routing result
GET  /tickets/{ticket_id}/review          -> pharmacist review payload
POST /approval/{ticket_id}/approve        -> approve + create final_v1 report (ticket.status -> APPROVED)
```

`GET /tickets?recall_number=...` is a shortcut to find a ticket_id if you
forgot the one returned by `/events/upload`.

## Events (`app/event/router.py`)

| Method | Path | Description |
|---|---|---|
| POST | `/events/upload` | Normalize a single FDA recall JSON payload, dedupe by `recall_number` (in-memory, resets on server restart), and create/reuse the ticket row in Postgres. Returns `event_id`, `duplicated`, `ticket_id`. Does **not** run the workflow — ticket is left at `CREATED`. 409 if the same `recall_number` was already uploaded this server run. |
| POST | `/events/collect` | Manually triggers openFDA bulk collection (`app.event.collector.periodic_collect`) and runs the same normalize/dedupe/create-ticket pipeline for every fetched recall. Does not run the workflow either. |
| GET | `/events/latest` | Not implemented yet. |

## Tickets & Orchestration

| Method | Path | Source | Description |
|---|---|---|---|
| GET | `/tickets` | `app/review/router.py` | Query param `recall_number`. Looks up the most recent ticket for that recall number and returns `ticket_id`, `status`, `workflow_stage`, `created_at`. 404 if none found. |
| GET | `/tickets/{ticket_id}` | `app/review/router.py` (`ticket_detail.py`) | Consolidated view for the workflow-execution screen: ticket status/priority/review_type, `can_rerun` (true only when `CREATED`/`WORKFLOW_FAILED`), `failure_reason` if the workflow failed, and a `steps` array (one entry per `inventory_match`/`evidence_retrieval`/`sufficiency_check`/`draft_generation`/`safety_check`/`policy_aggregation` — `pending`/`succeeded`/`failed`/`skipped` + duration + reason), built from `audit_logs`. Saves the frontend from stitching together `/run`, `/evidence-trace`, and `/audit` itself. |
| POST | `/tickets/{ticket_id}/run` | `app/orchestration/router.py` | Runs (or resumes) `run_ticket_workflow` for an existing ticket: inventory match -> evidence retrieval (Milvus + OpenAI embeddings) -> sufficiency check -> draft generation -> safety check -> policy routing. Only tickets in `CREATED` or `WORKFLOW_FAILED` are actually (re)processed; anything further along is returned unchanged (idempotent, see `can_rerun_workflow` in `app/workflow/state.py`). Returns `ticket_id`, final `status`, `message`. |
| GET | `/tickets/{ticket_id}/evidence-trace` | `app/rag/api.py` | Read-only debug view of the evidence retrieval step: gate status, routing reason, retrieval query/context, top chunks, citations. All fields are null until `/tickets/{ticket_id}/run` has executed the evidence step. |
| GET | `/tickets/{ticket_id}/review` | `app/review/router.py` | Pharmacist-facing review screen payload. Shape depends on `review_type` (`identity_review` / `evidence_review` / `action_review` / `final_approval`). `approval_status` reflects the latest row in `approvals` (not hardcoded). 404 if the ticket failed or `review_type` hasn't been determined yet (i.e. workflow hasn't reached policy routing). |

## Review & Approval (`app/review/router.py`)

| Method | Path | Body | Description |
|---|---|---|---|
| GET | `/approval/pending` | — | List tickets currently awaiting pharmacist approval. |
| POST | `/approval/{ticket_id}/approve` | `{ reviewer, comment? }` | Approves the ticket, persists the current draft as `final_v1`, and moves `ticket.status` to `APPROVED` (`workflow_stage` -> `CLOSED`). Fails if a `final_v1` already exists or no draft report is found. |
| POST | `/approval/{ticket_id}/reject` | `{ reviewer, comment }` | Rejects the ticket and moves `ticket.status` to `REJECTED` (`workflow_stage` -> `CLOSED`); `comment` is required. |
| POST | `/approval/{ticket_id}/revise` | `{ reviewer, revised_draft }` | Submits a pharmacist-edited draft, re-runs the safety check, saves `draft_v2`. Does not change `ticket.status` (stays in review). Response includes `safety_check_passed` and any `blocked_sentences`. |

## Audit & Reports (`app/review/router.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/audit/{ticket_id}` | Full step-by-step audit trace (why the ticket routed/failed/closed the way it did). |
| GET | `/reports/{ticket_id}/versions` | All report versions for the ticket (`draft_v1` -> `draft_v2` -> `final_v1`). |
| GET | `/reports/{ticket_id}` | Latest report version only. |

## Misc

| Method | Path | Description |
|---|---|---|
| GET | `/health-db` | Runs `SELECT 1` against Postgres; returns `{"db": "connected"}` or `{"db": "connection_error", ...}`. |

## Notes / known gaps

- `/events/upload` dedup is an in-memory set keyed on `recall_number` — it resets on server restart. Ticket-level idempotency (by `recall_number`/`ndc`/`lot` or `openfda_id`) is enforced separately and durably in Postgres via `get_or_create_ticket_record`.
- There is currently no endpoint to auto-run the workflow right after upload — `/events/upload` and `/events/collect` only create the ticket row; `/tickets/{ticket_id}/run` must be called explicitly. This was a deliberate choice to keep upload fast (evidence retrieval calls OpenAI + Milvus and can be slow).
- `/tickets/{ticket_id}/run` requires the Milvus stack (`etcd`, `minio`, `milvus` services, `profiles: ["rag"]` in `docker-compose.yml`) to be running, plus a valid `OPENAI_API_KEY` for query embeddings.
- Draft generation is a placeholder: `SimpleDraftGenerator` (`app/orchestration/service.py`) produces a fixed-template sentence, not an LLM-written draft. Every review payload's `draft_text` reflects this until it's swapped for a real generator.
- Chat (`/chat/{ticket_id}`) is not implemented in this branch — `app/chat/` is an empty package. It exists as a reviewed-but-unmerged PR elsewhere; that version is single-turn only (no conversation history feeds back into retrieval or answer generation) and has known bugs (session-per-request instead of one session per ticket, missing `recall_number_is_fallback` handling) that need fixing before merge.
