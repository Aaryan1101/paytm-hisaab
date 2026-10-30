"""Outbound messaging contract. Concrete channels (WhatsApp, DB log) implement it."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Button:
    id: str
    title: str


class Notifier(Protocol):
    def send(self, merchant_id: int, text: str, buttons: list[Button] | None = None, trace: dict | None = None) -> None: ...
