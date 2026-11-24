import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    claude_fast_model: str = "claude-haiku-4-5"   # small steps (phrasing a gap answer as a bullet)
    site_password: str = ""                       # legacy shared password (anyone can pick any profile)
    users_json: str = ""                          # {"moshik": "pw", "indhu": "pw", ...}: per-person logins

    # AWS (all optional -- leave unset for zero-cloud local development)
    s3_bucket_name: str | None = None      # job artifacts + profiles; local folders when unset
    ssm_prefix: str | None = None          # e.g. /resume-tailor -- secrets are read from SSM at cold start
    origin_secret: str = ""                # CloudFront-only header; blocks direct calls to the function URL

    local_storage_dir: str = ".local_jobs"
    local_profiles_dir: str = ".local_profiles"


settings = Settings()


def users() -> dict[str, str]:
    """Per-person logins (lower-case profile name -> password). Empty = legacy shared password."""
    import json

    if not settings.users_json:
        return {}
    data = json.loads(settings.users_json)
    return {str(k).strip().lower(): str(v) for k, v in data.items() if v}


def _load_ssm_secrets() -> None:
    """Pull the API key and site password from SSM Parameter Store (SecureString).

    They're created out-of-band (never in Terraform state) under the prefix,
    and only read once per Lambda cold start. `users` (per-person logins, a
    JSON object) is optional; without it the shared site password applies.
    """
    import boto3  # provided by the Lambda runtime

    names = {
        f"{settings.ssm_prefix}/anthropic-api-key": "anthropic_api_key",
        f"{settings.ssm_prefix}/site-password": "site_password",
        f"{settings.ssm_prefix}/users": "users_json",
    }
    required = {f"{settings.ssm_prefix}/anthropic-api-key"}
    resp = boto3.client("ssm").get_parameters(Names=list(names), WithDecryption=True)
    found = {p["Name"] for p in resp["Parameters"]}
    missing = required - found
    if missing:
        raise RuntimeError(f"Missing SSM parameters: {sorted(missing)}")
    if f"{settings.ssm_prefix}/site-password" not in found and f"{settings.ssm_prefix}/users" not in found:
        raise RuntimeError("Need SSM parameter site-password or users so the site isn't left open")
    for p in resp["Parameters"]:
        setattr(settings, names[p["Name"]], p["Value"])


if settings.ssm_prefix and not os.environ.get("RESUME_TAILOR_SKIP_SSM"):
    _load_ssm_secrets()
