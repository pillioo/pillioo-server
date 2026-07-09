# Evidence Retrieval Integration Design

This document defines the working direction for evidence retrieval improvements.
It is not a code walkthrough. Use it as the contract for how retrieval connects
to event normalization, orchestration, inventory, drafting, review, report
versioning, audit logs, and future chat features.

## 1. Purpose

Evidence retrieval should provide enough grounded, citation-ready context for
workflow routing and pharmacist review.

The retrieval layer must answer three questions:

- What evidence is relevant to this ticket?
- Is the evidence complete enough for the workflow to proceed?
- Can downstream draft/review/chat responses cite the evidence reliably?

Retrieval quality directly affects:

- `evidence_review` routing
- draft generation quality
- pharmacist trust in citations
- auditability of why a ticket was routed or approved
- future ticket-scoped evidence chat

## 2. Current Status

Current implemented pieces:

- `RetrievalContext` carries event/ticket identity fields.
- `EvidenceRouter` maps event type to required document types and target
  sections.
- `MetadataFilterBuilder` builds metadata filter fallback levels.
- `MilvusCandidateRetriever` retrieves vector candidates.
- `MetadataAwareReranker` promotes identifier, document-type, section, and
  citation-quality matches.
- `EvidenceSetBuilder` deduplicates/selects a final evidence set.
- `SufficiencyChecker` reports required, found, missing, weak document types,
  coverage score, evidence status, and citation readiness.
- Orchestration passes `normalized_drug_name` using
  `app.event.normalizer.sanitize_drug_name()`.
- Orchestration avoids using fallback recall numbers as strong recall filters.

Known limitations:

- Hybrid search is not yet implemented as a first-class strategy.
- Filter fallback quality needs more evaluation against real/golden queries.
- Reranking is metadata-aware but not yet calibrated against retrieval metrics.
- Ticket-scoped chat is not yet connected.
- Citation-aware response generation still needs a clear contract.
- Inventory no-match and retrieval sufficiency need coordinated test scenarios.

## 3. Retrieval Role in Workflow

Retrieval runs after inventory impact and before draft generation.

```text
TicketState + EventNormalized
  -> RetrievalContext
  -> retrieval plan by event_type
  -> metadata-filtered vector retrieval
  -> reranking
  -> evidence set selection
  -> sufficiency check
  -> TicketState.evidence_result + TicketState.sufficiency_check
```

Retrieval should not decide the final review route by itself. It should return
structured signals that policy routing can consume:

- `evidence_status`
- `coverage_score`
- `required_document_types`
- `found_document_types`
- `missing_document_types`
- `weak_document_types`
- `citations_ready`
- top chunks and citations

Routing logic belongs in `app.workflow.*`. Retrieval owns evidence quality
signals.

## 4. Interface with Other Modules

### Event Normalization

Inputs from event:

- `event_type`
- `drug_name`
- `product_description`
- `classification`
- `ndc`
- `lot`
- `recall_number`
- `recall_number_is_fallback`

Contracts:

- Retrieval identity should use the same normalized drug-name convention as RAG
  metadata.
- If `recall_number_is_fallback=True`, do not use it as a strong recall-number
  metadata filter.
- `product_description` is FDA source text. It can help query construction, but
  should not replace normalized identity fields.

### Orchestration

Orchestration responsibilities:

- Build and pass `RetrievalContext`.
- Pass `top_k`.
- Store evidence result and sufficiency result on the ticket.
- Write retrieval audit output.
- Route later through policy aggregation.

Retrieval responsibilities:

- Plan target document types and sections.
- Apply metadata filtering/fallback.
- Retrieve, rerank, dedupe, and select chunks.
- Compute sufficiency.

Orchestration should not duplicate retrieval scoring or filter fallback logic.

### Inventory

Relevant inventory signals:

- `matched`
- `match_confidence`
- `match_type`
- `needs_identity_review`
- `matched_rows`
- `ndc`
- `lot`

Contracts:

- Inventory and retrieval use identity signals differently.
- NDC/lot can strengthen retrieval relevance and reranking, but should be used
  carefully as hard filters because source metadata can be incomplete.
- If inventory identity is uncertain, retrieval can still provide evidence, but
  routing should preserve identity review.

### Draft Generation

Draft generation consumes:

- selected evidence chunks
- citations
- ticket context
- sufficiency status

Contracts:

- Draft text must be grounded in retrieved evidence.
- Generated draft is not final.
- Citation fields must be complete enough for review/report display.

### Draft Safety

Draft safety consumes generated draft text, not raw evidence.

Contracts:

- Source evidence may contain valid instructions such as quarantine, disposal,
  or do-not-use language.
- Do not treat evidence-source text with the same policy as generated
  pharmacist-facing draft text unless a separate evidence-safety policy is
  defined.

### Review / HITL

Review payloads should show:

- why evidence was sufficient or insufficient
- missing/weak document types
- top chunks/citations
- source paths and sections
- routing reason

For `evidence_review`, the reviewer should see exactly what evidence was
missing or weak.

### Audit

Retrieval audit output should include:

- query
- `top_k`
- retrieval context
- target document types and sections
- filter expressions and filter levels used
- chunk count before/after reranking if available
- selected chunk count
- evidence status
- coverage score
- found/missing/weak sources
- citation readiness

Audit should make it possible to debug why a ticket was routed to
`evidence_review`.

## 5. Data and DB Relationship

Primary DB handoff:

- `tickets.evidence_result`
- `tickets.sufficiency_check`
- `audit_logs.input_json`
- `audit_logs.output_json`

RAG storage:

- Evidence chunks are stored in Milvus/vector storage.
- Chunk metadata should align with fields described in `docs/rag-datasets.md`.

Important metadata fields:

- `document_type`
- `event_types`
- `section`
- `section_title`
- `source_path`
- `drug_name`
- `normalized_drug_name`
- `rxnorm_rxcui`
- `classification`
- `ndc`
- `lot`
- `recall_number`
- `content_hash`

DB identifier boundary:

- retrieval receives public workflow context through `TicketState`
- audit/report FK rows use internal `tickets.id`
- retrieval metadata should not assume public ticket IDs unless implementing
  ticket-scoped retrieval/chat

## 6. Retrieval Flow

Target flow:

```text
1. Build RetrievalContext
2. Route event type to EvidencePlan
3. Build metadata filter levels
4. Retrieve candidates from vector store
5. Optionally combine dense + lexical/hybrid candidates
6. Dedupe candidates
7. Rerank candidates
8. Build final evidence set
9. Run sufficiency check
10. Return evidence result + audit fields
```

### Metadata Filtering

Current direction:

- Strong identifier filters when reliable:
  - source recall number for recall notices
  - RxNorm RXCUI for labels
  - normalized drug name for label/recall metadata
- Section-aware filters for target sections.
- Document-type fallback as the loosest filter.

Future standard:

- Filters should be ordered from precise to broad.
- Each returned chunk should preserve `filter_expr` and `filter_level`.
- Document-type-only results may count as weak evidence when required sections
  were not matched.
- Do not use fallback recall numbers as strong filters.

### Hybrid Search

Goal:

- Combine dense vector search with lexical or keyword search where useful.

Potential use cases:

- exact recall number
- exact NDC
- lot number
- section title
- policy phrase
- quoted user/chat query terms

Future standard:

- Hybrid search should be additive and auditable.
- The final chunk should record why it was selected or boosted.
- Hybrid scoring must not hide missing required document types.

### Reranking

Current direction:

- Metadata-aware reranking promotes:
  - required document type
  - required section
  - recall number match
  - NDC match
  - lot match
  - citation-ready chunks

Future standard:

- Reranking reasons should be visible in chunk metadata/audit.
- Reranking should not select only high-score chunks if required document types
  are missing.
- Regression tests should cover identity-match promotion and wrong-type
  demotion.

### Section-Aware Retrieval

Goal:

- Retrieve evidence from sections relevant to the event and decision point.

Examples:

- recall:
  - `recall_notice`
  - `evidence_requirements`
  - `required_actions`
  - `procedure`
  - `safety_controls`
- label update:
  - `warnings`
  - `contraindications`
  - `boxed_warning`
  - `dosage_and_administration`
- shortage:
  - `evidence_requirements`
  - `review_routing`
  - `procedure`

Future standard:

- Section matching should affect sufficiency, not only score.
- Required document type found only through loose document-type fallback should
  be considered weak.

### Document-Type Prioritization

Retrieval should preserve required document type coverage.

For recall, required evidence normally includes:

- `recall_notice`
- `policy`
- `sop`

For label update, required evidence normally emphasizes:

- `label`

For shortage, required evidence normally emphasizes:

- `policy`
- `sop`

Future standard:

- Final evidence selection should avoid returning five chunks from one document
  type while missing required types.
- Optional document types can enrich context but should not satisfy required
  coverage by themselves.

### Evidence Sufficiency Check

Sufficiency should answer:

- Were all required document types found?
- Were required sections found, or only broad fallback results?
- Are citations complete enough?
- Is coverage high enough for workflow routing?

Policy routing currently treats missing, weak, low-coverage, or
citation-incomplete evidence as needing review.

## 7. Chat Integration Plan

Future ticket-scoped chat should reuse retrieval rather than creating a
separate search path.

Proposed flow:

```text
ticket_id
  -> load Ticket/TicketState
  -> combine user query with ticket context
  -> build RetrievalContext
  -> retrieve ticket-relevant evidence
  -> generate citation-aware answer
  -> return answer + citations + source chunks
```

Chat-specific requirements:

- Scope retrieval to the ticket's event context.
- Preserve citations in every answer.
- Show when evidence is missing or insufficient.
- Avoid using chat to bypass pharmacist review or safety checks.
- If the user asks to rewrite a report, route through draft versioning and
  safety review rather than directly changing final content.

Future standard:

- Chat should share retrieval filters, reranking, and sufficiency logic with the
  workflow retrieval path.
- Chat answers should be citation-aware and should not invent unsupported
  operational instructions.

## 8. Test Strategy

### Unit Tests

Cover:

- `RetrievalContext` construction
- metadata filter levels
- escaping/sanitization of filter values
- reranking reason assignment
- dedupe behavior
- evidence set selection by required document type
- sufficiency status for missing/weak/citation-incomplete evidence
- adapter mapping into workflow schemas

### Integration-Style Tests with Fakes

Cover:

- orchestration passes normalized drug identity into retrieval
- fallback recall number is not used as a strong filter
- recall event retrieves required `recall_notice`, `policy`, `sop`
- missing `recall_notice` routes to `evidence_review`
- document-type-only fallback is marked weak
- citations not ready routes to `evidence_review`

### Golden Query Evaluation

Maintain a small set of golden queries/events with expected supports.

Each case should define:

- event type
- query
- retrieval context
- required document types
- required sections
- expected source/chunk patterns
- required citation fields
- minimum coverage score

Evaluate:

- top-k recall of expected evidence
- required document type coverage
- required section coverage
- citation readiness
- wrong-document-type suppression
- filter fallback path used

Suggested golden cases:

- Class I recall with exact recall number
- recall with fallback recall number only
- piperacillin / tazobactam normalized name
- sodium chloride protected normalized name
- missing recall notice
- label update requiring warnings/contraindications
- shortage requiring policy/SOP
- ticket-scoped chat question asking for quarantine basis

### DB / Milvus Smoke Tests

Before relying on retrieval in workflow demos:

- run Milvus collection field validation
- load a small evidence dataset
- retrieve one recall, one label update, and one shortage case
- verify selected chunks have source path, section, document type, and content
- run a workflow smoke test and confirm evidence audit fields are persisted

## 9. Open Questions

- What exact threshold should define low `coverage_score`?
- Should NDC and lot ever be hard filters, or remain reranker-only signals?
- How should hybrid dense/lexical scores be combined?
- Should chat retrieval allow broader filters than workflow retrieval?
- How should stale or partial inventory identity affect retrieval context?
- What is the minimum citation shape required for pharmacist review?
- Should evidence source text ever be safety-scanned, or only generated draft
  text?
- Should ticket-scoped retrieval persist per-ticket evidence snapshots, or
  retrieve live each time?

## 10. Future Improvements

Planned improvement areas:

- stronger metadata filtering and fallback audits
- hybrid search for exact identifiers and lexical phrases
- calibrated reranking with visible rank reasons
- section-aware sufficiency scoring
- document-type-balanced final evidence selection
- ticket-scoped retrieval for chat
- citation-aware answer generation
- golden query evaluation in CI
- retrieval quality dashboards or reports
- persisted retrieval attempt/run metadata if retries need deeper tracing

Do not make orchestration responsible for these improvements. Orchestration
should consume retrieval outputs and route based on structured signals.

