# Refactor Report

## Summary

The public AI-core repository `medical-lab-ai-core` has been created and organized according to the approved scope. No original files outside `medical-lab-ai-core` were modified, deleted, renamed, or moved.

## Files Copied

- `medical-chatbot/ocr_service.py` -> `src/medical_lab_ai_core/ocr/service.py`
- `medical-chatbot/ontology_tests.json` -> `configs/ontology_tests.json`
- `medical-chatbot/ontology_units.json` -> `configs/ontology_units.json`
- `medical-chatbot/rag_kg/lab_unified_rag/config.py` -> `src/medical_lab_ai_core/core/config.py`
- `medical-chatbot/rag_kg/lab_unified_rag/lab_core.py` -> `src/medical_lab_ai_core/core/lab_core.py`
- `medical-chatbot/rag_kg/lab_unified_rag/indicates_mapping.py` -> `src/medical_lab_ai_core/extraction/indicates_mapping.py`
- `medical-chatbot/rag_kg/lab_unified_rag/neo4j_retriever.py` -> `src/medical_lab_ai_core/retrieval/neo4j_retriever.py`
- `medical-chatbot/rag_service.py` -> `src/medical_lab_ai_core/graph_rag/service.py`
- `medical-chatbot/chatbot_service_v2.py` -> `src/medical_lab_ai_core/agents/langgraph_chatbot.py`
- `medical-chatbot/cbc_demo_evidence.py` -> `src/medical_lab_ai_core/knowledge_base/cbc_demo_evidence.py`
- `medical-chatbot/biochem_demo_evidence.py` -> `src/medical_lab_ai_core/knowledge_base/biochem_demo_evidence.py`
- `medical-chatbot/rag_kg/lab_unified_rag/build_kb.py` -> `scripts/build_kb.py`
- `medical-chatbot/rag_kg/lab_unified_rag/build_index.py` -> `scripts/build_qdrant_index.py`
- `medical-chatbot/rag_kg/lab_unified_rag/build_graph.py` -> `scripts/build_neo4j_graph.py`
- `medical-chatbot/rag_kg/lab_unified_rag/run_final.py` -> `scripts/run_graphrag.py`
- `medical-chatbot/rag_kg/lab_unified_rag/run_llm_only.py` -> `scripts/run_llm_only.py`

## Files Created

- `.env.example`
- `.gitignore`
- `requirements.txt`
- `README.md`
- `docs/ARCHITECTURE.md`
- `examples/demo_cases_all_clean.sample.json`
- `examples/patterns/cbc_patterns.sample.jsonl`
- `examples/patterns/biochem_patterns.sample.json`
- `tests/test_smoke.py`
- Package `__init__.py` files
- `src/medical_lab_ai_core/llm/providers.py`
- `REFACTOR_PLAN.md`
- `REFACTOR_REPORT.md`

## Changes Made Inside the New Repository

- Converted flat imports to package imports under `medical_lab_ai_core`.
- Added direct-script support through `src/` path setup in scripts.
- Changed repository paths to be relative to the new repository root.
- Moved Qdrant, Neo4j, embedding, and LLM settings to environment variables.
- Replaced the old hard-coded Neo4j password default with a safe placeholder.
- Repointed OCR ontology paths to `configs/`.
- Added safe synthetic examples instead of copying real or large datasets.
- Rewrote `README.md` in English for external reviewers and contributors.
- Added optional/lazy imports for heavy OCR, database, GraphRAG, and LLM dependencies.
- Replaced debug prints in core GraphRAG, LangGraph, Neo4j retrieval, and LLM provider paths with logging.
- Removed duplicate LangGraph graph-construction code from the copied agent module.
- Removed the direct quick-test block from the Neo4j retriever; smoke tests live under `tests/`.

## Excluded Content

- Backend/API code: `ocr_api.py`, `chatbot_api.py`, FastAPI, Uvicorn, multipart upload handlers.
- Frontend/mobile code: `index.html`, Flutter or mobile application code.
- Secrets: `.env`, API keys, access tokens, passwords, private endpoints.
- Local environments and caches: `.venv/`, `.git/`, `__pycache__/`, `.pyc`.
- Generated outputs: logs, evaluation outputs, result CSV/JSONL files, charts.
- Raw source PDFs and generated database artifacts.
- Checkpoints, model weights, Qdrant snapshots, and Neo4j dumps.
- Temporary patch files, `.bak` files, profiling outputs, and obsolete experiments.

## Dependencies

Dependencies are documented in `requirements.txt`: PaddleOCR/PaddlePaddle, OpenCV, Pillow, NumPy, PyMuPDF, python-dotenv, requests, typing-extensions, sentence-transformers, qdrant-client, Neo4j, LangGraph, Langfuse, and google-genai.

## Environment Variables

- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`
- `GROQ_API_KEY`, `GROQ_MODEL`
- `COLAB_LLM_URL`, `COLAB_API_KEY`, `COLAB_MAX_NEW_TOKENS`, `COLAB_TEMPERATURE`, `COLAB_TIMEOUT`
- `LOCAL_LLM_URL`, `LOCAL_LLM_MODEL`
- `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_COLLECTION`, `EMBEDDING_MODEL_NAME`
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- `REQUEST_TIMEOUT`

## Commands

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
$env:PYTHONPATH = "src"
```

OCR:

```powershell
python -m medical_lab_ai_core.ocr.service path\to\image_or_folder
```

Build and retrieval scripts:

```powershell
python scripts/build_kb.py
python scripts/build_qdrant_index.py
python scripts/build_neo4j_graph.py
python scripts/run_graphrag.py
python scripts/run_llm_only.py
```

Validation:

```powershell
python -m compileall src scripts tests
python -m unittest discover -s tests
```

## Validation Performed

- Python syntax validation with `python -m compileall src scripts tests`: passed.
- Offline smoke tests with `python -m unittest discover -s tests`: passed, 3 tests.
- Import validation with `PYTHONPATH=src`: passed for package root, config, lab_core, Neo4j retriever, GraphRAG service, LangGraph agent module, and OCR service module.
- Secret and local-path scan: no hard-coded API keys, private tokens, old password literals, or local absolute workspace paths were found in repository contents.
- Frontend/backend scan: no FastAPI, Uvicorn, UploadFile, APIRouter, Flutter, or frontend entrypoint was found in `src/` or `scripts/`.
- Cache scan: no `.env`, `__pycache__`, `.pyc`, `.bak`, or patch files remain in the new repository.

## Not Fully Validated

- End-to-end OCR was not run because it can download OCR models and requires report images.
- Qdrant and Neo4j retrieval were not run against production or private databases.
- LLM calls were not executed to avoid paid or external API usage.
- KB construction from raw PDFs was not run because raw source documents are excluded from the public repository.
- README usage commands that require external assets/services were verified for paths and structure, but not executed end-to-end.

## Unresolved Items

- No license has been selected; reuse permissions are not defined.
- Public sample datasets are intentionally minimal and synthetic.
- External source documents, processed KB files, Qdrant collections, Neo4j data, and model files must be supplied separately.

## Confirmation

All changes were made inside `medical-lab-ai-core`. Existing files in `medical-chatbot` were not modified, deleted, renamed, or moved by this refactor. The old repository already had unrelated modified and untracked files before this continuation; they were left untouched.
