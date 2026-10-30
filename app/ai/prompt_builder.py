"""Assembles the system prompt: role base prompt + channel style + language + context."""
from datetime import date

from app.ai import prompts

_CHANNEL = {
    "whatsapp": "Format for WhatsApp: short lines, • bullets, *bold* for names and amounts, no headings.",
    "app": "Format for a mobile app card: concise plain text, a few short lines at most.",
    "voice": ("This reply will be spoken aloud: at most 2 sentences, no bullets, emoji, links or markdown, "
              "round amounts to speech style (e.g. 'ek lakh baarah hazaar'), headline first."),
}
_LANGUAGE = {"hi": "Default to Hinglish (Hindi in Roman script) unless the user writes in English or Devanagari; mirror them.",
             "en": "Default to English unless the user writes in Hindi; mirror them."}


def build(role: str, channel: str, language: str, merchant_name: str, today: date) -> str:
    base = prompts.load("agent_distributor" if role == "distributor" else "agent_system")
    return "\n".join([base, _CHANNEL.get(channel, _CHANNEL["app"]), _LANGUAGE.get(language, _LANGUAGE["hi"]),
                      f"You are talking to {merchant_name}. Today is {today:%A, %d %B %Y}."])
