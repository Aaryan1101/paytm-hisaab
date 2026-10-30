"""Descriptions of an action that needs the user's yes/no (or choice) before anything happens."""
from dataclasses import dataclass

from app.ai.agent import ToolTrace


@dataclass(frozen=True)
class Option:
    choice: str  # becomes the resume value and the last segment of the button id
    title: str   # shown on the button (WhatsApp truncates at 20 characters)


@dataclass(frozen=True)
class PendingAction:
    kind: str  # bill | dup | cash | pay  (selects the business action in button_actions)
    ref_id: int
    options: tuple[Option, ...]


YES_NO_CASH = (Option("ok", "Haan, sahi hai"), Option("no", "Nahi"))
YES_NO_PAY = (Option("ok", "Pay karein"), Option("no", "Cancel"))
YES_NO_BILL = (Option("ok", "Haan, sahi hai"), Option("no", "Nahi, hata do"))


def from_traces(traces: list[ToolTrace]) -> PendingAction | None:
    """What the agent prepared this turn that still needs a tap: a pending cash entry or a payment draft."""
    for t in reversed(traces):
        if "error" in t.result:
            continue
        if t.name == "log_cash_payment":
            return PendingAction("cash", t.result["pending_payment_id"], YES_NO_CASH)
        if t.name == "draft_payment":
            return PendingAction("pay", t.result["draft_id"], YES_NO_PAY)
    return None


def for_bill(invoice_id: int, supplier_name: str, is_duplicate: bool) -> PendingAction:
    if is_duplicate:
        first = supplier_name.split()[0]
        return PendingAction("dup", invoice_id, (Option("ignore", "Duplicate hai"), Option("new", "Naya bill hai"),
                                                 Option("ask", f"{first} se poochho")))
    return PendingAction("bill", invoice_id, YES_NO_BILL)
