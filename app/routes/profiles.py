from fastapi import APIRouter, HTTPException, Request

from app import profiles
from app.auth import resolve_profile
from app.resume_ingest import docx_ingest, pdf_ingest

router = APIRouter(prefix="/api", tags=["profiles"])


@router.get("/me")
async def me(request: Request):
    """Who's signed in. `locked` = per-person login, so the page hides the profile picker."""
    signed_in = getattr(request.state, "profile", None)
    return {
        "profile": signed_in,
        "label": profiles.label(signed_in) if signed_in else None,
        "locked": bool(signed_in),
        "profiles": [] if signed_in else [{"value": p, "label": profiles.label(p)} for p in profiles.PROFILES],
    }


@router.get("/profiles")
async def list_profiles(request: Request):
    signed_in = getattr(request.state, "profile", None)
    names = [signed_in] if signed_in else profiles.PROFILES
    return [{"value": p, "label": profiles.label(p)} for p in names]


@router.get("/profiles/{profile}/default-resume-meta")
async def default_resume_meta(profile: str, request: Request):
    profile = resolve_profile(request, profile)
    return profiles.default_resume_meta(profile)


@router.get("/profiles/{profile}/default-resume-preview")
async def default_resume_preview(profile: str, request: Request):
    """The saved resume's text blocks, so the page can show it as a sheet of paper."""
    profile = resolve_profile(request, profile)
    if not profiles.default_resume_meta(profile)["exists"]:
        raise HTTPException(404, "No saved resume")
    import io

    data, source_format = profiles.load_default_resume(profile)
    extractor = docx_ingest if source_format == "docx" else pdf_ingest
    try:
        blocks = extractor.extract(io.BytesIO(data))
    except Exception as exc:
        raise HTTPException(422, "Couldn't read the saved resume") from exc
    return {"blocks": [b.model_dump() for b in blocks], "source_format": source_format}


@router.get("/profiles/{profile}/tracker")
async def tracker(profile: str, request: Request):
    profile = resolve_profile(request, profile)
    entries = profiles.load_tracker(profile)
    entries.sort(key=lambda e: e["tracked_at"], reverse=True)
    return entries
