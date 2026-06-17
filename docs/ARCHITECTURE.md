# Architecture

## Offline Build Path

- `scripts/build_kb.py` reads permitted source documents from `data/raw_sources/` and builds processed knowledge-base JSON files under `data/processed/`.
- `scripts/build_qdrant_index.py` embeds processed KB records and uploads vectors to the configured Qdrant collection.
- `scripts/build_neo4j_graph.py` builds graph JSON plus Neo4j CSV and Cypher import artifacts.

Raw documents, generated CSV files, vector snapshots, and database dumps are excluded from the public repository.

## Runtime Path

- `medical_lab_ai_core.ocr.service` extracts structured laboratory fields from report images.
- `medical_lab_ai_core.core.lab_core` normalizes cases, builds reasoning context, retrieves evidence, and builds final prompts.
- `medical_lab_ai_core.retrieval.neo4j_retriever` retrieves evidence through test, condition, and INDICATES-chain graph paths.
- `medical_lab_ai_core.graph_rag.service` combines graph evidence, vector evidence, and LLM generation.
- `medical_lab_ai_core.agents.langgraph_chatbot` routes user questions and report follow-up requests through a LangGraph workflow.

## Boundary

This repository does not contain an API server or user interface. Applications can import this package as an AI-core dependency and keep credentials, private data, and deployment-specific code outside the public source tree.
