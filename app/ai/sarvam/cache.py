import hashlib
import json
from pathlib import Path
from typing import Any, Callable


class ResponseCache:
    """On-disk JSON cache keyed by a hash of the request inputs."""

    def __init__(self, directory: str):
        self._dir = Path(directory)

    @staticmethod
    def key(namespace: str, *parts: bytes | str) -> str:
        h = hashlib.sha256(namespace.encode())
        for p in parts:
            h.update(p if isinstance(p, bytes) else p.encode())
            h.update(b"\x00")
        return f"{namespace}-{h.hexdigest()[:32]}"

    def get_or_set(self, key: str, producer: Callable[[], Any]) -> Any:
        path = self._dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        value = producer()
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return value
