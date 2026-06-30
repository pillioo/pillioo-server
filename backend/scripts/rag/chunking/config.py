from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

try:
    import tiktoken  # noqa: F401
except ImportError:  # pragma: no cover
    tiktoken = None


ROOT_DIR = Path(__file__).resolve().parents[3]
RAG_DIR = ROOT_DIR / "data" / "rag"
DOCUMENTS_DIR = RAG_DIR / "documents"
PROCESSED_DIR = RAG_DIR / "processed"
DEFAULT_CHUNKS_PATH = PROCESSED_DIR / "evidence_chunks.jsonl"
DEFAULT_MANIFEST_PATH = PROCESSED_DIR / "chunk_manifest.json"

load_dotenv(ROOT_DIR / ".env")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
TOKEN_ENCODING_NAME = "cl100k_base"
TOKEN_COUNT_METHOD = "tiktoken" if tiktoken is not None else "char_estimate"

VALID_DOCUMENT_TYPES = {"label", "recall_notice", "sop", "policy"}
VALID_EVENT_TYPES = {"recall", "shortage", "label_update"}
DOCUMENT_TYPE_DIRS = ["label", "recall_notice", "sop", "policy"]

# Character windows are still used as a first pass because openFDA text often
# arrives as long unbroken paragraphs. Token limits below remain the hard cap.
MAX_SECTION_CHARS = {
    "label": 2_000,
    "recall_notice": 2_000,
    "sop": 2_400,
    "policy": 2_400,
}
OVERLAP_CHARS = 280
OVERLAP_TOKENS = 64

MAX_SECTION_TOKENS = {
    "label": 512,
    "recall_notice": 512,
    "sop": 600,
    "policy": 600,
}
DEFAULT_MAX_SECTION_TOKENS = 512

MIN_CHUNK_TOKENS = 30
MAX_MERGE_TOKENS = 600

# Keep only sections that are likely to answer retrieval questions. This avoids
# filling the vector index with legal boilerplate and low-signal label sections.
SECTION_INCLUDE_BY_TYPE = {
    "label": {
        "overview",
        "boxed_warning",
        "warnings",
        "contraindications",
        "indications_and_usage",
        "dosage_and_administration",
        "adverse_reactions",
        "drug_interactions",
        "use_in_specific_populations",
        "how_supplied",
        "storage_and_handling",
    },
    "sop": {
        "overview",
        "required_inputs",
        "evidence_requirements",
        "procedure",
        "safety_controls",
        "exception_handling",
        "review_routing",
        "audit_requirements",
        "completion_criteria",
    },
    "policy": {
        "overview",
        "policy_statement",
        "evidence_requirements",
        "required_actions",
        "escalation_criteria",
        "review_routing_rules",
        "approval_requirements",
        "prohibited_actions",
        "audit_requirements",
        "completion_criteria",
    },
}

TOP_LEVEL_METADATA_FIELDS = [
    "drug_name",
    "normalized_drug_name",
    "rxnorm_rxcui",
    "classification",
    "ndc",
    "lot",
    "recall_number",
]

# Fields here remain available for filters/citations without crowding the
# top-level chunk schema used by common retrieval paths.
NESTED_METADATA_FIELDS = [
    "lot_scope",
    "status",
    "reason_category",
    "recalling_firm",
    "recall_initiation_date",
    "recall_initiation_date_iso",
    "termination_date",
    "termination_date_iso",
    "distribution_pattern",
    "product_quantity",
    "event_id",
    "product_type",
    "voluntary_mandated",
    "initial_firm_notification",
    "center_classification_date",
    "center_classification_date_iso",
    "report_date",
    "report_date_iso",
    "priority",
    "requires_human_approval",
    "source",
    "source_record_id",
    "rxnorm_name",
    "rxnorm_tty",
    "drug_identity_match_basis",
    "openfda_drug_name",
    "product_ndc",
    "package_ndc",
    "route",
    "policy_id",
    "sop_id",
]

CONTEXT_PREFIX_RE = re.compile(r"[A-Z0-9 _/&(),+-]+ - .+\.")
