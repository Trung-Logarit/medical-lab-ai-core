from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


ROOT_DIR = Path(__file__).resolve().parents[3]
CONTEXT_PATH = ROOT_DIR / "clinical_demo_20_answer_context_verified.jsonl"
CBC_CASE_IDS = {f"{index}.jpg" for index in range(1, 11)}


@lru_cache(maxsize=1)
def load_verified_contexts() -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    if not CONTEXT_PATH.exists():
        return contexts
    with CONTEXT_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            case_id = str(row.get("case_id") or "").strip()
            if case_id not in CBC_CASE_IDS:
                continue
            if not row.get("finding_priorities") or not row.get("atomic_claims"):
                continue
            contexts[case_id] = row
    return contexts


def available_verified_case_ids() -> set[str]:
    return set(load_verified_contexts())


def _normalized_test_name(value: Any) -> str:
    return (
        str(value or "").strip().upper()
        .replace("_PERCENT", "%")
        .replace("_ABS", "#")
        .replace("NEUT", "NEUT")
        .replace("LYMPH", "LYM")
    )


def _normalized_item_test_name(item: dict[str, Any]) -> str:
    name = _normalized_test_name(item.get("test_name"))
    if name in {"NEUT", "LYM", "MONO", "EOS", "BASO"}:
        unit = str(item.get("unit") or "").strip()
        name += "%" if "%" in unit else "#"
    return name


def match_verified_case_id(report_data: list[dict[str, Any]]) -> Optional[str]:
    """Match an active report to a verified demo case using test/value pairs."""
    observed: dict[str, float] = {}
    for item in report_data or []:
        try:
            observed[_normalized_item_test_name(item)] = float(item.get("value"))
        except (TypeError, ValueError):
            continue

    best_case: Optional[str] = None
    best_matches = 0
    best_ratio = 0.0
    for case_id, row in load_verified_contexts().items():
        matches = 0
        compared = 0
        for item in row.get("structured_labs", []) or []:
            name = _normalized_item_test_name(item)
            if name not in observed:
                continue
            try:
                expected = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            compared += 1
            tolerance = max(abs(expected) * 0.005, 0.001)
            if abs(observed[name] - expected) <= tolerance:
                matches += 1
        ratio = matches / compared if compared else 0.0
        if matches >= 5 and ratio >= 0.75 and (ratio, matches) > (best_ratio, best_matches):
            best_case, best_matches, best_ratio = case_id, matches, ratio
    return best_case


def match_verified_runtime_context(report_data: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    return get_verified_runtime_context(match_verified_case_id(report_data))


def _case7_priority_correction(priorities: list[dict[str, Any]]) -> None:
    """Correct two issues found during the independent audit of the draft."""
    for priority in priorities:
        tests = set(priority.get("test_names", []) or [])
        if {"NEUT%", "NEUT#"} & tests:
            priority["summary_vi"] = "NEUT# và NEUT% đều thấp so với khoảng tham chiếu."
            priority["reason_vi"] = (
                "NEUT# thấp là thay đổi tuyệt đối, không được xem chỉ là hệ quả "
                "của việc LYM% tăng. Cần diễn giải theo mức độ và bối cảnh lâm sàng."
            )


def get_verified_runtime_context(case_id: Optional[str]) -> Optional[dict[str, Any]]:
    row = load_verified_contexts().get(str(case_id or "").strip())
    if not row:
        return None

    priorities = [dict(item) for item in row.get("finding_priorities", []) or []]
    if row.get("case_id") == "7.jpg":
        _case7_priority_correction(priorities)

    evidence_rows: list[dict[str, Any]] = []
    evidence_number_by_id: dict[str, int] = {}
    for index, evidence in enumerate(row.get("evidence", []) or [], start=1):
        if not evidence.get("quote_verified"):
            continue
        evidence_id = str(evidence.get("evidence_id") or f"evidence_{index}")
        evidence_number_by_id[evidence_id] = len(evidence_rows) + 1
        related_tests = sorted({
            test
            for cluster in row.get("interpretation_clusters", []) or []
            if evidence_id in (cluster.get("allowed_evidence_ids", []) or [])
            for test in (cluster.get("finding_test_names", []) or [])
        })
        evidence_rows.append({
            "evidence_id": evidence_id,
            "id": evidence_id,
            "source": evidence.get("source_title") or evidence.get("pdf_filename") or "Unknown source",
            "page": evidence.get("pdf_page"),
            "text": evidence.get("exact_quote", ""),
            "summary_vi": evidence.get("summary_vi", ""),
            "tests": related_tests,
            "conditions": [],
            "panel": "CBC",
            "type": evidence.get("evidence_role") or "interpretation",
            "score": 5.0,
            "trust": 1.0,
            "source_type": "verified_answer_context",
            "origin": "clinical_demo_20_answer_context_verified",
            "quote_verified": True,
            "is_static": False,
        })

    claims = []
    for claim in row.get("atomic_claims", []) or []:
        item = dict(claim)
        if row.get("case_id") == "7.jpg" and item.get("claim_id") == "c7_iron_deficiency_possible_not_confirmed":
            item["claim_vi"] = (
                "Thiếu sắt là một khả năng cần kiểm tra cho kiểu thiếu máu hồng cầu nhỏ này, "
                "nhưng chưa thể xác nhận chỉ từ CBC. Sắt huyết tương và độ bão hòa transferrin "
                "là các thông tin có thể dùng để đánh giá thêm."
            )
            item["conditions_vi"] = [
                "Không kết luận thiếu sắt khi chưa có xét nghiệm đánh giá tình trạng sắt."
            ]
        item["citation_numbers"] = [
            evidence_number_by_id[evidence_id]
            for evidence_id in claim.get("supported_by_evidence_ids", []) or []
            if evidence_id in evidence_number_by_id
        ]
        claims.append(item)

    outline = {
        "context_source": "verified_cbc_answer_context_v1",
        "finding_priorities": priorities,
        "atomic_claims": claims,
        "recommended_actions_vi": (
            [
                "Đối chiếu với triệu chứng hiện tại như sốt, đau họng, mệt nhiều hoặc nổi hạch.",
                "Trao đổi với bác sĩ về xét nghiệm đánh giá tình trạng sắt và việc lặp lại CBC nếu bất thường kéo dài.",
            ]
            if row.get("case_id") == "7.jpg"
            else row.get("recommended_actions_vi", [])
        ),
        "urgent_red_flags_vi": row.get("urgent_red_flags_vi", []),
        "followup_questions_vi": row.get("followup_questions_vi", []),
        "forbidden_claims_vi": row.get("forbidden_claims_vi", []),
        "data_quality_notes": row.get("data_quality_notes", []),
        "citation_map": evidence_number_by_id,
        "runtime_guardrails": {
            "use_only_atomic_claims_for_medical_causes": True,
            "mention_every_abnormal_finding": True,
            "case7_neut_absolute_low_is_independent": row.get("case_id") == "7.jpg",
            "case7_eos_absolute_high_must_be_mentioned": row.get("case_id") == "7.jpg",
        },
    }

    pattern_rows = [
        {
            "pattern_id": cluster.get("cluster_id"),
            "pattern_name": cluster.get("title_vi"),
            "panel": "CBC",
            "conditions": [],
            "description": cluster.get("plain_explanation_vi", ""),
            "confidence": 0.9,
            "source": "verified_answer_context",
        }
        for cluster in row.get("interpretation_clusters", []) or []
    ]

    return {
        "case_id": row.get("case_id"),
        "schema_version": row.get("schema_version"),
        "context_kind": "verified_answer_context",
        "patterns": pattern_rows,
        "conditions": [],
        "evidence": evidence_rows,
        "reasoning_paths": [],
        "answer_outline": outline,
    }
