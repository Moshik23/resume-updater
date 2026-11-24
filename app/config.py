import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    site_password: str = ""

    # AWS (all optional -- leave unset for zero-cloud local development)
    s3_bucket_name: str | None = None      # job artifacts + profiles; local folders when unset
    ssm_prefix: str | None = None          # e.g. /resume-tailor -- secrets are read from SSM at cold start
    origin_secret: str = ""                # CloudFront-only header; blocks direct calls to the function URL

    local_storage_dir: str = ".local_jobs"
    local_profiles_dir: str = ".local_profiles"


settings = Settings()


def _load_ssm_secrets() -> None:
    """Pull the API key and site password from SSM Parameter Store (SecureString).

    They're created out-of-band (never in Terraform state) under the prefix,
    and only read once per Lambda cold start.
    """
    import boto3  # provided by the Lambda runtime

    names = {
        f"{settings.ssm_prefix}/anthropic-api-key": "anthropic_api_key",
        f"{settings.ssm_prefix}/site-password": "site_password",
    }
    resp = boto3.client("ssm").get_parameters(Names=list(names), WithDecryption=True)
    missing = set(names) - {p["Name"] for p in resp["Parameters"]}
    if missing:
        raise RuntimeError(f"Missing SSM parameters: {sorted(missing)}")
    for p in resp["Parameters"]:
        setattr(settings, names[p["Name"]], p["Value"])


if settings.ssm_prefix and not os.environ.get("RESUME_TAILOR_SKIP_SSM"):
    _load_ssm_secrets()
