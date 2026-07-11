# API Reference

프론트 개발자가 Swagger UI(`/docs`)와 실제 화면 구현을 오가며 볼 수 있는 API 요약입니다.
정확한 request/response schema는 `/openapi.json` 또는 Swagger UI를 기준으로 확인하세요.

관련 문서:

- [workflow.md](workflow.md): workflow status/rerun 정책
- [api-test-flow.md](api-test-flow.md): Swagger 테스트 순서
- [evidence-retrieval.md](evidence-retrieval.md): RAG/evidence retrieval 상세

## 프론트 기본 플로우

```text
POST /events/upload                       -> 티켓 생성
GET  /tickets                             -> 목록/검색/필터
POST /tickets/{ticket_id}/run             -> workflow 실행
GET  /tickets/{ticket_id}                 -> 상세/진행 단계/timeline 기본 데이터
GET  /tickets/{ticket_id}/evidence        -> RAG evidence 검증 패널
GET  /reports/{ticket_id}                 -> report viewer
GET  /tickets/{ticket_id}/review          -> pharmacist review 화면
POST /chat/{ticket_id}                    -> ticket-aware evidence chat
POST /approval/{ticket_id}/approve        -> 승인/final_v1 freeze
GET  /reports/{ticket_id}/versions        -> draft/final version history
GET  /audit/{ticket_id}                   -> 상세 audit timeline
```

프론트에서 route key로 쓰는 ID는 항상 public `ticket_id`(`T-...`)를 우선 사용하세요.
일부 응답에 internal integer id가 같이 내려오더라도 URL path에는 public `ticket_id`를 넣는 것이 기본입니다.

## 화면별 API 매핑

| 화면 | 주 API | 프론트에서 봐야 할 것 |
|---|---|---|
| 이벤트 업로드 | `POST /events/upload` | `ticket_id`, duplicate/409 처리, workflow는 별도 실행 필요 |
| 이벤트 피드 | `GET /events/latest` | `ticket_id`, `can_run`, `product_description`, `raw_event_data` |
| 티켓 목록 | `GET /tickets` | 필터, 검색, pagination, 클릭 가능한 `ticket_id` |
| 티켓 상세 | `GET /tickets/{ticket_id}` | `status`, `workflow_stage`, `can_rerun`, `steps`, `failure_reason` |
| Workflow 실행 | `POST /tickets/{ticket_id}/run` | 실행 성공/실패, Milvus/OpenAI 설정 의존성 |
| Evidence 검증 | `GET /tickets/{ticket_id}/evidence` | `evidence_status`, `weak_sources`, `failure_reasons`, `selected_chunks` |
| Report | `GET /reports/{ticket_id}` | structured `report`, `report_text`, version metadata |
| Review | `GET /tickets/{ticket_id}/review` | `review_type`별 payload 차이 |
| Chat | `POST /chat/{ticket_id}` | `answer`, `sources`, planning/debug fields, `session_id` |
| Approval | `/approval/*` | pending row가 없을 수 있음, approve 후 `final_v1` 확인 |
| Dashboard | `GET /dashboard/summary` | counts + queues + empty state 처리 |
| Audit | `GET /audit/{ticket_id}` | timeline용 `title`, `message`, `severity`, `status` |

## Events

| Method | Path | Description |
|---|---|---|
| POST | `/events/upload` | 단일 recall payload를 normalize/dedup 후 ticket row를 생성 또는 재사용합니다. 성공 시 `event_id`, `duplicated`, `ticket_id`를 반환합니다. Workflow는 실행하지 않습니다. |
| POST | `/events/collect` | openFDA 데이터를 수동 수집합니다. 현재 프론트 핵심 플로우보다는 관리자/개발자용 trigger에 가깝습니다. Workflow는 실행하지 않습니다. |
| GET | `/events/latest?limit=20` | 최근 ticket 기반 event feed를 반환합니다. `ticket_id`, `source`, `is_duplicate`, `product_description`, `recall_reason`, `can_run`, `raw_event_data`, `created_at` 포함. |

프론트 코멘트:

- `/events/upload` 후 바로 상세 화면으로 이동하려면 응답의 `ticket_id`로 `/tickets/{ticket_id}` 또는 `/tickets/{ticket_id}/run`을 호출하세요.
- `/events/collect`의 `tickets_created`가 0이어도 orchestration 실패라고 보기는 어렵습니다. collect/dedup/event 처리 단계의 결과일 가능성이 큽니다.
- `/events/latest`는 이벤트 원본 feed라기보다 ticket 기반 최근 feed입니다. 클릭 동작은 `ticket_id` 기준으로 연결하세요.

## Tickets & Orchestration

| Method | Path | Source | Description |
|---|---|---|---|
| GET | `/tickets` | `app/review/router.py` | 프론트 목록/검색 API. Optional filters: `status`, `review_type`, `priority`, `recall_number`, free-text `q`. Pagination: `limit`(default 20, max 100), `offset`. 최신순 정렬. |
| GET | `/tickets/{ticket_id}` | `app/review/ticket_detail.py` | 상세 화면 기본 payload. Ticket 상태, priority, review type, rerun 가능 여부, 실패 사유, step 진행 상태를 반환합니다. |
| POST | `/tickets/{ticket_id}/run` | `app/orchestration/router.py` | workflow 실행 또는 재실행. Inventory, RAG evidence, sufficiency, report generation, safety, policy routing을 진행합니다. 이미 처리된 ticket은 idempotent하게 기존 상태를 반환할 수 있습니다. |
| GET | `/tickets/{ticket_id}/review` | `app/review/router.py` | pharmacist review 화면 payload. `review_type`에 따라 필요한 정보가 달라집니다. |

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

프론트 코멘트:

- `updated_at`은 ticket이 한 번도 update되지 않았으면 `null`일 수 있습니다.
- `POST /tickets/{ticket_id}/run`은 Milvus와 OpenAI-compatible 설정에 의존합니다. Milvus가 꺼져 있으면 `localhost:19530` 연결 에러가 납니다.
- `can_rerun`은 직접 status를 해석하지 말고 `/tickets/{ticket_id}`의 값을 우선 사용하세요.

## Evidence / RAG

| Method | Path | Description |
|---|---|---|
| GET | `/tickets/{ticket_id}/evidence` | ticket-level durable evidence snapshot. 프론트 Evidence/RAG 검증 패널의 주 데이터입니다. |
| GET | `/tickets/{ticket_id}/evidence-trace` | audit log와 ticket JSON 기반 debugging view. 운영 troubleshooting용으로 유용합니다. |

`GET /tickets/{ticket_id}/evidence` 핵심 필드:

| Field | Meaning |
|---|---|
| `snapshot_type` | 보통 `workflow_evidence`. Legacy ticket은 `legacy_ticket_evidence`일 수 있습니다. |
| `source_audit_log_id` | 해당 evidence decision을 만든 sufficiency-check audit log id. |
| `evidence_status` | `sufficient` 또는 `insufficient`. |
| `coverage_score` | required source 대비 found source 비율. |
| `citations_ready` | citation에 필요한 source/content가 준비되었는지. |
| `required_sources` | 현재 ticket/event type에서 필요한 source type. |
| `found_sources` | 실제 찾은 source type. |
| `missing_sources` | 없는 source type. |
| `weak_sources` | 찾았지만 충분히 강하지 않은 source type. |
| `failure_reasons` | insufficient/weak/citation failure 이유. |
| `selected_chunks` | 프론트가 보여줄 실제 evidence chunks. |
| `retrieval_context` | query에 사용된 ticket context. |
| `retrieval_plan` | target document type/section plan. |
| `retrieval_trace` | filter attempts, selected chunks, rank reasons 등 debugging metadata. |

Hybrid reranking metadata 예시:

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

프론트 코멘트:

- Evidence 패널에서는 `evidence_status`, `weak_sources`, `failure_reasons`를 먼저 보여주는 것이 좋습니다.
- Recall ticket에서 `recall_notice`가 `filter_level=section`이고 `matched_identifiers={}`라면 약한 근거로 보여주세요.
- `fallback_penalty`가 `rank_reasons`에 있으면 wrong recall notice 가능성을 표시할 수 있습니다.
- `retrieval_trace.filter_attempts`는 일반 사용자보다는 debug drawer/collapsible 영역에 넣는 것을 권장합니다.

## Reports

Report는 `report_versions`에 version별로 저장됩니다. 최신 구조는 structured `DraftReport`를 `report_json`에 저장하고, legacy/plain-text 소비자를 위해 `report_text`도 같이 제공합니다.

| Method | Path | Description |
|---|---|---|
| GET | `/reports/{ticket_id}` | 최신 report version. |
| GET | `/reports/{ticket_id}/versions` | ticket의 모든 report versions. `draft_v1`, optional `draft_v2`, optional `final_v1`. |

ReportVersion 핵심 필드:

| Field | Meaning |
|---|---|
| `version_tag` | `draft_v1`, `draft_v2`, `final_v1`. |
| `report_text` | fallback/plain-text display. |
| `report` | structured `DraftReport`. `report_json`에서 validation alias로 내려옵니다. |
| `created_by` | version 생성 주체. |
| `change_summary`, `change_reason`, `reviewer_comment` | draft_v2 revision metadata. |
| `safety_check_result` | revision safety check 결과. |
| `approved_by`, `approved_at`, `approval_comment`, `source_version` | final_v1 approval metadata. |

Structured report section:

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

프론트 코멘트:

- 가능하면 `report`를 우선 렌더링하고, 없으면 `report_text`를 fallback으로 사용하세요.
- `final_v1`은 승인된 draft를 그대로 freeze한 버전입니다. 승인 후 다시 LLM으로 생성된 문서가 아닙니다.
- Legacy row는 `report`가 없고 `report_text`만 있을 수 있습니다.

## Review & Approval

| Method | Path | Body | Description |
|---|---|---|---|
| GET | `/approval/pending` | n/a | `Approval(status=pending)` row 목록. `ticket_id`는 public id, `internal_id`는 내부 FK입니다. |
| POST | `/approval/{ticket_id}/approve` | `{ reviewer, comment? }` | 최신 draft를 `final_v1`으로 freeze하고 ticket을 승인합니다. |
| POST | `/approval/{ticket_id}/reject` | `{ reviewer, comment }` | ticket을 reject합니다. `comment` 필수. |
| POST | `/approval/{ticket_id}/revise` | `{ reviewer, revised_draft, comment? }` | 약사가 직접 수정한 text를 safety check 후 `draft_v2`로 저장합니다. |
| POST | `/approval/{ticket_id}/revise-with-llm` | `{ reviewer, reviewer_comment }` | structured report가 있는 최신 version을 LLM으로 bounded revision하고 safety check 후 `draft_v2` 저장. |

프론트 코멘트:

- `/approval/pending`은 현재 workflow 정책상 비어 있을 수 있습니다. `review_type=final_approval` ticket이 있어도 pending approval row가 없으면 빈 배열이 정상일 수 있습니다.
- 승인 대기 화면을 만들 때는 `/approval/pending`만 볼지, `GET /tickets?status=REVIEW_ROUTED&review_type=final_approval`도 같이 볼지 정책을 정해야 합니다.
- `revise-with-llm`은 최신 report version에 structured `report`가 없으면 `NO_STRUCTURED_REPORT` 계열 에러가 날 수 있습니다.

## Chat

| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/chat/{ticket_id}` | `{ user_query, session_id?, top_k? }` | ticket-aware evidence chat. Ticket당 session을 재사용합니다. |
| GET | `/chat/{ticket_id}/history` | n/a | 해당 ticket의 chat history를 시간순으로 반환합니다. |

`ChatResponse` 핵심 필드:

| Field | Meaning |
|---|---|
| `session_id` | 다음 질문에서 이어가기 위한 session id. |
| `answer` | LLM answer 또는 deterministic fallback. |
| `sources` | answer에 사용된 evidence citations. |
| `intent` | query intent classification. |
| `standalone_query` | multi-turn context를 반영해 재작성된 retrieval query. |
| `answer_mode` | `ticket_state_only`, `retrieval_required`, `hybrid`. |
| `target_profile` | retrieval target profile. |
| `evidence_status` | retrieved evidence status. |
| `answer_support_level` | answer support/debug signal. |

프론트 코멘트:

- 첫 질문은 `session_id=null`, 후속 질문은 이전 응답의 `session_id`를 보내세요.
- `sources`가 비어 있거나 `answer_support_level`이 낮으면 “근거 부족” UI를 보여주는 것이 좋습니다.
- Chat은 Milvus와 LLM 설정에 의존하므로 로컬 환경별 품질 차이가 있을 수 있습니다.

## Inventory

| Method | Path | Description |
|---|---|---|
| GET | `/inventory/impact/{ticket_id}` | ticket의 drug/NDC/lot 기준으로 inventory match, impact, quality check를 재계산합니다. |

Response shape:

- match 없음: `{ ticket_id, matched: false, message }`
- match 있음: `{ ticket_id, match_result, impact_result, quality_result }`

프론트 코멘트:

- 상세 화면 inventory panel에서 사용하기 좋습니다.
- Dashboard의 `inventory_impact`는 현재 ticket JSON/available fields 기반 요약이라, 실제 상세 impact는 이 endpoint로 재조회하는 것이 안전합니다.

## Dashboard

| Method | Path | Description |
|---|---|---|
| GET | `/dashboard/summary` | counts + operational queues. Dashboard 첫 화면용 요약 API입니다. |

현재 응답 주요 필드:

| Field | Meaning |
|---|---|
| `total_tickets` | 전체 ticket 수. |
| `by_status` | status별 count. |
| `by_review_type` | review type별 count. |
| `pending_approvals` | `Approval(status=pending)` row count. |
| `workflow_failed` | workflow failure ticket count. |
| `high_priority` | priority HIGH count. |
| `today_created` | 서버 날짜 기준 오늘 생성 ticket count. |
| `evidence_review_pending` | `review_type=evidence_review`, `status=REVIEW_ROUTED` count. |
| `urgent_tickets` | 현재는 `priority=HIGH`이고 closed가 아닌 ticket 최대 5개. |
| `recent_failures` | 최근 workflow failed tickets. |
| `recent_tickets` | 최근 tickets. |
| `evidence_queue` | evidence review 대상 ticket과 weak/citation summary. |
| `review_approval_queue` | pending approvals, revision candidates, safety-check-failed tickets. |
| `inventory_impact` | impacted/exact/possible/high-impact inventory summary. |

프론트 코멘트:

- `today_created`는 서버 날짜 기준입니다. Asia/Seoul UI와 UTC/DB date가 다르면 하루 차이가 날 수 있습니다.
- `pending_approvals=0`이어도 `review_type=final_approval` ticket이 있을 수 있습니다. Approval row 정책과 ticket review queue 정책을 구분하세요.
- `inventory_impact.impacted_count=0`은 정상일 수 있습니다. Mock inventory에 해당 NDC/lot이 없거나 dashboard summary가 아직 ticket-level inventory JSON을 충분히 읽지 못하는 경우입니다.
- Empty state를 정상 케이스로 디자인하세요. 예: `evidence_queue.tickets=[]`, `recent_failures=[]`.

## Audit & Health

| Method | Path | Description |
|---|---|---|
| GET | `/audit/{ticket_id}` | workflow/approval audit trace. `created_at` 순서. Timeline UI에 바로 쓰기 좋은 display fields 포함. |
| GET | `/health-db` | DB connection check. `{ "db": "connected" }` 또는 connection error. |

Audit entry display fields:

| Field | Meaning |
|---|---|
| `title` | 사람이 읽기 쉬운 step title. |
| `message` | timeline message. |
| `severity` | `info`, `warning`, `error`. |
| `status` | `succeeded`, `failed`, `skipped`. |

프론트 코멘트:

- Timeline UI는 `title/message/severity/status`를 우선 사용하고, 상세 drawer에서 `input_json/output_json`을 보여주는 구성이 좋습니다.
- Audit이 비어 있으면 아직 workflow가 실행되지 않은 ticket일 수 있습니다.

## 로컬 실행 주의

`POST /tickets/{ticket_id}/run`, chat, report generation은 외부/로컬 서비스 설정에 의존합니다.

Milvus가 꺼져 있으면 다음과 같은 에러가 납니다:

```text
Fail connecting to server on localhost:19530
```

Milvus 실행:

```powershell
cd C:\pillioo\pillioo\backend
docker compose --profile rag up -d etcd minio milvus
```

Milvus collection이 비어 있으면 RAG chunk load가 필요합니다:

```powershell
cd C:\pillioo\pillioo\backend
.\.venv\Scripts\Activate.ps1
python -m scripts.rag.embedding.load_milvus --drop-existing
```

## Known Gaps

- `/events/upload`과 `/events/collect`는 ticket만 만들고 workflow는 실행하지 않습니다. 프론트는 반드시 `/tickets/{ticket_id}/run`을 별도로 호출해야 합니다.
- `/events/collect`는 현재 fetched count와 ticket creation 결과 해석이 제한적입니다. `tickets_created=0`은 dedup/existing/event 처리 결과일 가능성이 큽니다.
- `/approval/pending`은 pending approval row 정책에 의존합니다. `final_approval` ticket이 있어도 비어 있을 수 있습니다.
- Review payload는 아직 flattened `draft_text` 중심인 부분이 있습니다. 구조화된 report section은 `/reports/{ticket_id}`와 `/reports/{ticket_id}/versions`를 우선 사용하세요.
- Chat/RAG/report는 Milvus/OpenAI-compatible 설정이 없으면 실패하거나 품질이 낮을 수 있습니다.
- Legacy report row는 structured `report` 없이 `report_text`만 가질 수 있습니다.
