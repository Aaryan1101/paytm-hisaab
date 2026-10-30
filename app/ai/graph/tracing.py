"""Turns LangSmith tracing on from our settings (LangSmith itself reads plain environment variables)."""
import os
from collections.abc import MutableMapping

from app.config import Settings


def configure_langsmith(settings: Settings, environ: MutableMapping[str, str] | None = None) -> bool:
    """Enable tracing when asked for and a key is present. Returns whether tracing is on."""
    env = os.environ if environ is None else environ
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return False
    env["LANGSMITH_TRACING"] = "true"
    env["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    env["LANGSMITH_PROJECT"] = settings.langsmith_project
    return True
