# Refactor Plan

Target repository: `medical-lab-ai-core`

Scope: public AI-core source code for OCR, laboratory-field extraction, normalization, Qdrant retrieval, Neo4j knowledge graph retrieval, GraphRAG orchestration, LangGraph agents, LLM integration, and safe synthetic or anonymized examples.

## Files Selected for Copying

### OCR and Image Processing

- `medical-chatbot/ocr_service.py` -> `src/medical_lab_ai_core/ocr/service.py`
- `medical-chatbot/ontology_tests.json` -> `configs/ontology_tests.json`
- `medical-chatbot/ontology_units.json` -> `configs/ontology_units.json`

### Extraction, Normalization, and Reasoning

- `medical-chatbot/rag_kg/lab_unified_rag/lab_core.py` -> `src/medical_lab_ai_core/core/lab_core.py`
- `medical-chatbot/rag_kg/lab_unified_rag/indicates_mapping.py` -> `src/medical_lab_ai_core/extraction/indicates_mapping.py`
- `medical-chatbot/cbc_demo_evidence.py` -> `src/medical_lab_ai_core/knowledge_base/cbc_demo_evidence.py`
- `medical-chatbot/biochem_demo_evidence.py` -> `src/medical_lab_ai_core/knowledge_base/biochem_demo_evidence.py`

### Knowledge Base, Qdrant, Neo4j, and GraphRAG

- `medical-chatbot/rag_kg/lab_unified_rag/config.py` -> `src/medical_lab_ai_core/core/config.py`
- `medical-chatbot/rag_kg/lab_unified_rag/build_kb.py` -> `scripts/build_kb.py`
- `medical-chatbot/rag_kg/lab_unified_rag/build_index.py` -> `scripts/build_qdrant_index.py`
- `medical-chatbot/rag_kg/lab_unified_rag/build_graph.py` -> `scripts/build_neo4j_graph.py`
- `medical-chatbot/rag_kg/lab_unified_rag/neo4j_retriever.py` -> `src/medical_lab_ai_core/retrieval/neo4j_retriever.py`
- `medical-chatbot/rag_kg/lab_unified_rag/run_final.py` -> `scripts/run_graphrag.py`
- `medical-chatbot/rag_service.py` -> `src/medical_lab_ai_core/graph_rag/service.py`

### LangGraph and LLM Integration

- `medical-chatbot/chatbot_service_v2.py` -> `src/medical_lab_ai_core/agents/langgraph_chatbot.py`
- LLM provider entry points are exposed through `src/medical_lab_ai_core/llm/providers.py`.

### Scripts and Tests

- `medical-chatbot/rag_kg/lab_unified_rag/run_llm_only.py` -> `scripts/run_llm_only.py`
- Offline smoke tests are placed under `tests/`.

### Safe Examples

- Synthetic laboratory cases -> `examples/demo_cases_all_clean.sample.json`
- Synthetic CBC patterns -> `examples/patterns/cbc_patterns.sample.jsonl`
- Synthetic biochemistry patterns -> `examples/patterns/biochem_patterns.sample.json`

## Files Excluded

### Backend and API Code

- `medical-chatbot/ocr_api.py`
- `medical-chatbot/chatbot_api.py`
- FastAPI, Uvicorn, multipart upload handlers, and REST API code.

### Frontend Code

- `medical-chatbot/index.html`
- Flutter or mobile application code.

### Secrets and Local Configuration

- `.env` files.
- API keys, tokens, database passwords, private endpoints, and production credentials.

### Data, Outputs, and Temporary Artifacts

- `.venv/`, `.git/`, `__pycache__/`
- `outputs/`, `intent_eval_outputs/`, generated evaluation outputs, CSV/JSONL result files, and chart images.
- Raw PDF source documents.
- Full generated Neo4j CSV files and Qdrant snapshots.
- `.bak`, patch scripts, profiling outputs, and obsolete experimental scripts.

## Target Structure

```text
medical-lab-ai-core/
├── configs/
├── docs/
├── examples/
├── scripts/
├── src/medical_lab_ai_core/
│   ├── agents/
│   ├── core/
│   ├── extraction/
│   ├── graph_rag/
│   ├── knowledge_base/
│   ├── llm/
│   ├── ocr/
│   └── retrieval/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── REFACTOR_PLAN.md
└── REFACTOR_REPORT.md
```

## Import and Configuration Changes

- Replace flat imports such as `import config` and `import lab_core` with package imports under `medical_lab_ai_core`.
- Replace direct Neo4j retriever imports with `medical_lab_ai_core.retrieval.neo4j_retriever`.
- Move runtime settings to environment variables documented in `.env.example`.
- Use repository-relative paths instead of local absolute paths.
- Keep external data, database artifacts, and model files outside Git.

## Open Items

- No license has been selected.
- Raw source documents and full datasets must be supplied separately because of privacy, licensing, and repository-size constraints.
- End-to-end OCR, Qdrant, Neo4j, and LLM runs require external services and assets.
