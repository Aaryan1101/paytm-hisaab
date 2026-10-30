import json
import time

from app.ai.sarvam.cache import ResponseCache
from app.ai.sarvam.errors import SarvamError
from app.ai.sarvam.transport import SarvamTransport

TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
SUCCESS = {"completed", "partially_completed"}


class DocumentAIClient:
    """Sarvam Document Intelligence: schema-based extraction via an async job (submit, poll, fetch)."""

    def __init__(self, transport: SarvamTransport, cache: ResponseCache, poll_interval_s: float, timeout_s: float):
        self._t, self._cache = transport, cache
        self._poll_interval_s, self._timeout_s = poll_interval_s, timeout_s

    def extract(self, file: bytes, filename: str, schema: dict, language: str = "en-IN",
                content_type: str = "image/jpeg") -> dict:
        """Return the extracted `result` object for the given JSON schema."""
        schema_json = json.dumps(schema, sort_keys=True)
        key = ResponseCache.key("docai", file, schema_json, language)
        return self._cache.get_or_set(key, lambda: self._run(file, filename, schema_json, language, content_type))

    def _run(self, file: bytes, filename: str, schema_json: str, language: str, content_type: str) -> dict:
        job = self._t.request(
            "POST",
            "/doc-ai/v1/job/extract",
            files={"file": (filename, file, content_type)},
            data={"schema": schema_json, "language": language, "output_format": "json"},
        )
        job_id = job["job_id"]
        self._wait(job_id)
        return self._t.request("GET", f"/doc-ai/v1/job/{job_id}/results")["result"]

    def _wait(self, job_id: str) -> None:
        deadline = time.monotonic() + self._timeout_s
        while time.monotonic() < deadline:
            status = self._t.request("GET", f"/doc-ai/v1/job/{job_id}/status")["status"].lower()
            if status in SUCCESS:
                return
            if status in TERMINAL:
                raise SarvamError(f"Document AI job {job_id} ended as {status}")
            time.sleep(self._poll_interval_s)
        raise SarvamError(f"Document AI job {job_id} timed out after {self._timeout_s}s")
