from __future__ import annotations

from typing import Any

from scripts.rag.common import normalize_block, slugify, yaml_value


def get_section_profiles(sop: dict[str, Any]) -> list[str]:
    profiles = sop.get("section_profiles")

    if isinstance(profiles, list) and profiles:
        return profiles

    event_types = sop.get("event_types")

    if isinstance(event_types, list) and event_types:
        return event_types

    # Older SOP fixtures only define event_type; treat it as the single profile.
    return [sop["event_type"]]


def has_profile(sop: dict[str, Any], profile: str) -> bool:
    # section_profiles controls generated guidance text separately from
    # event_types, which controls retrieval applicability.
    return profile in get_section_profiles(sop)


def build_sop_roles_and_responsibilities(sop: dict[str, Any]) -> list[str]:
    roles = [
        "Pharmacy operations staff are responsible for reviewing affected inventory and documenting operational findings.",
        "The pharmacist reviewer is responsible for approving safety-critical actions before the ticket is closed.",
        "The system is responsible for retrieving evidence, preparing draft summaries, and preserving citations.",
        "The system must not replace pharmacist judgment for clinical, substitution, disposal, or patient-facing decisions.",
    ]

    if has_profile(sop, "recall"):
        roles.extend(
            [
                "Inventory staff should verify affected NDC, lot, expiration, and department location when available.",
                "Medication safety staff should review Class I recalls and high-alert medication recalls before final approval.",
            ]
        )

    if has_profile(sop, "shortage"):
        roles.extend(
            [
                "Supply staff should validate on-hand quantity, expected restock date, and department-level demand.",
                "Pharmacists should review allocation or substitution language before communication to clinical departments.",
            ]
        )

    if has_profile(sop, "label_update"):
        roles.extend(
            [
                "Medication safety staff should review label updates involving warnings, contraindications, dosage, or boxed warnings.",
                "Clinical department communication should not be finalized until pharmacist review is complete.",
            ]
        )

    return roles


def build_sop_evidence_requirements(sop: dict[str, Any]) -> list[str]:
    requirements = [
        "Evidence chunks must include source_path, document_type, section, and chunk_index.",
        "The retrieved evidence must support the operational step being recommended.",
        "If required evidence is missing, the workflow must route to evidence_review rather than final approval.",
        "The generated draft must cite the evidence source used for each safety-critical claim.",
    ]

    if has_profile(sop, "recall"):
        requirements.extend(
            [
                "Recall workflows should retrieve recall_notice, policy, and SOP evidence.",
                "Recall evidence should include recall_number, classification, affected_product, reason_for_recall, and code_info when available.",
                "Inventory evidence should include match_type, NDC match, lot match, department, and quantity_on_hand.",
                "If only fuzzy name matching is available, the match must be treated as uncertain.",
            ]
        )

    if has_profile(sop, "shortage"):
        requirements.extend(
            [
                "Shortage workflows should retrieve shortage_notice, policy, SOP, and label evidence when available.",
                "Shortage evidence should include affected drug, severity, expected duration, inventory risk, and mitigation considerations.",
                "Inventory evidence should include current stock, usage estimate, days of supply, and high-risk department demand.",
                "Substitution-related evidence must include policy or SOP support before action language is drafted.",
            ]
        )

    if has_profile(sop, "label_update"):
        requirements.extend(
            [
                "Label update workflows should retrieve label, policy, and SOP evidence.",
                "Label evidence should include relevant sections such as warnings, contraindications, dosage, adverse reactions, drug interactions, or storage.",
                "The label source should include effective_time and source_record_id when available.",
                "Clinical interpretation must be separated from cited label text.",
            ]
        )

    return requirements


def build_sop_system_behavior(sop: dict[str, Any]) -> list[str]:
    behavior = [
        "The system should create a draft workflow summary rather than a final instruction when review is required.",
        "The system should separate confirmed evidence from uncertain or inferred findings.",
        "The system should preserve all intermediate routing decisions in the audit trail.",
        "The system should mark the ticket as requiring review when evidence is insufficient or safety-critical language is detected.",
    ]

    if has_profile(sop, "recall"):
        behavior.extend(
            [
                "For recall workflows, exact NDC and lot matches should be preferred over fuzzy name matches.",
                "If affected inventory is confirmed, the system should route to final_approval.",
                "If no inventory impact is found and evidence is sufficient, the system may prepare a no-impact closure summary.",
            ]
        )

    if has_profile(sop, "shortage"):
        behavior.extend(
            [
                "For shortage workflows, the system should estimate inventory risk before drafting mitigation language.",
                "The system should route allocation or substitution language to action_review.",
                "The system should prioritize ICU, ER, OR, oncology, and other high-risk departments in impact summaries.",
            ]
        )

    if has_profile(sop, "label_update"):
        behavior.extend(
            [
                "For label update workflows, the system should prioritize warnings, contraindications, dosage, interactions, and storage sections.",
                "The system should flag boxed warning or high-risk label language for pharmacist review.",
                "The system should not infer new clinical instructions beyond the cited label section.",
            ]
        )

    return behavior


def build_sop_safety_controls(sop: dict[str, Any]) -> list[str]:
    return [
        "Do not provide direct patient-specific medical instructions.",
        "Do not state that inventory has been quarantined, removed, substituted, or disposed unless approval is recorded.",
        "Do not recommend therapeutic substitution as a final action without pharmacist approval.",
        "Do not convert uncertain evidence into confirmed operational language.",
        "Do not close a ticket when required evidence sources are missing.",
        "Do not generate patient-facing communication without pharmacist or compliance review.",
    ]


def build_sop_review_routing(sop: dict[str, Any]) -> list[str]:
    rules = [
        "Route to evidence_review when required evidence is missing, conflicting, or low-confidence.",
        "Route to identity_review when inventory matching depends on fuzzy name matching or incomplete identifiers.",
        "Route to action_review when generated text includes quarantine, substitution, disposal, or patient notification language.",
        "Route to final_approval when evidence is sufficient and the remaining decision is safety-critical.",
    ]

    if has_profile(sop, "recall"):
        rules.extend(
            [
                "Route Class I recalls with confirmed inventory impact to final_approval.",
                "Route ambiguous NDC or lot matches to identity_review.",
                "Use no_impact_close only when recall evidence is sufficient and inventory matching returns no match.",
            ]
        )

    if has_profile(sop, "shortage"):
        rules.extend(
            [
                "Route shortage allocation decisions to action_review.",
                "Route substitution language to pharmacist review before final communication.",
                "Route high-severity shortage events to final_approval when department access may change.",
            ]
        )

    if has_profile(sop, "label_update"):
        rules.extend(
            [
                "Route boxed warning summaries to final_approval before department distribution.",
                "Route missing label sections to evidence_review.",
                "Route high-alert medication label updates to pharmacist review.",
            ]
        )

    return rules


def build_sop_audit_requirements(sop: dict[str, Any]) -> list[str]:
    return [
        "Record workflow step, timestamp, and ticket identifier for each SOP action.",
        "Record evidence citations with source_path, section, and chunk_index.",
        "Record inventory match type and impact assessment when inventory is involved.",
        "Record generated draft version and final report version when a report is produced.",
        "Record human reviewer status, reviewer decision, and approval timestamp when review is required.",
        "Record any blocked unsafe action category detected during safety check.",
    ]


def render_sop_document(sop: dict[str, Any]) -> str:
    frontmatter = {
        "document_id": sop["document_id"],
        "document_type": "sop",
        "event_type": sop["event_type"],
        "event_types": sop.get("event_types", [sop["event_type"]]),
        "section_profiles": get_section_profiles(sop),
        "sop_id": sop["sop_id"],
        "title": sop["title"],
        "priority": sop["priority"],
        "applies_to": sop["applies_to"],
        "requires_human_approval": sop["requires_human_approval"],
        "source": "internal SOP corpus",
        "data_origin": "synthetic_fixture",
        "version": "v1",
    }

    lines: list[str] = ["---"]

    for key, value in frontmatter.items():
        lines.append(f"{key}: {yaml_value(value)}")

    lines.extend(
        [
            "---",
            "",
            f"# {sop['title']}",
            "",
            "## purpose",
            normalize_block(sop["purpose"]),
            "",
            "## trigger",
            normalize_block(sop["trigger"]),
            "",
            "## roles_and_responsibilities",
        ]
    )

    for item in build_sop_roles_and_responsibilities(sop):
        lines.append(f"- {item}")

    lines.extend(["", "## required_inputs"])

    for item in sop["required_inputs"]:
        lines.append(f"- {item}")

    lines.extend(["", "## evidence_requirements"])

    for item in build_sop_evidence_requirements(sop):
        lines.append(f"- {item}")

    lines.extend(["", "## system_behavior"])

    for item in build_sop_system_behavior(sop):
        lines.append(f"- {item}")

    lines.extend(["", "## procedure"])

    for index, step in enumerate(sop["procedure"], start=1):
        lines.append(f"{index}. {step}")

    lines.extend(["", "## safety_controls"])

    for item in build_sop_safety_controls(sop):
        lines.append(f"- {item}")

    lines.extend(["", "## exception_handling"])

    for item in sop["exception_handling"]:
        lines.append(f"- {item}")

    lines.extend(["", "## review_routing"])

    for item in build_sop_review_routing(sop):
        lines.append(f"- {item}")

    lines.extend(["", "## audit_requirements"])

    for item in build_sop_audit_requirements(sop):
        lines.append(f"- {item}")

    lines.extend(["", "## completion_criteria"])

    for item in sop["completion_criteria"]:
        lines.append(f"- {item}")

    lines.append("")

    return "\n".join(lines)