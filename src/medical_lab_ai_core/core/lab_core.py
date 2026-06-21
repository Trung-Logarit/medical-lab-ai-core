# lab_core.py
from __future__ import annotations
import time
import csv
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

try:
    from google import genai
except Exception:
    genai = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    from qdrant_client import QdrantClient
except ImportError:
    QdrantClient = None

# Neo4j GraphRAG retriever (thêm vào để hỗ trợ graph retrieval)
try:
    from medical_lab_ai_core.retrieval.neo4j_retriever import neo4j_retrieve, retrieve_reasoning_chain
    NEO4J_RETRIEVER_AVAILABLE = True
except ImportError:
    NEO4J_RETRIEVER_AVAILABLE = False

from medical_lab_ai_core.core.config import (
    TEST_NORMALIZATION,
    TEST_LABELS,
    STATUS_NORMALIZATION,
    SOURCE_TRUST,
    CBC_TEST_MAP,
    BIOCHEM_TEST_MAP,
    CBC_TOPIC_KEYWORDS,
    BIOCHEM_TOPIC_KEYWORDS,
    TYPE_PATTERNS,
    PANEL_PATTERNS,
    CROSS_PANEL_PATTERNS,
    BOUNDARY_REGEX_TEXT,
    MIN_WORDS,
    MAX_WORDS,
    PDF_SKIP_FIRST_PAGES,
    PDF_SKIP_PAGES_BY_FILE,
    KB_QUALITY_THRESHOLD,
    MAX_CHUNKS_PER_PDF,
    COLLECTION_NAME,
    QDRANT_HOST,
    QDRANT_PORT,
    EMBEDDING_MODEL_NAME,
    TOP_K_PER_QUERY,
    MAX_RAW_EVIDENCE,
    MAX_FINAL_EVIDENCE,
    REQUEST_TIMEOUT,
    COLAB_MAX_NEW_TOKENS,
    COLAB_TEMPERATURE,
)


_EMBEDDING_MODEL: SentenceTransformer | None = None
_QDRANT_CLIENT: QdrantClient | None = None
_BOUNDARY_REGEX = re.compile(BOUNDARY_REGEX_TEXT, flags=re.IGNORECASE)
logger = logging.getLogger(__name__)


# =========================================================
# BASIC IO
# =========================================================

def load_json(path: Path | str) -> Any:
    path = Path(path)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path | str, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_jsonl(path: Path | str) -> list[dict]:
    path = Path(path)
    data: list[dict] = []

    if not path.exists():
        return data

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                data.append(json.loads(line))
            except Exception as exc:
                print(f"Warning: cannot parse JSONL line {line_no} in {path}: {exc}")

    return data


def append_jsonl(path: Path | str, obj: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def stable_hash(text: str, n: int = 10) -> str:
    return hashlib.md5(str(text).encode("utf-8")).hexdigest()[:n]


def slugify(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        return float(value)
    except Exception:
        return default


def ensure_list(value: Any) -> list:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


# =========================================================
# TEXT CLEANING / PDF PROCESSING
# =========================================================

def clean_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("\x00", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


def clean_text_keep_case(text: str) -> str:
    text = str(text or "")
    text = text.replace("\x00", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    text = str(text or "").strip()

    if not text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def get_pdf_skip_pages(pdf_path: Path | str) -> int:
    pdf_path = Path(pdf_path)
    return int(PDF_SKIP_PAGES_BY_FILE.get(pdf_path.name, PDF_SKIP_FIRST_PAGES))


def read_pdf_pages(pdf_path: Path | str, skip_first_pages: int | None = None) -> list[dict]:
    """
    Returns:
    [
      {"page": 18, "text": "..."},
      ...
    ]

    page is 1-based actual PDF page number.
    """

    pdf_path = Path(pdf_path)

    if skip_first_pages is None:
        skip_first_pages = get_pdf_skip_pages(pdf_path)

    pages: list[dict] = []

    if not pdf_path.exists():
        logger.warning("PDF source not found: %s", pdf_path)
        return pages

    if fitz is None:
        raise RuntimeError("PyMuPDF is required to read PDF sources.")

    doc = fitz.open(pdf_path)

    for page_index in range(len(doc)):
        page_no = page_index + 1

        if page_no <= skip_first_pages:
            continue

        try:
            page = doc.load_page(page_index)
            text = page.get_text("text")
            text = clean_text(text)

            if text:
                pages.append({
                    "page": page_no,
                    "text": text,
                })

        except Exception as exc:
            print(f"Warning: cannot read page {page_no} from {pdf_path.name}: {exc}")

    doc.close()
    return pages


# =========================================================
# KB BUILD: DETECTION
# =========================================================

def get_panel_test_map(panel: str) -> dict[str, list[str]]:
    panel = str(panel).upper()

    if panel == "CBC":
        return CBC_TEST_MAP

    if panel == "BIOCHEM":
        return BIOCHEM_TEST_MAP

    raise ValueError(f"Unknown panel: {panel}")


def get_panel_topic_keywords(panel: str) -> dict[str, list[str]]:
    panel = str(panel).upper()

    if panel == "CBC":
        return CBC_TOPIC_KEYWORDS

    if panel == "BIOCHEM":
        return BIOCHEM_TOPIC_KEYWORDS

    raise ValueError(f"Unknown panel: {panel}")


def detect_tests_in_text(text: str, panel: str) -> list[str]:
    text_l = str(text or "").lower()
    found: list[str] = []

    for test, keywords in get_panel_test_map(panel).items():
        for kw in keywords:
            kw_l = str(kw).lower().strip()

            if not kw_l:
                continue

            # For very short tokens such as k, na, cl, avoid excessive false positives.
            if len(kw_l) <= 2:
                pattern = rf"(?<![a-z0-9]){re.escape(kw_l)}(?![a-z0-9])"
            else:
                pattern = rf"\b{re.escape(kw_l)}\b"

            if re.search(pattern, text_l):
                found.append(test)
                break

    return sorted(set(found))


def detect_topics_in_text(text: str, panel: str) -> list[str]:
    text_l = str(text or "").lower()
    topics: list[str] = []

    for topic, keywords in get_panel_topic_keywords(panel).items():
        for kw in keywords:
            kw_l = str(kw).lower().strip()

            if kw_l and kw_l in text_l:
                topics.append(topic)
                break

    return sorted(set(topics))


def classify_chunk_type(text: str) -> str:
    text_l = str(text or "").lower()

    for ctype, patterns in TYPE_PATTERNS.items():
        for pattern in patterns:
            if str(pattern).lower() in text_l:
                return ctype

    return "general"


def extract_keywords(text: str, panel: str) -> list[str]:
    text_l = str(text or "").lower()

    if panel == "CBC":
        candidates = [
            "anemia", "iron", "deficiency", "infection", "bacterial", "viral",
            "inflammation", "bleeding", "bone marrow", "thalassemia",
            "polycythemia", "neutrophilia", "neutropenia", "lymphocytosis",
            "thrombocytopenia", "macrocytic", "microcytic", "hypochromic",
            "megaloblastic", "hemolytic", "sepsis", "coagulation", "left shift",
            "pancytopenia", "leukocytosis", "leukopenia", "eosinophilia",
            "basophilia", "erythrocytosis",
        ]
    else:
        candidates = [
            "hepatitis", "hepatocellular", "transaminase", "aminotransferase",
            "azotemia", "uremia", "acute kidney injury", "chronic kidney disease",
            "renal function", "electrolyte", "hyponatremia", "hypernatremia",
            "hypokalemia", "hyperkalemia", "diabetes", "hyperglycemia",
            "hypoglycemia", "glycemic control", "hba1c", "dyslipidemia",
            "atherosclerosis", "cardiovascular risk", "lipoprotein",
            "myocardial infarction", "acute coronary syndrome", "heart failure",
            "troponin", "natriuretic peptide", "ferritin", "iron deficiency",
            "albumin", "hypoalbuminemia", "malnutrition", "protein loss",
            "ionized calcium", "parathyroid hormone", "hypercalcemia",
            "hypocalcemia", "urate", "gout", "hyperuricemia",
        ]

    return sorted({kw for kw in candidates if kw in text_l})


def infer_conditions_from_text(text: str, panel: str, tests: list[str], topics: list[str], keywords: list[str]) -> list[str]:
    text_l = str(text or "").lower()
    topics_l = [str(x).lower() for x in topics]
    keywords_l = [str(x).lower() for x in keywords]

    conditions: set[str] = set()

    topic_map = {
        # CBC
        "anemia": ["anemia"],
        "infection": ["infection"],
        "inflammation": ["inflammation"],
        "bleeding": ["bleeding_risk"],
        "bone_marrow": ["bone_marrow_disorder"],
        "thalassemia": ["thalassemia"],
        "polycythemia": ["polycythemia"],
        "coagulation": ["coagulation_disorder"],

        # BIOCHEM
        "liver_injury": ["liver_injury", "hepatocellular_injury"],
        "renal_function": ["renal_impairment", "reduced_kidney_function"],
        "electrolyte_disorder": ["electrolyte_disorder"],
        "diabetes": ["hyperglycemia", "diabetes_risk"],
        "dyslipidemia": ["dyslipidemia", "cardiovascular_risk"],
        "cardiac_biomarker": ["myocardial_injury", "cardiac_stress"],
        "iron_metabolism": ["iron_store_abnormality"],
        "protein_nutrition": ["hypoalbuminemia"],
        "bone_mineral": ["bone_mineral_disorder"],
        "purine_metabolism": ["hyperuricemia", "gout_risk"],
    }

    for topic in topics_l:
        for cond in topic_map.get(topic, []):
            conditions.add(cond)

    trigger_map = [
        # CBC
        (r"iron deficiency|iron deficient", "iron_deficiency_anemia"),
        (r"microcytic", "microcytic_anemia"),
        (r"macrocytic|megaloblastic|vitamin b12|folate", "macrocytic_anemia"),
        (r"thalassemia|thalassaemia", "thalassemia"),
        (r"hemolytic|hemolysis", "hemolytic_anemia"),
        (r"neutrophilia|bacterial infection", "bacterial_infection"),
        (r"lymphocytosis|viral infection", "viral_infection"),
        (r"left shift|immature granulocyte|band cell", "left_shift_stress_response"),
        (r"thrombocytopenia", "thrombocytopenia"),
        (r"thrombocytosis", "thrombocytosis"),
        (r"polycythemia|erythrocytosis", "polycythemia"),
        (r"leukocytosis", "leukocytosis"),
        (r"leukopenia", "leukopenia"),
        (r"neutropenia", "neutropenia"),
        (r"eosinophilia", "eosinophilia"),
        (r"basophilia", "basophilia"),

        # BIOCHEM
        (r"hepatocellular|aminotransferase|transaminase|hepatitis", "hepatocellular_injury"),
        (r"renal|kidney|creatinine|urea|azotemia|uremia", "renal_impairment"),
        (r"hyperglycemia|diabetes|glycemic", "hyperglycemia"),
        (r"dyslipidemia|lipoprotein|cardiovascular risk|atherosclerosis", "dyslipidemia"),
        (r"hyperkalemia|hypokalemia|hyponatremia|hypernatremia", "electrolyte_disorder"),
        (r"hypoalbuminemia|albumin", "hypoalbuminemia"),
        (r"ferritin|iron stores|iron storage", "iron_store_abnormality"),
        (r"urate|uric acid|gout|hyperuricemia", "hyperuricemia"),
        (r"troponin|ck-mb|myocardial|acute coronary syndrome", "myocardial_injury"),
        (r"natriuretic peptide|heart failure|pro-bnp|bnp", "cardiac_stress"),
        (r"parathyroid|pth|calcium", "bone_mineral_disorder"),
    ]

    combined = " ".join([text_l] + topics_l + keywords_l)

    for pattern, condition in trigger_map:
        if re.search(pattern, combined):
            conditions.add(condition)

    # Test-based weak hints, useful for KG and rerank.
    if panel == "CBC":
        test_condition_hints = {
            "HGB": ["anemia", "polycythemia"],
            "RBC": ["anemia", "polycythemia"],
            "HCT": ["anemia", "polycythemia"],
            "MCV": ["microcytic_anemia", "macrocytic_anemia"],
            "MCH": ["microcytic_anemia"],
            "MCHC": ["red_cell_index_abnormality"],
            "RDW": ["anisocytosis", "iron_deficiency_anemia"],
            "WBC": ["infection", "leukocytosis", "leukopenia"],
            "NEUT": ["bacterial_infection", "neutrophilia", "neutropenia"],
            "LYMPH": ["viral_infection", "lymphocytosis", "lymphopenia"],
            "PLT": ["thrombocytopenia", "thrombocytosis"],
            "IG": ["left_shift_stress_response"],
        }
    else:
        test_condition_hints = {
            "AST": ["liver_injury"],
            "ALT": ["liver_injury"],
            "UREA": ["renal_impairment"],
            "CREATININE": ["renal_impairment"],
            "NA": ["electrolyte_disorder"],
            "K": ["electrolyte_disorder"],
            "CL": ["electrolyte_disorder"],
            "GLUCOSE": ["hyperglycemia", "diabetes_risk"],
            "HBA1C": ["diabetes_risk", "poor_glycemic_control"],
            "CHOLESTEROL": ["dyslipidemia", "cardiovascular_risk"],
            "TRIGLYCERIDE": ["dyslipidemia", "cardiovascular_risk"],
            "HDL_C": ["dyslipidemia", "cardiovascular_risk"],
            "LDL_C": ["dyslipidemia", "cardiovascular_risk"],
            "CK_MB": ["myocardial_injury"],
            "TROPONIN_T": ["myocardial_injury"],
            "PRO_BNP": ["cardiac_stress"],
            "FERRITIN": ["iron_store_abnormality"],
            "ALBUMIN": ["hypoalbuminemia"],
            "CALCIUM_ION": ["bone_mineral_disorder"],
            "PTH": ["bone_mineral_disorder"],
            "URIC_ACID": ["hyperuricemia", "gout_risk"],
        }

    for test in tests:
        for cond in test_condition_hints.get(test, []):
            if cond.replace("_", " ") in combined or cond in combined:
                conditions.add(cond)

    return sorted(conditions)


def generate_query_hints(panel: str, tests: list[str], topics: list[str], conditions: list[str]) -> list[str]:
    queries: list[str] = []

    for test in tests:
        queries.append(f"{test.lower()} abnormal interpretation")
        queries.append(f"{test.lower()} clinical significance")
        queries.append(f"{test.lower()} causes of increase or decrease")

        if panel == "CBC":
            queries.append(f"{test.lower()} complete blood count finding")
        else:
            queries.append(f"{test.lower()} clinical chemistry interpretation")

    for topic in topics:
        if panel == "CBC":
            queries.append(f"{topic} cbc finding")
        else:
            queries.append(f"{topic} biochemistry interpretation")

    for condition in conditions:
        queries.append(f"{condition} laboratory interpretation")

    seen = set()
    output = []

    for q in queries:
        q = str(q).strip()

        if q and q not in seen:
            seen.add(q)
            output.append(q)

    return output


def is_noise_text(text: str) -> bool:
    text_l = str(text or "").lower().strip()
    words = text_l.split()

    if len(words) < MIN_WORDS:
        return True

    hard_noise = [
        "table of contents",
        "contents",
        "copyright",
        "isbn",
        "bibliography",
        "references",
        "index",
        "chapter contents",
        "permission",
        "all rights reserved",
        "printed in",
        "editorial",
    ]

    if any(x in text_l for x in hard_noise):
        # Avoid removing clinically valuable sentences that merely cite references.
        if len(words) < 80:
            return True

    # Too many numeric-only tokens often means tables, references, or index lines.
    numeric_tokens = 0

    for w in words:
        cleaned = w.replace(".", "").replace(",", "").replace("-", "").replace("–", "")
        if cleaned.isdigit():
            numeric_tokens += 1

    digit_ratio = numeric_tokens / max(len(words), 1)

    if digit_ratio > 0.45:
        return True

    # Reference-heavy paragraph.
    if text_l.count(" et al") >= 3 or text_l.count(" doi") >= 1:
        return True

    return False


def score_chunk(text: str, ctype: str, tests: list[str], topics: list[str], conditions: list[str]) -> float:
    text_l = str(text or "").lower()
    words = len(text_l.split())
    points = 0.0

    if ctype == "interpretation":
        points += 3.0
    elif ctype == "cause":
        points += 2.0
    elif ctype == "definition":
        points += 1.0

    if len(tests) >= 3:
        points += 2.5
    elif len(tests) == 2:
        points += 1.8
    elif len(tests) == 1:
        points += 1.0

    if topics:
        points += min(1.5, len(topics) * 0.5)

    if conditions:
        points += min(2.0, len(conditions) * 0.6)

    clinical_markers = [
        "indicates", "suggests", "consistent with", "associated with",
        "reflects", "is seen in", "caused by", "due to", "leads to",
        "result of", "elevation of", "decrease in", "low levels", "high levels",
    ]

    if any(marker in text_l for marker in clinical_markers):
        points += 1.0

    if 25 <= words <= MAX_WORDS:
        points += 1.0
    elif words > MAX_WORDS:
        points += 0.4

    # Penalize weak text.
    if not tests and not topics:
        points -= 1.0

    if is_noise_text(text_l):
        points -= 2.0

    score = points / 10.0
    score = max(0.0, min(1.0, score))

    return round(score, 2)


def semantic_chunk_page_text(text: str) -> list[str]:
    sentences = split_sentences(text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        if is_noise_text(sentence):
            continue

        current_words = len(current.split())
        sentence_words = len(sentence.split())

        should_start_new = (
            _BOUNDARY_REGEX.search(sentence) is not None
            and current_words >= 25
        )

        if should_start_new:
            if current.strip():
                chunks.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip()

        if len(current.split()) >= MAX_WORDS:
            chunks.append(current.strip())
            current = ""

        # If single sentence is very long, cut it softly.
        if sentence_words >= MAX_WORDS and current:
            chunks.append(current.strip())
            current = ""

    if len(current.split()) >= MIN_WORDS:
        chunks.append(current.strip())

    cleaned_chunks = []

    for chunk in chunks:
        chunk = re.sub(r"\s+", " ", chunk).strip()

        if not chunk:
            continue

        if is_noise_text(chunk):
            continue

        if len(chunk.split()) < MIN_WORDS:
            continue

        cleaned_chunks.append(chunk)

    return cleaned_chunks


def build_kb_from_pdf_paths(pdf_paths: list[Path], panel: str) -> list[dict]:
    panel = str(panel).upper()
    kb: list[dict] = []

    print("=" * 80)
    print(f"BUILDING {panel} KB FROM PDF")
    print("=" * 80)

    for pdf_path in pdf_paths:
        pdf_path = Path(pdf_path)
        source = pdf_path.name
        trust = SOURCE_TRUST.get(source, 0.8)
        skip_pages = get_pdf_skip_pages(pdf_path)

        print(f"\nPDF: {pdf_path}")
        print(f"Skip first pages: {skip_pages}")

        if not pdf_path.exists():
            print(f"Warning: missing PDF, skip: {pdf_path}")
            continue

        pages = read_pdf_pages(pdf_path, skip_first_pages=skip_pages)
        print(f"Pages read: {len(pages)}")

        source_count = 0

        for page_obj in pages:
            page_no = page_obj["page"]
            page_text = page_obj["text"]
            chunks = semantic_chunk_page_text(page_text)

            for chunk in chunks:
                tests = detect_tests_in_text(chunk, panel)
                topics = detect_topics_in_text(chunk, panel)
                keywords = extract_keywords(chunk, panel)
                ctype = classify_chunk_type(chunk)
                conditions = infer_conditions_from_text(chunk, panel, tests, topics, keywords)
                score = score_chunk(chunk, ctype, tests, topics, conditions)

                if score < KB_QUALITY_THRESHOLD:
                    continue

                evidence_id = f"ev_{panel.lower()}_{len(kb):06d}_{stable_hash(source + str(page_no) + chunk)}"

                item = {
                    "evidence_id": evidence_id,
                    "panel": panel,
                    "text": chunk,
                    "bm25_text": chunk,
                    "tests": tests,
                    "topics": topics,
                    "keywords": keywords,
                    "conditions": conditions,
                    "query_hints": generate_query_hints(panel, tests, topics, conditions),
                    "type": ctype,
                    "score": score,
                    "trust": trust,
                    "source": source,
                    "page": page_no,
                    "source_type": "pdf_book",
                }

                item["embedding_text"] = build_embedding_text(item)

                kb.append(item)
                source_count += 1

                if MAX_CHUNKS_PER_PDF is not None and source_count >= MAX_CHUNKS_PER_PDF:
                    break

            if MAX_CHUNKS_PER_PDF is not None and source_count >= MAX_CHUNKS_PER_PDF:
                break

        print(f"Chunks kept from {source}: {source_count}")

    print(f"\nTotal {panel} KB chunks: {len(kb)}")
    return kb


# =========================================================
# NORMALIZATION FOR CASE INPUT
# =========================================================

def normalize_raw_test_name(test_name: str) -> str:
    raw = str(test_name or "").strip()
    raw = raw.replace("-", "_")
    raw = raw.replace(" ", "_")
    raw = raw.upper()
    return raw


def guess_panel(test_name: str) -> str:
    raw = normalize_raw_test_name(test_name)

    for panel, mapping in TEST_NORMALIZATION.items():
        if raw in mapping:
            return panel

    cbc_tests = {
        "RBC", "HGB", "HB", "HCT", "MCV", "MCH", "MCHC",
        "RDW", "RDW_SD", "RDW_CV", "WBC", "NEUT", "LYM",
        "LYMPH", "MONO", "EOS", "BASO", "PLT", "IG",
        "NEUT_PERCENT", "NEUT_ABS", "LYM_PERCENT", "LYM_ABS",
        "MONO_PERCENT", "MONO_ABS", "EOS_PERCENT", "EOS_ABS",
        "BASO_PERCENT", "BASO_ABS", "IG_PERCENT", "IG_ABS",
        "PCT", "MPV", "PDW",
    }

    if raw in cbc_tests:
        return "CBC"

    return "BIOCHEM"


def normalize_test_name(test_name: str, panel: str | None = None) -> str:
    raw = normalize_raw_test_name(test_name)

    if panel:
        panel = str(panel).upper()
        return TEST_NORMALIZATION.get(panel, {}).get(raw, raw)

    guessed_panel = guess_panel(raw)
    return TEST_NORMALIZATION.get(guessed_panel, {}).get(raw, raw)


def normalize_status(status: Any) -> str:
    raw = str(status or "").strip().lower()

    if not raw:
        return ""

    return STATUS_NORMALIZATION.get(raw, raw)


def normalize_panel(panel: Any, test_name: str = "") -> str:
    if panel:
        p = str(panel).strip().upper()

        if p in {"CBC", "HEMATOLOGY", "HAEMATOLOGY"}:
            return "CBC"

        if p in {"BIOCHEM", "BIOCHEMISTRY", "CHEMISTRY", "CLINICAL_CHEMISTRY"}:
            return "BIOCHEM"

    return guess_panel(test_name)


def get_case_id(case: dict, idx: int = 0) -> str:
    """
    Case identity rule:
    - case_id has highest priority.
    - otherwise id/image_id/file_name.
    - CBC id == BIOCHEM id means same patient/case.
    - Different ids are treated as different cases.
    """

    for key in ["case_id", "id", "image_id", "img_id", "file_name", "filename"]:
        if case.get(key):
            return str(case[key])

    return f"case_{idx:04d}"


def format_ref_range(ref_range: Any) -> str:
    if not ref_range:
        return ""

    if isinstance(ref_range, dict):
        ref_min = ref_range.get("ref_min")
        ref_max = ref_range.get("ref_max")

        if ref_min is not None and ref_max is not None:
            return f"{ref_min} - {ref_max}"

        return json.dumps(ref_range, ensure_ascii=False)

    return str(ref_range)


def extract_case_items(case: dict | list, default_panel: str | None = None) -> list[dict]:
    if isinstance(case, list):
        raw_items = case
    else:
        raw_items = (
            case.get("data")
            or case.get("results")
            or case.get("items")
            or case.get("lab_results")
            or []
        )

    output: list[dict] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        raw_test = (
            item.get("test_name")
            or item.get("name")
            or item.get("test")
            or item.get("parameter")
            or item.get("analyte")
            or ""
        )

        if not raw_test:
            continue

        panel = normalize_panel(item.get("panel") or default_panel, raw_test)
        test = normalize_test_name(raw_test, panel)
        status = normalize_status(item.get("status", ""))

        ref_range = (
            item.get("reference_range")
            or item.get("ref_range")
            or item.get("ref")
            or item.get("range")
            or ""
        )

        output.append({
            "panel": panel,
            "raw_test": raw_test,
            "test": test,
            "test_label": TEST_LABELS.get(test, test),
            "value": item.get("value"),
            "raw_value": item.get("raw_value"),
            "unit": item.get("unit", ""),
            "status": status,
            "reference_range": format_ref_range(ref_range),
            "raw_text_line": item.get("raw_text_line", ""),
            "source_case_item": item,
        })

    return output


def normalize_single_case(case: dict, idx: int = 0, default_panel: str | None = None) -> dict:
    case_id = get_case_id(case, idx)
    items = extract_case_items(case, default_panel=default_panel)

    return {
        "case_id": case_id,
        "data": items,
        "raw_case": case,
    }


def merge_case_lists(cbc_cases: list[dict], biochem_cases: list[dict]) -> list[dict]:
    """
    Merge by case_id/id only.
    Same id = same patient.
    Different id = different case.
    """

    merged: dict[str, dict] = {}

    for idx, case in enumerate(cbc_cases):
        norm = normalize_single_case(case, idx, default_panel="CBC")
        case_id = norm["case_id"]

        merged.setdefault(case_id, {
            "case_id": case_id,
            "data": [],
            "raw_sources": {},
        })

        merged[case_id]["data"].extend(norm["data"])
        merged[case_id]["raw_sources"]["CBC"] = case

    for idx, case in enumerate(biochem_cases):
        norm = normalize_single_case(case, idx, default_panel="BIOCHEM")
        case_id = norm["case_id"]

        merged.setdefault(case_id, {
            "case_id": case_id,
            "data": [],
            "raw_sources": {},
        })

        merged[case_id]["data"].extend(norm["data"])
        merged[case_id]["raw_sources"]["BIOCHEM"] = case

    output = list(merged.values())
    output.sort(key=lambda x: str(x.get("case_id", "")))
    return output


def extract_lab_items(case: dict) -> list[dict]:
    raw_items = case.get("data", [])
    output: list[dict] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        raw_test = item.get("raw_test") or item.get("test_name") or item.get("test") or ""
        test = item.get("test") or normalize_test_name(raw_test, item.get("panel"))
        panel = normalize_panel(item.get("panel"), raw_test or test)
        status = normalize_status(item.get("status", ""))

        ref_range = (
            item.get("reference_range")
            or item.get("ref_range")
            or item.get("ref")
            or ""
        )

        output.append({
            "panel": panel,
            "raw_test": raw_test or test,
            "test": test,
            "test_label": TEST_LABELS.get(test, test),
            "value": item.get("value"),
            "raw_value": item.get("raw_value"),
            "unit": item.get("unit", ""),
            "status": status,
            "reference_range": format_ref_range(ref_range),
            "raw_text_line": item.get("raw_text_line", ""),
            "source_case_item": item.get("source_case_item", item),
        })

    return output


def extract_abnormal_items(items: list[dict]) -> list[dict]:
    abnormal: list[dict] = []

    for item in items:
        status = normalize_status(item.get("status"))

        if status and status != "normal":
            x = dict(item)
            x["status"] = status
            abnormal.append(x)

    return abnormal


# =========================================================
# STATIC PATTERNS / REAL-TIME REPORT AUGMENTATION
# =========================================================

def _condition_slug(text: str) -> str:
    text = str(text or "").lower().strip()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    return re.sub(r"_+", "_", text).strip("_")


def _context_has_finding(ctx: dict, panel: str, test: str, status: str) -> bool:
    panel = str(panel).upper()
    test = normalize_test_name(test, panel)
    status = normalize_status(status)
    return any(
        str(item.get("panel", "")).upper() == panel
        and item.get("test") == test
        and normalize_status(item.get("status")) == status
        for item in ctx.get("abnormal_items", [])
    )


def _context_tags(ctx: dict) -> set[str]:
    return {
        f"{item.get('test')}_{normalize_status(item.get('status')).capitalize()}"
        for item in ctx.get("abnormal_items", [])
        if item.get("test") and normalize_status(item.get("status"))
    }


def match_cbc_demo_patterns(ctx: dict, demo_patterns: list[dict]) -> list[dict]:
    matches: list[dict] = []
    for row in demo_patterns or []:
        raw_input = row.get("input", {}) or {}
        if not isinstance(raw_input, dict) or not raw_input:
            continue
        required = [
            (normalize_test_name(test, "CBC"), normalize_status(status))
            for test, status in raw_input.items()
        ]
        hits = sum(_context_has_finding(ctx, "CBC", test, status) for test, status in required)
        ratio = hits / len(required)
        if hits == 0 or (len(required) > 1 and ratio < 0.6) or (len(required) == 1 and ratio < 1.0):
            continue

        patterns = row.get("patterns", []) or [{
            "pattern_name": row.get("case_id", "CBC demo pattern"),
            "interpretation": row.get("combined_interpretation", ""),
            "match_score": ratio,
        }]
        for pattern in patterns:
            name = pattern.get("pattern_name", "CBC demo pattern")
            matches.append({
                "pattern_id": f"cbc_static_{_condition_slug(name)}",
                "pattern_name": name,
                "panel": "CBC",
                "conditions": [_condition_slug(name)],
                "description": pattern.get("interpretation") or row.get("combined_interpretation", ""),
                "confidence": round(safe_float(pattern.get("match_score"), ratio), 2),
                "matched_required": [f"{test}_{status}" for test, status in required],
                "matched_optional": [],
                "source": "cbc_demo_cases",
                "static_rule": True,
            })
    return matches


def match_biochem_static_patterns(ctx: dict, biochem_patterns: dict) -> list[dict]:
    matches: list[dict] = []
    tags = _context_tags(ctx)
    single_rules = (biochem_patterns or {}).get("single_test_patterns", {}) or {}

    for item in ctx.get("abnormal_items", []):
        if item.get("panel") != "BIOCHEM":
            continue
        test = item.get("test")
        status = normalize_status(item.get("status"))
        rule = (single_rules.get(test, {}) or {}).get(status, {}) or {}
        if not rule:
            continue
        label = rule.get("label") or f"{test} {status}"
        matches.append({
            "pattern_id": f"biochem_single_{test}_{status}",
            "pattern_name": label,
            "panel": "BIOCHEM",
            "conditions": [_condition_slug(label)],
            "description": rule.get("clinical_meaning") or rule.get("note") or "",
            "confidence": 0.85,
            "matched_required": [f"{test}_{status}"],
            "matched_optional": [],
            "source": "biochem_patterns_single",
            "static_rule": True,
            "extra": {
                "associated_tests": rule.get("associated_tests", []),
                "clinical_flags": rule.get("clinical_flags", []),
                "causes": rule.get("causes", []),
            },
        })

    for combo in (biochem_patterns or {}).get("pattern_combinations", []) or []:
        required = combo.get("required_tags", []) or []
        optional = combo.get("optional_tags", []) or []
        required_hits = [tag for tag in required if tag in tags]
        optional_hits = [tag for tag in optional if tag in tags]
        minimum = int(combo.get("confidence_required", 1) or 1)
        if required and len(required_hits) < len(required):
            continue
        if not required and len(optional_hits) < minimum:
            continue
        total = max(len(required) + len(optional), 1)
        name = combo.get("name", "BIOCHEM combination pattern")
        matches.append({
            "pattern_id": combo.get("pattern_id", "biochem_combo_pattern"),
            "pattern_name": name,
            "panel": "BIOCHEM",
            "conditions": [_condition_slug(combo.get("pattern_id") or name)],
            "description": combo.get("interpretation", ""),
            "confidence": round((len(required_hits) + len(optional_hits)) / total, 2),
            "matched_required": required_hits,
            "matched_optional": optional_hits,
            "source": "biochem_patterns_combo",
            "static_rule": True,
            "extra": {
                "next_steps": combo.get("next_steps", []),
                "sources": combo.get("sources", []),
                "severity_escalators": combo.get("severity_escalators", {}),
            },
        })
    return matches


def build_safety_warnings(ctx: dict, _biochem_patterns: dict) -> list[dict]:
    thresholds = {
        "K": [(lambda value: value >= 6.5, "Kali ≥ 6,5 mmol/L: cần được đánh giá y tế khẩn cấp."),
              (lambda value: value <= 2.5, "Kali ≤ 2,5 mmol/L: cần được đánh giá y tế khẩn cấp.")],
        "NA": [(lambda value: value <= 120, "Natri ≤ 120 mmol/L: nguy cơ hạ natri máu nặng."),
               (lambda value: value >= 160, "Natri ≥ 160 mmol/L: nguy cơ tăng natri máu nặng.")],
        "GLUCOSE": [(lambda value: value < 3.0, "Glucose < 3,0 mmol/L: nguy cơ hạ đường huyết nặng."),
                    (lambda value: value >= 20, "Glucose ≥ 20 mmol/L: tăng đường huyết nặng.")],
        "CREATININE": [(lambda value: value >= 354, "Creatinine ≥ 354 µmol/L: cần đánh giá chức năng thận sớm.")],
        "UREA": [(lambda value: value >= 25, "Urê ≥ 25 mmol/L: cần đánh giá y tế sớm.")],
    }
    warnings: list[dict] = []
    for item in ctx.get("abnormal_items", []):
        value = safe_float(item.get("value"), None)
        if value is None:
            continue
        for predicate, message in thresholds.get(item.get("test"), []):
            if predicate(value):
                warnings.append({
                    "test": item.get("test"), "value": value,
                    "unit": item.get("unit", ""), "level": "critical", "message": message,
                })
    return warnings


def augment_reasoning_context_with_static_patterns(
    ctx: dict,
    cbc_demo_patterns: list[dict],
    biochem_patterns: dict,
) -> dict:
    augmented = dict(ctx)
    augmented["static_context"] = (
        match_cbc_demo_patterns(augmented, cbc_demo_patterns)
        + match_biochem_static_patterns(augmented, biochem_patterns)
    )
    augmented["safety_warnings"] = build_safety_warnings(augmented, biochem_patterns)
    return augmented


# =========================================================
# PATTERN DETECTION
# =========================================================

def has_finding(abnormal_items: list[dict], panel: str, test: str, status: str) -> bool:
    panel = str(panel).upper()
    test = normalize_test_name(test, panel)
    status = normalize_status(status)

    for item in abnormal_items:
        if (
            str(item.get("panel", "")).upper() == panel
            and item.get("test") == test
            and normalize_status(item.get("status")) == status
        ):
            return True

    return False


def detect_panel_patterns(abnormal_items: list[dict]) -> list[dict]:
    detected: list[dict] = []

    for panel, rules in PANEL_PATTERNS.items():
        panel_items = [x for x in abnormal_items if x.get("panel") == panel]

        if not panel_items:
            continue

        for rule in rules:
            requires = rule.get("requires", [])
            optional = rule.get("optional", [])

            required_hits = 0
            matched_required = []

            for test, status in requires:
                if has_finding(abnormal_items, panel, test, status):
                    required_hits += 1
                    matched_required.append(f"{test}_{status}")

            if requires and required_hits < len(requires):
                continue

            optional_hits = 0
            matched_optional = []

            for test, status in optional:
                if has_finding(abnormal_items, panel, test, status):
                    optional_hits += 1
                    matched_optional.append(f"{test}_{status}")

            denominator = len(requires) + max(len(optional), 1)
            confidence = (required_hits + 0.5 * optional_hits) / denominator
            confidence = min(0.95, max(0.6, confidence))

            detected.append({
                "pattern_id": rule["pattern_id"],
                "pattern_name": rule["name"],
                "panel": panel,
                "conditions": rule.get("conditions", []),
                "description": rule.get("description", ""),
                "confidence": round(confidence, 2),
                "matched_required": matched_required,
                "matched_optional": matched_optional,
                "source": "panel_rule",
            })

    detected.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return detected


def detect_cross_panel_patterns(abnormal_items: list[dict]) -> list[dict]:
    panels = {item.get("panel") for item in abnormal_items}

    # Do not apply cross-panel rules unless the same merged case contains both panels.
    if not {"CBC", "BIOCHEM"}.issubset(panels):
        return []

    detected: list[dict] = []

    for rule in CROSS_PANEL_PATTERNS:
        requires = rule.get("requires", [])
        optional = rule.get("optional", [])

        required_hits = 0
        matched_required = []

        for panel, test, status in requires:
            if has_finding(abnormal_items, panel, test, status):
                required_hits += 1
                matched_required.append(f"{panel}_{test}_{status}")

        if requires and required_hits < len(requires):
            continue

        optional_hits = 0
        matched_optional = []

        for panel, test, status in optional:
            if has_finding(abnormal_items, panel, test, status):
                optional_hits += 1
                matched_optional.append(f"{panel}_{test}_{status}")

        denominator = len(requires) + max(len(optional), 1)
        confidence = (required_hits + 0.5 * optional_hits) / denominator
        confidence = min(0.95, max(0.65, confidence))

        detected.append({
            "pattern_id": rule["pattern_id"],
            "pattern_name": rule["name"],
            "panel": "CROSS_PANEL",
            "conditions": rule.get("conditions", []),
            "description": rule.get("description", ""),
            "confidence": round(confidence, 2),
            "matched_required": matched_required,
            "matched_optional": matched_optional,
            "source": "cross_panel_rule",
        })

    detected.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return detected


def build_reasoning_context(case: dict, idx: int = 0) -> dict:
    case_id = get_case_id(case, idx)

    items = extract_lab_items(case)
    abnormal_items = extract_abnormal_items(items)

    panel_patterns = detect_panel_patterns(abnormal_items)
    cross_patterns = detect_cross_panel_patterns(abnormal_items)

    detected_patterns = sorted(
        panel_patterns + cross_patterns,
        key=lambda x: x.get("confidence", 0),
        reverse=True,
    )

    panels = sorted({x["panel"] for x in items if x.get("panel")})
    abnormal_tests = sorted({x["test"] for x in abnormal_items if x.get("test")})

    conditions = sorted({
        condition
        for pattern in detected_patterns
        for condition in pattern.get("conditions", [])
    })

    return {
        "case_id": case_id,
        "panels": panels,
        "items": items,
        "abnormal_items": abnormal_items,
        "abnormal_tests": abnormal_tests,
        "detected_patterns": detected_patterns,
        "conditions": conditions,
    }


# =========================================================
# KB NORMALIZATION / EMBEDDING TEXT
# =========================================================

def build_embedding_text(item: dict) -> str:
    parts: list[str] = []

    parts.append("Panel: " + str(item.get("panel", "")))
    parts.append("Clinical text: " + str(item.get("text", "")))

    if item.get("tests"):
        parts.append("Tests: " + ", ".join(item["tests"]))

    if item.get("topics"):
        parts.append("Topics: " + ", ".join(item["topics"]))

    if item.get("conditions"):
        parts.append("Conditions: " + ", ".join(item["conditions"]))

    if item.get("keywords"):
        parts.append("Keywords: " + ", ".join(item["keywords"]))

    if item.get("type"):
        parts.append("Type: " + str(item["type"]))

    if item.get("tests"):
        parts.append("Clinical interpretation of " + ", ".join(item["tests"]))

    return " | ".join(parts)


def normalize_kb_item(item: dict, panel: str, idx: int = 0) -> dict:
    x = dict(item)
    panel = str(panel).upper()
    source = str(x.get("source", "Unknown"))
    text = str(x.get("text", ""))

    x["panel"] = panel
    x["evidence_id"] = x.get("evidence_id") or f"ev_{panel.lower()}_{idx:06d}_{stable_hash(text)}"
    x["tests"] = sorted({normalize_test_name(t, panel) for t in x.get("tests", []) if t})
    x["topics"] = x.get("topics", [])
    x["keywords"] = x.get("keywords", [])

    if not x.get("conditions"):
        x["conditions"] = infer_conditions_from_text(
            text=text,
            panel=panel,
            tests=x["tests"],
            topics=x["topics"],
            keywords=x["keywords"],
        )

    x["type"] = x.get("type", "general")
    x["score"] = safe_float(x.get("score"), 0.3)
    x["trust"] = safe_float(x.get("trust"), SOURCE_TRUST.get(source, 0.8))
    x["source_type"] = x.get("source_type", "pdf_book")
    x["embedding_text"] = x.get("embedding_text") or build_embedding_text(x)

    return x


# =========================================================
# QUERY BUILDING
# =========================================================

def build_query_hints(reasoning_context: dict) -> list[str]:
    queries: list[str] = []

    for item in reasoning_context.get("abnormal_items", []):
        panel = item.get("panel")
        test = item.get("test")
        status = item.get("status")

        if not test or not status:
            continue

        queries.append(f"{panel} {test} {status} interpretation")
        queries.append(f"{test} {status} clinical significance")
        queries.append(f"{test} {status} causes")

        if panel == "CBC":
            queries.append(f"{test} {status} complete blood count interpretation")

        if panel == "BIOCHEM":
            queries.append(f"{test} {status} clinical chemistry interpretation")

    for pattern in reasoning_context.get("detected_patterns", []):
        if pattern.get("pattern_name"):
            queries.append(pattern["pattern_name"])

        if pattern.get("description"):
            queries.append(pattern["description"])

        for condition in pattern.get("conditions", []):
            queries.append(f"{condition} laboratory interpretation")

    abnormal_tests = reasoning_context.get("abnormal_tests", [])
    if abnormal_tests:
        queries.append(" ".join(abnormal_tests) + " laboratory abnormal pattern")

    queries.append("complete blood count interpretation")
    queries.append("clinical chemistry interpretation")
    queries.append("laboratory test abnormal pattern interpretation")

    seen = set()
    output = []

    for q in queries:
        q = str(q).strip()

        if q and q not in seen:
            seen.add(q)
            output.append(q)

    return output


# =========================================================
# QDRANT RETRIEVAL
# =========================================================

def get_embedding_model() -> SentenceTransformer:
    global _EMBEDDING_MODEL

    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is required for embedding retrieval.")

    if _EMBEDDING_MODEL is None:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)
        _EMBEDDING_MODEL = SentenceTransformer(EMBEDDING_MODEL_NAME)

    return _EMBEDDING_MODEL


def get_qdrant_client() -> QdrantClient:
    global _QDRANT_CLIENT

    if QdrantClient is None:
        raise RuntimeError("qdrant-client is required for vector retrieval.")

    if _QDRANT_CLIENT is None:
        _QDRANT_CLIENT = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    return _QDRANT_CLIENT


def build_embedding_text_for_query(query: str) -> str:
    return f"Clinical laboratory interpretation query: {query}"


def qdrant_search(query: str, top_k: int = TOP_K_PER_QUERY) -> list[dict]:
    model = get_embedding_model()
    client = get_qdrant_client()

    query_text = build_embedding_text_for_query(query)
    vector = model.encode([query_text])[0].tolist()

    if hasattr(client, "search"):
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=vector,
            limit=top_k,
            with_payload=True,
        )
    else:
        query_result = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=top_k,
            with_payload=True,
        )
        results = query_result.points

    evidence: list[dict] = []

    for hit in results:
        payload = hit.payload or {}
        hit_score = float(getattr(hit, "score", 0) or 0)

        evidence.append({
            "evidence_id": payload.get("evidence_id") or f"ev_{stable_hash(payload.get('text', ''))}",
            "panel": payload.get("panel", "UNKNOWN"),
            "text": payload.get("text", ""),
            "bm25_text": payload.get("bm25_text", ""),
            "tests": payload.get("tests", []),
            "topics": payload.get("topics", []),
            "conditions": payload.get("conditions", []),
            "keywords": payload.get("keywords", []),
            "type": payload.get("type", "general"),
            "score": hit_score,
            "kb_score": payload.get("score", 0),
            "trust": float(payload.get("trust", 0.8) or 0.8),
            "source": payload.get("source", "Unknown source"),
            "page": payload.get("page", ""),
            "source_type": payload.get("source_type", "pdf_book"),
            "is_static": False,
        })

    return evidence


def dedup_evidence(evidence: list[dict]) -> list[dict]:
    seen = set()
    output = []

    for e in evidence:
        text = re.sub(r"\s+", " ", str(e.get("text", "")).lower()).strip()
        fp = text[:260]

        if not fp:
            continue

        if fp in seen:
            continue

        seen.add(fp)
        output.append(e)

    return output


def rerank_evidence(evidence: list[dict], reasoning_context: dict) -> list[dict]:
    abnormal_tests = set(reasoning_context.get("abnormal_tests", []))
    panels = set(reasoning_context.get("panels", []))
    conditions = set(reasoning_context.get("conditions", []))

    ranked: list[dict] = []

    for e in evidence:
        score = safe_float(e.get("score"), 0.0)
        evidence_text = str(e.get("text") or "").lower()

        e_tests = set(e.get("tests", []))
        e_conditions = set(e.get("conditions", []))
        e_panel = e.get("panel")

        score += safe_float(e.get("trust"), 0.8) * 0.10
        score += safe_float(e.get("kb_score"), 0.0) * 0.12

        if e_tests & abnormal_tests:
            score += 0.30

        if e_conditions & conditions:
            score += 0.30

        if e_panel in panels:
            score += 0.18

        if e.get("type") == "interpretation":
            score += 0.12
        elif e.get("type") == "cause":
            score += 0.08
        elif e.get("type") == "definition":
            score += 0.03

        # Người dùng quan tâm nguyên nhân, nguy cơ và bước đánh giá hơn
        # các đoạn chỉ định nghĩa thuật ngữ. Ưu tiên các trích đoạn
        # có khả năng hỗ trợ trực tiếp cho phần "liên quan đến gì".
        causal_terms = (
            "due to", "cause", "caused by", "indicates", "associated with",
            "viral", "bacterial", "infection", "inflammation", "deficiency",
            "helminth", "atopic", "allergic", "risk of",
        )
        action_terms = (
            "evaluation", "should include", "examination", "blood smear",
            "persistent", "persisting", "follow-up", "repeat",
        )
        definition_terms = (
            "refers to", "is defined as", "defined as", "is an increase in",
        )
        if any(term in evidence_text for term in causal_terms):
            score += 0.55
        if any(term in evidence_text for term in action_terms):
            score += 0.35
        if any(term in evidence_text for term in definition_terms):
            score -= 0.20

        # Penalty Neo4j chunk không nhắc đến test nào trong phiếu
        if e.get("retrieval_path", "").startswith("neo4j"):
            test_keywords = {t.lower() for t in abnormal_tests}
            text_lower = evidence_text
            keyword_hits = sum(1 for kw in test_keywords if kw in text_lower)
            if keyword_hits == 0:
                score -= 0.25

        x = dict(e)
        x["final_score"] = round(score, 4)
        ranked.append(x)

    ranked.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return ranked


def retrieve_evidence(reasoning_context: dict) -> list[dict]:
    """
    GraphRAG retrieval: kết hợp Qdrant (semantic) + Neo4j (graph relation).
    - Qdrant: tìm evidence gần nghĩa với query
    - Neo4j Path A: Evidence theo Test bất thường (MENTIONS_TEST)
    - Neo4j Path B: Evidence theo Condition từ Pattern (SUPPORTS)
    """
    all_evidence: list[dict] = []

    # --- Qdrant semantic retrieval ---
    queries = build_query_hints(reasoning_context)
    logger.debug("Qdrant queries: %s", queries[:3])

    for query in queries[:10]:
        try:
            hits = qdrant_search(query, top_k=TOP_K_PER_QUERY)
            all_evidence.extend(hits)
        except Exception as exc:
            logger.warning("Qdrant search failed for query=%r: %s", query, exc)

    qdrant_count = len(all_evidence)
    logger.debug("Qdrant returned %s evidence items before deduplication.", qdrant_count)

    # --- Neo4j graph retrieval ---
    if NEO4J_RETRIEVER_AVAILABLE:
        try:
            graph_evidence = neo4j_retrieve(reasoning_context)
            all_evidence.extend(graph_evidence)
            logger.debug("Neo4j returned %s evidence items.", len(graph_evidence))
        except Exception as exc:
            logger.warning("Neo4j retrieval failed: %s", exc)
    else:
        logger.info("Neo4j retriever is unavailable; using Qdrant only.")

    # --- Dedup + rerank ---
    all_evidence = dedup_evidence(all_evidence)
    all_evidence = rerank_evidence(all_evidence, reasoning_context)

    logger.debug("Returning top %s evidence items after deduplication and reranking.", MAX_RAW_EVIDENCE)
    return all_evidence[:MAX_RAW_EVIDENCE]


# =========================================================
# REASONING PATHS / GRAPH EXPLAINABILITY
# =========================================================

def finding_node_id(case_id: str, panel: str, test: str, status: str) -> str:
    return f"finding_{slugify(case_id)}_{panel}_{test}_{status}"


def build_reasoning_paths(reasoning_context: dict, evidence: list[dict]) -> list[dict]:
    """
    Xây dựng reasoning paths để đưa vào prompt LLM.
    Ưu tiên dùng Neo4j chain (graph thật), fallback về memory nếu không có.
    """
    # --- Thử Neo4j chain trước ---
    if NEO4J_RETRIEVER_AVAILABLE:
        case_id = reasoning_context.get("case_id", "")
        try:
            chain_rows = retrieve_reasoning_chain(case_id, limit=12)
            if chain_rows:
                # Group theo finding
                from collections import defaultdict
                grouped: dict = defaultdict(lambda: {"patterns": [], "evidence": []})
                for row in chain_rows:
                    key = f"{row.get('test_code')}_{row.get('direction')}"
                    node = grouped[key]
                    node["finding"] = {
                        "panel":           "CBC",
                        "test":            row.get("test_code", ""),
                        "test_label":      row.get("test_code", ""),
                        "status":          row.get("direction", ""),
                        "value":           row.get("value", ""),
                        "unit":            row.get("unit", ""),
                        "reference_range": "",
                    }
                    pat = {
                        "pattern_name": row.get("pattern_name", ""),
                        "conditions":   [row.get("condition_name", "")],
                        "confidence":   row.get("pattern_score", 0),
                    }
                    if pat not in node["patterns"]:
                        node["patterns"].append(pat)
                    ev = {
                        "evidence_id": row.get("ev_id", ""),
                        "source":      row.get("src_name", ""),
                        "page":        row.get("page", ""),
                        "score":       float(row.get("trust") or 0),
                    }
                    if ev not in node["evidence"]:
                        node["evidence"].append(ev)
                paths_neo4j = [
                    {
                        "finding":  v["finding"],
                        "patterns": v["patterns"][:3],
                        "evidence": v["evidence"][:3],
                    }
                    for v in grouped.values() if v.get("finding")
                ]
                if paths_neo4j:
                    return paths_neo4j
        except Exception as exc:
            logger.warning("Neo4j reasoning chain failed: %s", exc)

    # --- Fallback: build từ memory (logic cũ) ---
    paths: list[dict] = []

    abnormal_items = reasoning_context.get("abnormal_items", [])
    patterns = reasoning_context.get("detected_patterns", [])

    for item in abnormal_items:
        finding = {
            "panel": item.get("panel"),
            "test": item.get("test"),
            "test_label": item.get("test_label"),
            "status": item.get("status"),
            "value": item.get("value"),
            "raw_value": item.get("raw_value"),
            "unit": item.get("unit", ""),
            "reference_range": item.get("reference_range", ""),
        }

        related_patterns = []
        for pattern in patterns:
            pattern_panel = pattern.get("panel")

            if pattern_panel in [item.get("panel"), "CROSS_PANEL"]:
                related_patterns.append({
                    "pattern_id": pattern.get("pattern_id"),
                    "pattern_name": pattern.get("pattern_name"),
                    "panel": pattern.get("panel"),
                    "conditions": pattern.get("conditions", []),
                    "confidence": pattern.get("confidence"),
                    "description": pattern.get("description"),
                })

        related_evidence = []
        for e in evidence:
            if item.get("test") in e.get("tests", []):
                related_evidence.append({
                    "evidence_id": e.get("evidence_id"),
                    "panel": e.get("panel"),
                    "source": e.get("source"),
                    "page": e.get("page"),
                    "score": e.get("final_score", e.get("score")),
                })

        paths.append({
            "finding": finding,
            "patterns": related_patterns[:3],
            "evidence": related_evidence[:3],
        })

    return paths


def enrich_reasoning_paths(reasoning_context: dict, evidence: list[dict]) -> list[dict]:
    """Compatibility entry point used by the real-time GraphRAG service."""
    return build_reasoning_paths(reasoning_context, evidence)


def format_reasoning_paths_for_prompt(reasoning_paths: list[dict]) -> str:
    if not reasoning_paths:
        return "- Không có graph reasoning path rõ ràng."

    lines = []

    for idx, path in enumerate(reasoning_paths[:8], start=1):
        finding = path.get("finding", {})
        patterns = path.get("patterns", [])
        evidence = path.get("evidence", [])

        finding_text = (
            f"{finding.get('panel')} {finding.get('test')} "
            f"{finding.get('status')} ({finding.get('value')} {finding.get('unit', '')})"
        )

        if patterns:
            pattern_text = "; ".join([
                f"{p.get('pattern_name')} → {', '.join(p.get('conditions', []))}"
                for p in patterns[:2]
            ])
        else:
            pattern_text = "No matched pattern"

        if evidence:
            ev_text = "; ".join([
                f"{e.get('evidence_id')} ({e.get('source')}, p.{e.get('page')})"
                for e in evidence[:2]
            ])
        else:
            ev_text = "No direct evidence linked"

        lines.append(f"{idx}. Finding: {finding_text} → Pattern/Condition: {pattern_text} → Evidence: {ev_text}")

    return "\n".join(lines)


def clean_reference_quote(text: str, max_len: int = 360) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split()).strip()
    return cleaned[:max_len].rstrip() + " […]" if len(cleaned) > max_len else cleaned


def build_references_block(
    evidence: list[dict],
    citation_numbers: set[int] | None = None,
) -> str:
    if not evidence:
        return "📚 Tài liệu tham khảo:\n- Không có bằng chứng sách phù hợp để trích dẫn."

    lines = ["📚 Tài liệu tham khảo:"]
    for index, item in enumerate(evidence[:MAX_FINAL_EVIDENCE], start=1):
        if citation_numbers and index not in citation_numbers:
            continue
        source = item.get("source", "Unknown source")
        page = item.get("page")
        location = f", trang {page}" if page not in (None, "") else ""
        # Luôn hiển thị nguyên văn bằng chứng để người dùng có thể
        # đối chiếu với tên tài liệu và số trang. Bản dịch (nếu có)
        # phải được hiển thị riêng, không thay thế nguyên văn này.
        quote = clean_reference_quote(item.get("text", ""))
        lines.append(f"[{index}] {source}{location}. “{quote}”")
    if len(lines) == 1:
        lines.append("- Câu trả lời không sử dụng citation trực tiếp.")
    return "\n".join(lines)


def describe_knowledge_source(source: str) -> str:
    source_name = str(source or "Unknown source").strip()
    normalized = source_name.lower().replace("_", " ")
    if "harrison" in normalized:
        return (
            f"- {source_name}: giáo trình nội khoa tham khảo quốc tế, cung cấp nền tảng "
            "bệnh học và cách tiếp cận lâm sàng đa chuyên khoa."
        )
    if "clinical hematology" in normalized or "clinical hematology" in normalized.replace(".pdf", ""):
        return (
            f"- {source_name}: chuyên khảo huyết học lâm sàng, được sử dụng để đối chiếu "
            "công thức máu, hình thái tế bào và các rối loạn huyết học."
        )
    if "henry" in normalized:
        return (
            f"- {source_name}: giáo trình chuyên ngành y học xét nghiệm, trình bày nguyên lý "
            "phân tích, diễn giải kết quả và ứng dụng xét nghiệm trong thực hành lâm sàng."
        )
    if "tietz" in normalized:
        return (
            f"- {source_name}: giáo trình hóa sinh lâm sàng, cung cấp cơ sở khoa học cho "
            "diễn giải các chất phân tích và dấu ấn xét nghiệm."
        )
    return f"- {source_name}: tài liệu chuyên môn được hệ thống truy xuất cho nội dung trên."


def build_source_intro(evidence: list[dict]) -> str:
    lines = ["📚 Nguồn học thuật được sử dụng:"]
    seen_sources: set[str] = set()
    for item in evidence:
        source = str(item.get("source") or "Unknown source").strip()
        key = source.casefold()
        if key in seen_sources:
            continue
        seen_sources.add(key)
        lines.append(describe_knowledge_source(source))
    if not seen_sources:
        lines.append("- Không có tài liệu nào được trích dẫn trực tiếp trong câu trả lời này.")
    lines.extend([
        "",
        "Lưu ý: Nội dung chỉ hỗ trợ diễn giải xét nghiệm, không thay thế chẩn đoán hoặc điều trị của bác sĩ.",
    ])
    return "\n".join(lines)


def build_user_visible_answer(answer: str, ctx: dict, evidence: list[dict]) -> str:
    cited_numbers = {int(number) for number in re.findall(r"\[(\d+)\]", str(answer or ""))}
    if cited_numbers:
        cited_evidence = [
            item for index, item in enumerate(evidence, start=1)
            if index in cited_numbers
        ]
    else:
        cited_evidence = evidence[:3]

    cleaned_answer = mechanical_cleanup_answer(answer)
    # Preserve the original evidence order so [n] in the answer always maps
    # to the same [n] in the reference block.
    references = build_references_block(
        evidence,
        cited_numbers if cited_numbers else set(range(1, min(len(evidence), 3) + 1)),
    )
    source_intro = build_source_intro(cited_evidence)
    return f"{cleaned_answer}\n\n{references}\n\n{source_intro}".strip()


# =========================================================
# GRAPH BUILDER
# =========================================================

def build_graph_from_kb_and_cases(kb: list[dict], cases: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(node_id: str, node_type: str, **props):
        if node_id not in nodes:
            nodes[node_id] = {
                "id": node_id,
                "node_type": node_type,
                **props,
            }

    def add_edge(source: str, relation: str, target: str, **props):
        edges.append({
            "source": source,
            "relation": relation,
            "target": target,
            **props,
        })

    for idx, item in enumerate(kb):
        panel = item.get("panel", "UNKNOWN")
        text = item.get("text", "")
        ev_id = item.get("evidence_id") or f"ev_{panel.lower()}_{idx:06d}_{stable_hash(text)}"

        source = item.get("source", "Unknown")
        source_id = f"source_{slugify(source)}"
        panel_id = f"panel_{panel}"

        add_node(panel_id, "Panel", name=panel)

        add_node(
            ev_id,
            "Evidence",
            panel=panel,
            text=text,
            source=source,
            page=item.get("page", ""),
            trust=item.get("trust", 0.8),
            score=item.get("score", 0),
            evidence_type=item.get("type", "general"),
        )

        add_node(source_id, "Source", name=source)

        add_edge(ev_id, "FROM_SOURCE", source_id, confidence=item.get("trust", 0.8))
        add_edge(ev_id, "BELONGS_TO_PANEL", panel_id)

        for test in item.get("tests", []):
            test_id = f"test_{test}"
            add_node(test_id, "Test", name=test, display_name=TEST_LABELS.get(test, test))
            add_edge(ev_id, "MENTIONS_TEST", test_id)

        for condition in item.get("conditions", []):
            condition_id = f"condition_{slugify(condition)}"
            add_node(condition_id, "Condition", name=condition)
            add_edge(ev_id, "SUPPORTS", condition_id)

    for idx, case in enumerate(cases):
        ctx = build_reasoning_context(case, idx)
        case_id = ctx["case_id"]
        case_node_id = f"case_{slugify(case_id)}"

        add_node(case_node_id, "Case", case_id=case_id)

        for item in ctx.get("abnormal_items", []):
            panel = item.get("panel")
            test = item.get("test")
            status = item.get("status")

            finding_id = finding_node_id(case_id, panel, test, status)
            test_id = f"test_{test}"
            status_id = f"status_{status}"
            panel_id = f"panel_{panel}"

            add_node(panel_id, "Panel", name=panel)
            add_node(test_id, "Test", name=test, display_name=TEST_LABELS.get(test, test))
            add_node(status_id, "Status", name=status)

            add_node(
                finding_id,
                "Finding",
                panel=panel,
                test=test,
                status=status,
                value=item.get("value"),
                raw_value=item.get("raw_value"),
                unit=item.get("unit", ""),
                reference_range=item.get("reference_range", ""),
            )

            add_edge(case_node_id, "HAS_FINDING", finding_id)
            add_edge(finding_id, "OF_TEST", test_id)
            add_edge(finding_id, "HAS_STATUS", status_id)
            add_edge(test_id, "BELONGS_TO_PANEL", panel_id)

        for pattern in ctx.get("detected_patterns", []):
            pattern_id = f"pattern_{slugify(pattern.get('pattern_id'))}"

            add_node(
                pattern_id,
                "Pattern",
                name=pattern.get("pattern_name"),
                panel=pattern.get("panel"),
                confidence=pattern.get("confidence"),
                description=pattern.get("description"),
            )

            add_edge(
                case_node_id,
                "MATCHES_PATTERN",
                pattern_id,
                confidence=pattern.get("confidence"),
            )

            for condition in pattern.get("conditions", []):
                condition_id = f"condition_{slugify(condition)}"
                add_node(condition_id, "Condition", name=condition)

                add_edge(
                    pattern_id,
                    "SUGGESTS",
                    condition_id,
                    confidence=pattern.get("confidence"),
                )

    seen = set()
    deduped_edges = []

    for edge in edges:
        key = (edge["source"], edge["relation"], edge["target"])

        if key not in seen:
            seen.add(key)
            deduped_edges.append(edge)

    node_type_counts: dict[str, int] = {}
    edge_type_counts: dict[str, int] = {}

    for node in nodes.values():
        node_type = node.get("node_type", "Unknown")
        node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

    for edge in deduped_edges:
        relation = edge.get("relation", "Unknown")
        edge_type_counts[relation] = edge_type_counts.get(relation, 0) + 1

    return {
        "nodes": list(nodes.values()),
        "edges": deduped_edges,
        "stats": {
            "num_nodes": len(nodes),
            "num_edges": len(deduped_edges),
            "node_type_counts": node_type_counts,
            "edge_type_counts": edge_type_counts,
        },
    }


def export_graph_csv(graph: dict, output_dir: Path | str) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = output_dir / "nodes.csv"
    edges_path = output_dir / "relationships.csv"

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    node_keys = sorted({key for node in nodes for key in node.keys()})
    edge_keys = sorted({key for edge in edges for key in edge.keys()})

    with open(nodes_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=node_keys)
        writer.writeheader()

        for node in nodes:
            writer.writerow(node)

    with open(edges_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=edge_keys)
        writer.writeheader()

        for edge in edges:
            writer.writerow(edge)


# =========================================================
# PROMPT FORMAT
# =========================================================

def clean_quote(text: str, max_len: int = 350) -> str:
    text = str(text or "").replace("\n", " ")
    text = " ".join(text.split()).strip()

    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."

    return text


def format_abnormal_findings(reasoning_context: dict) -> str:
    items = reasoning_context.get("abnormal_items", [])

    if not items:
        return "- Không phát hiện bất thường rõ ràng."

    lines = []

    for item in items:
        value = item.get("value")

        if value is None:
            value = item.get("raw_value", "")

        status_vi = {"high": "cao", "low": "thấp", "normal": "bình thường"}.get(
            str(item.get("status") or "").lower(), item.get("status")
        )
        panel_vi = {"CBC": "Công thức máu", "BIOCHEM": "Hóa sinh"}.get(
            str(item.get("panel") or "").upper(), item.get("panel")
        )
        line = (
            f"- {panel_vi} | {item.get('test')}: {value} {item.get('unit', '')}, "
            f"trạng thái = {status_vi}"
        )

        if item.get("reference_range"):
            line += f", khoảng tham chiếu = {item.get('reference_range')}"

        lines.append(line)

    return "\n".join(lines)


def format_patterns(reasoning_context: dict) -> str:
    patterns = reasoning_context.get("detected_patterns", [])

    if not patterns:
        return "- Không phát hiện mẫu hình phối hợp rõ ràng."

    lines = []

    for pattern in patterns[:6]:
        line = f"- {pattern.get('description')}"

        lines.append(line)

    return "\n".join(lines)


def format_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return "- Không có evidence phù hợp."

    lines = []

    for i, e in enumerate(evidence[:MAX_FINAL_EVIDENCE], start=1):
        text = clean_quote(e.get("text", ""))
        source = e.get("source", "Unknown")
        page = e.get("page", "")
        panel = e.get("panel", "UNKNOWN")
        tests = ", ".join(e.get("tests", []))
        conditions = ", ".join(e.get("conditions", []))
        score = e.get("final_score", e.get("score"))

        lines.append(
            f"[{i}] Panel={panel}; Tests={tests}; Conditions={conditions}; "
            f"Source={source}; Page={page}; Score={score}; Quote=\"{text}\""
        )

    return "\n".join(lines)


def build_final_prompt(
    reasoning_context: dict,
    evidence: list[dict],
    reasoning_paths: list[dict] | None = None,
) -> str:
    abnormal_text = format_abnormal_findings(reasoning_context)
    pattern_text = format_patterns(reasoning_context)
    evidence_text = format_evidence(evidence)
    graph_text = format_reasoning_paths_for_prompt(reasoning_paths or [])
    normal_companions = [
        {
            "test": item.get("test"),
            "value": item.get("value"),
            "unit": item.get("unit", ""),
            "status": item.get("status"),
        }
        for item in reasoning_context.get("items", [])
        if normalize_status(item.get("status")) == "normal"
    ]
    companion_text = json.dumps(normal_companions, ensure_ascii=False, indent=2)
    curated_outline = reasoning_context.get("curated_answer_outline") or {}
    curated_text = json.dumps(curated_outline, ensure_ascii=False, indent=2)

    return f"""
Bạn là chuyên gia diễn giải xét nghiệm cận lâm sàng.

Nhiệm vụ:
- Diễn giải các bất thường xét nghiệm CBC và/hoặc sinh hóa cho người dùng cuối bằng tiếng Việt.
- Toàn bộ phần trả lời phải dùng tiếng Việt tự nhiên. Chỉ giữ nguyên mã xét nghiệm
  (ví dụ WBC, NEUT#, MCHC), đơn vị và tên sách/tài liệu tiếng Anh.
- Không hiển thị tên mẫu hình, nhãn lâm sàng hay trạng thái bằng tiếng Anh;
  phải chuyển chúng sang tiếng Việt.
- Dùng ABNORMAL FINDINGS để biết chính xác xét nghiệm nào bất thường.
- Dùng DETECTED PATTERNS và GRAPH REASONING PATHS như context hỗ trợ suy luận.
- Chỉ dùng EVIDENCE từ sách PDF để đặt citation [1], [2], [3].
- Không dùng static pattern/rule làm citation nếu static pattern/rule không nằm trong EVIDENCE.
- Không bịa xét nghiệm không có trong ABNORMAL FINDINGS.
- Dùng NORMAL COMPANION FINDINGS để phân biệt thay đổi tương đối và tuyệt đối.
- Nếu VERIFIED CURATED OUTLINE có nội dung, phải tuân thủ các mục
  supported_interpretations, unsupported_interpretations và companion_normal_findings.
- Nếu runtime_guardrails.etiology_supported_by_current_evidence = false, tuyệt đối không
  nêu nhiễm trùng, viêm, stress, thuốc hoặc nguyên nhân bệnh lý như một diễn giải của pattern.
  Chỉ được nói chưa đủ dữ liệu xác định nguyên nhân và liệt kê chúng dưới dạng thông tin cần hỏi thêm.
- Nếu runtime_guardrails.etiology_support_scope = "evaluation_context_only", chỉ được nói
  một tình trạng là bối cảnh bác sĩ thường kiểm tra hoặc cần loại trừ; không được nói
  đó là nguyên nhân của ca hiện tại hay dùng cụm "có khả năng bị".
- Không được biến nội dung recommended_followup_questions thành kết luận lâm sàng.
- Không bịa nguồn, tên sách hoặc số trang.
- Không chẩn đoán chắc chắn. Khi chỉ đang mô tả đúng bất thường đã đo được, ưu tiên
  cách nói dễ hiểu như "cho thấy" hoặc "nghĩa là". Chỉ dùng "gợi ý", "có thể"
  cho nhận định chưa chắc chắn. Hạn chế lặp cụm "phù hợp với".
- Nếu evidence không đủ cho một nhận định, phải nói rõ là bằng chứng còn hạn chế và không suy diễn quá xa.
- Citation phải hỗ trợ trực tiếp cho đúng nhận định đứng trước nó; evidence chỉ định nghĩa
  một chỉ số không được dùng để khẳng định nguyên nhân của bất thường đó.
- Không áp dụng evidence dành riêng cho trẻ em, thai kỳ hoặc nhóm tuổi cụ thể khi case
  không cung cấp thông tin nhân khẩu học tương ứng.
- Khi một chỉ số bất thường không được evidence hỗ trợ rõ ràng, hãy nói rõ rằng hiện chưa đủ dữ liệu để kết luận nguyên nhân cụ thể.
- Ưu tiên diễn giải theo các bất thường có liên quan trực tiếp với nhau; tránh kết nối các chỉ số riêng lẻ quá rộng nếu không có căn cứ.
- Không dùng câu như "đây chắc chắn là...", "bệnh này xác định là...", hoặc "nguy hiểm ngay lập tức" nếu chưa có dấu hiệu cấp độ cao.
- Không kê thuốc, không đưa liều điều trị.
- Không nhắc lại prompt.
- Không dùng dấu "...".
- Trả lời ngắn gọn, dễ hiểu, phù hợp để hiển thị trực tiếp cho người dùng
  không có chuyên môn y khoa. Tránh lặp cùng một ý ở nhiều mục.
- Không tạo mục "Hạn chế". Chỉ lồng ghép thông tin thực sự cần bổ sung vào mục
  "Bạn nên làm gì?" bằng một câu ngắn.
- Không liệt kê xét nghiệm hoặc thông tin không liên quan trực tiếp đến phiếu hiện tại.
- Phải đề cập mọi chỉ số trong ABNORMAL FINDINGS. Với bất thường nhẹ không có
  evidence trực tiếp, chỉ mô tả mức lệch và khuyến nghị đối chiếu/lặp lại, không gán nguyên nhân.
- Khi có cả trị số tuyệt đối và tỷ lệ phần trăm, dùng trị số tuyệt đối làm căn cứ chính;
  tỷ lệ phần trăm chỉ là dấu hiệu đi kèm, không dùng đơn độc để kết luận.
- Một chỉ số chỉ vượt ngưỡng rất ít phải được mô tả là "tăng rất nhẹ" hoặc "giảm rất nhẹ";
  cần đối chiếu các chỉ số liên quan và chất lượng mẫu trước khi gán ý nghĩa bệnh lý.
- Không viết theo cấu trúc lặp nghĩa như "tăng bạch cầu trung tính gợi ý tăng bạch cầu
  trung tính". Hãy nói trực tiếp: "WBC cao kèm NEUT# cao cho thấy số lượng bạch cầu
  trung tính trong máu cao hơn bình thường [citation]."

========================
ABNORMAL FINDINGS
{abnormal_text}

NORMAL COMPANION FINDINGS
{companion_text}

DETECTED PATTERNS
{pattern_text}

VERIFIED CURATED OUTLINE
{curated_text}

GRAPH REASONING PATHS
{graph_text}

EVIDENCE
{evidence_text}
========================

YÊU CẦU OUTPUT (chỉ dùng 4 mục sau):

### 1. Nhận định chính
- Mở đầu bằng "Điểm cần chú ý nhất là..." và nêu cụm bất thường quan trọng nhất.
- Không chép lại toàn bộ bảng giá trị vì người dùng đã nhìn thấy bảng xét nghiệm.
- Xếp các kết quả thành mức ưu tiên: bất thường chính, thay đổi đi kèm và sai lệch rất nhẹ.
- Nói rõ chỉ số phần trăm chỉ là thay đổi tương đối khi số lượng tuyệt đối vẫn bình thường.

### 2. Kết quả này thường liên quan đến gì?
- Đây là phần người dùng quan tâm nhất. Nếu evidence hỗ trợ nguyên nhân/bối cảnh, nêu tối đa
  2 nhóm nguyên nhân thường gặp, dùng ngôn ngữ xác suất và citation trực tiếp.
- Nếu evidence chỉ định nghĩa chỉ số, không bịa nguyên nhân. Viết ngắn: "Phiếu xét nghiệm
  xác nhận thay đổi này nhưng chưa cho biết nguyên nhân; cần đối chiếu triệu chứng và bệnh sử."
- Không nêu bệnh hoặc nhóm nguyên nhân nào không xuất hiện rõ trong quote của EVIDENCE;
  đặc biệt không tự thêm bệnh tự miễn, ung thư hoặc nhiễm trùng từ kiến thức chung.
- Mỗi cụm chỉ số phải gắn với đúng evidence của nó: LYM# không dùng evidence của EOS#;
  thiếu máu hồng cầu nhỏ không dùng đoạn chỉ định nghĩa thiếu máu để khẳng định nguyên nhân.
- Không lặp lại định nghĩa đã nói trong mục 1.
- Nếu evidence nói về "persisting leukocytosis", chỉ được nhắc nguy cơ bệnh huyết học theo điều kiện:
  WBC tăng kéo dài qua các lần xét nghiệm và không có nguyên nhân nhiễm trùng rõ. Không được
  suy ra ung thư máu hoặc bệnh tăng sinh tủy từ một phiếu đơn lẻ.
- Nếu evidence về đánh giá leukocytosis nhắc tới nhiễm trùng, có thể nói nhiễm trùng là một
  bối cảnh bác sĩ sẽ kiểm tra; không được nói người dùng chắc chắn đang nhiễm trùng.
- Với sai lệch rất nhẹ như MCHC 362 so với giới hạn 360, chỉ cần một câu: thường ưu tiên
  xem cùng các chỉ số hồng cầu khác và chất lượng mẫu, không xem là kết luận chính.

### 3. Bạn nên làm gì?
- Viết tối đa 2 gạch đầu dòng, xếp theo thứ tự ưu tiên và chỉ nêu hành động thiết thực.
- Khuyên trao đổi với bác sĩ cùng triệu chứng, bệnh sử và thuốc đang dùng.
- Chỉ nhắc CRP, phết máu hoặc lặp CBC nếu có triệu chứng phù hợp hoặc bác sĩ chỉ định;
  không viết như một yêu cầu mặc định.

### 4. Khi nào cần đi khám ngay?
- Nói rõ không thể đánh giá mức độ nặng chỉ từ phiếu xét nghiệm.
- Chỉ liệt kê ngắn các triệu chứng cảnh báo thực sự phù hợp với dữ liệu hiện có.
- Không khẳng định người dùng an toàn hoặc "không có dấu hiệu nặng".
- Chỉ viết 1 gạch đầu dòng ngắn, không tạo danh sách cảnh báo dài.

Lưu ý citation:
- Chỉ dùng citation dạng [1], [2], [3], [4], [5], [6] tương ứng với thứ tự trong EVIDENCE.
- Không dùng citation ngoài danh sách EVIDENCE.
- Không trích nguyên văn quote dài trong phần trả lời chính.
""".strip()

# =========================================================
# LLM
# =========================================================
def call_local_ollama_llm(prompt: str) -> str:
    load_dotenv()

    local_url = os.getenv("LOCAL_LLM_URL", "").strip()
    model_name = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:3b").strip()

    if not local_url:
        raise ValueError("Missing LOCAL_LLM_URL in .env")

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": COLAB_TEMPERATURE,
            "num_predict": COLAB_MAX_NEW_TOKENS,
        },
    }

    headers = {
        "Content-Type": "application/json",
        "ngrok-skip-browser-warning": "true",
    }

    logger.info("Calling local Ollama model: %s", model_name)

    start = time.time()

    response = requests.post(
        local_url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    elapsed = time.time() - start
    logger.debug("Local Ollama returned in %.1fs.", elapsed)

    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict):
        text = (
            data.get("response")
            or data.get("text")
            or data.get("output")
            or data.get("generated_text")
            or data.get("answer")
            or ""
        )
    else:
        text = str(data)

    text = extract_final_answer(str(text))

    if not text:
        raise ValueError(f"Local Ollama returned empty response: {data}")

    return text

def timed_llm_call(provider_name: str, func, prompt: str) -> tuple[str, dict]:
    start = time.time()
    text = func(prompt)
    elapsed = time.time() - start

    meta = {
        "model_used": provider_name,
        "elapsed_seconds": round(elapsed, 2),
    }

    return text, meta


def normalize_colab_url(url: str) -> str:
    url = str(url or "").strip().rstrip("/")

    if not url:
        return ""

    if not url.endswith("/generate"):
        url += "/generate"

    return url


def call_colab_llm(prompt: str) -> str:
    load_dotenv()

    colab_url = normalize_colab_url(os.getenv("COLAB_LLM_URL", ""))

    if not colab_url:
        raise ValueError("Missing COLAB_LLM_URL in .env")

    payload = {
        "prompt": prompt,
        "max_new_tokens": COLAB_MAX_NEW_TOKENS,
        "temperature": COLAB_TEMPERATURE,
    }

    logger.info("Calling Colab LLM endpoint.")

    start = time.time()

    response = requests.post(
        colab_url,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    elapsed = time.time() - start
    logger.debug("Colab LLM returned in %.1fs.", elapsed)

    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict):
        text = (
            data.get("response")
            or data.get("text")
            or data.get("output")
            or data.get("generated_text")
            or data.get("answer")
            or ""
        )
    else:
        text = str(data)

    text = extract_final_answer(str(text))

    if not text:
        raise ValueError("Colab LLM returned empty response")

    return text


def call_gemini_llm(prompt: str) -> str:
    load_dotenv()

    if genai is None:
        raise RuntimeError("google-genai is not installed")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY in .env")

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    logger.info("Calling Gemini model: %s", model_name)

    start = time.time()

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
    )

    elapsed = time.time() - start
    logger.debug("Gemini returned in %.1fs.", elapsed)

    text = str(getattr(response, "text", "") or "").strip()
    text = extract_final_answer(text)

    if not text:
        raise ValueError("Gemini returned empty response")

    return text


def call_deepseek_llm(prompt: str) -> str:
    """Generate a response through an OpenRouter-compatible DeepSeek model."""

    load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if not api_key:
        raise ValueError("Missing OPENROUTER_API_KEY in .env")

    model_name = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")

    logger.info("Calling OpenRouter model: %s", model_name)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": COLAB_TEMPERATURE,
        "max_tokens": COLAB_MAX_NEW_TOKENS,
    }

    start = time.time()

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    elapsed = time.time() - start
    logger.debug("OpenRouter returned in %.1fs.", elapsed)

    response.raise_for_status()
    data = response.json()

    try:
        text = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise ValueError(f"Unexpected OpenRouter response format: {data}") from exc

    text = extract_final_answer(str(text))

    if not text:
        raise ValueError("OpenRouter/DeepSeek returned empty response")

    return text

def call_llm_with_meta(prompt: str) -> tuple[str, dict]:
    """
    Provider order:
    1. Local Ollama via LOCAL_LLM_URL
    2. Gemini
    3. OpenRouter/DeepSeek
    4. Colab LLM
    """

    load_dotenv()

    errors = []

    # 1. Local Ollama first
    try:
        model_name = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:3b").strip()
        return timed_llm_call(
            f"local_ollama/{model_name}",
            call_local_ollama_llm,
            prompt,
        )
    except Exception as exc:
        err = f"Local Ollama failed: {exc}"
        logger.warning(err)
        errors.append(err)

    # 2. Gemini fallback
    try:
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        return timed_llm_call(model_name, call_gemini_llm, prompt)
    except Exception as exc:
        err = f"Gemini failed: {exc}"
        logger.warning(err)
        errors.append(err)

    # 3. OpenRouter/DeepSeek fallback
    try:
        model_name = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")
        return timed_llm_call(f"openrouter/{model_name}", call_deepseek_llm, prompt)
    except Exception as exc:
        err = f"OpenRouter/DeepSeek failed: {exc}"
        logger.warning(err)
        errors.append(err)

    # 4. Colab fallback
    try:
        return timed_llm_call("colab_llm", call_colab_llm, prompt)
    except Exception as exc:
        err = f"Colab LLM failed: {exc}"
        logger.warning(err)
        errors.append(err)

    raise RuntimeError("All LLM providers failed:\n" + "\n".join(errors))


def call_llm(prompt: str) -> str:
    """
    Wrapper giữ compatibility với run_final.py hiện tại.
    run_final.py đang gọi call_llm(prompt) và expect string.
    """

    text, _meta = call_llm_with_meta(prompt)
    return text


def extract_final_answer(raw_text: str) -> str:
    if not raw_text:
        return ""

    text = str(raw_text).strip()
    lower = text.lower()

    markers = [
        "\nassistant\n",
        "\nassistant:",
        "assistant\n",
        "assistant:",
    ]

    found_pos = -1
    found_marker = ""

    for marker in markers:
        pos = lower.rfind(marker)

        if pos > found_pos:
            found_pos = pos
            found_marker = marker

    if found_pos != -1:
        cleaned = text[found_pos + len(found_marker):].strip()

        if cleaned:
            return cleaned

    return text.strip()


def has_bad_placeholders(text: str) -> bool:
    if not text:
        return True

    bad_patterns = [
        r"\(\.\.\.\)",
        r"\.\.\.",
        r"\(source,\s*p\.[^)]+\)",
        r"\[citation needed\]",
    ]

    lower = text.lower()

    for pattern in bad_patterns:
        if re.search(pattern, lower, flags=re.IGNORECASE):
            return True

    return False


def build_repair_prompt(bad_answer: str) -> str:
    return f"""
Bạn hãy sửa lại câu trả lời sau cho đúng format citation.

YÊU CẦU:
- Giữ nguyên nội dung y khoa nếu hợp lý.
- Xóa toàn bộ dấu "...".
- Xóa toàn bộ "(...)".
- Xóa toàn bộ "(Source, p.xxx)".
- Nếu cần citation, chỉ dùng dạng [1], [2], [3], [4], [5], [6].
- Không thêm thông tin mới.
- Không nhắc lại prompt.
- Chỉ trả về bản đã sửa bằng tiếng Việt.

NỘI DUNG CẦN SỬA:
{bad_answer}
""".strip()


def generate_clean_answer(prompt: str) -> tuple[str, dict]:
    answer, meta = call_llm_with_meta(prompt)

    if not has_bad_placeholders(answer):
        return answer.strip(), meta

        logger.warning("Detected placeholder citation; attempting repair.")

    repair_prompt = build_repair_prompt(answer)

    try:
        repaired, repair_meta = call_llm_with_meta(repair_prompt)

        if repaired and not has_bad_placeholders(repaired):
            meta["repaired"] = True
            meta["repair_model_used"] = repair_meta.get("model_used")
            meta["repair_elapsed_seconds"] = repair_meta.get("elapsed_seconds")
            meta["total_elapsed_seconds"] = round(
                float(meta.get("elapsed_seconds", 0))
                + float(repair_meta.get("elapsed_seconds", 0)),
                2,
            )
            return repaired.strip(), meta

    except Exception as exc:
        logger.warning("Citation repair failed: %s", exc)

    meta["repaired"] = False
    return mechanical_cleanup_answer(answer), meta


def mechanical_cleanup_answer(text: str) -> str:
    if not text:
        return ""

    text = text.replace("(...)", "")
    text = text.replace("...", "")
    text = re.sub(r"\(Source,\s*p\.[^)]+\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[citation needed\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


def build_references(evidence: list[dict]) -> list[dict]:
    refs = []

    for i, e in enumerate(evidence[:MAX_FINAL_EVIDENCE], start=1):
        refs.append({
            "id": i,
            "panel": e.get("panel"),
            "source": e.get("source"),
            "page": e.get("page"),
            "tests": e.get("tests", []),
            "conditions": e.get("conditions", []),
            "quote": clean_quote(e.get("text", ""), max_len=260),
            "score": e.get("final_score", e.get("score")),
        })

    return refs


def extract_final_answer(raw_text: str) -> str:
    if not raw_text:
        return ""

    text = str(raw_text).strip()
    lower = text.lower()

    markers = [
        "\nassistant\n",
        "\nassistant:",
        "assistant\n",
        "assistant:",
    ]

    found_pos = -1
    found_marker = ""

    for marker in markers:
        pos = lower.rfind(marker)

        if pos > found_pos:
            found_pos = pos
            found_marker = marker

    if found_pos != -1:
        cleaned = text[found_pos + len(found_marker):].strip()

        if cleaned:
            return cleaned

    return text.strip()


def has_bad_placeholders(text: str) -> bool:
    if not text:
        return True

    bad_patterns = [
        r"\(\.\.\.\)",
        r"\(source,\s*p\.[^)]+\)",
        r"\[citation needed\]",
    ]

    lower = text.lower()

    for pattern in bad_patterns:
        if re.search(pattern, lower, flags=re.IGNORECASE):
            return True

    return False


def mechanical_cleanup_answer(text: str) -> str:
    if not text:
        return ""

    text = text.replace("(...)", "")
    text = re.sub(r"\(Source,\s*p\.[^)]+\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[citation needed\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


def build_references(evidence: list[dict]) -> list[dict]:
    refs = []

    for i, e in enumerate(evidence[:MAX_FINAL_EVIDENCE], start=1):
        refs.append({
            "id": i,
            "panel": e.get("panel"),
            "source": e.get("source"),
            "page": e.get("page"),
            "tests": e.get("tests", []),
            "conditions": e.get("conditions", []),
            "quote": clean_quote(e.get("text", ""), max_len=260),
            "score": e.get("final_score", e.get("score")),
        })

    return refs

