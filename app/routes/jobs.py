import io
import uuid

import anthropic
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import storage
from app.claude_client import analyze, phrase_answer_as_bullet
from app.models import GapAnalysis, SuggestedEdit
from app.resume_apply import docx_inplace, docx_rebuild
from app.resume_ingest import docx_ingest, pdf_ingest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_SOURCE_FORMATS = {"docx": "docx", "pdf": "pdf"}


class JobAnalysisResponse(BaseModel):
    job_id: str
    source_format: str
    gaps: list
    suggested_edits: list


class AnswerItem(BaseModel):
    requirement: str
    answer: str


class AnswersRequest(BaseModel):
    answers: list[AnswerItem]


class ApplyRequest(BaseModel):
    accepted_edits: list[SuggestedEdit]


def _extract_blocks(source_format: str, data: bytes):
    stream = io.BytesIO(data)
    if source_format == "docx":
        return docx_ingest.extract(stream)
    return pdf_ingest.extract(stream)


def _load_analysis(job_id: str) -> GapAnalysis:
    if not storage.exists(job_id, "analysis.json"):
        raise HTTPException(404, "Unknown job_id")
    return GapAnalysis.model_validate_json(storage.load_bytes(job_id, "analysis.json"))


@router.post("", response_model=JobAnalysisResponse)
async def create_job(resume: UploadFile = File(...), job_description: str = Form(...)):
    filename = resume.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    source_format = _SOURCE_FORMATS.get(ext)
    if source_format is None:
        raise HTTPException(400, "Resume must be a .docx or .pdf file")

    data = await resume.read()
    job_id = uuid.uuid4().hex

    try:
        blocks = _extract_blocks(source_format, data)
    except Exception as exc:
        raise HTTPException(422, f"Could not read this {source_format} file — it may be corrupt or password-protected.") from exc

    if not blocks:
        raise HTTPException(422, "No readable text found in this resume file.")

    try:
        analysis = analyze(blocks, job_description)
    except anthropic.APIError as exc:
        raise HTTPException(502, f"The AI analysis service failed: {exc.message}") from exc
    except Exception as exc:
        # Covers SDK-level failures raised before any HTTP call (e.g. no
        # ANTHROPIC_API_KEY configured), not just anthropic.APIError.
        raise HTTPException(502, f"The AI analysis service failed: {exc}") from exc

    storage.save_bytes(job_id, f"original.{source_format}", data)
    storage.save_bytes(job_id, "source_format.txt", source_format.encode("utf-8"))
    storage.save_bytes(job_id, "analysis.json", analysis.model_dump_json().encode("utf-8"))

    return JobAnalysisResponse(
        job_id=job_id,
        source_format=source_format,
        gaps=[g.model_dump() for g in analysis.gaps],
        suggested_edits=[e.model_dump() for e in analysis.suggested_edits],
    )


@router.post("/{job_id}/answers")
async def submit_answers(job_id: str, body: AnswersRequest):
    analysis = _load_analysis(job_id)
    answers_by_requirement = {a.requirement: a.answer for a in body.answers}

    for edit in analysis.suggested_edits:
        if edit.requires_user_input and edit.related_gap in answers_by_requirement:
            answer = answers_by_requirement[edit.related_gap]
            gap = next((g for g in analysis.gaps if g.requirement == edit.related_gap), None)
            question = gap.question_to_user if gap else edit.related_gap
            edit.new_text = phrase_answer_as_bullet(edit.related_gap, question, answer)
            edit.requires_user_input = False

    storage.save_bytes(job_id, "analysis.json", analysis.model_dump_json().encode("utf-8"))
    return {"job_id": job_id, "suggested_edits": [e.model_dump() for e in analysis.suggested_edits]}


@router.post("/{job_id}/apply")
async def apply_job(job_id: str, body: ApplyRequest):
    if not storage.exists(job_id, "source_format.txt"):
        raise HTTPException(404, "Unknown job_id")

    source_format = storage.load_bytes(job_id, "source_format.txt").decode("utf-8")
    original = storage.load_bytes(job_id, f"original.{source_format}")

    output = io.BytesIO()
    if source_format == "docx":
        failed = docx_inplace.apply_edits(io.BytesIO(original), body.accepted_edits, output)
    else:
        blocks = pdf_ingest.extract(io.BytesIO(original))
        failed = docx_rebuild.build(blocks, body.accepted_edits, output)

    storage.save_bytes(job_id, "final.docx", output.getvalue())
    return {
        "job_id": job_id,
        "failed_edit_ids": failed,
        "download_url": f"/api/jobs/{job_id}/download",
    }


@router.get("/{job_id}/download")
async def download_job(job_id: str):
    if not storage.exists(job_id, "final.docx"):
        raise HTTPException(404, "No final resume for this job_id yet")
    data = storage.load_bytes(job_id, "final.docx")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="tailored_resume.docx"'},
    )
