"""Job artifact storage: Azure Blob Storage when configured, a local temp
directory otherwise (so Phase 0/1 development needs zero Azure dependency).

Two containers: `jobs` (ephemeral -- 2-day lifecycle-deleted job artifacts,
see terraform/storage.tf) and `profiles` (persistent -- per-named-profile
default resume + application tracker, never auto-deleted).
"""

from pathlib import Path

from app.config import settings


def _use_azure() -> bool:
    return bool(settings.azure_storage_account_name)


def _blob_client(container: str, path: str):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    account_url = f"https://{settings.azure_storage_account_name}.blob.core.windows.net"
    service = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return service.get_blob_client(container=container, blob=path)


def _local_root(container: str) -> Path:
    return Path(settings.local_storage_dir) if container == "jobs" else Path(settings.local_profiles_dir)


def _local_path(container: str, path: str) -> Path:
    full = _local_root(container) / path
    full.parent.mkdir(parents=True, exist_ok=True)
    return full


def _save(container: str, path: str, data: bytes) -> None:
    if _use_azure():
        _blob_client(container, path).upload_blob(data, overwrite=True)
    else:
        _local_path(container, path).write_bytes(data)


def _load(container: str, path: str) -> bytes:
    if _use_azure():
        return _blob_client(container, path).download_blob().readall()
    return _local_path(container, path).read_bytes()


def _exists(container: str, path: str) -> bool:
    if _use_azure():
        return _blob_client(container, path).exists()
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
