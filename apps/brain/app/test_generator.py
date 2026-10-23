"""
Chapter Test Generator Service Module.

Orchestrates two phases to produce a structured, curriculum-aligned test:

  Phase 1 – Qdrant Full-Chapter Retrieval:
      Uses metadata-filtered scroll pagination (NOT similarity search) to
      fetch 100% of chunks belonging to a chapter.  Avoids `top_k` entirely.

  Phase 2 – Groq LLM Structured Generation:
      Aggregates retrieved chunks by sub-topic, constructs a strict system
      prompt for a senior CBSE curriculum designer, calls Groq with JSON
      mode, and validates the response through Pydantic v2 models.

Dependencies:
    - qdrant-client >= 1.7
    - groq >= 1.0
    - pydantic >= 2.0
    - python-dotenv
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from dotenv import find_dotenv, load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.rag import get_groq_client, get_qdrant_client
from app.test_schemas import (
    ChapterTestResponse,
    GenerateTestRequest,
)

# Load environment variables
load_dotenv(find_dotenv(usecwd=True))

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum points returned per scroll() call — Qdrant hard-caps at 10 000
_SCROLL_BATCH_LIMIT: int = 256

# Default Groq model for test generation
_DEFAULT_TEST_MODEL: str = "llama-3.3-70b-versatile"

# LLM generation parameters
_LLM_TEMPERATURE: float = 0.3
_LLM_MAX_TOKENS: int = 8192


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1 — Qdrant Full-Chapter Retrieval via Scroll Pagination
# ═══════════════════════════════════════════════════════════════════════════

def _build_chapter_filter(
    class_level: str,
    subject: str,
    chapter_number: str,
) -> models.Filter:
    """
    Build a Qdrant metadata filter that matches all chunks for a specific
    chapter.  Uses OR-logic for field name variants (``class`` vs
    ``class_name``) and case variants for the subject to tolerate
    inconsistent ingestion metadata.

    Args:
        class_level: e.g. ``"7"``
        subject:     e.g. ``"Science"``
        chapter_number: e.g. ``"1"`` or ``"01"``

    Returns:
        A ``models.Filter`` with three ``must`` conditions.
    """
    class_val = str(class_level)
    chapter_val = str(chapter_number)

    # Subject case variants for fault-tolerant matching
    subj_variants: List[str] = list(dict.fromkeys([
        subject,
        subject.lower(),
        subject.capitalize(),
        subject.upper(),
        subject.title(),
    ]))

    must_conditions: List[Any] = [
        # Condition 1 — class level (tolerate both field names)
        models.Filter(
            should=[
                models.FieldCondition(
                    key="class_name",
                    match=models.MatchValue(value=class_val),
                ),
                models.FieldCondition(
                    key="class",
                    match=models.MatchValue(value=class_val),
                ),
            ],
        ),
        # Condition 2 — subject (case-insensitive via multiple variants)
        models.Filter(
            should=[
                models.FieldCondition(
                    key="subject",
                    match=models.MatchValue(value=variant),
                )
                for variant in subj_variants
            ],
        ),
        # Condition 3 — chapter number
        models.Filter(
            should=[
                models.FieldCondition(
                    key="chapter",
                    match=models.MatchValue(value=chapter_val),
                ),
                # Some ingestion pipelines store it as an integer string "01"
                models.FieldCondition(
                    key="chapter",
                    match=models.MatchValue(value=chapter_val.lstrip("0") or "0"),
                ),
            ],
        ),
    ]

    return models.Filter(must=must_conditions)


def fetch_full_chapter_chunks(
    collection_name: str,
    class_level: str,
    subject: str,
    chapter_number: str,
) -> List[Dict[str, Any]]:
    """
    Retrieve **every** chunk belonging to a chapter from Qdrant using
    metadata-filtered scroll pagination.

    This deliberately avoids similarity search (``query_points`` /
    ``search``) so that the entire chapter content is returned without
    any ranking cut-off.

    Strategy:
        1. Build a strict metadata filter on (class_level, subject, chapter_number).
        2. Use ``client.scroll()`` with ``with_vectors=False`` to conserve
           bandwidth — we only need payloads.
        3. Paginate via the ``offset`` cursor returned by each scroll call
           until the cursor becomes ``None`` (all points consumed).

    Args:
        collection_name: Qdrant collection name.
        class_level:     Class / grade level, e.g. ``"7"``.
        subject:         Subject name, e.g. ``"Science"``.
        chapter_number:  Chapter number string, e.g. ``"1"``.

    Returns:
        A list of dicts, each containing:
            - ``text``: the chunk's textual content
            - ``section``: the chunk's hierarchical section breadcrumb
            - ``metadata``: the full payload dict

    Raises:
        ValueError: If the collection yields zero chunks for the filter.
    """
    client: QdrantClient = get_qdrant_client()
    scroll_filter: models.Filter = _build_chapter_filter(
        class_level, subject, chapter_number,
    )

    all_chunks: List[Dict[str, Any]] = []
    offset: Optional[str | int] = None  # initial offset — start from the beginning
    page_count: int = 0

    logger.info(
        "Fetching chapter chunks — collection=%s, class=%s, subject=%s, chapter=%s",
        collection_name, class_level, subject, chapter_number,
    )

    while True:
        page_count += 1

        # Qdrant scroll() returns (points, next_offset)
        points, next_offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            limit=_SCROLL_BATCH_LIMIT,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for point in points:
            payload: Dict[str, Any] = point.payload or {}
            text = (
                payload.get("page_content")
                or payload.get("text")
                or payload.get("content")
                or ""
            )
            section = payload.get("section", "General")

            if text.strip():
                all_chunks.append({
                    "text": text.strip(),
                    "section": section,
                    "metadata": payload,
                })

        logger.info(
            "  scroll page %d: received %d points (running total: %d)",
            page_count, len(points), len(all_chunks),
        )

        # If next_offset is None, we have exhausted all matching points
        if next_offset is None:
            break

        offset = next_offset

    if not all_chunks:
        raise ValueError(
            f"No chunks found for class={class_level}, subject={subject}, "
            f"chapter={chapter_number} in collection '{collection_name}'.  "
            "Verify that the chapter has been ingested with correct metadata."
        )

    logger.info(
        "Chapter retrieval complete: %d chunks across %d scroll pages.",
        len(all_chunks), page_count,
    )

    return all_chunks


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 — Groq LLM Structured Test Generation
# ═══════════════════════════════════════════════════════════════════════════

def _group_chunks_by_section(
    chunks: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """
    Group chunk texts by their ``section`` breadcrumb so that the LLM
    prompt presents content in a logically organised manner.

    Returns:
        An ordered dict mapping ``section_name → [chunk_text, ...]``.
    """
    grouped: Dict[str, List[str]] = defaultdict(list)
    for chunk in chunks:
        section = chunk.get("section", "General")
        grouped[section].append(chunk["text"])
    return dict(grouped)


def _build_chapter_context(grouped_chunks: Dict[str, List[str]]) -> str:
    """
    Serialize grouped chunks into a single context string suitable for
    the LLM prompt.  Each section is headed by its breadcrumb.
    """
    parts: List[str] = []
    for section, texts in grouped_chunks.items():
        parts.append(f"--- SECTION: {section} ---")
        parts.append("\n\n".join(texts))
        parts.append("")  # blank line separator
    return "\n".join(parts)


def _build_system_prompt() -> str:
    """
    Construct the system prompt that frames the LLM as a senior CBSE
    curriculum designer.  The prompt enforces JSON output structure,
    question type distribution, difficulty ratios, and pedagogical
    quality requirements.
    """
    return """You are a Senior Class 7 CBSE Science Curriculum Designer and Assessment Expert with 20+ years of experience creating standardised tests for the National Council of Educational Research and Training (NCERT).

YOUR TASK:
Generate a comprehensive, curriculum-aligned chapter test based ONLY on the textbook content provided below.  Do NOT invent facts or concepts that are absent from the provided content.

OUTPUT FORMAT — Respond with a single, valid JSON object that conforms EXACTLY to this structure:

{
  "class_level": "<string>",
  "subject": "<string>",
  "chapter_number": "<string>",
  "chapter_title": "<string — infer from the content>",
  "total_marks": <number — must equal the sum of all question marks>,
  "duration_minutes": <integer>,
  "questions": [
    {
      "question_number": <int, 1-indexed sequential>,
      "question_type": "<MCQ | FILL_IN_BLANKS | TRUE_FALSE | ASSERTION_REASON | SHORT_ANSWER_1 | SHORT_ANSWER_2 | LONG_ANSWER | CASE_STUDY>",
      "question_text": "<string>",
      "options": [{"label": "A", "text": "..."}, ...] | null,
      "correct_answer": "<string>",
      "marks": <number>,
      "negative_marks": <number, 0 if none>,
      "difficulty": "<EASY | MEDIUM | HARD>",
      "bloom_level": "<REMEMBER | UNDERSTAND | APPLY | ANALYZE | EVALUATE | CREATE>",
      "topic": "<specific sub-topic from the chapter>",
      "step_wise_marking": ["step 1...", "step 2..."] | null,
      "explanation": "<student-friendly explanation>",
      "sub_questions": [
        {
          "sub_question_number": <int>,
          "question_text": "<string>",
          "question_type": "<MCQ | SHORT_ANSWER_1>",
          "options": [...] | null,
          "correct_answer": "<string>",
          "marks": <number>,
          "explanation": "<string>"
        }
      ] | null
    }
  ]
}

QUESTION TYPE DISTRIBUTION (generate ALL of these):
  • 5  MCQ questions (1 mark each, negative_marks = 0.25)
  • 3  FILL_IN_BLANKS questions (1 mark each)
  • 3  TRUE_FALSE questions (1 mark each)
  • 2  ASSERTION_REASON questions (1 mark each, 4 options)
  • 3  SHORT_ANSWER_1 questions (2 marks each — answer in 1-2 sentences)
  • 3  SHORT_ANSWER_2 questions (3 marks each — answer in 3-5 sentences, must include step_wise_marking)
  • 2  LONG_ANSWER questions (5 marks each — detailed paragraph, must include step_wise_marking)
  • 1  CASE_STUDY question (4 marks total — passage + at least 4 sub-questions of 1 mark each)

  Total: 22 questions, total_marks = 40

DIFFICULTY DISTRIBUTION:
  • EASY   ≈ 30% of questions (about 6-7 questions)
  • MEDIUM ≈ 50% of questions (about 10-11 questions)
  • HARD   ≈ 20% of questions (about 4-5 questions)

BLOOM'S TAXONOMY:
  • REMEMBER / UNDERSTAND — primarily for MCQ, FILL_IN_BLANKS, TRUE_FALSE
  • APPLY / ANALYZE       — primarily for SHORT_ANSWER_1, SHORT_ANSWER_2, ASSERTION_REASON
  • EVALUATE / CREATE     — primarily for LONG_ANSWER, CASE_STUDY

QUALITY RULES:
  1. Every question MUST be traceable to specific content in the provided textbook material.
  2. MCQ distractors must be plausible but clearly incorrect.
  3. Explanations must be written for a 12-13 year old student — simple, clear, encouraging.
  4. step_wise_marking must be provided for SHORT_ANSWER_2 and LONG_ANSWER types.
  5. CASE_STUDY passage should be a real-world scenario connecting to chapter concepts.
  6. For ASSERTION_REASON: options must be:
       A: Both Assertion and Reason are true, and Reason is the correct explanation.
       B: Both Assertion and Reason are true, but Reason is NOT the correct explanation.
       C: Assertion is true but Reason is false.
       D: Assertion is false but Reason is true.
  7. Ensure questions cover ALL major sub-topics from the chapter — do NOT cluster around a single section.
  8. Respond ONLY with the JSON object. No markdown, no code fences, no additional text."""


def _build_user_prompt(
    class_level: str,
    subject: str,
    chapter_number: str,
    chapter_context: str,
) -> str:
    """
    Build the user prompt containing chapter metadata and the full
    textbook content grouped by sections.
    """
    return (
        f"Generate a complete chapter test for:\n"
        f"  Class: {class_level}\n"
        f"  Subject: {subject}\n"
        f"  Chapter Number: {chapter_number}\n\n"
        f"TEXTBOOK CONTENT (grouped by sections):\n"
        f"{'=' * 60}\n"
        f"{chapter_context}\n"
        f"{'=' * 60}\n\n"
        f"Now generate the JSON test object following ALL the rules in your system instructions."
    )


def _extract_json_from_response(raw_text: str) -> dict:
    """
    Robustly extract a JSON object from the LLM's raw response text.

    Handles common LLM quirks:
      - Response wrapped in markdown code fences (```json ... ```)
      - Leading/trailing whitespace or newlines
      - BOM characters

    Args:
        raw_text: The raw string returned by the LLM.

    Returns:
        A parsed Python dict.

    Raises:
        ValueError: If no valid JSON object can be extracted.
    """
    text = raw_text.strip()

    # Strip BOM if present
    if text.startswith("\ufeff"):
        text = text[1:]

    # Strip markdown code fences
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1:]
        # Remove closing fence
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()

    # Attempt direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find the first { ... last } substring
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace: last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise ValueError(
        "Failed to extract valid JSON from LLM response.  "
        f"Response preview (first 500 chars): {raw_text[:500]}"
    )


def _call_groq_for_test(
    chapter_context: str,
    class_level: str,
    subject: str,
    chapter_number: str,
    model: Optional[str] = None,
) -> dict:
    """
    Call Groq LLM with structured JSON mode to generate the test.

    Args:
        chapter_context: Aggregated textbook content string.
        class_level:     Class filter value.
        subject:         Subject filter value.
        chapter_number:  Chapter filter value.
        model:           Optional model override.

    Returns:
        Parsed JSON dict from the LLM response.

    Raises:
        ValueError: If Groq returns an empty or unparsable response.
        RuntimeError: If the Groq API call itself fails.
    """
    groq = get_groq_client()
    chosen_model = model or os.getenv("GROQ_TEST_MODEL", _DEFAULT_TEST_MODEL)

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(
        class_level, subject, chapter_number, chapter_context,
    )

    logger.info(
        "Calling Groq model=%s (temp=%.1f, max_tokens=%d) for test generation...",
        chosen_model, _LLM_TEMPERATURE, _LLM_MAX_TOKENS,
    )
    start = time.time()

    try:
        completion = groq.chat.completions.create(
            model=chosen_model,
            temperature=_LLM_TEMPERATURE,
            max_tokens=_LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
    except Exception as exc:
        raise RuntimeError(
            f"Groq API call failed for model '{chosen_model}': {exc}"
        ) from exc

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info("Groq responded in %d ms.", elapsed_ms)

    raw_content = (completion.choices[0].message.content or "").strip()
    if not raw_content:
        raise ValueError("Groq returned an empty response — no content generated.")

    parsed = _extract_json_from_response(raw_content)
    return parsed


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API — Generate Chapter Test (end-to-end)
# ═══════════════════════════════════════════════════════════════════════════

def generate_chapter_test(
    collection_name: str,
    class_level: str,
    subject: str,
    chapter_number: str,
    model: Optional[str] = None,
) -> ChapterTestResponse:
    """
    End-to-end chapter test generation pipeline.

    Steps:
        1. Fetch 100% of chapter chunks from Qdrant via scroll pagination.
        2. Group chunks by sub-topic / section.
        3. Build a structured prompt and call Groq LLM with JSON mode.
        4. Parse and validate the JSON response through Pydantic v2.
        5. Return the validated ``ChapterTestResponse``.

    Args:
        collection_name: Qdrant collection name.
        class_level:     Class filter, e.g. ``"7"``.
        subject:         Subject filter, e.g. ``"Science"``.
        chapter_number:  Chapter number filter, e.g. ``"1"``.
        model:           Optional Groq model override.

    Returns:
        A fully validated ``ChapterTestResponse`` Pydantic model.

    Raises:
        ValueError:  If no chunks found or LLM output fails validation.
        RuntimeError: If Groq API call fails.
    """
    logger.info("=" * 70)
    logger.info(
        "TEST GENERATION START — class=%s, subject=%s, chapter=%s, collection=%s",
        class_level, subject, chapter_number, collection_name,
    )

    # Phase 1: Full-chapter retrieval
    chunks = fetch_full_chapter_chunks(
        collection_name=collection_name,
        class_level=class_level,
        subject=subject,
        chapter_number=chapter_number,
    )
    logger.info("Retrieved %d chunks from Qdrant.", len(chunks))

    # Group and build context
    grouped = _group_chunks_by_section(chunks)
    chapter_context = _build_chapter_context(grouped)
    logger.info(
        "Chapter context built: %d sections, %d characters.",
        len(grouped), len(chapter_context),
    )

    # Phase 2: LLM generation
    raw_json = _call_groq_for_test(
        chapter_context=chapter_context,
        class_level=class_level,
        subject=subject,
        chapter_number=chapter_number,
        model=model,
    )

    # Phase 3: Pydantic validation
    try:
        test_response = ChapterTestResponse.model_validate(raw_json)
    except Exception as validation_err:
        logger.error(
            "Pydantic validation failed on LLM output: %s", validation_err,
        )
        logger.debug("Raw LLM JSON: %s", json.dumps(raw_json, indent=2)[:3000])
        raise ValueError(
            f"LLM generated structurally invalid test data: {validation_err}"
        ) from validation_err

    logger.info(
        "TEST GENERATION COMPLETE — %d questions, %s total marks, duration %d min.",
        len(test_response.questions),
        test_response.total_marks,
        test_response.duration_minutes,
    )
    logger.info("=" * 70)

    return test_response


def generate_chapter_test_from_request(
    request: GenerateTestRequest,
) -> ChapterTestResponse:
    """
    Convenience wrapper that accepts a ``GenerateTestRequest`` Pydantic
    model and delegates to ``generate_chapter_test()``.
    """
    return generate_chapter_test(
        collection_name=request.collection_name,
        class_level=request.class_level,
        subject=request.subject,
        chapter_number=request.chapter_number,
        model=request.model,
    )
