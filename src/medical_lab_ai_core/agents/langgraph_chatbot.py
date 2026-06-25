"""LangGraph workflow for laboratory-result chat orchestration."""
from __future__ import annotations
import json
import logging
import re
import traceback
from typing import Any, Dict, List, Optional, Literal

from typing_extensions import TypedDict
try:
    from langgraph.graph import StateGraph, END, START
except ImportError:
    StateGraph = None
    END = START = None

# Tích hợp Langfuse Tracing an toàn
try:
    from langfuse.decorators import observe, langfuse_context
except ImportError:
    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    class _NoopLangfuseContext:
        def update_current_trace(self, **kwargs):
            return None
    langfuse_context = _NoopLangfuseContext()

from medical_lab_ai_core.core import lab_core
from medical_lab_ai_core.graph_rag import service as rag_service

logger = logging.getLogger(__name__)

try:
    from medical_lab_ai_core.knowledge_base import cbc_demo_evidence
except Exception:
    cbc_demo_evidence = None

try:
    from medical_lab_ai_core.knowledge_base import biochem_demo_evidence
except Exception:
    biochem_demo_evidence = None


# =========================================================
# SESSION STORE — lưu trong RAM theo session_id
# =========================================================

SESSIONS: Dict[str, Dict[str, Any]] = {}


def get_session(session_id: Optional[str]) -> Dict[str, Any]:
    sid = session_id or "default"
    if sid not in SESSIONS:
        SESSIONS[sid] = {
            "active_report_data": None,
            "report_summary": None,
            "history": [],
        }
    return SESSIONS[sid]


def update_session_memory(
    session_id: str,
    active_report_data: Optional[list] = None,
    report_summary: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(session_id)
    if active_report_data is not None:
        session["active_report_data"] = active_report_data
    if report_summary is not None:
        session["report_summary"] = report_summary
    return session


# =========================================================
# STATE — trạng thái được truyền qua các node trong graph
# =========================================================

class ChatState(TypedDict):
    # Input
    user_text: str
    session_id: str

    # Từ session (nạp vào input_node)
    has_report: bool
    active_report_data: Optional[list]
    report_summary: Optional[str]
    history: List[Dict[str, str]]

    # Routing
    intent: str                        # general_chat | report_followup | medical_knowledge

    # Output
    answer: str


# =========================================================
# HELPERS
# =========================================================

def is_greeting(text: str) -> bool:
    greetings = {"hi", "hello", "xin chào", "chào", "chào bạn", "alo",
                 "ok", "cảm ơn", "thank you", "thanks"}
    return text.strip().lower() in greetings


def is_contextual_report_followup(text: str) -> bool:
    """Recognize questions that depend on the currently active report."""
    text_l = text.strip().lower()
    contextual_phrases = (
        "kết quả này",
        "phiếu này",
        "chỉ số này",
        "với kết quả",
        "trong phiếu",
        "tôi nên kiểm tra",
        "tôi cần đi khám",
        "triệu chứng nào",
        "khi nào cần đi khám",
        "có khẳng định tôi",
    )
    return any(phrase in text_l for phrase in contextual_phrases)


def is_urgent_red_flag_question(text: str) -> bool:
    text_l = text.strip().lower()
    return (
        "triệu chứng nào" in text_l
        or "khi nào cần đi khám" in text_l
        or "khi nào nên đi khám" in text_l
        or "dấu hiệu cảnh báo" in text_l
    )


def safe_route_intent(user_text: str, has_report: bool = False) -> str:
    if is_greeting(user_text):
        return "general_chat"

    if has_report and is_contextual_report_followup(user_text):
        return "report_followup"

    try:
        scores = {}
        model = rag_service.get_embedding_model()
        query_emb = model.encode(user_text)
        for intent, embs in rag_service.get_route_embeddings().items():
            scores[intent] = max([rag_service.cosine_similarity(query_emb, e) for e in embs])
        
        best = max(scores, key=scores.get)
        second = sorted(scores.values(), reverse=True)[1]
        
        if scores[best] - second > 0.1:
            logger.debug("Semantic routing selected %s with score %.3f.", best, scores[best])
            if best == "report_followup" and not has_report:
                return "medical_knowledge"
            return best
            
        logger.debug("Semantic routing scores are close: %.3f vs %.3f.", scores[best], second)
        prompt = f"""Phân loại ý định câu hỏi sau vào đúng 1 trong 3 nhãn:
- general_chat: hội thoại thông thường, chào hỏi, không liên quan xét nghiệm
- medical_knowledge: hỏi về kiến thức xét nghiệm máu, chỉ số, bệnh lý
- report_followup: hỏi về kết quả phiếu xét nghiệm cụ thể của bản thân {"(người dùng ĐÃ có phiếu)" if has_report else "(người dùng CHƯA có phiếu)"}

Câu hỏi: "{user_text}"

Chỉ trả về đúng 1 nhãn, không giải thích."""
        
        result = rag_service.call_llm(prompt).strip().lower()
        for intent in ["general_chat", "medical_knowledge", "report_followup"]:
            if intent in result:
                logger.debug("LLM router selected %s.", intent)
                if intent == "report_followup" and not has_report:
                    return "medical_knowledge"
                return intent
                
    except Exception as e:
        logger.warning("Intent routing failed; using keyword fallback: %s", e)

    text_l = user_text.lower()
    report_words = ["của tôi", "phiếu", "kết quả", "chỉ số này",
                    "bất thường", "cao", "thấp", "giảm", "tăng", "có sao không"]
    medical_words = ["wbc", "rbc", "hgb", "hct", "mcv", "plt", "neut",
                     "bạch cầu", "hồng cầu", "tiểu cầu", "glucose",
                     "creatinine", "ast", "alt", "cholesterol", "sinh hóa"]
    if has_report and any(w in text_l for w in report_words):
        return "report_followup"
    if any(w in text_l for w in medical_words):
        return "medical_knowledge"
    return "general_chat"


def format_evidence_block(evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "- Không có bằng chứng phù hợp."
    parts = []
    for i, e in enumerate(evidence, 1):
        src = e.get("source", "Unknown")
        page = e.get("page", "?")
        text = str(e.get("text") or e.get("bm25_text") or "")[:400]
        parts.append(f"[{i}] {src} trang {page}.\n\"{text}\"")
    return "\n\n".join(parts)


def build_clean_answer(raw: str, evidence: List[Dict[str, Any]]) -> str:
    try:
        return lab_core.build_user_visible_answer(raw, {}, evidence)
    except Exception:
        return raw


DIFFERENTIAL_LABELS = {
    "NEUT": "bạch cầu trung tính",
    "LYM": "bạch cầu lympho",
    "MONO": "bạch cầu mono",
    "EOS": "bạch cầu ái toan",
    "BASO": "bạch cầu ái kiềm",
}


def _find_report_indicator(report_data: List[Dict[str, Any]], names: set[str]) -> Optional[Dict[str, Any]]:
    for item in report_data:
        test_name = str(item.get("test_name") or "").upper().replace("_PERCENT", "%").replace("_ABS", "#")
        if test_name in names:
            return item
    return None


def _indicator_summary(item: Optional[Dict[str, Any]], display_name: str) -> str:
    if not item:
        return ""
    status_vi = {"high": "cao", "low": "thấp", "normal": "bình thường"}.get(
        str(item.get("status") or "").lower(), ""
    )
    value = item.get("value")
    unit = item.get("unit") or ""
    suffix = f", {status_vi}" if status_vi else ""
    return f"{display_name} = {value} {unit}{suffix}".strip()


def answer_common_lab_notation_question(
    user_text: str,
    report_data: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    text_upper = str(user_text or "").upper()
    asks_notation = any(token in str(user_text or "").lower() for token in (
        "là gì", "khác gì", "khác nhau", "viết tắt", "nghĩa là", "#", "%",
    ))
    if not asks_notation:
        return None

    code = next((item for item in DIFFERENTIAL_LABELS if re.search(rf"\b{item}\b", text_upper)), None)
    if not code:
        return None

    label = DIFFERENTIAL_LABELS[code]
    report_data = report_data or []
    percent_item = _find_report_indicator(report_data, {f"{code}%", f"{code}_PERCENT"})
    absolute_item = _find_report_indicator(report_data, {f"{code}#", f"{code}_ABS"})

    lines = [
        f"**{code} là gì?**",
        f"{code} là mã viết tắt của {label}, một nhóm tế bào bạch cầu trong máu.",
        "",
        "**Dấu % và # khác nhau như thế nào?**",
        f"- **{code}%**: tỷ lệ {label} trong tổng số bạch cầu.",
        f"- **{code}#**: số lượng tuyệt đối của {label} trong một thể tích máu, thường ghi bằng G/L hoặc 10^9/L.",
        "- Khi hai chỉ số không cùng chiều, trị số **#** thường quan trọng hơn để xác định có tăng/giảm thật hay chỉ thay đổi tỷ lệ.",
    ]

    report_values = [
        value for value in (
            _indicator_summary(percent_item, f"{code}%"),
            _indicator_summary(absolute_item, f"{code}#"),
        ) if value
    ]
    if report_values:
        lines.extend(["", "**Trong phiếu hiện tại:**", "- " + "; ".join(report_values) + "."])
        percent_status = str((percent_item or {}).get("status") or "").lower()
        absolute_status = str((absolute_item or {}).get("status") or "").lower()
        if absolute_status in {"high", "low"}:
            direction = "tăng" if absolute_status == "high" else "giảm"
            lines.append(
                f"- Vì {code}# cũng {direction}, đây không chỉ là thay đổi tỷ lệ; "
                f"số lượng {label} tuyệt đối cũng đang {direction}."
            )
        elif percent_status in {"high", "low"} and absolute_status == "normal":
            lines.append(
                f"- {code}% thay đổi nhưng {code}# bình thường, nên đây chủ yếu là thay đổi tỷ lệ tương đối."
            )
    return "\n".join(lines)


# =========================================================
# NODE 1 — input_node: nạp session vào state
# =========================================================

def input_node(state: ChatState) -> ChatState:
    """Nạp thông tin phiên hội thoại từ SESSION store vào state."""
    session = get_session(state["session_id"])
    return {
        **state,
        "has_report": bool(
            session.get("active_report_data") or session.get("report_summary")
        ),
        "active_report_data": session.get("active_report_data"),
        "report_summary": session.get("report_summary"),
        "history": session.get("history", []),
    }


# =========================================================
# NODE 2 — routing_node: phân loại ý định
# =========================================================

@observe(as_type="span", name="Graph Node: Router")
def routing_node(state: ChatState) -> ChatState:
    """Phân loại ý định người dùng thành 3 nhánh."""
    intent = safe_route_intent(state["user_text"], has_report=state["has_report"])
    logger.debug("Routing node selected intent=%s has_report=%s.", intent, state["has_report"])
    return {**state, "intent": intent}


def route_to_agent(state: ChatState) -> Literal["general_chat", "report_followup", "medical_knowledge"]:
    """Hàm điều kiện — quyết định node tiếp theo dựa trên intent."""
    intent = state["intent"]
    if intent == "report_followup" and state["has_report"]:
        return "report_followup"
    if intent == "medical_knowledge":
        return "medical_knowledge"
    return "general_chat"


# =========================================================
# NODE 3A — general_chat_node: hội thoại thông thường
# =========================================================

@observe(as_type="generation", name="Graph Node: General Chat")
def general_chat_node(state: ChatState) -> ChatState:
    """Tác nhân hội thoại thông thường — không cần bằng chứng y khoa."""
    user_text = state["user_text"]

    if is_greeting(user_text):
        answer = (
            "Xin chào! Bạn có thể gửi câu hỏi về xét nghiệm máu hoặc "
            "tải phiếu xét nghiệm để tôi hỗ trợ phân tích."
        )
        return {**state, "answer": answer}

    prompt = f"""Bạn là trợ lý y khoa hỗ trợ giải thích xét nghiệm máu bằng tiếng Việt.

Người dùng hỏi:
{user_text}

Yêu cầu:
- Trả lời ngắn gọn, dễ hiểu.
- Nếu câu hỏi không liên quan xét nghiệm máu, lịch sự nói rằng bạn hỗ trợ chính về xét nghiệm máu.
- Không chẩn đoán chắc chắn, không kê thuốc."""

    answer = rag_service.call_llm(prompt)
    return {**state, "answer": answer}


# =========================================================
# NODE 3B — medical_knowledge_node: hỏi đáp y khoa
# =========================================================

def _build_knowledge_ctx(user_text: str) -> Dict[str, Any]:
    try:
        panels = _infer_panels(user_text)
        tests, topics, conditions = [], [], []
        for panel in panels:
            try:
                tests += lab_core.detect_tests_in_text(user_text, panel)
                topics += lab_core.detect_topics_in_text(user_text, panel)
                kws = lab_core.extract_keywords(user_text, panel)
                conditions += lab_core.infer_conditions_from_text(
                    user_text, panel, tests, topics, kws
                )
            except Exception:
                pass
        hints = [user_text]
        for t in tests:
            hints += [f"{t} definition", f"{t} clinical significance",
                      f"{t} blood test meaning"]
        return {
            "case_id": "chat_knowledge",
            "panels": panels,
            "items": [],
            "abnormal_items": [],
            "abnormal_tests": sorted(set(tests)),
            "detected_patterns": [],
            "conditions": sorted(set(conditions)),
            "topics": sorted(set(topics)),
            "query_hints": hints,
        }
    except Exception:
        return {
            "case_id": "chat_knowledge", "panels": ["CBC", "BIOCHEM"],
            "items": [], "abnormal_items": [], "abnormal_tests": [],
            "detected_patterns": [], "conditions": [], "topics": [],
            "query_hints": [user_text],
        }


def _infer_panels(text: str) -> List[str]:
    text_l = text.lower()
    cbc_kws = ["wbc", "rbc", "hgb", "hct", "mcv", "mch", "plt", "neut",
               "lymph", "lym", "bạch cầu", "hồng cầu", "tiểu cầu"]
    biochem_kws = ["glucose", "creatinine", "urea", "ast", "alt", "cholesterol",
                   "triglyceride", "albumin", "men gan", "mỡ máu", "sinh hóa"]
    has_cbc = any(w in text_l for w in cbc_kws)
    has_bio = any(w in text_l for w in biochem_kws)
    if has_cbc and not has_bio:
        return ["CBC"]
    if has_bio and not has_cbc:
        return ["BIOCHEM"]
    return ["CBC", "BIOCHEM"]


@observe(as_type="generation", name="Graph Node: Medical Knowledge")
def medical_knowledge_node(state: ChatState) -> ChatState:
    """Tác nhân y khoa — trả lời câu hỏi kiến thức có bằng chứng từ KB."""
    user_text = state["user_text"]
    direct_answer = answer_common_lab_notation_question(user_text, state.get("active_report_data"))
    if direct_answer:
        return {**state, "answer": direct_answer}
    ctx = _build_knowledge_ctx(user_text)

    # Ưu tiên demo evidence local
    evidence: List[Dict[str, Any]] = []
    local_label = ""
    if cbc_demo_evidence:
        try:
            evidence = cbc_demo_evidence.get_cbc50_evidence_for_question(user_text) or []
            if evidence:
                local_label = "CBC50"
        except Exception:
            pass
    if not evidence and biochem_demo_evidence:
        try:
            evidence = biochem_demo_evidence.get_biochem50_evidence_for_question(user_text) or []
            if evidence:
                local_label = "BIOCHEM50"
        except Exception:
            pass

    # Fallback GraphRAG
    if not evidence:
        try:
            graph_ev = rag_service.fetch_evidence_from_neo4j(
                ctx["abnormal_tests"], ctx["conditions"]
            )
            vector_ev = lab_core.retrieve_evidence(ctx)
            combined = lab_core.dedup_evidence(graph_ev + vector_ev)
            evidence = lab_core.rerank_evidence(combined, ctx)
        except Exception as e:
            logger.warning("Medical knowledge evidence retrieval failed: %s", e)

    evidence = evidence[:3]
    ev_block = format_evidence_block(evidence)
    src_label = local_label or "Knowledge Graph / Vector DB"

    prompt = f"""Bạn là trợ lý y khoa giải thích xét nghiệm máu bằng tiếng Việt.

Câu hỏi:
{user_text}

Bằng chứng từ {src_label}:
{ev_block}

Yêu cầu:
- Trả lời trực tiếp, dễ hiểu, ngắn gọn dựa trên bằng chứng trên.
- Dùng citation [1], [2]... nếu thật sự lấy thông tin từ bằng chứng đó.
- Không chẩn đoán chắc chắn, không kê thuốc.
- Dùng từ "gợi ý", "có thể liên quan", "cần đối chiếu lâm sàng" khi nói về bất thường."""

    raw = rag_service.call_llm(prompt)
    if evidence and "[1]" not in raw:
        raw = raw.rstrip() + " [1]"
    answer = build_clean_answer(raw, evidence)
    return {**state, "answer": answer}


# =========================================================
# NODE 3C — report_followup_node: hỏi tiếp về phiếu
# =========================================================

@observe(as_type="generation", name="Graph Node: Report Follow-up")
def report_followup_node(state: ChatState) -> ChatState:
    """Tác nhân phiếu xét nghiệm — trả lời câu hỏi tiếp theo về phiếu đã phân tích."""
    user_text = state["user_text"]
    report_data = state["active_report_data"] or []
    report_summary = state["report_summary"] or ""
    direct_answer = answer_common_lab_notation_question(user_text, report_data)
    if direct_answer:
        return {**state, "answer": direct_answer}

    verified_context = None
    try:
        from medical_lab_ai_core.knowledge_base.verified_answer_context import (
            match_verified_runtime_context,
        )
        verified_context = match_verified_runtime_context(report_data)
    except Exception as exc:
        logger.debug("Verified follow-up context matching failed: %s", exc)

    if verified_context:
        evidence = (verified_context.get("evidence") or [])[:6]
        outline = verified_context.get("answer_outline") or {}
        red_flags = outline.get("urgent_red_flags_vi") or []
        if is_urgent_red_flag_question(user_text) and red_flags:
            items = "\n".join(f"- {item}" for item in red_flags)
            answer = (
                "Với các bất thường trên phiếu này, bạn nên đi khám sớm nếu có:\n\n"
                f"{items}\n\n"
                "Nếu chưa có các dấu hiệu trên, bạn vẫn nên trao đổi với bác sĩ "
                "và theo dõi lại CBC theo chỉ định."
            )
            return {**state, "answer": answer}
        ev_block = format_evidence_block(evidence)
        prompt = f"""Bạn là trợ lý y khoa hỗ trợ giải thích phiếu xét nghiệm máu bằng tiếng Việt.

Người dùng hỏi tiếp:
{user_text}

Dữ liệu phiếu:
{json.dumps(report_data, ensure_ascii=False)}

Nội dung y khoa đã kiểm chứng cho phiếu này:
{json.dumps(outline, ensure_ascii=False)}

Bằng chứng đã kiểm chứng:
{ev_block}

Yêu cầu:
- Trả lời đúng câu hỏi, ngắn gọn, dễ hiểu và dùng số liệu của phiếu khi hữu ích.
- Chỉ nêu nguyên nhân y khoa có trong atomic_claims; tuân thủ conditions_vi và forbidden_claims_vi.
- Chỉ đề xuất xét nghiệm hoặc hành động có trong recommended_actions_vi hoặc conditions_vi;
  không tự thêm xét nghiệm huyết thanh, CRP, thuốc hay thủ thuật từ kiến thức chung.
- Nếu người dùng hỏi khi nào cần đi khám hoặc hỏi về triệu chứng cảnh báo,
  chỉ trả lời từ urgent_red_flags_vi; không chuyển sang bệnh lý hay xét nghiệm khác.
- Dùng citation_numbers trong atomic_claims. Không gắn citation không hỗ trợ claim.
- Nếu một claim có nhiều citation_numbers, phải giữ đủ các citation đó; hệ thống sẽ tự đánh lại
  số liên tục trong câu trả lời và danh sách tài liệu.
- Không chẩn đoán chắc chắn, không kê thuốc.
- Không nhắc tới JSON, context, evidence ID hay quy tắc nội bộ."""
        raw = rag_service.call_llm(prompt)
        answer = build_clean_answer(raw, evidence)
        return {**state, "answer": answer}

    # Xây dựng ctx từ dữ liệu phiếu
    ctx = _build_knowledge_ctx(user_text)
    ctx["query_hints"] = list(ctx.get("query_hints", [])) + [user_text]

    try:
        graph_ev = rag_service.fetch_evidence_from_neo4j(
            ctx["abnormal_tests"], ctx["conditions"]
        )
        vector_ev = lab_core.retrieve_evidence(ctx)
        combined = lab_core.dedup_evidence(graph_ev + vector_ev)
        evidence = lab_core.rerank_evidence(combined, ctx)[:6]
    except Exception as e:
        logger.warning("Report follow-up evidence retrieval failed: %s", e)
        evidence = []

    ev_block = format_evidence_block(evidence)

    prompt = f"""Bạn là trợ lý y khoa hỗ trợ giải thích phiếu xét nghiệm máu bằng tiếng Việt.

Người dùng hỏi tiếp:
{user_text}

Tóm tắt phiếu xét nghiệm đã phân tích:
{report_summary}

Dữ liệu phiếu xét nghiệm:
{json.dumps(report_data, ensure_ascii=False)}

Bằng chứng từ Knowledge Graph / Vector DB:
{ev_block}

Yêu cầu:
- Trả lời dựa trên phiếu xét nghiệm của người dùng, dùng số liệu cụ thể nếu có.
- Dùng citation [1]...[6] nếu thật sự lấy thông tin từ bằng chứng tương ứng.
- Không bịa nguồn, không bịa chỉ số không có trong phiếu.
- Không chẩn đoán chắc chắn, không kê thuốc.
- Khuyên người dùng trao đổi bác sĩ nếu cần."""

    raw = rag_service.call_llm(prompt)
    answer = build_clean_answer(raw, evidence)
    return {**state, "answer": answer}


# NODE 4 — output_node: lưu history vào session
def output_node(state: ChatState) -> ChatState:
    session = get_session(state["session_id"])

    session["history"].append({
        "role": "user",
        "content": state["user_text"]
    })

    session["history"].append({
        "role": "assistant",
        "content": state["answer"]
    })

    if len(session["history"]) > 40:
        session["history"] = session["history"][-40:]

    return state


# =========================================================
# GRAPH CONSTRUCTION
# =========================================================

def build_graph() -> Any:
    if StateGraph is None:
        raise RuntimeError("langgraph is required to build the chat workflow.")
    g = StateGraph(ChatState)

    g.add_node("input_node",            input_node)
    g.add_node("routing_node",          routing_node)
    g.add_node("general_chat",          general_chat_node)
    g.add_node("medical_knowledge",     medical_knowledge_node)
    g.add_node("report_followup",       report_followup_node)
    g.add_node("output_node",           output_node)

    g.add_edge(START,           "input_node")
    g.add_edge("input_node",    "routing_node")

    g.add_conditional_edges(
        "routing_node",
        route_to_agent,
        {
            "general_chat":      "general_chat",
            "medical_knowledge": "medical_knowledge",
            "report_followup":   "report_followup",
        },
    )

    g.add_edge("general_chat",      "output_node")
    g.add_edge("medical_knowledge", "output_node")
    g.add_edge("report_followup",   "output_node")
    g.add_edge("output_node",       END)

    return g.compile()


_graph = None

def get_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph

logger.debug(
    "LangGraph compiled with nodes: %s",
    ["input_node", "routing_node", "general_chat", "medical_knowledge", "report_followup", "output_node"],
)


# =========================================================
# ENTRY POINT — gọi từ chatbot_api.py
# =========================================================

@observe(name="LangGraph Chat Workflow")
def handle_chat(text: str, session_id: str) -> Dict[str, str]:
    """
    Entry point chính — chạy StateGraph và trả về answer + intent.
    Interface giữ nguyên để chatbot_api.py không cần sửa.
    """
    # Gắn trace hiện tại theo session của user
    langfuse_context.update_current_trace(
        session_id=session_id or "default",
        tags=["langgraph_chat"]
    )
    
    user_text = (text or "").strip()
    if not user_text:
        return {"answer": "Bạn vui lòng nhập câu hỏi nhé.", "intent": "general_chat"}

    initial_state: ChatState = {
        "user_text":          user_text,
        "session_id":         session_id or "default",
        "has_report":         False,
        "active_report_data": None,
        "report_summary":     None,
        "history":            [],
        "intent":             "",
        "answer":             "",
    }

    try:
        result = get_graph().invoke(initial_state)
        return {
            "answer": result.get("answer", ""),
            "intent": result.get("intent", "general_chat"),
        }
    except Exception:
        logger.error("Chat handling failed:\n%s", traceback.format_exc())
        return {
            "answer": "Xin lỗi, hệ thống gặp lỗi khi xử lý câu hỏi.",
            "intent": "general_chat",
        }