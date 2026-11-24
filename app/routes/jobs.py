import io
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import anthropic
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import cover_letter, profiles, storage
from app.claude_client import analyze, generate_cover_letter, phrase_answer_as_bullet
from app.models import GapAnalysis, SuggestedEdit, TrackerEntry
from app.resume_apply import docx_inplace, docx_rebuild
from app.resume_ingest import docx_ingest, pdf_ingest
from app.summary import build_summary_markdown, compute_match_score

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_SOURCE_FORMATS = {"docx": "docx", "pdf": "pdf"}


class JobAnalysisResponse(BaseModel):
    job_id: str
    source_format: str
    gaps: list
    suggested_edits: list
    match_score_before: float
    company_name: str | None = None
    job_title: str | None = None


class AnswerItem(BaseModel):
    requirement: str
    answer: str


class AnswersRequest(BaseModel):
    answers: list[AnswerItem]


class ApplyRequest(BaseModel):
    accepted_edits: list[SuggestedEdit]
    include_resume: bool = True
    include_cover_letter: bool = False
    profile: str | None = None
    track_application: bool = False
    company_name: str | None = None
    job_title: str | None = None


def _extract_blocks(source_format: str, data: bytes):
    stream = io.BytesIO(data)
    if source_format == "docx":
        return docx_ingest.extract(stream)
    return pdf_ingest.extract(stream)


def _load_analysis(job_id: str) -> GapAnalysis:
    if not storage.exists(job_id, "analysis.json"):
        raise HTTPException(404, "Unknown job_id")
    return GapAnalysis.model_validate_json(storage.load_bytes(job_id, "analysis.json"))


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str


def _set_status(job_id: str, state: str, error: str | None = None) -> None:
    storage.save_bytes(job_id, "status.json", json.dumps({"state": state, "error": error}).encode("utf-8"))


def _dispatch_analysis(job_id: str, background: BackgroundTasks) -> None:
    """Start the slow Claude analysis without holding the HTTP request open.

    On Lambda the function invokes itself asynchronously (see
    app/lambda_handler.py) -- work left running after a response is frozen,
    so FastAPI background tasks can't be used there. Locally, a background
    task does the same job.
    """
    function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    if function_name:
        import boto3  # provided by the Lambda runtime

        boto3.client("lambda").invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps({"resume_tailor_task": "analyze", "job_id": job_id}).encode("utf-8"),
        )
    else:
        background.add_task(run_analysis, job_id)


def run_analysis(job_id: str) -> None:
    """Gap analysis for a job whose inputs are already stored. Records the outcome in status.json."""
    try:
        source_format = storage.load_bytes(job_id, "source_format.txt").decode("utf-8")
        data = storage.load_bytes(job_id, f"original.{source_format}")
        job_description = storage.load_bytes(job_id, "job_description.txt").decode("utf-8")
        analysis = analyze(_extract_blocks(source_format, data), job_description)
    except anthropic.APIError as exc:
        _set_status(job_id, "error", f"The AI analysis service failed: {exc.message}")
        return
    except Exception as exc:
        # Covers SDK-level failures raised before any HTTP call (e.g. no
        # ANTHROPIC_API_KEY configured), not just anthropic.APIError.
        _set_status(job_id, "error", f"The AI analysis service failed: {exc}")
        return

    storage.save_bytes(job_id, "analysis.json", analysis.model_dump_json().encode("utf-8"))
    _set_status(job_id, "done")


@router.post("", response_model=JobAcceptedResponse, status_code=202)
async def create_job(
    background: BackgroundTasks,
    profile: str = Form(...),
    job_description: str = Form(...),
    resume: UploadFile | None = File(None),
):
    if not profiles.is_valid_profile(profile):
        raise HTTPException(400, "Unknown profile")

    if resume is not None:
        filename = resume.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        source_format = _SOURCE_FORMATS.get(ext)
        if source_format is None:
            raise HTTPException(400, "Resume must be a .docx or .pdf file")
        data = await resume.read()
        profiles.save_default_resume(profile, filename, source_format, data)
    else:
        meta = profiles.default_resume_meta(profile)
        if not meta["exists"]:
            raise HTTPException(400, "No resume attached and no saved default resume for this profile")
        data, source_format = profiles.load_default_resume(profile)

    job_id = uuid.uuid4().hex

    # Parse up front (fast) so a bad file fails immediately instead of after polling
    try:
        blocks = _extract_blocks(source_format, data)
    except Exception as exc:
        raise HTTPException(422, f"Could not read this {source_format} file — it may be corrupt or password-protected.") from exc

    if not blocks:
        raise HTTPException(422, "No readable text found in this resume file.")

    storage.save_bytes(job_id, f"original.{source_format}", data)
    storage.save_bytes(job_id, "source_format.txt", source_format.encode("utf-8"))
    storage.save_bytes(job_id, "job_description.txt", job_description.encode("utf-8"))
    _set_status(job_id, "pending")

    _dispatch_analysis(job_id, background)
    return JobAcceptedResponse(job_id=job_id, status="pending")


@router.get("/{job_id}")
async def get_job(job_id: str):
    """Poll target: {"status": "pending"}, {"status": "error", "detail": ...}, or the full analysis."""
    if not storage.exists(job_id, "status.json"):
        raise HTTPException(404, "Unknown job_id")
    status = json.loads(storage.load_bytes(job_id, "status.json"))

    if status["state"] == "pending":
        return {"job_id": job_id, "status": "pending"}
    if status["state"] == "error":
        return {"job_id": job_id, "status": "error", "detail": status.get("error") or "Analysis failed"}

    analysis = _load_analysis(job_id)
    source_format = storage.load_bytes(job_id, "source_format.txt").decode("utf-8")
    return {
        "status": "done",
        **JobAnalysisResponse(
            job_id=job_id,
            source_format=source_format,
            gaps=[g.model_dump() for g in analysis.gaps],
            suggested_edits=[e.model_dump() for e in analysis.suggested_edits],
            match_score_before=compute_match_score(analysis),
            company_name=analysis.company_name,
            job_title=analysis.job_title,
        ).model_dump(),
    }


@router.post("/{job_id}/answers")
async def submit_answers(job_id: str, body: AnswersRequest):
    analysis = _load_analysis(job_id)
    answers_by_requirement = {a.requirement: a.answer for a in body.answers}

    to_phrase = []
    for edit in analysis.suggested_edits:
        if edit.requires_user_input and edit.related_gap in answers_by_requirement:
            answer = answers_by_requirement[edit.related_gap]
            gap = next((g for g in analysis.gaps if g.requirement == edit.related_gap), None)
            question = gap.question_to_user if gap else edit.related_gap
            to_phrase.append((edit, question, answer))

    # One small Claude call per answer -- run them side by side so several
    # answers don't add up past the CDN's 60s origin timeout.
    if to_phrase:
        with ThreadPoolExecutor(max_workers=min(8, len(to_phrase))) as pool:
            bullets = list(pool.map(lambda t: phrase_answer_as_bullet(t[0].related_gap, t[1], t[2]), to_phrase))
        for (edit, _, _), bullet in zip(to_phrase, bullets):
            edit.new_text = bullet
            edit.requires_user_input = False

    storage.save_bytes(job_id, "analysis.json", analysis.model_dump_json().encode("utf-8"))
    return {"job_id": job_id, "suggested_edits": [e.model_dump() for e in analysis.suggested_edits]}


@router.post("/{job_id}/apply")
async def apply_job(job_id: str, body: ApplyRequest):
    if not storage.exists(job_id, "source_format.txt"):
        raise HTTPException(404, "Unknown job_id")
    if not body.include_resume and not body.include_cover_letter:
        raise HTTPException(400, "Select at least one of: tailored resume, cover letter")

    source_format = storage.load_bytes(job_id, "source_format.txt").decode("utf-8")
    original = storage.load_bytes(job_id, f"original.{source_format}")
    analysis = _load_analysis(job_id)

    result: dict = {"job_id": job_id}

    if body.include_resume:
        output = io.BytesIO()
        if source_format == "docx":
            failed = docx_inplace.apply_edits(io.BytesIO(original), body.accepted_edits, output)
        else:
            blocks = pdf_ingest.extract(io.BytesIO(original))
            failed = docx_rebuild.build(blocks, body.accepted_edits, output)

        storage.save_bytes(job_id, "final.docx", output.getvalue())

        summary_markdown = build_summary_markdown(analysis, body.accepted_edits, failed)
        storage.save_bytes(job_id, "summary.md", summary_markdown.encode("utf-8"))

        result.update(
            failed_edit_ids=failed,
            download_url=f"/api/jobs/{job_id}/download",
            summary_markdown=summary_markdown,
            summary_download_url=f"/api/jobs/{job_id}/summary",
            match_score_before=compute_match_score(analysis),
            match_score_after=compute_match_score(analysis, body.accepted_edits, failed),
        )

    if body.include_cover_letter:
        job_description = storage.load_bytes(job_id, "job_description.txt").decode("utf-8")
        blocks = _extract_blocks(source_format, original)
        try:
            cover_letter_text = generate_cover_letter(blocks, job_description, body.accepted_edits)
        except anthropic.APIError as exc:
            raise HTTPException(502, f"The AI cover letter service failed: {exc.message}") from exc

        cover_letter_output = io.BytesIO()
        cover_letter.render_docx(cover_letter_text, cover_letter_output)
        storage.save_bytes(job_id, "cover_letter.docx", cover_letter_output.getvalue())

        result["cover_letter_download_url"] = f"/api/jobs/{job_id}/download-cover-letter"

    if body.track_application:
        if not body.profile or not profiles.is_valid_profile(body.profile):
            raise HTTPException(400, "A valid profile is required to track this application")
        profiles.append_tracker_entry(
            body.profile,
            TrackerEntry(
                job_id=job_id,
                company_name=body.company_name,
                job_title=body.job_title,
                tracked_at=datetime.now(timezone.utc).isoformat(),
                match_score_before=result.get("match_score_before"),
                match_score_after=result.get("match_score_after"),
            ),
        )

    return result


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


@router.get("/{job_id}/download-cover-letter")
async def download_cover_letter(job_id: str):
    if not storage.exists(job_id, "cover_letter.docx"):
        raise HTTPException(404, "No cover letter for this job_id yet")
    data = storage.load_bytes(job_id, "cover_letter.docx")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="cover_letter.docx"'},
    )


@router.get("/{job_id}/summary")
async def download_summary(job_id: str):
    if not storage.exists(job_id, "summary.md"):
        raise HTTPException(404, "No summary for this job_id yet")
    data = storage.load_bytes(job_id, "summary.md")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="resume_changes_summary.md"'},
    )
