"""Calls Claude to analyze a resume against a job description.

Uses a forced tool-use call so the response is schema-validated by the API
rather than hand-parsed JSON, and marks the (static) system prompt for
prompt-caching since it's identical across every job.
"""

import json

import anthropic

from app.config import settings
from app.models import ContentBlock, GapAnalysis

_SYSTEM_PROMPT = """\
You are an ATS (Applicant Tracking System) resume analyst. You are given a \
resume broken into addressable content blocks, and a job description. Your job:

1. Extract the concrete requirements from the job description (skills, tools, \
certifications, years of experience, soft skills).
2. For each requirement, find matching evidence in the resume's content blocks, \
citing the block id.
3. For requirements with no evidence in the resume, produce a gap: a short, \
direct question to ask the candidate so they can supply the missing information \
(e.g. "Do you have hands-on experience with X? If so, briefly describe it.").
4. Identify the hiring company's name and the job title/role, if the job \
description states them plainly. Leave either as null rather than guessing if \
it isn't clearly stated.
5. Propose suggested_edits that would improve ATS match: inserting missing \
keywords into existing bullets (replace_phrase / insert_keyword, anchored to an \
exact substring of the block's text), or adding a new bullet after a block \
(append_bullet / new_bullet_after). Never invent experience the resume doesn't \
support — edits should rephrase/surface what's already true, or be flagged with \
requires_user_input=true and linked to a gap via related_gap so the user can \
supply the missing fact first.

Only edit paragraphs that are clearly resume content (skills, experience \
bullets, summary) — do not touch section headers or contact information unless \
the job description specifically requires a certification/credential line to \
be added there.
"""

_TOOL_SCHEMA = {
    "name": "submit_gap_analysis",
    "description": "Submit the extracted JD requirements, resume/JD gaps, and suggested ATS-improving edits.",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_name": {"type": ["string", "null"]},
            "job_title": {"type": ["string", "null"]},
            "extracted_requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["skill", "tool", "certification", "experience", "soft_skill"],
                        },
                    },
                    "required": ["requirement", "category"],
                },
            },
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement": {"type": "string"},
                        "block_id": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["requirement", "block_id", "evidence"],
                },
            },
            "gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement": {"type": "string"},
                        "question_to_user": {"type": "string"},
                    },
                    "required": ["requirement", "question_to_user"],
                },
            },
            "suggested_edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "edit_id": {"type": "string"},
                        "block_id": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["replace_phrase", "insert_keyword", "append_bullet", "new_bullet_after"],
                        },
                        "anchor_text": {"type": ["string", "null"]},
                        "new_text": {"type": "string"},
                        "rationale": {"type": "string"},
                        "requires_user_input": {"type": "boolean"},
                        "related_gap": {"type": ["string", "null"]},
                    },
                    "required": ["edit_id", "block_id", "type", "new_text", "rationale"],
                },
            },
        },
        "required": ["extracted_requirements", "matches", "gaps", "suggested_edits"],
    },
}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key or None)


def analyze(blocks: list[ContentBlock], job_description: str) -> GapAnalysis:
    resume_json = json.dumps([b.model_dump() for b in blocks])

    response = _client().messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "submit_gap_analysis"},
        messages=[
            {
                "role": "user",
                "content": f"RESUME CONTENT BLOCKS (JSON):\n{resume_json}\n\nJOB DESCRIPTION:\n{job_description}",
            }
        ],
    )

    tool_use = next(block for block in response.content if block.type == "tool_use")
    return GapAnalysis.model_validate(tool_use.input)


def phrase_answer_as_bullet(gap_requirement: str, question: str, user_answer: str) -> str:
    """Turn a raw user answer to a gap question into one well-phrased resume bullet."""
    response = _client().messages.create(
        model=settings.claude_model,
        max_tokens=256,
        system=(
            "Turn the user's raw answer into a single, concise, resume-style bullet "
            "point (no more than one sentence, no leading bullet character). "
            "Only use facts the user actually stated — do not embellish."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Missing requirement: {gap_requirement}\n"
                    f"Question asked: {question}\n"
                    f"User's answer: {user_answer}"
                ),
            }
        ],
    )
    text_block = next(block for block in response.content if block.type == "text")
    return text_block.text.strip()


_COVER_LETTER_SYSTEM_PROMPT = """\
You write concise, professional cover letters. You are given a candidate's \
resume content blocks and a job description. Write a cover letter (3-4 short \
paragraphs, no more than ~300 words) that connects the candidate's real, \
stated experience to the job's requirements.

Rules:
- Only use facts present in the resume content blocks — never invent \
experience, employers, dates, or skills.
- Address it "Dear Hiring Manager," unless the job description names an \
actual hiring manager or recruiter.
- No placeholder brackets (e.g. "[Company Name]") — if you don't know a \
detail, omit the sentence rather than leaving a placeholder.
- Plain text output: paragraphs separated by a single blank line, no \
markdown formatting, no subject line, no signature block beyond "Sincerely,".
"""


def generate_cover_letter(
    blocks: list[ContentBlock], job_description: str, accepted_edits: list | None = None
) -> str:
    resume_json = json.dumps([b.model_dump() for b in blocks])
    accepted_facts = "\n".join(f"- {e.new_text}" for e in (accepted_edits or []))

    user_content = f"RESUME CONTENT BLOCKS (JSON):\n{resume_json}\n\nJOB DESCRIPTION:\n{job_description}"
    if accepted_facts:
        user_content += f"\n\nADDITIONAL CONFIRMED FACTS (from candidate's own answers):\n{accepted_facts}"

    response = _client().messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=_COVER_LETTER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    text_block = next(block for block in response.content if block.type == "text")
    return text_block.text.strip()
