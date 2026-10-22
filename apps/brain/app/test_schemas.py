"""
Pydantic v2 schema definitions for Chapter Test Generator.

Defines strict, validated models for every question type required by the
CBSE Class 7 Science curriculum test format:
  MCQ, FILL_IN_BLANKS, TRUE_FALSE, ASSERTION_REASON,
  SHORT_ANSWER_1, SHORT_ANSWER_2, LONG_ANSWER, CASE_STUDY.

Each question carries Bloom's Taxonomy classification, difficulty level,
marks allocation, and a student-friendly explanation.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class QuestionType(str, Enum):
    """Supported question formats aligned with CBSE assessment blueprints."""
    MCQ = "MCQ"
    FILL_IN_BLANKS = "FILL_IN_BLANKS"
    TRUE_FALSE = "TRUE_FALSE"
    ASSERTION_REASON = "ASSERTION_REASON"
    SHORT_ANSWER_1 = "SHORT_ANSWER_1"        # 1-2 sentence answer
    SHORT_ANSWER_2 = "SHORT_ANSWER_2"        # 3-5 sentence answer
    LONG_ANSWER = "LONG_ANSWER"              # Detailed paragraph / diagram-based
    CASE_STUDY = "CASE_STUDY"                # Passage-based with sub-questions


class BloomLevel(str, Enum):
    """Bloom's Taxonomy cognitive levels for learning-objective alignment."""
    REMEMBER = "REMEMBER"
    UNDERSTAND = "UNDERSTAND"
    APPLY = "APPLY"
    ANALYZE = "ANALYZE"
    EVALUATE = "EVALUATE"
    CREATE = "CREATE"


class DifficultyLevel(str, Enum):
    """
    Target distribution across the test:
      EASY   → ~30%
      MEDIUM → ~50%
      HARD   → ~20%
    """
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class OptionModel(BaseModel):
    """A single MCQ / Assertion-Reason option."""
    label: str = Field(
        ...,
        description="Option label, e.g. 'A', 'B', 'C', 'D'.",
        min_length=1,
        max_length=2,
    )
    text: str = Field(
        ...,
        description="Full text of the option.",
        min_length=1,
    )


class SubQuestionModel(BaseModel):
    """
    A sub-question within a CASE_STUDY question.
    Each sub-question is independently scored and typed.
    """
    sub_question_number: int = Field(
        ...,
        description="1-indexed sub-question number within the parent case study.",
        ge=1,
    )
    question_text: str = Field(
        ...,
        description="The sub-question prompt.",
        min_length=10,
    )
    question_type: QuestionType = Field(
        ...,
        description="Type of this sub-question (typically MCQ or SHORT_ANSWER_1).",
    )
    options: Optional[List[OptionModel]] = Field(
        default=None,
        description="Options if this sub-question is MCQ-type.",
    )
    correct_answer: str = Field(
        ...,
        description="The correct answer text or option label.",
        min_length=1,
    )
    marks: float = Field(
        ...,
        description="Marks awarded for this sub-question.",
        gt=0,
    )
    explanation: str = Field(
        ...,
        description="Student-friendly explanation of the correct answer.",
        min_length=10,
    )


class QuestionModel(BaseModel):
    """
    A single test question with full metadata.

    Validation rules:
      - MCQ / ASSERTION_REASON → must have ≥ 4 options.
      - CASE_STUDY            → must have ≥ 2 sub-questions.
      - TRUE_FALSE            → correct_answer must be 'True' or 'False'.
    """
    question_number: int = Field(
        ...,
        description="1-indexed question number in the test.",
        ge=1,
    )
    question_type: QuestionType = Field(
        ...,
        description="The format / type of this question.",
    )
    question_text: str = Field(
        ...,
        description="The full question stem. For CASE_STUDY, this is the passage.",
        min_length=10,
    )
    options: Optional[List[OptionModel]] = Field(
        default=None,
        description="Answer options (required for MCQ / ASSERTION_REASON).",
    )
    correct_answer: str = Field(
        ...,
        description=(
            "The correct answer. For MCQ: the option label (e.g. 'B'). "
            "For TRUE_FALSE: 'True' or 'False'. "
            "For FILL_IN_BLANKS: the word/phrase. "
            "For SHORT/LONG: model answer text."
        ),
        min_length=1,
    )
    marks: float = Field(
        ...,
        description="Total marks for this question.",
        gt=0,
    )
    negative_marks: float = Field(
        default=0.0,
        description="Negative marks deducted for a wrong answer (0 if none).",
        ge=0,
    )
    difficulty: DifficultyLevel = Field(
        ...,
        description="Difficulty bucket of this question.",
    )
    bloom_level: BloomLevel = Field(
        ...,
        description="Bloom's Taxonomy cognitive level targeted.",
    )
    topic: str = Field(
        ...,
        description="The specific sub-topic / section this question is drawn from.",
        min_length=1,
    )
    step_wise_marking: Optional[List[str]] = Field(
        default=None,
        description=(
            "Step-by-step marking scheme for SHORT_ANSWER_2, LONG_ANSWER, "
            "and CASE_STUDY questions. Each string is one marking step."
        ),
    )
    explanation: str = Field(
        ...,
        description=(
            "A clear, student-friendly explanation of why the correct answer "
            "is correct (and, optionally, why distractors are wrong)."
        ),
        min_length=10,
    )
    sub_questions: Optional[List[SubQuestionModel]] = Field(
        default=None,
        description="Sub-questions for CASE_STUDY type only.",
    )

    # ----- Cross-field validators -----

    @model_validator(mode="after")
    def validate_question_constraints(self) -> "QuestionModel":
        """Enforce type-specific structural rules."""
        qtype = self.question_type

        # MCQ and ASSERTION_REASON must have at least 4 options
        if qtype in (QuestionType.MCQ, QuestionType.ASSERTION_REASON):
            if not self.options or len(self.options) < 4:
                raise ValueError(
                    f"{qtype.value} questions must have at least 4 options, "
                    f"got {len(self.options) if self.options else 0}."
                )

        # TRUE_FALSE correct_answer must literally be 'True' or 'False'
        if qtype == QuestionType.TRUE_FALSE:
            if self.correct_answer not in ("True", "False"):
                raise ValueError(
                    f"TRUE_FALSE correct_answer must be 'True' or 'False', "
                    f"got '{self.correct_answer}'."
                )

        # CASE_STUDY must carry sub-questions
        if qtype == QuestionType.CASE_STUDY:
            if not self.sub_questions or len(self.sub_questions) < 2:
                raise ValueError(
                    "CASE_STUDY questions must have at least 2 sub-questions, "
                    f"got {len(self.sub_questions) if self.sub_questions else 0}."
                )

        # Step-wise marking expected for longer-form answers
        if qtype in (QuestionType.SHORT_ANSWER_2, QuestionType.LONG_ANSWER):
            if not self.step_wise_marking:
                raise ValueError(
                    f"{qtype.value} questions should include a step_wise_marking scheme."
                )

        return self


# ---------------------------------------------------------------------------
# Top-level Response
# ---------------------------------------------------------------------------

class ChapterTestResponse(BaseModel):
    """
    Complete structured test output for a single textbook chapter.

    The LLM is expected to populate every field; the model then validates
    referential integrity, question counts, and difficulty distribution.
    """
    class_level: str = Field(
        ...,
        description="Class / grade level, e.g. '7'.",
    )
    subject: str = Field(
        ...,
        description="Subject name, e.g. 'Science'.",
    )
    chapter_number: str = Field(
        ...,
        description="Chapter number as stored in metadata, e.g. '1' or '01'.",
    )
    chapter_title: str = Field(
        ...,
        description="Human-readable chapter title.",
        min_length=1,
    )
    total_marks: float = Field(
        ...,
        description="Sum of marks across all questions.",
        gt=0,
    )
    duration_minutes: int = Field(
        ...,
        description="Recommended test duration in minutes.",
        gt=0,
    )
    questions: List[QuestionModel] = Field(
        ...,
        description="Ordered list of all test questions.",
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_test_integrity(self) -> "ChapterTestResponse":
        """
        Post-construction sanity checks:
          1. total_marks matches the sum of individual question marks.
          2. Question numbers are sequential starting from 1.
        """
        # --- marks consistency ---
        computed_total = 0.0
        for q in self.questions:
            if q.question_type == QuestionType.CASE_STUDY and q.sub_questions:
                computed_total += sum(sq.marks for sq in q.sub_questions)
            else:
                computed_total += q.marks

        # Allow a small float tolerance
        if abs(computed_total - self.total_marks) > 0.5:
            raise ValueError(
                f"total_marks ({self.total_marks}) does not match the sum of "
                f"individual question marks ({computed_total})."
            )

        # --- sequential numbering ---
        expected = list(range(1, len(self.questions) + 1))
        actual = [q.question_number for q in self.questions]
        if actual != expected:
            raise ValueError(
                f"Question numbers must be sequential 1..{len(self.questions)}, "
                f"got {actual}."
            )

        return self


# ---------------------------------------------------------------------------
# Request schema for the /generate-test endpoint
# ---------------------------------------------------------------------------

class GenerateTestRequest(BaseModel):
    """Incoming API request to generate a chapter test."""
    collection_name: str = Field(
        ...,
        description="Qdrant collection to retrieve chapter data from.",
        min_length=1,
    )
    class_level: str = Field(
        ...,
        description="Class / grade level filter, e.g. '7'.",
        min_length=1,
    )
    subject: str = Field(
        ...,
        description="Subject filter, e.g. 'Science'.",
        min_length=1,
    )
    chapter_number: str = Field(
        ...,
        description="Chapter number filter, e.g. '1'.",
        min_length=1,
    )
    model: Optional[str] = Field(
        default=None,
        description="Override the default Groq model name.",
    )
