from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import threading
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "web" / "index.html"
DEMO_REPORTS_PATH = BASE_DIR / "data" / "demo" / "all_results_data_ocr.jsonl"
TRANSLATION_CACHE_PATH = BASE_DIR / "data" / "cache" / "evidence_translations.json"
load_dotenv(BASE_DIR / ".env")
_translation_cache_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("OCR_PRELOAD", "true").strip().lower() in {"1", "true", "yes", "on"}:
        from medical_lab_ai_core.ocr.service import get_ocr_engine

        await asyncio.to_thread(get_ocr_engine)
    yield


app = FastAPI(title="Medical Lab AI Demo", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConfirmedData(BaseModel):
    indicators: list[dict[str, Any]]
    session_id: str
    demo_case_id: Optional[str] = None


class ChatMessage(BaseModel):
    text: str
    session_id: str


class EvidenceTranslationRequest(BaseModel):
    text: str


@lru_cache(maxsize=1)
def load_demo_reports() -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    if not DEMO_REPORTS_PATH.exists():
        return reports
    with DEMO_REPORTS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            report_id = str(row.get("id") or "").strip()
            if report_id:
                reports[report_id] = row
    return reports


@lru_cache(maxsize=1)
def load_translation_cache() -> dict[str, str]:
    if not TRANSLATION_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(TRANSLATION_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_translation_cache(cache: dict[str, str]) -> None:
    TRANSLATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = TRANSLATION_CACHE_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(TRANSLATION_CACHE_PATH)


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(INDEX_PATH)


@app.get("/health")
def health() -> dict[str, Any]:
    providers = {
        "groq": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
        "colab": bool(os.getenv("COLAB_LLM_URL", "").strip()),
        "gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
    }
    return {"status": "ok", "llm_providers": providers}


@app.options("/api/v1/{endpoint}", include_in_schema=False)
def api_options(endpoint: str) -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/demo-reports")
def list_demo_reports() -> dict[str, Any]:
    reports = load_demo_reports()
    try:
        from medical_lab_ai_core.knowledge_base.clinical_demo_context import available_case_ids

        verified_cases = available_case_ids()
    except Exception:
        verified_cases = set()
    items = []
    for report_id, report in reports.items():
        indicators = report.get("data", []) or []
        abnormal_count = sum(
            str(item.get("status") or "").lower() in {"high", "low"}
            for item in indicators
        )
        items.append({
            "id": report_id,
            "indicator_count": len(indicators),
            "abnormal_count": abnormal_count,
            "verified_v3": report_id in verified_cases,
        })
    return {"status": "success", "reports": items}


@app.get("/api/v1/demo-reports/{report_id}")
def get_demo_report(report_id: str) -> dict[str, Any]:
    report = load_demo_reports().get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiếu demo.")
    return {"status": "success", "report": report}


@app.post("/api/v1/extract")
def extract_ocr(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "report.jpg").suffix or ".jpg"
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = Path(temp_file.name)

        from medical_lab_ai_core.ocr.service import run_end_to_end_pipeline

        extracted = run_end_to_end_pipeline(temp_path)
        if not extracted:
            return {
                "status": "error",
                "message": "OCR không tìm thấy bảng chỉ số nào trong ảnh.",
            }
        return {"status": "success", "ocr_table": extracted}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    finally:
        file.file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@app.post("/api/v1/analyze")
def analyze_report(data: ConfirmedData) -> dict[str, Any]:
    try:
        from medical_lab_ai_core.agents.langgraph_chatbot import update_session_memory
        from medical_lab_ai_core.graph_rag.service import analyze_indicators_with_llm

        summary = analyze_indicators_with_llm(
            data.indicators,
            data.session_id,
            demo_case_id=data.demo_case_id,
        )
        update_session_memory(
            session_id=data.session_id,
            active_report_data=data.indicators,
            report_summary=summary,
        )
        return {"status": "success", "summary": summary}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@app.post("/api/v1/chat")
def chat(msg: ChatMessage) -> dict[str, Any]:
    try:
        from medical_lab_ai_core.agents.langgraph_chatbot import handle_chat

        result = handle_chat(msg.text, msg.session_id)
        return {"status": "success", **result}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@app.post("/api/v1/translate-evidence")
def translate_evidence(data: EvidenceTranslationRequest) -> dict[str, Any]:
    source_text = " ".join(str(data.text or "").split()).strip()
    if not source_text:
        return {"status": "error", "message": "Dẫn chứng đang trống."}
    if len(source_text) > 2500:
        return {"status": "error", "message": "Dẫn chứng quá dài để dịch."}

    cache_key = source_text.casefold()
    with _translation_cache_lock:
        cached = load_translation_cache().get(cache_key)
    if cached:
        return {"status": "success", "translation": cached, "cached": True}

    try:
        from medical_lab_ai_core.graph_rag.service import call_llm

        prompt = f"""
Dịch nguyên văn y khoa sau từ tiếng Anh sang tiếng Việt.
Yêu cầu:
- Dịch trung thành, không thêm, bớt hoặc diễn giải.
- Giữ nguyên số liệu, đơn vị, tên viết tắt và thuật ngữ xét nghiệm cần thiết.
- Chỉ trả về bản dịch tiếng Việt, không mở đầu, không ghi chú.

Nguyên văn:
{source_text}
""".strip()
        translation = " ".join(call_llm(prompt).split()).strip()
        if not translation:
            raise RuntimeError("Mô hình trả về bản dịch trống.")

        with _translation_cache_lock:
            cache = load_translation_cache()
            cache[cache_key] = translation
            save_translation_cache(cache)
        return {"status": "success", "translation": translation, "cached": False}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
