"""Deterministic replies rendered straight from tool results. Used as the fallback and for the grounding guard."""
from app.ai.money_format import inr, spoken

_NOTE_HI = "Aapke paas yeh record nahi hai. Kya main add kar doon?"
_NOTE_EN = "I don't have that record. Shall I add it?"


def _err(result: dict, hi: bool) -> str:
    if result["error"] == "not_found":
        return "Yeh record mujhe nahi mila. Naam dobara bataiye." if hi else "I couldn't find that. Please check the name."
    return "Abhi yeh nahi ho paya. Thodi der baad try karein." if hi else "That didn't work just now. Please try again."


def render(tool: str, result: dict, language: str = "hi", channel: str = "app") -> str:
    hi, voice = language != "en", channel == "voice"
    if "error" in result:
        return _err(result, hi)
    fn = _RENDERERS.get(tool)
    return fn(result, hi, voice) if fn else (("Ho gaya." if hi else "Done."))


def _dues(r: dict, hi: bool, voice: bool) -> str:
    if not r["items"]:
        return "Is samay koi dues nahi hain." if hi else "Nothing is due right now."
    n, first = r["count"], r["items"][0]["supplier"]
    period = {"today": "Aaj", "week": "Is hafte", "month": "Is mahine"}[r["period"]] if hi else f"This {r['period']}" if r["period"] != "today" else "Today"
    if voice:
        return (f"{period} {n} suppliers ko {spoken(r['total'])} rupaye dena hai, sabse pehle {first}." if hi
                else f"{period} you owe {spoken(r['total'])} rupees to {n} suppliers, {first} first.")
    head = f"{period} {n} suppliers ko {r['total_display']} dena hai:" if hi else f"{period} you owe {r['total_display']} to {n} suppliers:"
    lines = [f"• {i['supplier']} {i['amount_display']} ({i['due_date'][8:]}/{i['due_date'][5:7]})" for i in r["items"]]
    return "\n".join([head, *lines])


def _forecast(r: dict, hi: bool, voice: bool) -> str:
    if not r["shortfall"]:
        return "Agle 14 din paise ki kami nahi dikh rahi." if hi else "No cash shortfall in the next 14 days."
    day = r["weekday"]
    if voice:
        return (f"{day} ko {spoken(r['shortfall_amount'])} rupaye kam pad sakte hain. Credit option dekhna chahenge?" if hi
                else f"You may be {spoken(r['shortfall_amount'])} rupees short on {day}. Want to see a credit option?")
    return (f"{day} ({r['shortfall_date']}) ko {r['shortfall_display']} kam pad sakte hain. Credit option dekhein?" if hi
            else f"You may be {r['shortfall_display']} short on {day} ({r['shortfall_date']}). See a credit option?")


def _ledger(r: dict, hi: bool, voice: bool) -> str:
    head = f"{r['supplier']} ka hisaab: baaki {r['balance_display']}." if hi else f"{r['supplier']}: balance due {r['balance_display']}."
    if voice or not r["open_issues"]:
        return head
    return head + "\n" + "\n".join(f"⚠️ {i}" for i in r["open_issues"])


def _score(r: dict, hi: bool, voice: bool) -> str:
    reasons = [x["text_hi" if hi else "text_en"] for x in r["reasons"]]
    head = f"Aapka Hisaab Score {r['score']} hai." if hi else f"Your Hisaab Score is {r['score']}."
    return head if voice else "\n".join([head, *[f"• {x}" for x in reasons]])


def _credit(r: dict, hi: bool, voice: bool) -> str:
    if not r["eligible"]:
        return f"Abhi credit offer nahi hai: {r['reason']}." if hi else f"No credit offer right now: {r['reason']}."
    amt = spoken(r["limit"]) if voice else r["limit_display"]
    return (f"Aapko {amt} tak ka credit offer hai, {r['tenure_days']} din ke liye. App mein consent dekar le sakte hain." if hi
            else f"You have a credit offer of up to {amt} for {r['tenure_days']} days. Give consent in the app to take it.")


def _alerts(r: dict, hi: bool, voice: bool) -> str:
    if r["count"] == 0:
        return "Koi alert nahi hai." if hi else "No open alerts."
    head = f"{r['count']} alert hain." if hi else f"You have {r['count']} open alerts."
    return head if voice else "\n".join([head, *[f"• {a['message_hi' if hi else 'message_en']}" for a in r["alerts"][:5]]])


def _cash(r: dict, hi: bool, voice: bool) -> str:
    return (f"{r['supplier']} ko {r['amount_display']} cash likh liya hai. Confirm karein?" if hi
            else f"Logged {r['amount_display']} cash to {r['supplier']}. Confirm?")


def _draft(r: dict, hi: bool, voice: bool) -> str:
    return (f"{r['supplier']} ko {r['amount_display']} ka payment taiyaar hai. Bhejne ke liye confirm karein." if hi
            else f"Payment of {r['amount_display']} to {r['supplier']} is ready. Confirm to send.")


def _export(r: dict, hi: bool, voice: bool) -> str:
    return f"{r['month']} ka purchase register taiyaar hai: {r['url']}" if hi else f"Purchase register for {r['month']} is ready: {r['url']}"


def _receivables(r: dict, hi: bool, voice: bool) -> str:
    head = (f"{r['retailers']} retailers mein se {r['total_overdue_display']} overdue hai." if hi
            else f"{r['total_overdue_display']} is overdue across {r['retailers']} retailers.")
    if voice or not r["top"]:
        return head
    return "\n".join([head, *[f"• {t['retailer']} {t['overdue_display']} ({t['days_overdue']}d)" for t in r["top"][:5] if t["overdue"]]])


def _ims(r: dict, hi: bool, voice: bool) -> str:
    c = r["counts"]
    return (f"IMS: {c['accept']} accept, {c['reject']} reject, {c['pending']} pending suggest kiye hain." if hi
            else f"IMS suggestions: {c['accept']} accept, {c['reject']} reject, {c['pending']} pending.")


def _reminders(r: dict, hi: bool, voice: bool) -> str:
    return f"{r['count']} reminders taiyaar hain. Bhejne se pehle dekh lein." if hi else f"{r['count']} reminders drafted. Review before sending."


_RENDERERS = {"get_dues": _dues, "forecast_cash": _forecast, "get_supplier_ledger": _ledger, "get_hisaab_score": _score,
              "get_credit_offer": _credit, "list_alerts": _alerts, "log_cash_payment": _cash, "draft_payment": _draft,
              "export_purchase_register": _export, "get_receivables": _receivables, "ims_suggestions": _ims,
              "draft_reminders": _reminders}
