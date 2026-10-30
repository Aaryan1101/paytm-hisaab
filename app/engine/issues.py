from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Literal["info", "warn", "high"]
    message_en: str
    message_hi: str
    field: str | None = None
    line_index: int | None = None
