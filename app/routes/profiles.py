from fastapi import APIRouter, HTTPException

from app import profiles

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("")
async def list_profiles():
    return [{"value": p, "label": profiles.PROFILE_LABELS[p]} for p in profiles.PROFILES]


@router.get("/{profile}/default-resume-meta")
async def default_resume_meta(profile: str):
    if not profiles.is_valid_profile(profile):
        raise HTTPException(404, "Unknown profile")
    return profiles.default_resume_meta(profile)


@router.get("/{profile}/tracker")
async def tracker(profile: str):
    if not profiles.is_valid_profile(profile):
        raise HTTPException(404, "Unknown profile")
    entries = profiles.load_tracker(profile)
    entries.sort(key=lambda e: e["tracked_at"], reverse=True)
    return entries
