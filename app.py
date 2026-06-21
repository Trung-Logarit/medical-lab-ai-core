from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "web" / "index.html"
DEMO_REPORTS_PATH = BASE_DIR / "data" / "demo" / "all_results_data_ocr.jsonl"
load_dotenv(BASE_DIR / ".env")


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


class ChatMessage(BaseModel):
    text: str
    session_id: str


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

        summary = analyze_indicators_with_llm(data.indicators, data.session_id)
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
