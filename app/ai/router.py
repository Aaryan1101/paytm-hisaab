"""Keyword intent router: the safety net when LLM tool calling is flaky. Pure; maps phrases to a tool call."""
import re
from dataclasses import dataclass, field

from app.ai.hindi_numbers import parse_amount


# Phrases that state a fact to record ("Sharma ko 5,000 cash diye", "mere paas 40000 cash hai"). If the router is sure the user said
# one, the model must have called the matching tool; answering a question about dues instead silently drops what they told us.
MUST_RECORD = frozenset({"log_cash_payment", "set_cash_balance"})


def needs_router(route: "Route | None", calls: list[tuple[str, dict]]) -> bool:
    """Should the router's own call replace what the model did? Two cases where a wrong call quietly gives a wrong answer:
    the user stated a fact to record and the model never recorded it, or the user named one supplier and the model asked
    for everyone's dues. Anything else the model chose (a different but sensible read tool) is left alone."""
    if route is None:
        return False
    names = [n for n, _ in calls]
    if route.tool in MUST_RECORD:
        return route.tool not in names
    if route.tool == "get_dues" and route.args.get("supplier"):
        dues_calls = [a for n, a in calls if n == "get_dues"]
        return bool(dues_calls) and not any(a.get("supplier") for a in dues_calls)
    return False


@dataclass(frozen=True)
class Route:
    tool: str
    args: dict = field(default_factory=dict)


def _norm(text: str) -> str:
    """Lower-case and drop punctuation, but keep the separators inside numbers ("5,000", "2.5 lakh")."""
    return re.sub(r"[?!]+|(?<!\d)[.,]|[.,](?!\d)", " ", text.casefold()).strip()


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


def _cash_balance(t: str) -> Route | None:
    """"mere paas 40000 cash hai", "cash in hand 40000", "bank balance 2 lakh": the merchant tells us their balance."""
    m = re.search(r"(?:mere paas|cash in hand|cash balance|bank balance|my balance|my cash)\s*(?P<rest>.*)", t)
    if not m:
        return None
    amount = parse_amount(m.group("rest"))
    return Route("set_cash_balance", {"amount": amount}) if amount else None


def _retailer_route(t: str) -> Route | None:
    if (r := _cash_payment(t)):
        return r
    if (r := _cash_balance(t)):
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
