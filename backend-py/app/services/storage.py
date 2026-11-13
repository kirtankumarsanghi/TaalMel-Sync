"""File storage behind a small interface. Local disk for now; S3 can be added without touching callers."""

from pathlib import Path
from typing import Protocol


class StorageService(Protocol):
    def upload(self, key: str, data: bytes) -> None: ...
    def download(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalStorageService:
    def __init__(self, base_path: Path) -> None:
        self._base = base_path.resolve()

    def _path_for(self, key: str) -> Path:
        candidate = (self._base / key).resolve()
        # Refuse keys that escape the base directory (path traversal).
        if self._base not in candidate.parents:
            raise ValueError(f"Storage key escapes base directory: {key}")
        return candidate

    def upload(self, key: str, data: bytes) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def download(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()


def get_storage() -> StorageService:
    from app.config import get_settings

    return LocalStorageService(get_settings().upload_dir)
