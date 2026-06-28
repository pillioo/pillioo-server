from __future__ import annotations

from typing import Any

from scripts.rag.common import normalize_block, slugify, yaml_value


def get_event_types(policy: dict[str, Any]) -> list[str]:
    event_types = policy.get("event_types")

    if event_types is None:
        # Keep older fixtures valid while newer indexers can prefer event_types.
        return [str(policy["event_type"])]

    if not isinstance(event_types, list) or not all(
        isinstance(item, str) for item in event_types
    ):
        raise ValueError("policy.event_types must be a list of strings.")

    return event_types


def get_template_profile(policy: dict[str, Any]) -> str:
    # Common policies apply to several event types without inheriting
    # recall-, shortage-, or label-specific generated language.
    return str(policy.get("template_profile") or policy["event_type"])


def build_evidence_requirements(policy: dict[str, Any]) -> list[str]:
    template_profile = get_template_profile(policy)

    common = [
        "The policy document itself must be available as a cited evidence source.",
        "Retrieved evidence must include source_path, document_type, section, and chunk_index.",
        "Evidence used for routing must be traceable to the original canonical evidence document.",
        "If required evidence is missing, the ticket must not be treated as fully supported.",
    ]

    if template_profile == "common":
        return common

    if template_profile == "recall":
        return common + [
            "Recall evidence should include recall_number, classification, affected_product, reason_for_recall, and recall_initiation_date when available.",
            "Inventory evidence should include match_type, NDC match result, lot match result, department, and quantity on hand.",
            "Recall notice evidence must be distinguished from general policy or SOP evidence.",
            "If the recall notice lacks NDC or lot information, fuzzy name matching must be treated as uncertain evidence.",
        ]

    if template_profile == "shortage":
        return common + [
            "Shortage evidence should include affected drug, severity, expected duration, inventory risk, and mitigation options.",
            "Inventory evidence should include on-hand stock, usage estimate, department demand, and days-of-supply estimate.",
            "Substitution evidence must include policy or SOP support before being presented as an actionable recommendation.",
            "If shortage severity or duration is unknown, the case should be routed to pharmacist review.",
        ]

    if template_profile == "label_update":
        return common + [
            "Label evidence should include the relevant label section such as warnings, contraindications, dosage, adverse reactions, drug interactions, or storage.",
            "The label source must include source_record_id, effective_time, and section metadata when available.",
            "Clinical interpretation must be separated from direct label text.",
            "If the label section is missing or ambiguous, the case should be routed to evidence review.",
        ]

    return common


def build_system_behavior(policy: dict[str, Any]) -> list[str]:
    template_profile = get_template_profile(policy)
    requires_human_approval = policy["requires_human_approval"]

    behavior = [
        "The system should retrieve policy evidence together with event-specific evidence before generating an operational summary.",
        "The system should clearly separate confirmed findings from uncertain or inferred findings.",
        "The system should include citations for all evidence-based claims in drafts and summaries.",
        "The system should avoid presenting generated text as final operational instruction unless approval requirements are satisfied.",
    ]

    if requires_human_approval:
        behavior.extend(
            [
                "The system should route the ticket to human review when this policy applies.",
                "The system should mark generated reports as draft until approval is recorded.",
                "The system should preserve reviewer decisions and approval status in the audit trail.",
            ]
        )
    else:
        behavior.extend(
            [
                "The system may recommend closure only when all required evidence is present and no escalation criterion is met.",
                "The system should still retain the evidence and routing rationale used for the closure decision.",
            ]
        )

    if template_profile == "recall":
        behavior.extend(
            [
                "For recall events, the system should prioritize exact NDC and lot matching over fuzzy drug-name matching.",
                "If affected inventory is found, the system should route the case to final approval or pharmacist review.",
                "If no inventory impact is found, the system should generate a no-impact closure summary only when evidence is sufficient.",
            ]
        )

    if template_profile == "shortage":
        behavior.extend(
            [
                "For shortage events, the system should estimate inventory risk before suggesting mitigation language.",
                "The system should not recommend substitution unless policy and SOP evidence support review of substitution.",
                "The system should prioritize high-risk departments when summarizing operational impact.",
            ]
        )

    if template_profile == "label_update":
        behavior.extend(
            [
                "For label update events, the system should prioritize warning, contraindication, dosage, interaction, and storage sections.",
                "The system should flag boxed warning or high-risk label language for pharmacist review.",
                "The system should not infer clinical practice changes beyond the cited label text.",
            ]
        )

    return behavior


def build_prohibited_actions(policy: dict[str, Any]) -> list[str]:
    return [
        "Do not provide direct patient-specific medical instructions.",
        "Do not state that inventory has been quarantined, removed, substituted, or disposed unless human approval is recorded.",
        "Do not recommend therapeutic substitution as a final action without pharmacist approval.",
        "Do not present uncertain evidence as confirmed fact.",
        "Do not close a ticket when required evidence sources are missing.",
        "Do not generate patient-facing communication unless pharmacist or compliance approval is recorded.",
    ]


def build_review_routing_rules(policy: dict[str, Any]) -> list[str]:
    template_profile = get_template_profile(policy)

    rules = [
        "Route to evidence_review when required evidence sources are missing or conflicting.",
        "Route to identity_review when inventory matching depends only on fuzzy name matching.",
        "Route to action_review when generated text includes substitution, disposal, quarantine, or patient notification language.",
        "Route to final_approval when evidence is sufficient and the remaining decision is safety-critical.",
    ]

    if template_profile == "common":
        return rules

    if template_profile == "recall":
        rules.extend(
            [
                "Use no_impact_close only when recall evidence is sufficient and inventory matching returns no exact or high-confidence match.",
                "Use final_approval when affected inventory is confirmed for a Class I or high-alert medication recall.",
            ]
        )

    if template_profile == "shortage":
        rules.extend(
            [
                "Use action_review when allocation or substitution language is generated.",
                "Use final_approval when a shortage mitigation plan changes department-level medication access.",
            ]
        )

    if template_profile == "label_update":
        rules.extend(
            [
                "Use evidence_review when the required label section cannot be retrieved.",
                "Use final_approval when the label update summary will be distributed to clinical departments.",
            ]
        )

    return rules


def build_completion_criteria(policy: dict[str, Any]) -> list[str]:
    return [
        "Required evidence sources have been retrieved or explicitly marked as missing.",
        "The evidence status is consistent with missing_sources and coverage_score.",
        "All generated draft statements are supported by citations or marked as requiring review.",
        "Escalation criteria have been evaluated and the selected review route is recorded.",
        "Approval requirements have been satisfied before the ticket is marked approved or closed.",
        "Audit requirements have been recorded with workflow step, timestamp, and source references.",
    ]


def render_policy_document(policy: dict[str, Any]) -> str:
    event_types = get_event_types(policy)
    template_profile = get_template_profile(policy)

    frontmatter = {
        "document_id": policy["document_id"],
        "document_type": "policy",
        "event_type": policy["event_type"],
        "event_types": event_types,
        "template_profile": template_profile,
        "policy_id": policy["policy_id"],
        "title": policy["title"],
        "priority": policy["priority"],
        "applies_to": policy["applies_to"],
        "requires_human_approval": policy["requires_human_approval"],
        "source": "internal policy corpus",
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
            f"# {policy['title']}",
            "",
            "## purpose",
            normalize_block(policy["purpose"]),
            "",
            "## scope",
            normalize_block(policy["scope"]),
            "",
            "## policy_statement",
            normalize_block(policy["policy_statement"]),
            "",
            "## evidence_requirements",
        ]
    )

    for item in build_evidence_requirements(policy):
        lines.append(f"- {item}")

    lines.extend(["", "## system_behavior"])

    for item in build_system_behavior(policy):
        lines.append(f"- {item}")

    lines.extend(["", "## required_actions"])

    for action in policy["required_actions"]:
        lines.append(f"- {action}")

    lines.extend(["", "## escalation_criteria"])

    for criterion in policy["escalation_criteria"]:
        lines.append(f"- {criterion}")

    lines.extend(["", "## review_routing_rules"])

    for rule in build_review_routing_rules(policy):
        lines.append(f"- {rule}")

    lines.extend(["", "## approval_requirements"])

    for requirement in policy["approval_requirements"]:
        lines.append(f"- {requirement}")

    lines.extend(["", "## prohibited_actions"])

    for action in build_prohibited_actions(policy):
        lines.append(f"- {action}")

    lines.extend(["", "## audit_requirements"])

    for requirement in policy["audit_requirements"]:
        lines.append(f"- {requirement}")

    lines.extend(["", "## completion_criteria"])

    for criterion in build_completion_criteria(policy):
        lines.append(f"- {criterion}")

    lines.append("")

    return "\n".join(lines)
