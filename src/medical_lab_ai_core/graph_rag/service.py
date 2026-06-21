import os
import json
import uuid
import logging
import requests
import numpy as np
from pathlib import Path
from dotenv import load_dotenv

# Load biến môi trường
BASE_DIR = Path(__file__).resolve().parents[3]
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# =========================================================
# KẾT NỐI CÁC EXTERNAL SERVICES (LLM, NEO4J, QDRANT)
# =========================================================
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

try:
    from langfuse.decorators import observe, langfuse_context
except ImportError:
    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    class _NoopLangfuseContext:
        def update_current_observation(self, **kwargs):
            return None

        def update_current_trace(self, **kwargs):
            return None

    langfuse_context = _NoopLangfuseContext()

# Import Core Engine duy nhất
from medical_lab_ai_core.core import config, lab_core

COLAB_LLM_URL = getattr(config, "COLAB_LLM_URL", "").strip()
COLAB_API_KEY = getattr(config, "COLAB_API_KEY", "").strip()
COLAB_MAX_NEW_TOKENS = getattr(config, "COLAB_MAX_NEW_TOKENS", 970)
COLAB_TEMPERATURE = getattr(config, "COLAB_TEMPERATURE", 0.2)
COLAB_TIMEOUT = getattr(config, "COLAB_TIMEOUT", 300)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

logger = logging.getLogger(__name__)
neo4j_driver = None
embedding_model = None
_route_embeddings = None


def get_neo4j_driver():
    global neo4j_driver
    if GraphDatabase is None:
        return None
    if neo4j_driver is None:
        try:
            neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            neo4j_driver.verify_connectivity()
        except Exception as exc:
            logger.warning("Neo4j connection unavailable: %s", exc)
            neo4j_driver = None
    return neo4j_driver


def get_embedding_model():
    global embedding_model
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is required for semantic routing.")
    if embedding_model is None:
        embedding_model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    return embedding_model

# =========================================================
# SEMANTIC ROUTING (PHÂN LUỒNG Ý ĐỊNH CHATBOT)
# =========================================================
ROUTE_EXAMPLES = {
    "report_followup": [
        "của tôi", "kết quả", "report", "phiếu", "chỉ số này", "nó", "cái này", 
        "bất thường", "có sao không", "xét nghiệm của tôi", "đọc giúp tôi",
        "chỉ số wbc của tôi cao quá", "tại sao giảm", "kiểm tra lại", "bị bệnh gì"
    ],
    "medical_knowledge": [
        "wbc là gì", "rbc là gì", "hgb", "hct", "mcv", "mch", "mchc", "plt", "neut", 
        "lym", "mono", "eos", "baso", "ig", "máu", "cbc", "bạch cầu là gì", 
        "hồng cầu", "bệnh thiếu máu", "tiểu cầu", "triệu chứng", "nguyên nhân"
    ],
    "general_chat": [
        "xin chào", "hello", "hi", "cảm ơn", "thank you", "bạn là ai", 
        "tạm biệt", "chào bác sĩ", "ok", "dạ", "chào"
    ]
}
def get_route_embeddings():
    global _route_embeddings
    if _route_embeddings is None:
        model = get_embedding_model()
        _route_embeddings = {intent: model.encode(examples) for intent, examples in ROUTE_EXAMPLES.items()}
    return _route_embeddings

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

@observe(as_type="span", name="Semantic Routing")
def semantic_route_intent(query: str, has_report: bool = False) -> str:
    model = get_embedding_model()
    query_emb = model.encode(query)
    best_intent, best_score = "general_chat", -1

    for intent, embs in get_route_embeddings().items():
        max_score = max([cosine_similarity(query_emb, e) for e in embs])
        if max_score > best_score:
            best_score, best_intent = max_score, intent

    langfuse_context.update_current_observation(output={"intent": best_intent, "confidence": float(best_score)})

    if has_report and best_intent == "medical_knowledge" and best_score < 0.6:
        return "report_followup"
    return best_intent if best_score >= 0.35 else "general_chat"


# =========================================================
# GỌI LLM (DEEPSEEK / GEMINI)
# =========================================================
@observe(as_type="generation", name="Gemini Fallback Generation")
def call_gemini(prompt):
    if genai is None or types is None:
        raise RuntimeError("google-genai is required for Gemini generation.")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    client = genai.Client(api_key=api_key)
    res = client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=2000)
    )
    return res.text.strip()

@observe(as_type="generation", name="OpenRouter Generation")
def call_deepseek(prompt):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"model": OPENROUTER_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 2000}
    res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=40)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()
@observe(as_type="generation", name="Colab LLM Generation")
def call_colab_llm(prompt):
    if not COLAB_LLM_URL:
        raise RuntimeError("Thiếu COLAB_LLM_URL trong .env")

    headers = {
        "Content-Type": "application/json"
    }

    if COLAB_API_KEY:
        headers["Authorization"] = f"Bearer {COLAB_API_KEY}"

    payload = {
        "prompt": prompt,
        "max_new_tokens": COLAB_MAX_NEW_TOKENS,
        "temperature": COLAB_TEMPERATURE,
    }

    res = requests.post(
        COLAB_LLM_URL,
        headers=headers,
        json=payload,
        timeout=COLAB_TIMEOUT,
    )
    res.raise_for_status()

    data = res.json()

    answer = (
        data.get("response")
        or data.get("answer")
        or data.get("text")
        or data.get("generated_text")
        or ""
    )

    if not answer.strip():
        raise RuntimeError(f"Colab response không có nội dung hợp lệ: {data}")

    return answer.strip()
@observe(as_type="generation", name="Groq Generation")
def call_groq(prompt):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")
    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": groq_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 2000
    }
    res = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers, json=data, timeout=30
    )
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()

@observe(as_type="span", name="LLM Execution")
def call_llm(prompt):
    providers = []
    if os.getenv("GROQ_API_KEY", "").strip():
        providers.append(("Groq", call_groq))
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        providers.append(("OpenRouter", call_deepseek))
    if COLAB_LLM_URL:
        providers.append(("Colab", call_colab_llm))
    if os.getenv("GEMINI_API_KEY", "").strip():
        providers.append(("Gemini", call_gemini))

    if not providers:
        raise RuntimeError(
            "Chưa cấu hình LLM. Hãy thêm ít nhất một API key vào file .env "
            "(GROQ_API_KEY, OPENROUTER_API_KEY hoặc GEMINI_API_KEY)."
        )

    errors = []
    for name, provider in providers:
        try:
            return provider(prompt)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger.warning("%s generation failed: %s", name, exc)

    raise RuntimeError("Tất cả LLM provider đã cấu hình đều lỗi: " + " | ".join(errors))


# =========================================================
# NEO4J QUERY CORE
# =========================================================
@observe(as_type="retrieval", name="Neo4j Cypher Retrieval")
def fetch_evidence_from_neo4j(abnormal_tests: list, conditions: list) -> list:
    driver = get_neo4j_driver()
    if not driver or (not abnormal_tests and not conditions):
        return []
    
    # Query đồ thị: Tìm sách y khoa (Evidence) hỗ trợ các Bệnh lý (Condition) hoặc có nhắc tới Chỉ số (Test)
    query = """
    MATCH (e:Evidence)
    OPTIONAL MATCH (e)-[:MENTIONS_TEST]->(t:Test)
    OPTIONAL MATCH (e)-[:SUPPORTS]->(c:Condition)
    WHERE t.test_code IN $tests OR c.name IN $conditions
    RETURN DISTINCT e.id AS evidence_id, e.text AS text, e.source AS source, 
                    e.page AS page, e.score AS kb_score, e.panel AS panel
    ORDER BY kb_score DESC
    LIMIT 6
    """
    evidence_list = []
    with driver.session() as session:
        result = session.run(query, tests=abnormal_tests, conditions=conditions)
        for r in result:
            evidence_list.append({
                "evidence_id": r["evidence_id"],
                "text": r["text"],
                "source": r["source"],
                "page": r["page"],
                "kb_score": r["kb_score"],
                "panel": r["panel"],
                "tests": abnormal_tests,
                "conditions": conditions,
                "score": r["kb_score"] + 0.5  # Boost điểm vì lấy từ Graph có độ ưu tiên cao
            })
            
    langfuse_context.update_current_observation(output={"nodes_found": len(evidence_list)})
    return evidence_list


# =========================================================
# LUỒNG CHÍNH (GRAPHRAG PIPELINE)
# =========================================================
def format_ui_data_to_case(user_indicators: list, session_id: str) -> dict:
    case_data = {
        "case_id": session_id or f"realtime_{uuid.uuid4().hex[:6]}",
        "data": []
    }
    for item in user_indicators:
        ref_min = item.get('ref_range', {}).get('ref_min', '')
        ref_max = item.get('ref_range', {}).get('ref_max', '')
        ref_str = f"{ref_min} - {ref_max}".strip(" -")
        
        case_data["data"].append({
            "test_name": item.get("test_name"),
            "value": item.get("value"),
            "unit": item.get("unit", ""),
            "status": item.get("status"),
            "reference_range": ref_str
        })
    return case_data


@observe(name="GraphRAG Report Analysis")
def analyze_indicators_with_llm(
    user_indicators: list,
    session_id: str = None,
    demo_case_id: str = None,
) -> str:
    if session_id:
        langfuse_context.update_current_trace(session_id=session_id, tags=["graphrag_analysis"])
        
    logger.info("Starting GraphRAG analysis.")

    # 1. Chuyen doi Du lieu & Xay dung Context Suy luan
    case_dict = format_ui_data_to_case(user_indicators, session_id)
    ctx = lab_core.build_reasoning_context(case_dict, 0)
    
    cbc_demo = lab_core.load_jsonl(config.CBC_DEMO_PATTERN_PATH) if config.CBC_DEMO_PATTERN_PATH.exists() else []
    biochem_patt = lab_core.load_json(config.BIOCHEM_PATTERN_PATH) if config.BIOCHEM_PATTERN_PATH.exists() else {}
    ctx = lab_core.augment_reasoning_context_with_static_patterns(ctx, cbc_demo, biochem_patt)

    demo_context = None
    if demo_case_id:
        try:
            from medical_lab_ai_core.knowledge_base.clinical_demo_context import get_runtime_context

            demo_context = get_runtime_context(demo_case_id)
            if demo_context:
                ctx["case_id"] = demo_case_id
                ctx["detected_patterns"] = demo_context["patterns"]
                ctx["conditions"] = demo_context["conditions"]
                ctx["curated_answer_outline"] = demo_context["answer_outline"]
                logger.info(
                    "Using verified clinical graph context %s for demo case %s.",
                    demo_context["schema_version"], demo_case_id,
                )
        except Exception as exc:
            logger.warning("Clinical demo context loading failed: %s", exc)

    abnormal_tests = ctx.get("abnormal_tests", [])
    conditions = ctx.get("conditions", [])

    if not ctx.get("abnormal_items"):
        return "Ket qua xet nghiem cua ban nam trong gioi han tham chieu. Khong phat hien chi so bat thuong nao."

    # 2. Truy xuất kiến thức. Demo V3 ưu tiên evidence exact-match PDF,
    # sau đó bổ sung evidence từ gói sách QA100 nếu liên quan trực tiếp.
    if demo_context:
        from medical_lab_ai_core.knowledge_base.curated_evidence import retrieve_for_report_context

        supplemental_evidence = retrieve_for_report_context(
            ctx,
            max_items=config.MAX_FINAL_EVIDENCE,
        )
        # Không áp dụng kết luận dành riêng cho trẻ em khi phiếu
        # không có tuổi. Các đoạn khác trên cùng trang vẫn có thể dùng.
        supplemental_evidence = [
            item for item in supplemental_evidence
            if "in children" not in str(item.get("text") or "").lower()
        ]
        combined_evidence = lab_core.dedup_evidence(
            supplemental_evidence + demo_context["evidence"]
        )
        final_evidence = lab_core.rerank_evidence(
            combined_evidence,
            ctx,
        )[:config.MAX_FINAL_EVIDENCE]
        evidence_blob = " ".join(
            str(item.get("text") or "").lower() for item in final_evidence
        )
        etiology_terms = [
            term for term in ("infection", "inflammation", "stress", "drug", "medication")
            if term in evidence_blob
        ]
        runtime_guardrails = (
            ctx.get("curated_answer_outline", {})
            .setdefault("runtime_guardrails", {})
        )
        runtime_guardrails["etiology_supported_by_current_evidence"] = bool(etiology_terms)
        runtime_guardrails["etiology_terms_found_in_evidence"] = etiology_terms
        runtime_guardrails["etiology_support_scope"] = "evaluation_context_only"
        runtime_guardrails["etiology_scope_instruction"] = (
            "Evidence bổ sung chỉ hỗ trợ các bối cảnh cần đánh giá; "
            "không xác nhận nguyên nhân hoặc chẩn đoán cho ca hiện tại."
        )
        logger.info(
            "Demo V3 returned %s case evidence items plus %s curated book items.",
            len(demo_context["evidence"]),
            len(supplemental_evidence),
        )
    else:
        logger.info("Querying Neo4j for conditions: %s", conditions)
        graph_evidence = fetch_evidence_from_neo4j(abnormal_tests, conditions)

        # Path D: INDICATES chain
        try:
            from medical_lab_ai_core.retrieval.neo4j_retriever import retrieve_by_indicates
            abnormal_items = [
                {"test": item.get("test_name", ""), "status": item.get("status", "")}
                for item in user_indicators
                if (item.get("status") or "").lower() in ("high", "low")
            ]
            indicates_evidence = retrieve_by_indicates(abnormal_items, limit_per_test=3)
            graph_evidence = graph_evidence + indicates_evidence
            logger.info("INDICATES chain returned %s evidence items.", len(indicates_evidence))
        except Exception as e:
            logger.warning("INDICATES chain retrieval skipped: %s", e)

        logger.info("Querying Qdrant vector evidence.")
        vector_evidence = lab_core.retrieve_evidence(ctx)

        try:
            from medical_lab_ai_core.knowledge_base.curated_evidence import retrieve_for_report_context

            curated_evidence = retrieve_for_report_context(ctx, max_items=config.MAX_FINAL_EVIDENCE)
            logger.info("Curated QA100 packs returned %s evidence items.", len(curated_evidence))
        except Exception as exc:
            logger.warning("Curated QA100 evidence retrieval skipped: %s", exc)
            curated_evidence = []

        combined_evidence = lab_core.dedup_evidence(
            curated_evidence + graph_evidence + vector_evidence
        )
        final_evidence = lab_core.rerank_evidence(combined_evidence, ctx)[:config.MAX_FINAL_EVIDENCE]

    graph_reasoning_paths = (
        demo_context["reasoning_paths"]
        if demo_context
        else lab_core.enrich_reasoning_paths(ctx, final_evidence)
    )

    prompt = lab_core.build_final_prompt(
        reasoning_context=ctx,
        evidence=final_evidence,
        reasoning_paths=graph_reasoning_paths
    )

    raw_answer = call_llm(prompt)
    final_answer = lab_core.build_user_visible_answer(raw_answer, ctx, final_evidence)

    return final_answer

