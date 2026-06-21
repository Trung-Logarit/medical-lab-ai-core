from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CONTEXT_PATH = ROOT_DIR / "clinical_graph_context_v3.jsonl"

PATTERN_LABELS_VI = {
    "absolute_eosinophilia": "Tăng bạch cầu ái toan tuyệt đối",
    "absolute_lymphocytosis": "Tăng bạch cầu lympho tuyệt đối",
    "absolute_lymphopenia": "Giảm bạch cầu lympho tuyệt đối",
    "absolute_monocytosis": "Tăng bạch cầu mono tuyệt đối",
    "aminotransferase_elevation": "Tăng men gan AST/ALT",
    "anemia_without_microcytosis": "Thiếu máu không kèm hồng cầu nhỏ",
    "atherogenic_lipid_abnormality": "Rối loạn lipid làm tăng nguy cơ tim mạch",
    "creatinine_high_reduced_gfr_signal": "Creatinine tăng, gợi ý giảm khả năng lọc của thận",
    "creatinine_low_signal": "Creatinine thấp",
    "crp_high_acute_phase_signal": "CRP tăng, gợi ý phản ứng viêm",
    "glucose_high_signal": "Glucose máu tăng",
    "hyperbilirubinemia_pattern": "Tăng bilirubin máu",
    "hypokalemia_signal": "Kali máu thấp",
    "hyponatremia_signal": "Natri máu thấp",
    "immature_granulocyte_signal": "Tăng bạch cầu hạt non",
    "leukocytosis_without_absolute_neutrophilia": "Tăng bạch cầu không kèm tăng bạch cầu trung tính tuyệt đối",
    "microcytic_hypochromic_anemia": "Thiếu máu hồng cầu nhỏ, nhược sắc",
    "microcytosis_or_hypochromia_without_anemia": "Hồng cầu nhỏ hoặc nhược sắc chưa kèm thiếu máu",
    "neutrophilic_leukocytosis": "Tăng bạch cầu trung tính tuyệt đối",
    "polycythemia_or_erythrocytosis_signal": "Dấu hiệu tăng khối hồng cầu",
    "relative_eosinophil_percentage_high": "Tăng tỷ lệ bạch cầu ái toan tương đối",
    "relative_lymphocyte_percentage_low": "Giảm tỷ lệ bạch cầu lympho tương đối",
    "relative_monocyte_percentage_high": "Tăng tỷ lệ bạch cầu mono tương đối",
    "thrombocytopenia_signal": "Giảm tiểu cầu",
}

PATTERN_DESCRIPTIONS_VI = {
    "absolute_eosinophilia": "EOS# tăng, phù hợp với tăng bạch cầu ái toan tuyệt đối.",
    "absolute_lymphocytosis": "LYM# tăng, phù hợp với tăng bạch cầu lympho tuyệt đối.",
    "absolute_lymphopenia": "LYM# thấp, phù hợp với giảm bạch cầu lympho tuyệt đối.",
    "absolute_monocytosis": "MONO# tăng, phù hợp với tăng bạch cầu mono tuyệt đối.",
    "aminotransferase_elevation": "AST hoặc ALT tăng, phù hợp với mẫu hình tăng men gan.",
    "anemia_without_microcytosis": "HGB hoặc HCT giảm nhưng MCV/MCH không giảm; chưa phù hợp với thiếu máu hồng cầu nhỏ, nhược sắc.",
    "atherogenic_lipid_abnormality": "Triglyceride hoặc non-HDL-C tăng; cần đánh giá cùng nguy cơ tim mạch tổng thể.",
    "creatinine_high_reduced_gfr_signal": "Creatinine tăng có thể gợi ý giảm khả năng lọc của thận hoặc thay đổi chuyển hóa creatinine.",
    "creatinine_low_signal": "Creatinine thấp hơn khoảng tham chiếu; ý nghĩa phụ thuộc khối cơ, tuổi, dinh dưỡng và tình trạng pha loãng mẫu.",
    "crp_high_acute_phase_signal": "CRP tăng, phù hợp với tăng chất phản ứng pha cấp; cần đối chiếu bối cảnh lâm sàng.",
    "glucose_high_signal": "Glucose cao hơn khoảng tham chiếu; cần biết mẫu đói hay không để diễn giải.",
    "hyperbilirubinemia_pattern": "Bilirubin toàn phần hoặc trực tiếp tăng, phù hợp với tăng bilirubin máu theo kết quả xét nghiệm.",
    "hypokalemia_signal": "K thấp so với khoảng tham chiếu, phù hợp với kali máu thấp.",
    "hyponatremia_signal": "Na thấp so với khoảng tham chiếu, phù hợp với natri máu thấp.",
    "immature_granulocyte_signal": "IG% hoặc IG# tăng, phù hợp với tăng bạch cầu hạt non trên công thức máu.",
    "leukocytosis_without_absolute_neutrophilia": "WBC tăng nhưng NEUT# không tăng; chưa đủ tiêu chuẩn gọi là tăng bạch cầu trung tính tuyệt đối.",
    "microcytic_hypochromic_anemia": "HGB hoặc HCT giảm kèm MCV hoặc MCH giảm, phù hợp với thiếu máu hồng cầu nhỏ, nhược sắc.",
    "microcytosis_or_hypochromia_without_anemia": "MCV hoặc MCH giảm nhưng HGB/HCT không giảm; chưa đủ tiêu chuẩn thiếu máu hồng cầu nhỏ, nhược sắc.",
    "neutrophilic_leukocytosis": "WBC tăng kèm NEUT# tăng cho thấy số lượng bạch cầu trung tính trong máu cao hơn bình thường.",
    "polycythemia_or_erythrocytosis_signal": "HGB hoặc HCT cao, gợi ý tăng khối hồng cầu so với khoảng tham chiếu.",
    "relative_eosinophil_percentage_high": "EOS% tăng nhưng EOS# bình thường, phù hợp với tăng tỷ lệ bạch cầu ái toan tương đối, chưa đủ tiêu chuẩn tăng tuyệt đối.",
    "relative_lymphocyte_percentage_low": "LYM% thấp nhưng LYM# bình thường cho thấy chỉ tỷ lệ bạch cầu lympho giảm; số lượng tuyệt đối không giảm.",
    "relative_monocyte_percentage_high": "MONO% tăng nhưng MONO# bình thường, phù hợp với tăng tỷ lệ bạch cầu mono tương đối, không phải tăng tuyệt đối.",
    "thrombocytopenia_signal": "PLT thấp, phù hợp với giảm tiểu cầu theo khoảng tham chiếu của phiếu.",
}


def _localize_outline_text(value: Any) -> Any:
    """Việt hóa nhãn nội bộ trước khi đưa vào prompt cho người dùng."""
    if isinstance(value, dict):
        return {
            key: item if key.endswith("_id") else _localize_outline_text(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_localize_outline_text(item) for item in value]
    if not isinstance(value, str):
        return value

    replacements = (
        ("neutrophilic leukocytosis", "tăng bạch cầu trung tính tuyệt đối"),
        ("neutrophilia", "tăng bạch cầu trung tính tuyệt đối"),
        ("lymphocytosis tuyệt đối", "tăng bạch cầu lympho tuyệt đối"),
        ("lymphopenia tuyệt đối", "giảm bạch cầu lympho tuyệt đối"),
        ("lymphocytosis", "tăng bạch cầu lympho"),
        ("lymphopenia", "giảm bạch cầu lympho"),
        ("lymphocyte", "bạch cầu lympho"),
        (" high", " cao"),
        (" low", " thấp"),
        (" normal", " bình thường"),
        (" hỗ trợ ", " cho thấy "),
    )
    localized = value
    for source, target in replacements:
        localized = re.sub(re.escape(source), target, localized, flags=re.IGNORECASE)
    return localized


@lru_cache(maxsize=1)
def load_contexts() -> dict[str, dict[str, Any]]:
    path = Path(os.getenv("CLINICAL_DEMO_CONTEXT_PATH", str(DEFAULT_CONTEXT_PATH)))
    contexts: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return contexts
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            case_id = str(row.get("case_id") or "").strip()
            if case_id:
                contexts[case_id] = row
    return contexts


def available_case_ids() -> set[str]:
    return set(load_contexts())


def get_runtime_context(case_id: str | None) -> dict[str, Any] | None:
    row = load_contexts().get(str(case_id or "").strip())
    if not row:
        return None

    graph = row.get("graph", {}) or {}
    nodes = {node["node_id"]: node for node in graph.get("nodes", []) if node.get("node_id")}
    edges = graph.get("edges", []) or []

    pattern_rows: list[dict[str, Any]] = []
    evidence_ids: list[str] = []
    condition_ids: list[str] = []
    confidence_map = {"high": 0.9, "medium": 0.75, "low": 0.6}

    for pattern in row.get("patterns", []) or []:
        pattern_id = pattern.get("pattern_id")
        pattern_key = str(pattern.get("pattern_key") or "")
        pattern_node = nodes.get(pattern_id, {})
        condition_id = pattern.get("supported_condition_id")
        condition_node = nodes.get(condition_id, {})
        if condition_id:
            condition_ids.append(condition_id)

        linked_evidence = [
            edge.get("target_id")
            for edge in edges
            if edge.get("source_id") == pattern_id
            and edge.get("relation") == "SUPPORTED_BY_EVIDENCE"
        ]
        for evidence_id in linked_evidence:
            if evidence_id and evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)

        confidence_label = str(pattern.get("confidence") or "medium").lower()
        pattern_rows.append({
            "pattern_id": pattern_id,
            "pattern_name": PATTERN_LABELS_VI.get(pattern_key, pattern_node.get("label") or pattern_key),
            "panel": pattern_node.get("panel") or "CURATED_DEMO",
            "conditions": [],
            "description": PATTERN_DESCRIPTIONS_VI.get(
                pattern_key,
                pattern.get("clinical_interpretation", ""),
            ),
            "confidence": confidence_map.get(confidence_label, 0.7),
            "matched_required": pattern.get("required_findings", []),
            "matched_optional": pattern.get("matched_findings", []),
            "limitations": pattern.get("limitations", ""),
            "source": "clinical_graph_context_v3",
        })

    evidence_rows: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        evidence = nodes.get(evidence_id, {})
        if evidence.get("node_type") != "Evidence" or not evidence.get("quote_verified"):
            continue
        quote = str(evidence.get("evidence_quote") or "")
        # The demo reports do not contain patient age. Do not use evidence
        # whose applicability is explicitly limited to children.
        if "in children" in quote.lower():
            continue
        source = nodes.get(evidence.get("source_id"), {})
        title = str(source.get("title") or evidence.get("verified_pdf_filename") or "Unknown source")
        edition = str(source.get("edition") or "").strip()
        source_label = f"{title}, {edition}" if edition and edition.lower() not in title.lower() else title

        related_patterns = [
            pattern for pattern in row.get("patterns", []) or []
            if evidence_id in [
                edge.get("target_id") for edge in edges
                if edge.get("source_id") == pattern.get("pattern_id")
                and edge.get("relation") == "SUPPORTED_BY_EVIDENCE"
            ]
        ]
        finding_ids = {
            finding_id
            for pattern in related_patterns
            for finding_id in (
                (pattern.get("required_findings", []) or [])
                + (pattern.get("matched_findings", []) or [])
            )
        }
        tests = sorted({
            str(nodes.get(finding_id, {}).get("canonical_test") or "")
            for finding_id in finding_ids
            if nodes.get(finding_id, {}).get("canonical_test")
        })

        evidence_rows.append({
            "evidence_id": evidence_id,
            "id": evidence_id,
            "panel": source.get("panel") or "CURATED_DEMO",
            "source": source_label,
            "page": evidence.get("verified_pdf_page") or evidence.get("pdf_page"),
            "text": quote,
            "summary_vi": _localize_outline_text(evidence.get("evidence_summary_vi", "")),
            "tests": tests,
            "topics": [],
            "conditions": [
                str(nodes.get(pattern.get("supported_condition_id"), {}).get("condition_key") or "")
                for pattern in related_patterns
                if pattern.get("supported_condition_id")
            ],
            "type": "verified_demo_book_evidence",
            "score": 3.0,
            "trust": 1.0,
            "source_type": "verified_demo_book_evidence",
            "origin": "clinical_graph_context_v3",
            "quote_verified": True,
            "is_static": False,
        })

    evidence_by_id = {item["evidence_id"]: item for item in evidence_rows}
    pattern_by_id = {item["pattern_id"]: item for item in pattern_rows}
    reasoning_paths: list[dict[str, Any]] = []
    for raw_pattern in row.get("patterns", []) or []:
        pattern_id = raw_pattern.get("pattern_id")
        pattern = pattern_by_id.get(pattern_id, {})
        linked_evidence_ids = [
            edge.get("target_id")
            for edge in edges
            if edge.get("source_id") == pattern_id
            and edge.get("relation") == "SUPPORTED_BY_EVIDENCE"
        ]
        linked_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in linked_evidence_ids
            if evidence_id in evidence_by_id
        ]
        for finding_id in raw_pattern.get("matched_findings", []) or []:
            finding = nodes.get(finding_id, {})
            if finding.get("node_type") != "Finding":
                continue
            reasoning_paths.append({
                "finding": {
                    "panel": finding.get("panel"),
                    "test": finding.get("canonical_test"),
                    "test_label": finding.get("raw_test_name"),
                    "measurement_kind": finding.get("measurement_kind"),
                    "status": finding.get("status"),
                    "value": finding.get("value"),
                    "unit": finding.get("unit", ""),
                    "reference_range": finding.get("ref_range", {}),
                },
                "patterns": [pattern],
                "conditions": pattern.get("conditions", []),
                "evidence": linked_evidence,
            })

    answer_outline = _localize_outline_text(dict(row.get("answer_outline", {}) or {}))
    supported_finding_ids = {
        finding_id
        for pattern in row.get("patterns", []) or []
        for finding_id in pattern.get("matched_findings", []) or []
    }
    unpatterned_abnormalities = [
        finding
        for finding in answer_outline.get("primary_abnormalities", []) or []
        if finding.get("finding_id") not in supported_finding_ids
    ]
    evidence_blob = " ".join(item.get("text", "").lower() for item in evidence_rows)
    etiology_terms = [
        term for term in ("infection", "inflammation", "stress", "drug", "medication")
        if term in evidence_blob
    ]
    answer_outline["runtime_guardrails"] = {
        "etiology_supported_by_current_evidence": bool(etiology_terms),
        "etiology_terms_found_in_evidence": etiology_terms,
        "unpatterned_abnormalities": unpatterned_abnormalities,
        "instructions": [
            "Không suy ra nguyên nhân nếu evidence hiện tại chỉ định nghĩa chỉ số hoặc pattern.",
            "Chỉ số phần trăm là dấu hiệu đi kèm; ưu tiên số lượng tuyệt đối khi có cả hai.",
            "Bất thường nhẹ không thuộc pattern phải được mô tả thận trọng, không gán nguyên nhân.",
        ],
    }

    # Ưu tiên bằng chứng giúp người dùng hiểu nguyên nhân, nguy cơ hoặc hành động;
    # các trích đoạn chỉ định nghĩa chỉ số được xếp sau.
    def evidence_usefulness(item: dict[str, Any]) -> tuple[int, float]:
        content = f"{item.get('text', '')} {item.get('summary_vi', '')}".lower()
        useful_terms = (
            "due to", "caused", "associated", "can occur", "risk", "evaluation",
            "management", "nên", "cần", "nguy cơ", "nguyên nhân", "liên quan",
        )
        definition_terms = ("refers to", "defined as", "định nghĩa")
        score = 2 if any(term in content for term in useful_terms) else 1
        if any(term in content for term in definition_terms):
            score -= 1
        return score, float(item.get("trust") or 0)

    evidence_rows.sort(key=evidence_usefulness, reverse=True)

    return {
        "case_id": row.get("case_id"),
        "patterns": pattern_rows,
        "conditions": sorted(set(condition_ids)),
        "evidence": evidence_rows,
        "reasoning_paths": reasoning_paths,
        "answer_outline": answer_outline,
        "schema_version": row.get("schema_version"),
    }
