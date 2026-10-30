from app.ai.sarvam.cache import ResponseCache
from app.ai.sarvam.chat import ChatClient
from app.ai.sarvam.docai import DocumentAIClient
from app.ai.sarvam.stt import SpeechToTextClient
from app.ai.sarvam.transport import SarvamTransport
from app.ai.sarvam.tts import TextToSpeechClient
from app.config import Settings


class Sarvam:
    """Composition root: wires one transport + cache into the four endpoint clients."""

    def __init__(self, s: Settings):
        transport = SarvamTransport(s.sarvam_api_key, s.sarvam_base_url, s.sarvam_timeout_s)
        cache = ResponseCache(s.sarvam_cache_dir)
        self.chat = ChatClient(transport, cache, s.sarvam_chat_model)
        self.stt = SpeechToTextClient(transport, cache, s.sarvam_stt_model)
        self.tts = TextToSpeechClient(transport, cache, s.sarvam_tts_model, s.sarvam_tts_speaker)
        self.docai = DocumentAIClient(transport, cache, s.sarvam_docai_poll_interval_s, s.sarvam_docai_timeout_s)
