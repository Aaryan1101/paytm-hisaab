"""Keyword intent router: the safety net when LLM tool calling is flaky. Pure; maps phrases to a tool call."""
import re
from dataclasses import dataclass, field

from app.ai.hindi_numbers import parse_amount


@dataclass(frozen=True)
class Route:
    tool: str
    args: dict = field(default_factory=dict)


def _norm(text: str) -> str:
    return re.sub(r"[?!.,]+", " ", text.casefold()).strip()


def _has(t: str, *words: str) -> bool:
    return any(w in t for w in words)


def _clean_name(name: str) -> str:
    return re.sub(r"\b(mera|meri|ka|ki|ke|the|for|of)\b", " ", name).strip()


def _period(t: str) -> str:
    if _has(t, "aaj", "today"):
        return "today"
    if _has(t, "mahine", "mahina", "month"):
        return "month"
    return "week"


def _cash_payment(t: str) -> Route | None:
    m = re.search(r"(?P<name>.+?)\s+ko\s+(?P<rest>.+?)\s+(?:cash|nakad|naqad)\s+(?:diye|diya|de diye|de diya|di)\b", t)
    if not m:
        m = re.search(r"paid\s+(?P<name>.+?)\s+(?P<rest>[\d,.]+\s*(?:k|lakh)?)\s+(?:in\s+)?cash", t)
    if not m:
        return None
    amount = parse_amount(m.group("rest"))
    return Route("log_cash_payment", {"supplier": _clean_name(m.group("name")), "amount": amount}) if amount else None


def _retailer_route(t: str) -> Route | None:
    if (r := _cash_payment(t)):
        return r
    m = re.search(r"(?P<name>.+?)\s+(?:ka|ki)\s+(?:hisaab|ledger|khata)", t) or re.search(r"ledger\s+(?:of|for)\s+(?P<name>.+)", t)
    if m:
        return Route("get_supplier_ledger", {"supplier": _clean_name(m.group("name"))})
    if _has(t, "kam pad", "shortfall", "forecast", "paise kab", "cash flow", "cashflow"):
        return Route("forecast_cash")
    if _has(t, "credit", "loan", "udhar", "paise chahiye", "restock ke liye"):
        return Route("get_credit_offer")
    if _has(t, "score"):
        return Route("get_hisaab_score")
    if _has(t, "ca ke liye", "report bhejo", "purchase register", "register export"):
        return Route("export_purchase_register")
    if re.search(r"\bims\b", t):
        return Route("ims_suggestions")
    if _has(t, "alert", "mismatch", "problem", "duplicate", "galat"):
        return Route("list_alerts")
    if _has(t, "dena hai", "kitna dena", "kitna baaki", "owe", "dues", "payable"):
        m = re.search(r"(?P<name>.+?)\s+ko\s+kitna", t)
        args = {"period": _period(t)}
        if m:
            args["supplier"] = _clean_name(m.group("name"))
        return Route("get_dues", args)
    return None


def _distributor_route(t: str) -> Route | None:
    if _has(t, "reminder", "yaad dila"):
        return Route("draft_reminders", {"language": "en" if _has(t, "english") else "hi"})
    m = re.search(r"credit limit\s+(?:for|of)\s+(?P<name>.+)", t) or re.search(r"(?P<name>.+?)\s+(?:ka|ko)\s+(?:kitna\s+)?credit\s+limit", t)
    if m:
        return Route("suggest_credit_limit", {"retailer": _clean_name(m.group("name"))})
    if _has(t, "settlement", "receipt", "mdr", "match"):
        return Route("match_settlements")
    if _has(t, "kaun kitna", "who owes", "receivable", "outstanding", "baaki", "overdue"):
        return Route("get_receivables")
    return None


def route(text: str, role: str) -> Route | None:
    t = _norm(text)
    return _distributor_route(t) if role == "distributor" else _retailer_route(t)
