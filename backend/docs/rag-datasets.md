# RAG Evidence Datasets

This project generates four RAG evidence document datasets and one drug
identity reference cache:

- `label`
- `recall_notice`
- `sop`
- `policy`
- `identity` reference cache

The generated markdown and processed artifacts are local build outputs. They are
not committed to Git because they can be regenerated from scripts, YAML fixtures,
and openFDA raw data.

## Dataset Types

### Identity

Drug identity cache entries are generated from RxNorm lookups.

Generated cache output is written to:

```text
data/reference/drug_identity_cache.json
```

The cache maps raw drug names to normalized identity metadata:

- `raw_name`
- `normalized_drug_name`
- `rxnorm_rxcui`
- `rxnorm_name`
- `rxnorm_tty`
- `match_basis`

OpenFDA label and recall markdown generation uses this cache when available.
NDC and lot matching should still remain the strongest inventory matching
signals; RxNorm identity is a supporting signal for salt/form/name variation.

### Label

Label documents are generated from the openFDA drug label API.

Generated documents are written to:

```text
data/rag/documents/label/
```

Each label document includes frontmatter such as:

- `document_type: label`
- `event_type: label_update`
- `drug_name`
- `openfda_drug_name`
- `rxnorm_rxcui`
- `rxnorm_name`
- `rxnorm_tty`
- `product_ndc`
- `package_ndc`
- `route`
- `included_sections`
- `empty_sections`
- `source_record_id`

Label documents preserve useful label sections such as warnings,
contraindications, dosage, adverse reactions, drug interactions, storage, and
clinical pharmacology. Sections with placeholder-like content such as `None` or
`has not been formally studied` are excluded from the body and recorded in
`empty_sections` for traceability.

### Recall Notice

Recall notice documents are generated from the openFDA drug enforcement API.

Generated documents are written to:

```text
data/rag/documents/recall_notice/
```

Each recall notice document includes frontmatter such as:

- `document_type: recall_notice`
- `event_type: recall`
- `source_mode`
- `drug_name`
- `openfda_drug_name`
- `rxnorm_rxcui`
- `rxnorm_name`
- `rxnorm_tty`
- `classification`
- `reason_category`
- `recall_number`
- `status`
- `ndc`
- `lot`
- `lot_scope`
- `source_record_id`

Lot metadata is normalized for downstream inventory matching:

```text
code_info indicates all lots  -> lot: null, lot_scope: "all_lots"
code_info lists specific lots -> lot: "...", lot_scope: "specific_lots"
code_info is missing/unclear  -> lot: null, lot_scope: "unknown"
```

Empty NDC values are written as `null`, not an empty string, so inventory
matching does not accidentally attempt an exact match against `""`.

### SOP

SOP documents are generated from YAML fixtures under:

```text
scripts/rag/sop/sop_documents.yaml
```

Generated documents are written to:

```text
data/rag/documents/sop/
```

SOP documents define operational procedures for recall, shortage, and label
update workflows. They include metadata such as:

- `document_type: sop`
- `event_type`
- `sop_id`
- `priority`
- `applies_to`
- `requires_human_approval`

The `applies_to` list must include the document `event_type` value, such as
`recall`, `shortage`, or `label_update`, so future retrieval filters can use it
as a secondary signal.

### Policy

Policy documents are generated from YAML fixtures under:

```text
scripts/rag/policy/policy_documents.yaml
```

Generated documents are written to:

```text
data/rag/documents/policy/
```

Policy documents define review, escalation, approval, and safety rules for
recall, shortage, and label update workflows. They include metadata such as:

- `document_type: policy`
- `event_type`
- `policy_id`
- `priority`
- `applies_to`
- `requires_human_approval`

Like SOP documents, every policy `applies_to` list should include its
`event_type` value.

## Generation Commands

Generate the identity cache and all document datasets:

```powershell
python -m scripts.generate_data --all
```

Generate individual datasets:

```powershell
python -m scripts.generate_data --labels
python -m scripts.generate_data --recalls
python -m scripts.generate_data --sop
python -m scripts.generate_data --policy
python -m scripts.generate_data --identity
```

Running `python -m scripts.generate_data` with no flags also builds the identity
cache and generates all four document datasets.

OpenFDA fetchers can also be run directly when lower-level options are needed:

```powershell
python -m scripts.rag.identity.build_drug_identity_cache
python -m scripts.rag.openfda.fetch_labels --clean
python -m scripts.rag.openfda.fetch_recalls --clean
python -m scripts.rag.openfda.fetch_labels --from-raw --clean
python -m scripts.rag.openfda.fetch_recalls --from-raw --clean
```

Use `--from-raw` to rebuild markdown from saved raw JSON without calling the
openFDA API.

## Generated Output Policy

The following paths are generated outputs and are ignored by Git:

```text
data/rag/raw/
data/rag/documents/
data/rag/processed/
data/reference/drug_identity_cache.json
```

Commit the generation code and YAML fixtures, not the generated markdown or raw
API output.

Commit:

- `scripts/generate_data.py`
- `scripts/rag/openfda/`
- `scripts/rag/sop/`
- `scripts/rag/policy/`
- `scripts/rag/common.py`
- `scripts/rag/sop/sop_documents.yaml`
- `scripts/rag/policy/policy_documents.yaml`

Do not commit:

- raw openFDA JSON
- generated markdown documents
- fetch manifests
- generated RxNorm cache
- future chunk JSONL files

## Current Scope

This dataset generation work covers evidence source creation only.

Included:

- openFDA label raw JSON fetch
- openFDA recall/enforcement raw JSON fetch
- RxNorm drug identity cache generation
- label markdown generation
- recall notice markdown generation
- SOP markdown generation from YAML
- policy markdown generation from YAML
- consistent frontmatter metadata
- safe reruns with clean generated outputs

Out of scope:

- chunking
- embedding generation
- Milvus insertion
- retrieval API
- RAG quality scoring
- LLM draft generation
