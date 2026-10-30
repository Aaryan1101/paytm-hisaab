"""Turns a chat reply into something a TTS voice should read: no markup, emoji or links, at most two sentences."""
import re

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF✅⚠️]")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


def speakable(text: str, max_sentences: int = 2, max_chars: int = 260) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    out = " ".join(_SENTENCE_END.split(text)[:max_sentences])
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return out
