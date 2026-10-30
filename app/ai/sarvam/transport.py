import time
from typing import Any

import httpx

from app.ai.sarvam.errors import SarvamError

RETRY_STATUSES = {429, 500, 502, 503, 504}


class SarvamTransport:
    """Authenticated HTTP layer with retry. Knows nothing about specific endpoints."""

    def __init__(self, api_key: str, base_url: str, timeout_s: float, max_retries: int = 2,
                 client: httpx.Client | None = None, backoff_s: float = 1.0):
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={"api-subscription-key": api_key},
            timeout=timeout_s,
        )
        self._max_retries, self._backoff_s = max_retries, backoff_s

    def request(self, method: str, path: str, **kwargs: Any) -> dict:
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.request(method, path, **kwargs)
            except httpx.TransportError as e:  # timeouts, resets, DNS: worth another try, then a clear failure
                if attempt < self._max_retries:
                    time.sleep(self._backoff_s * 2**attempt)
                    continue
                raise SarvamError(f"{method} {path} failed: {type(e).__name__}") from e
            if resp.is_success:
                return resp.json()
            if resp.status_code in RETRY_STATUSES and attempt < self._max_retries:
                time.sleep(self._backoff_s * 2**attempt)
                continue
            raise SarvamError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}", resp.status_code)
        raise SarvamError(f"{method} {path} failed")  # unreachable
