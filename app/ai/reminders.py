"""Drafts a payment reminder with the LLM; falls back to a fixed template if the LLM fails or misquotes figures."""
import logging
import re

from app.ai import prompts
from app.ai.money_format import inr
from app.ai.sarvam_port import ChatPort

log = logging.getLogger(__name__)
_LANG = {"hi": "Hinglish (Hindi in Roman script)", "en": "English"}
_TEMPLATES = {
    "hi": {"friendly": "Namaste {retailer}, {distributor} ki taraf se yaad dila rahe hain: {amount} ka bill jald due hai. Paytm QR se pay kar sakte hain.",
           "polite": "Namaste {retailer}, aapke {amount} {days} din se baaki hain. Kripya Paytm QR se pay kar dein. Dhanyavaad.",
           "firm": "{retailer}, {distributor} ke {amount} {days} din se overdue hain. Kripya aaj hi Paytm QR se payment karein.",
           "final": "{retailer}, {distributor} ke {amount} {days} din se overdue hain. Yeh aakhri reminder hai; kripya turant payment karein ya humse sampark karein."},
    "en": {"friendly": "Hello {retailer}, a friendly reminder from {distributor}: your bill of {amount} is due soon. You can pay via your Paytm QR.",
           "polite": "Hello {retailer}, {amount} has been pending for {days} days. Please pay via the Paytm QR. Thank you.",
           "firm": "{retailer}, {amount} owed to {distributor} is {days} days overdue. Please pay today via the Paytm QR.",
           "final": "{retailer}, this is our final reminder: {amount} owed to {distributor} is {days} days overdue. Please pay immediately or contact us."},
}


def template(retailer_name: str, distributor_name: str, amount: float, days_overdue: int, tone: str, language: str) -> str:
    lang = _TEMPLATES.get(language, _TEMPLATES["hi"])
    return lang[tone].format(retailer=retailer_name, distributor=distributor_name, amount=inr(amount), days=max(days_overdue, 0))


class ReminderDrafter:
    def __init__(self, chat: ChatPort | None):
        self._chat = chat

    def __call__(self, retailer_name: str, distributor_name: str, amount: float, days_overdue: int, tone: str,
                 language: str = "hi") -> str:
        fallback = template(retailer_name, distributor_name, amount, days_overdue, tone, language)
        if self._chat is None:
            return fallback
        system = prompts.load("reminder").format(language_name=_LANG.get(language, _LANG["hi"]), tone=tone)
        facts = (f"Retailer: {retailer_name}\nDistributor: {distributor_name}\nAmount overdue: {inr(amount)}\n"
                 f"Days overdue: {days_overdue}")
        try:
            text = (self._chat.complete([{"role": "system", "content": system}, {"role": "user", "content": facts}],
                                        temperature=0.5, max_tokens=300).get("content") or "").strip()
        except Exception:
            log.exception("reminder drafting failed")
            return fallback
        return text if text and self._quotes_amount_correctly(text, amount) else fallback

    @staticmethod
    def _quotes_amount_correctly(text: str, amount: float) -> bool:
        """The reminder must state the true amount and no other money figure."""
        found = {float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text) if len(m.replace(",", "")) >= 4}
        return found == {round(amount)} or found == {amount} or (not found and False)
