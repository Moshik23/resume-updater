"""Shared test setup: Claude is always stubbed (no API key or network needed)."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")

from app.models import GapAnalysis  # noqa: E402

FAKE_ANALYSIS = GapAnalysis(
    extracted_requirements=[
        {"requirement": "Terraform", "category": "tool"},
        {"requirement": "Kubernetes", "category": "tool"},
    ],
    matches=[{"requirement": "Terraform", "block_id": "p5", "evidence": "Wrote Terraform modules"}],
    gaps=[{"requirement": "Kubernetes", "question_to_user": "Used Kubernetes?"}],
    suggested_edits=[
        {"edit_id": "e1", "block_id": "p6", "type": "replace_phrase", "anchor_text": "Azure DevOps",
         "new_text": "Azure DevOps and GitHub Actions", "rationale": "r"},
        {"edit_id": "e2", "block_id": "p5", "type": "append_bullet", "new_text": "", "rationale": "r",
         "requires_user_input": True, "related_gap": "Kubernetes"},
    ],
    company_name="Acme",
    job_title="Cloud Engineer",
)

JOB_DESCRIPTION = (ROOT / "samples" / "sample_job_description.txt").read_text()
RESUME = (ROOT / "samples" / "sample_resume.docx").read_bytes()


def fresh_app_modules():
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]


def stub_claude(jobs_module):
    jobs_module.analyze = lambda blocks, jd: FAKE_ANALYSIS.model_copy(deep=True)
    jobs_module.phrase_answer_as_bullet = lambda req, q, a: f"Did {a}"
    jobs_module.generate_cover_letter = lambda blocks, jd, edits: "Dear team,\n\nHello.\n\nRegards"


@pytest.fixture
def local_env(tmp_path, monkeypatch):
    """App in local mode (folders for storage, background task instead of self-invoke)."""
    for var in ["S3_BUCKET_NAME", "SSM_PREFIX", "ORIGIN_SECRET", "AWS_LAMBDA_FUNCTION_NAME", "SITE_PASSWORD", "USERS_JSON", "ANTHROPIC_API_KEY"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("LOCAL_PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.chdir(tmp_path)  # so a developer's .env isn't picked up
    fresh_app_modules()
    yield
    fresh_app_modules()
