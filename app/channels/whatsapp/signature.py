"""Verifies Meta's X-Hub-Signature-256 header. Fails closed: no secret configured means nothing is trusted."""
import hashlib
import hmac


def verify(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))
