# Medical Laboratory Result Interpretation AI Core

This repository contains the AI core for extracting structured information from Vietnamese medical laboratory reports and generating evidence-grounded interpretations with OCR, knowledge retrieval, GraphRAG, and large language models.

The project is focused on research and engineering components only. It does not include a frontend, mobile application, REST API, production deployment code, private patient records, or model checkpoints.

## Project Motivation

Laboratory reports are often difficult for non-specialist users to understand because they combine abbreviations, numeric values, reference intervals, units, and clinical context. OCR can recover text from report images, but OCR alone does not determine whether a value is abnormal, how findings relate to medical conditions, or which evidence supports an interpretation.

This repository combines field extraction, normalization, semantic retrieval, graph retrieval, and LLM response generation so that generated explanations can be grounded in traceable evidence. The system is designed as a research prototype and does not claim clinical validation.

## Key Capabilities

- OCR-based text recognition from laboratory report images using PaddleOCR PP-OCRv5.
- Layout-aware extraction of laboratory test names, values, units, and reference ranges.
- Normalization of laboratory test fields and abnormality status.
- Knowledge-base construction from supported source documents.
- Semantic retrieval with Qdrant and sentence-transformer embeddings.
- Knowledge graph retrieval with Neo4j.
- GraphRAG-style evidence aggregation from vector and graph retrieval results.
- Multi-step chat orchestration with LangGraph.
- Vietnamese response generation through configurable LLM providers.
- Environment-based configuration for models, databases, and provider endpoints.

## System Architecture

```text
Laboratory Report Image
        |
        v
PP-OCRv5
        |
        v
Layout and Field Extraction
        |
        v
Structured Laboratory Data
        |
        v
Qdrant Semantic Retrieval + Neo4j Graph Retrieval
        |
        v
Evidence Aggregation
        |
        v
LangGraph Agent Workflow
        |
        v
Evidence-Grounded LLM Response
```

## Repository Structure

```text
medical-lab-ai-core/
├── configs/                         # OCR ontology files for test names and units
├── docs/                            # Architecture and repository notes
├── examples/                        # Synthetic or anonymized sample inputs
├── scripts/                         # Offline KB, Qdrant, Neo4j, and GraphRAG scripts
├── src/medical_lab_ai_core/
│   ├── agents/                      # LangGraph chat workflow
│   ├── core/                        # Shared configuration and reasoning utilities
│   ├── extraction/                  # Mapping and normalization helpers
│   ├── graph_rag/                   # GraphRAG service orchestration
│   ├── knowledge_base/              # Static evidence helpers
│   ├── llm/                         # LLM provider entry points
│   ├── ocr/                         # OCR and report field extraction
│   └── retrieval/                   # Neo4j graph retrieval
├── tests/                           # Offline smoke tests
├── .env.example                     # Safe placeholder configuration
├── .gitignore
├── requirements.txt
├── REFACTOR_PLAN.md
└── REFACTOR_REPORT.md
```

Generated outputs, raw source documents, database snapshots, checkpoints, local environments, and secret files are intentionally excluded.

## Technology Stack

- Python
- PaddleOCR and PP-OCRv5
- OpenCV and Pillow
- PyMuPDF
- sentence-transformers
- Qdrant
- Neo4j
- LangGraph
- Langfuse decorators, when installed and configured
- Google Gemini, OpenRouter-compatible models, Groq, local Ollama, or a custom Colab-hosted LLM endpoint

## Installation

Python 3.10 or newer is recommended. Some OCR and ML dependencies may have platform-specific installation requirements.

```powershell
cd medical-lab-ai-core
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
$env:PYTHONPATH = "src"
```

External services are required for the full pipeline:

- Qdrant for vector retrieval.
- Neo4j for knowledge graph retrieval.
- At least one configured LLM provider for response generation.
- Raw source documents or processed KB files for knowledge-base construction and retrieval.

## Configuration

All runtime configuration is provided through environment variables. Use `.env.example` as a template and keep `.env` out of version control.

| Variable | Required | Purpose | Example |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | Optional | API key for Gemini fallback generation | empty |
| `GEMINI_MODEL` | Optional | Gemini model name | `gemini-2.5-flash` |
| `OPENROUTER_API_KEY` | Optional | API key for OpenRouter-compatible generation | empty |
| `OPENROUTER_MODEL` | Optional | OpenRouter model name | `deepseek/deepseek-chat` |
| `GROQ_API_KEY` | Optional | API key for Groq generation | empty |
| `GROQ_MODEL` | Optional | Groq model name | `llama-3.3-70b-versatile` |
| `COLAB_LLM_URL` | Optional | Custom hosted LLM endpoint | empty |
| `COLAB_API_KEY` | Optional | Bearer token for the custom endpoint | empty |
| `COLAB_MAX_NEW_TOKENS` | Optional | Maximum generated tokens for Colab endpoint | `970` |
| `COLAB_TEMPERATURE` | Optional | Generation temperature | `0.2` |
| `COLAB_TIMEOUT` | Optional | Request timeout in seconds | `300` |
| `LOCAL_LLM_URL` | Optional | Local Ollama-compatible generation endpoint | `http://localhost:11434/api/generate` |
| `LOCAL_LLM_MODEL` | Optional | Local model name | `gemma3:1b` |
| `QDRANT_HOST` | Required for vector retrieval | Qdrant host | `localhost` |
| `QDRANT_PORT` | Required for vector retrieval | Qdrant port | `6333` |
| `QDRANT_COLLECTION` | Required for vector retrieval | Qdrant collection name | `lab_kb` |
| `EMBEDDING_MODEL_NAME` | Required for retrieval | Sentence-transformer model | `all-MiniLM-L6-v2` |
| `NEO4J_URI` | Required for graph retrieval | Neo4j Bolt URI | `bolt://localhost:7687` |
| `NEO4J_USER` | Required for graph retrieval | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Required for graph retrieval | Neo4j password placeholder | `password` |
| `REQUEST_TIMEOUT` | Optional | Default HTTP request timeout | `300` |

## Usage

The commands below match the repository layout. Commands that depend on Qdrant, Neo4j, raw documents, or LLM credentials require those assets and services to be supplied separately.

### OCR Inference

```powershell
$env:PYTHONPATH = "src"
python -m medical_lab_ai_core.ocr.service path\to\image_or_folder
```

OCR outputs are written to `outputs/`, which is ignored by Git.

### Knowledge-Base Construction

Place permitted source PDFs under `data/raw_sources/` according to the paths configured in `src/medical_lab_ai_core/core/config.py`, then run:

```powershell
python scripts/build_kb.py
```

Raw PDFs are not included in this public repository.

### Qdrant Indexing

After KB files are available in `data/processed/`, run:

```powershell
python scripts/build_qdrant_index.py
```

This recreates and uploads vectors to the configured Qdrant collection.

### Neo4j Graph Construction

After KB and case files are available, run:

```powershell
python scripts/build_neo4j_graph.py
```

The script generates Neo4j CSV and Cypher import artifacts under `neo4j_csv/`. Generated CSV files are ignored by Git.

### GraphRAG Response Generation

```powershell
python scripts/run_graphrag.py
```

This command requires processed cases, KB files, vector retrieval, graph retrieval, and an available LLM provider.

### LLM-Only Baseline

```powershell
python scripts/run_llm_only.py
```

This command runs the response-generation path without retrieved book evidence.

## Input and Output Example

The following example is illustrative and synthetic.

Input:

```json
{
  "test_name": "WBC",
  "value": 12.5,
  "unit": "10^9/L",
  "reference_range": "4.0-10.0"
}
```

Output shape:

```json
{
  "normalized_test_name": "White Blood Cell Count",
  "status": "high",
  "evidence": [],
  "interpretation": "The value is above the supplied reference interval. A qualified healthcare professional should interpret it together with symptoms, history, and other laboratory findings."
}
```

## Model Training and Fine-Tuning

No model training or fine-tuning scripts are included in this public repository. Datasets, checkpoints, and model weights are excluded because of privacy, licensing, and repository-size constraints. Inference and response generation are configured through external OCR, embedding, database, and LLM dependencies.

## Evaluation

The current public repository includes offline smoke tests for repository structure and configuration. The source code contains components that can support OCR, extraction, RAG, and GraphRAG evaluation when appropriate datasets are supplied separately, but no private evaluation datasets or thesis result tables are included.

Recommended evaluation areas for reproducible extensions include:

- OCR character error rate.
- Field extraction accuracy.
- Intent classification accuracy.
- Retrieval precision for Qdrant and Neo4j evidence.
- Response-quality review with evidence citation checks.

No benchmark scores are claimed in this README.

## Privacy and Data Protection

- No identifiable patient data is intentionally included.
- Example data must remain synthetic or fully anonymized.
- Sensitive medical data must not be committed to Git.
- Users are responsible for complying with applicable privacy regulations and institutional review requirements.
- API keys, database credentials, private endpoints, logs, and generated outputs must remain outside version control.

## Medical Disclaimer

> This project is intended for research and educational purposes only. It does not provide medical diagnosis, treatment recommendations, or professional medical advice. Laboratory results must be interpreted by qualified healthcare professionals in the appropriate clinical context.

## Limitations

- OCR quality depends on image resolution, lighting, rotation, table layout, and report format.
- Field extraction depends on report structure and may fail on unseen templates.
- Status interpretation depends on reference ranges supplied by the laboratory.
- Medical knowledge coverage is limited by the available KB and graph data.
- LLM outputs may contain omissions or hallucinations without strict review.
- Full functionality depends on external services, models, and database availability.
- The system has not been clinically validated.

## Reproducibility

The repository can reproduce source-level structure, configuration, syntax checks, smoke tests, and pipeline entry points. Full OCR, retrieval, graph construction, and response generation require external assets:

- Permitted raw medical reference sources or processed KB files.
- Qdrant and Neo4j service instances.
- Embedding model downloads.
- OCR model downloads.
- LLM provider credentials or a local LLM endpoint.

## Future Work

- Broader laboratory-test coverage.
- Stronger evidence ranking and citation validation.
- Improved Vietnamese medical terminology normalization.
- Automated evaluation pipelines with shareable synthetic datasets.
- Containerized local development environment.
- Additional privacy safeguards and data-governance checks.

## License

No license has been selected yet. Reuse permissions are therefore not defined. This is recorded as an unresolved repository item in `REFACTOR_REPORT.md`.
