"""Convenience entry points for LLM calls used by the GraphRAG pipeline."""

from medical_lab_ai_core.core.lab_core import (
    call_colab_llm,
    call_deepseek_llm,
    call_gemini_llm,
    call_llm,
    call_llm_with_meta,
)

__all__ = [
    "call_colab_llm",
    "call_deepseek_llm",
    "call_gemini_llm",
    "call_llm",
    "call_llm_with_meta",
]
