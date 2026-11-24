"""Job artifact storage: Amazon S3 when configured, a local directory otherwise
(so local development needs zero cloud dependency).

Two prefixes in one bucket: `jobs/` (ephemeral -- expired after 2 days by an
S3 lifecycle rule, see terraform/storage.tf) and `profiles/` (persistent --
per-named-profile default resume + application tracker, never auto-deleted).
"""

from functools import lru_cache
from pathlib import Path

from app.config import settings


def _use_s3() -> bool:
    return bool(settings.s3_bucket_name)


@lru_cache(maxsize=1)
def _s3():
    import boto3  # provided by the Lambda runtime

    return boto3.client("s3")


def _key(container: str, path: str) -> str:
    return f"{container}/{path}"


def _local_root(container: str) -> Path:
    return Path(settings.local_storage_dir) if container == "jobs" else Path(settings.local_profiles_dir)


def _local_path(container: str, path: str) -> Path:
    full = _local_root(container) / path
    full.parent.mkdir(parents=True, exist_ok=True)
    return full


def _save(container: str, path: str, data: bytes) -> None:
    if _use_s3():
        _s3().put_object(Bucket=settings.s3_bucket_name, Key=_key(container, path), Body=data)
    else:
        _local_path(container, path).write_bytes(data)


def _load(container: str, path: str) -> bytes:
    if _use_s3():
        obj = _s3().get_object(Bucket=settings.s3_bucket_name, Key=_key(container, path))
        return obj["Body"].read()
    return _local_path(container, path).read_bytes()


def _exists(container: str, path: str) -> bool:
    if _use_s3():
        from botocore.exceptions import ClientError

        try:
            _s3().head_object(Bucket=settings.s3_bucket_name, Key=_key(container, path))
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
    return _local_path(container, path).exists()


def save_bytes(job_id: str, name: str, data: bytes) -> None:
    _save("jobs", f"{job_id}/{name}", data)


def load_bytes(job_id: str, name: str) -> bytes:
    return _load("jobs", f"{job_id}/{name}")


def exists(job_id: str, name: str) -> bool:
    return _exists("jobs", f"{job_id}/{name}")


def save_profile_bytes(profile: str, name: str, data: bytes) -> None:
    _save("profiles", f"{profile}/{name}", data)


def load_profile_bytes(profile: str, name: str) -> bytes:
    return _load("profiles", f"{profile}/{name}")


def profile_exists(profile: str, name: str) -> bool:
    return _exists("profiles", f"{profile}/{name}")
