from typing import Literal

from pydantic import BaseModel


class ContentBlock(BaseModel):
    """One addressable chunk of resume text, extracted by either ingest path."""

    id: str
    text: str
    style_name: str | None = None


class ExtractedRequirement(BaseModel):
    requirement: str
    category: Literal["skill", "tool", "certification", "experience", "soft_skill"]


class RequirementMatch(BaseModel):
    requirement: str
    block_id: str
    evidence: str


class GapQuestion(BaseModel):
    requirement: str
    question_to_user: str


class SuggestedEdit(BaseModel):
    edit_id: str
    block_id: str
    type: Literal["replace_phrase", "insert_keyword", "append_bullet", "new_bullet_after"]
    anchor_text: str | None = None
    new_text: str
    rationale: str
    requires_user_input: bool = False
    related_gap: str | None = None


class GapAnalysis(BaseModel):
    extracted_requirements: list[ExtractedRequirement]
    matches: list[RequirementMatch]
    gaps: list[GapQuestion]
    suggested_edits: list[SuggestedEdit]
    company_name: str | None = None
    job_title: str | None = None


class TrackerEntry(BaseModel):
    job_id: str
    company_name: str | None = None
    job_title: str | None = None
    tracked_at: str
    match_score_before: float | None = None
    match_score_after: float | None = None


class JobState(BaseModel):
    job_id: str
    source_format: Literal["docx", "pdf"]
    analysis: GapAnalysis
