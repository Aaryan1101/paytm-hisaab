"""Composition root for AI dependencies: built once at startup, swapped for fakes in tests."""
import logging
from dataclasses import dataclass

from sqlmodel import Session

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.ai.agent import Agent
from app.ai.graph.agent_graph import GraphAgent
from app.ai.graph.checkpointing import memory_checkpointer, postgres_checkpointer
from app.ai.graph.confirmations import Confirmations
from app.ai.extract import InvoiceExtractor
from app.ai.reminders import ReminderDrafter
from app.ai.sarvam_port import ChatPort, DocAIPort, SttPort, TtsPort
from app.ai.structuring import LlmStructurer
from app.ai.voice import VoicePipeline
from app.channels.base import Notifier
from app.channels.db_notifier import DbNotifier
from app.channels.whatsapp.client import WhatsAppClient
from app.channels.whatsapp.notifier import WhatsAppNotifier
from app.config import Settings
from app.storage import MediaStore

log = logging.getLogger(__name__)


@dataclass
class Container:
    chat: ChatPort
    docai: DocAIPort
    stt: SttPort
    tts: TtsPort
    media: MediaStore
    router_first: bool = False
    whatsapp: WhatsAppClient | None = None
    agent_engine: str = "native"
    checkpointer: BaseCheckpointSaver | None = None

    def __post_init__(self) -> None:
        self.checkpointer = self.checkpointer or memory_checkpointer()
        self.confirmations = Confirmations(self.checkpointer)
        self.extractor = InvoiceExtractor(self.docai, LlmStructurer(self.chat))
        self.agent = (GraphAgent(self.chat, self.checkpointer, router_first=self.router_first) if self.agent_engine == "graph"
                      else Agent(self.chat, router_first=self.router_first))
        self.voice = VoicePipeline(self.stt, self.tts, self.agent, self.media)
        self.reminders = ReminderDrafter(self.chat)

    def notifier(self, session: Session) -> Notifier:
        if self.whatsapp is not None:
            return WhatsAppNotifier(self.whatsapp, session)
        return DbNotifier(session)


def build_container(settings: Settings) -> Container:
    from app.ai.sarvam import Sarvam
    sarvam = Sarvam(settings)
    wa = (WhatsAppClient(settings.whatsapp_access_token, settings.whatsapp_phone_number_id)
          if settings.whatsapp_access_token and settings.whatsapp_phone_number_id else None)
    checkpointer = None
    if settings.agent_engine == "graph":
        try:
            checkpointer = postgres_checkpointer(settings.database_url)
        except Exception:  # keep serving; memory and pending confirmations just won't survive a restart
            log.warning("Postgres checkpointer unavailable; using in-memory agent state", exc_info=True)
    return Container(sarvam.chat, sarvam.docai, sarvam.stt, sarvam.tts,
                     MediaStore(settings.media_dir, settings.public_base_url), settings.agent_router_first, wa,
                     settings.agent_engine, checkpointer)
