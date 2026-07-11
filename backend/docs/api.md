# API Reference

API summary for frontend implementation and Swagger UI (`/docs`) testing.
For exact request/response schemas, use `/openapi.json` or the live Swagger UI.

Related docs:

- [workflow.md](workflow.md): workflow status and rerun policy
- [api-test-flow.md](api-test-flow.md): Swagger test sequence
- [evidence-retrieval.md](evidence-retrieval.md): RAG/evidence retrieval details

## Frontend Flow

```text
POST /events/upload                       -> create a ticket
GET  /tickets                             -> list, search, and filter tickets
POST /tickets/{ticket_id}/run             -> run the workflow
GET  /tickets/{ticket_id}                 -> ticket detail, workflow steps, timeline basics
GET  /tickets/{ticket_id}/evidence        -> RAG/evidence verification panel
GET  /reports/{ticket_id}                 -> report viewer
GET  /tickets/{ticket_id}/review          -> pharmacist review screen
POST /chat/{ticket_id}                    -> ticket-aware evidence chat
POST /approval/{ticket_id}/approve        -> approve and freeze final_v1
GET  /reports/{ticket_id}/versions        -> draft/final version history
GET  /audit/{ticket_id}                   -> detailed audit timeline
```

Use the public `ticket_id` (`T-...`) as the frontend route key. Some responses
also expose internal integer ids, but URL path parameters should use the public
`ticket_id` unless an endpoint explicitly says otherwise.

## Screen-To-API Map

| Screen | Primary API | Frontend notes |
|---|---|---|
| Event upload | `POST /events/upload` | Use returned `ticket_id`; handle duplicate/409; workflow must be run separately. |
| Event feed | `GET /events/latest` | Use `ticket_id`, `can_run`, `product_description`, and `raw_event_data`. |
| Ticket list | `GET /tickets` | Supports filters, search, pagination, and clickable public `ticket_id`. |
| Ticket detail | `GET /tickets/{ticket_id}` | Use `status`, `workflow_stage`, `can_rerun`, `steps`, and `failure_reason`. |
| Workflow run | `POST /tickets/{ticket_id}/run` | Depends on Milvus/OpenAI-compatible settings; handle run failures. |
| Evidence verification | `GET /tickets/{ticket_id}/evidence` | Use `evidence_status`, `weak_sources`, `failure_reasons`, and `selected_chunks`. |
| Report | `GET /reports/{ticket_id}` | Prefer structured `report`; fall back to `report_text`. |
| Review | `GET /tickets/{ticket_id}/review` | Payload shape depends on `review_type`. |
| Chat | `POST /chat/{ticket_id}` | Use `answer`, `sources`, planning/debug fields, and `session_id`. |
| Approval | `/approval/*` | Pending rows may be empty; verify `final_v1` after approve. |
| Dashboard | `GET /dashboard/summary` | Use counts and queues; design empty states as normal states. |
| Audit | `GET /audit/{ticket_id}` | Use `title`, `message`, `severity`, and `status` for timeline UI. |

## Events

| Method | Path | Description |
|---|---|---|
| POST | `/events/upload` | Normalizes and deduplicates one recall payload, then creates or reuses a ticket row. Returns `event_id`, `duplicated`, and `ticket_id`. Does not run the workflow. |
| POST | `/events/collect` | Manually collects openFDA data. This is closer to an admin/developer trigger than a core frontend user flow. Does not run the workflow. |
| GET | `/events/latest?limit=20` | Returns a recent ticket-backed event feed. Includes `ticket_id`, `source`, `is_duplicate`, `product_description`, `recall_reason`, `can_run`, `raw_event_data`, and `created_at`. |

Frontend notes:

- After `/events/upload`, use the returned `ticket_id` to navigate to `/tickets/{ticket_id}` or trigger `/tickets/{ticket_id}/run`.
- `tickets_created=0` from `/events/collect` does not necessarily mean orchestration failed. It is usually a collect/dedup/event-processing result.
- `/events/latest` is a ticket-backed recent feed, not a raw event-source feed. Click-through navigation should use `ticket_id`.

## Tickets & Orchestration

| Method | Path | Source | Description |
|---|---|---|---|
| GET | `/tickets` | `app/review/router.py` | Frontend list/search API. Optional filters: `status`, `review_type`, `priority`, `recall_number`, and free-text `q`. Pagination: `limit` (default 20, max 100), `offset`. Sorted newest first. |
| GET | `/tickets/{ticket_id}` | `app/review/ticket_detail.py` | Base payload for the ticket detail screen. Returns ticket status, priority, review type, rerun eligibility, failure reason, and workflow step status. |
| POST | `/tickets/{ticket_id}/run` | `app/orchestration/router.py` | Runs or reruns the workflow: inventory, RAG evidence, sufficiency, report generation, safety, and policy routing. Already-processed tickets may return the existing state idempotently. |
| GET | `/tickets/{ticket_id}/review` | `app/review/router.py` | Pharmacist review screen payload. Required data varies by `review_type`. |

`GET /tickets` response:

```json
{
  "items": [
    {
      "ticket_id": "T-...",
      "status": "REVIEW_ROUTED",
      "workflow_stage": "PENDING_REVIEW",
      "drug_name": "fentanyl",
      "ndc": "71449007241",
      "lot": "2331062",
      "classification": "class_i",
      "recall_number": "D-0277-2024",
      "priority": "HIGH",
      "review_type": "identity_review",
      "created_at": "2026-07-11T12:01:44.502340",
      "updated_at": null
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

Frontend notes:

- `updated_at` can be `null` when a ticket has never been updated after creation.
- `POST /tickets/{ticket_id}/run` depends on Milvus and OpenAI-compatible settings. If Milvus is down, the backend will fail to connect to `localhost:19530`.
- Prefer the `can_rerun` value from `/tickets/{ticket_id}` instead of reimplementing status logic on the frontend.

## Evidence / RAG

| Method | Path | Description |
|---|---|---|
| GET | `/tickets/{ticket_id}/evidence` | Ticket-level durable evidence snapshot. This is the primary data source for the frontend Evidence/RAG verification panel. |
| GET | `/tickets/{ticket_id}/evidence-trace` | Debugging view reconstructed from audit logs and ticket JSON. Useful for operational troubleshooting. |

Core fields from `GET /tickets/{ticket_id}/evidence`:

| Field | Meaning |
|---|---|
| `snapshot_type` | Usually `workflow_evidence`. Legacy tickets may return `legacy_ticket_evidence`. |
| `source_audit_log_id` | Sufficiency-check audit log id that produced this evidence decision. |
| `evidence_status` | `sufficient` or `insufficient`. |
| `coverage_score` | Ratio of found sources to required sources. |
| `citations_ready` | Whether source/content fields needed for citations are available. |
| `required_sources` | Source types required for the current ticket/event type. |
| `found_sources` | Source types found by retrieval. |
| `missing_sources` | Required source types that were not found. |
| `weak_sources` | Source types found but not strong enough for a reliable decision. |
| `failure_reasons` | Reasons for insufficient, weak, or citation-not-ready states. |
| `selected_chunks` | Evidence chunks that the frontend should render in the evidence view. |
| `retrieval_context` | Ticket context used to build the retrieval query. |
| `retrieval_plan` | Target document type/section plan. |
| `retrieval_trace` | Debugging metadata: filter attempts, selected chunks, rank reasons, and related signals. |

Hybrid reranking metadata example:

```json
{
  "document_type": "recall_notice",
  "section": "recall_notice",
  "similarity_score": 0.551,
  "rank_score": 1.0477,
  "filter_level": "strong_identifier_section",
  "rank_reasons": [
    "lexical_overlap",
    "required_document_type",
    "required_section",
    "recall_number_match",
    "lot_match"
  ],
  "matched_identifiers": {
    "recall_number": "D-0277-2024",
    "lot": "2331062"
  },
  "lexical_overlap_score": 0.0667,
  "lexical_overlap_terms": ["0277", "2024", "class", "recall"]
}
```

Frontend notes:

- In the Evidence panel, show `evidence_status`, `weak_sources`, and `failure_reasons` before the raw chunks.
- For recall tickets, treat a `recall_notice` with `filter_level=section` and empty `matched_identifiers` as weak evidence.
- If `rank_reasons` includes `fallback_penalty`, consider showing a warning that the recall notice may not strongly match the ticket.
- `retrieval_trace.filter_attempts` is best placed in a debug drawer/collapsible area rather than the primary user view.

## Reports

Reports are stored per version in `report_versions`. The current structure stores
a structured `DraftReport` in `report_json` and also provides `report_text` for
legacy/plain-text consumers.

| Method | Path | Description |
|---|---|---|
| GET | `/reports/{ticket_id}` | Returns the latest report version. |
| GET | `/reports/{ticket_id}/versions` | Returns all report versions for the ticket: `draft_v1`, optional `draft_v2`, and optional `final_v1`. |

ReportVersion core fields:

| Field | Meaning |
|---|---|
| `version_tag` | `draft_v1`, `draft_v2`, or `final_v1`. |
| `report_text` | Fallback/plain-text display. |
| `report` | Structured `DraftReport`, exposed through the `report_json` validation alias. |
| `created_by` | Version creator. |
| `change_summary`, `change_reason`, `reviewer_comment` | `draft_v2` revision metadata. |
| `safety_check_result` | Revision safety-check result. |
| `approved_by`, `approved_at`, `approval_comment`, `source_version` | `final_v1` approval metadata. |

Structured report sections:

- `title`
- `summary`
- `affected_product`
- `event_classification`
- `inventory_impact`
- `evidence_summary`
- `recommended_review_action`
- `pharmacist_checklist`
- `citations`
- `pharmacist_notes`
- `safety_notes`
- `limitations`

Frontend notes:

- Prefer rendering structured `report` when present. Fall back to `report_text` for legacy rows.
- `final_v1` is an exact freeze of the approved draft. It is not regenerated by the LLM at approval time.
- Legacy rows may only have `report_text` and no structured `report`.

## Review & Approval

| Method | Path | Body | Description |
|---|---|---|---|
| GET | `/approval/pending` | n/a | Lists `Approval(status=pending)` rows. `ticket_id` is the public id; `internal_id` is the internal foreign key. |
| POST | `/approval/{ticket_id}/approve` | `{ reviewer, comment? }` | Freezes the latest draft as `final_v1` and approves the ticket. |
| POST | `/approval/{ticket_id}/reject` | `{ reviewer, comment }` | Rejects the ticket. `comment` is required. |
| POST | `/approval/{ticket_id}/revise` | `{ reviewer, revised_draft, comment? }` | Saves pharmacist-edited text as `draft_v2` after safety check. |
| POST | `/approval/{ticket_id}/revise-with-llm` | `{ reviewer, reviewer_comment }` | Applies bounded LLM revision to the latest structured report, runs safety check, and saves `draft_v2`. |

Frontend notes:

- `/approval/pending` can be empty under the current workflow policy. A `review_type=final_approval` ticket does not always imply that a pending `Approval` row exists.
- For an approval queue, decide whether to rely only on `/approval/pending` or also query `GET /tickets?status=REVIEW_ROUTED&review_type=final_approval`.
- `revise-with-llm` can return a `NO_STRUCTURED_REPORT`-style error if the latest report version has no structured `report`.

## Chat

| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/chat/{ticket_id}` | `{ user_query, session_id?, top_k? }` | Ticket-aware evidence chat. Reuses one chat session per ticket. |
| GET | `/chat/{ticket_id}/history` | n/a | Returns the ticket chat history in chronological order. |

`ChatResponse` core fields:

| Field | Meaning |
|---|---|
| `session_id` | Session id to send with follow-up questions. |
| `answer` | LLM answer or deterministic fallback. |
| `sources` | Evidence citations used for the answer. |
| `intent` | Query intent classification. |
| `standalone_query` | Retrieval query rewritten with multi-turn context. |
| `answer_mode` | `ticket_state_only`, `retrieval_required`, or `hybrid`. |
| `target_profile` | Retrieval target profile. |
| `evidence_status` | Retrieved evidence status. |
| `answer_support_level` | Answer support/debug signal. |

Frontend notes:

- Send `session_id=null` for the first message, then reuse the returned `session_id` for follow-up turns.
- If `sources` is empty or `answer_support_level` is low, show an "insufficient support" state instead of presenting the answer as fully grounded.
- Chat quality depends on Milvus and LLM configuration, so local environments may differ.

## Inventory

| Method | Path | Description |
|---|---|---|
| GET | `/inventory/impact/{ticket_id}` | Recomputes inventory match, impact, and quality check from the ticket drug/NDC/lot. |

Response shape:

- No match: `{ ticket_id, matched: false, message }`
- Match: `{ ticket_id, match_result, impact_result, quality_result }`

Frontend notes:

- This endpoint is suitable for a ticket detail inventory panel.
- Dashboard `inventory_impact` is a summary derived from available ticket fields. For detailed inventory display, refetch this endpoint per ticket.

## Dashboard

| Method | Path | Description |
|---|---|---|
| GET | `/dashboard/summary` | Counts and operational queues for the dashboard landing screen. |

Current response fields:

| Field | Meaning |
|---|---|
| `total_tickets` | Total ticket count. |
| `by_status` | Count by ticket status. |
| `by_review_type` | Count by review type. |
| `pending_approvals` | Count of `Approval(status=pending)` rows. |
| `workflow_failed` | Count of workflow-failed tickets. |
| `high_priority` | Count of HIGH priority tickets. |
| `today_created` | Tickets created today according to the server date. |
| `evidence_review_pending` | Count of `review_type=evidence_review` and `status=REVIEW_ROUTED` tickets. |
| `urgent_tickets` | Up to five non-closed HIGH priority tickets. |
| `recent_failures` | Recent workflow-failed tickets. |
| `recent_tickets` | Recent tickets. |
| `evidence_queue` | Evidence-review tickets with weak/citation summary. |
| `review_approval_queue` | Pending approvals, revision candidates, and safety-check-failed tickets. |
| `inventory_impact` | Impacted/exact/possible/high-impact inventory summary. |

Frontend notes:

- `today_created` uses the server date. If the UI uses Asia/Seoul and the DB/server date differs, counts can appear one day off.
- `pending_approvals=0` can still coexist with `review_type=final_approval` tickets. Keep the Approval-row queue policy separate from the ticket review queue policy.
- `inventory_impact.impacted_count=0` can be valid. The mock inventory may not contain matching NDC/lot data, or the dashboard summary may not have enough ticket-level inventory fields yet.
- Design empty states as normal states, e.g. `evidence_queue.tickets=[]` or `recent_failures=[]`.

## Audit & Health

| Method | Path | Description |
|---|---|---|
| GET | `/audit/{ticket_id}` | Workflow/approval audit trace ordered by `created_at`. Includes display fields suitable for timeline UI. |
| GET | `/health-db` | Database connection check. Returns `{ "db": "connected" }` or connection error details. |

Audit entry display fields:

| Field | Meaning |
|---|---|
| `title` | Human-readable step title. |
| `message` | Timeline message. |
| `severity` | `info`, `warning`, or `error`. |
| `status` | `succeeded`, `failed`, or `skipped`. |

Frontend notes:

- Timeline UI should primarily use `title`, `message`, `severity`, and `status`.
- Put raw `input_json` / `output_json` in a details drawer or debug panel.
- An empty audit trace can simply mean the workflow has not run for that ticket yet.

## Local Runtime Notes

`POST /tickets/{ticket_id}/run`, chat, and report generation depend on local or
external services.

If Milvus is down, you may see:

```text
Fail connecting to server on localhost:19530
```

Start Milvus:

```powershell
cd C:\pillioo\pillioo\backend
docker compose --profile rag up -d etcd minio milvus
```

If the Milvus collection is empty, load RAG chunks:

```powershell
cd C:\pillioo\pillioo\backend
.\.venv\Scripts\Activate.ps1
python -m scripts.rag.embedding.load_milvus --drop-existing
```

## Known Gaps

- `/events/upload` and `/events/collect` only create tickets. The frontend must call `/tickets/{ticket_id}/run` separately.
- `/events/collect` currently has limited result diagnostics. `tickets_created=0` is likely a dedup/existing/event-processing result.
- `/approval/pending` depends on the pending approval row policy. It can be empty even when `final_approval` tickets exist.
- Review payloads still contain flattened `draft_text` in some places. Prefer `/reports/{ticket_id}` and `/reports/{ticket_id}/versions` for structured report sections.
- Chat/RAG/report generation can fail or vary in quality when Milvus/OpenAI-compatible settings are missing.
- Legacy report rows may have `report_text` without structured `report`.
