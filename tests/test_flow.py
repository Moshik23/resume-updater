"""End-to-end API flow with Claude stubbed: local mode, per-person logins, and AWS mode (moto)."""
import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from tests.conftest import JOB_DESCRIPTION, RESUME, fresh_app_modules, stub_claude


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def run_flow(client, headers, profile="guest"):
    r = client.post("/api/jobs", data={"profile": profile, "job_description": JOB_DESCRIPTION},
                    files={"resume": ("cv.docx", RESUME)}, headers=headers)
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert r.json()["block_count"] > 5

    for _ in range(50):
        body = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if body["status"] != "pending":
            break
        time.sleep(0.05)
    assert body["status"] == "done", body
    assert body["company_name"] == "Acme"
    assert body["blocks"] and body["requirement_count"] == 2
    assert body["match_score_before"] == 50.0

    r = client.post(f"/api/jobs/{job_id}/answers", json={"answers": [{"requirement": "Kubernetes", "answer": "EKS"}]}, headers=headers)
    edits = r.json()["suggested_edits"]
    assert edits[1]["new_text"] == "Did EKS" and not edits[1]["requires_user_input"]

    r = client.post(f"/api/jobs/{job_id}/apply", headers=headers, json={
        "accepted_edits": edits, "include_resume": True, "include_cover_letter": True,
        "track_application": True, "company_name": "Acme", "job_title": "Cloud Engineer"})
    assert r.status_code == 200, r.text
    assert r.json()["match_score_after"] == 100.0
    assert client.get(r.json()["download_url"], headers=headers).status_code == 200
    assert client.get(r.json()["cover_letter_download_url"], headers=headers).status_code == 200
    return job_id


def test_local_flow(local_env):
    import app.routes.jobs as jobs
    stub_claude(jobs)
    from app.main import app
    client = TestClient(app)
    run_flow(client, {})
    tracker = client.get("/api/profiles/guest/tracker").json()
    assert tracker[0]["company_name"] == "Acme"
    preview = client.get("/api/profiles/guest/default-resume-preview").json()
    assert preview["source_format"] == "docx" and preview["blocks"]


def test_input_limits(local_env):
    import app.routes.jobs as jobs
    stub_claude(jobs)
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/jobs", data={"profile": "guest", "job_description": "too short"}, files={"resume": ("cv.docx", RESUME)})
    assert r.status_code == 400 and "too short" in r.json()["detail"]
    r = client.post("/api/jobs", data={"profile": "guest", "job_description": "x" * 20_001}, files={"resume": ("cv.docx", RESUME)})
    assert r.status_code == 400
    r = client.post("/api/jobs", data={"profile": "guest", "job_description": JOB_DESCRIPTION}, files={"resume": ("cv.docx", b"0" * (4 * 1024 * 1024 + 1))})
    assert r.status_code == 413
    r = client.post("/api/jobs", data={"profile": "guest", "job_description": JOB_DESCRIPTION}, files={"resume": ("cv.txt", b"hi")})
    assert r.status_code == 400


def test_per_person_logins(local_env, monkeypatch):
    monkeypatch.setenv("USERS_JSON", json.dumps({"moshik": "pw-m", "indhu": "pw-i"}))
    fresh_app_modules()
    import app.routes.jobs as jobs
    stub_claude(jobs)
    from app.main import app
    client = TestClient(app)

    assert client.get("/").status_code == 401
    assert client.get("/", headers=basic("indhu", "pw-m")).status_code == 401  # someone else's password
    assert client.get("/", headers=basic("nobody", "pw-m")).status_code == 401
    me = client.get("/api/me", headers=basic("Indhu", "pw-i")).json()
    assert me == {"profile": "indhu", "label": "Indhu", "locked": True, "profiles": []}

    indhu, moshik = basic("indhu", "pw-i"), basic("moshik", "pw-m")
    job_id = run_flow(client, indhu, profile="indhu")
    # Moshik can't see Indhu's job, resume or tracker
    assert client.get(f"/api/jobs/{job_id}", headers=moshik).status_code == 404
    assert client.get(f"/api/jobs/{job_id}/download", headers=moshik).status_code == 404
    assert client.get("/api/profiles/indhu/tracker", headers=moshik).status_code == 403
    assert client.get("/api/profiles/indhu/default-resume-meta", headers=moshik).status_code == 403
    assert client.get("/api/profiles/indhu/tracker", headers=indhu).json()[0]["company_name"] == "Acme"
    assert client.get("/logout", headers=indhu).status_code == 401


def test_aws_mode(monkeypatch):
    """S3 storage, SSM secrets, async self-invocation through the Lambda handler, origin secret."""
    moto = pytest.importorskip("moto")
    import boto3

    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket="rt-test-bucket", CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"})
        ssm = boto3.client("ssm")
        ssm.put_parameter(Name="/rt/anthropic-api-key", Value="sk-test", Type="SecureString")
        ssm.put_parameter(Name="/rt/site-password", Value="pw", Type="SecureString")
        for k, v in {"S3_BUCKET_NAME": "rt-test-bucket", "SSM_PREFIX": "/rt", "ORIGIN_SECRET": "os", "AWS_LAMBDA_FUNCTION_NAME": "fn"}.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("USERS_JSON", raising=False)
        fresh_app_modules()

        import app.config as cfg
        assert cfg.settings.site_password == "pw" and cfg.settings.anthropic_api_key == "sk-test"
        import app.routes.jobs as jobs
        stub_claude(jobs)
        import app.lambda_handler as lh

        class FakeLambda:
            def invoke(self, FunctionName, InvocationType, Payload):
                assert FunctionName == "fn" and InvocationType == "Event"
                lh.handler(json.loads(Payload), None)

        real_client = boto3.client
        monkeypatch.setattr(boto3, "client", lambda svc, *a, **k: FakeLambda() if svc == "lambda" else real_client(svc, *a, **k))

        client = TestClient(lh.app)
        assert client.get("/healthz").status_code == 403  # no origin secret = not via CloudFront
        assert client.get("/healthz", headers={"x-origin-secret": "os"}).status_code == 200
        assert client.get("/", headers={"x-origin-secret": "os"}).status_code == 401
        headers = {**basic("x", "pw"), "x-origin-secret": "os"}
        job_id = run_flow(client, headers)
        keys = [o["Key"] for o in real_client("s3").list_objects_v2(Bucket="rt-test-bucket")["Contents"]]
        assert any(k.startswith(f"jobs/{job_id}/") for k in keys)
        assert any(k.startswith("profiles/guest/") for k in keys)
    fresh_app_modules()
