"""Job artifact storage: Azure Blob Storage when configured, a local temp
directory otherwise (so Phase 0/1 development needs zero Azure dependency).
"""

from pathlib import Path

from app.config import settings


def _use_azure() -> bool:
    return bool(settings.azure_storage_account_name)


def _blob_client(job_id: str, name: str):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    account_url = f"https://{settings.azure_storage_account_name}.blob.core.windows.net"
    service = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return service.get_blob_client(container="jobs", blob=f"{job_id}/{name}")


def _local_path(job_id: str, name: str) -> Path:
    job_dir = Path(settings.local_storage_dir) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir / name


def save_bytes(job_id: str, name: str, data: bytes) -> None:
    if _use_azure():
        _blob_client(job_id, name).upload_blob(data, overwrite=True)
    else:
        _local_path(job_id, name).write_bytes(data)


def load_bytes(job_id: str, name: str) -> bytes:
    if _use_azure():
        return _blob_client(job_id, name).download_blob().readall()
    return _local_path(job_id, name).read_bytes()


def exists(job_id: str, name: str) -> bool:
    if _use_azure():
        return _blob_client(job_id, name).exists()
    return _local_path(job_id, name).exists()
