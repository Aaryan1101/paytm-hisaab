"""Local media store for bill images and voice replies. Files are private to the server except audio served by URL."""
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredFile:
    path: Path
    url: str


class MediaStore:
    def __init__(self, directory: str, public_base_url: str):
        self._dir, self._base = Path(directory), public_base_url.rstrip("/")

    def save(self, data: bytes, ext: str, kind: str) -> StoredFile:
        folder = self._dir / kind
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.{ext.lstrip('.')}"
        path = folder / name
        path.write_bytes(data)
        return StoredFile(path, f"{self._base}/media/{kind}/{name}")

    @property
    def root(self) -> Path:
        return self._dir
