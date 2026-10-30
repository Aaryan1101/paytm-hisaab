from datetime import date

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://hisaab:hisaab@localhost:5544/hisaab"

    demo_today: date | None = date(2026, 10, 31)  # fixed "today" so seed data and demo stay consistent
    cors_origins: str = "http://localhost:3000"  # comma-separated browser origins allowed to call the API (the web dashboard)
    auto_seed: bool = True  # seed demo data on startup when the database is empty
    agent_engine: str = "graph"  # graph (LangGraph, durable memory) | native (hand-written loop)
    langsmith_tracing: bool = False  # send every agent turn to LangSmith (needs langsmith_api_key)
    langsmith_api_key: str = ""
    langsmith_project: str = "hisaab-agent"
    agent_router_first: bool = False  # use the keyword router as the primary path (stage safety net)
    media_dir: str = ".media"
    public_base_url: str = "http://localhost:8000"
    whatsapp_verify_token: str = "hisaab-verify"
    whatsapp_app_secret: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""

    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_cache_dir: str = ".cache/sarvam"
    sarvam_timeout_s: float = 20.0  # chat/TTS/STT answer in ~1s; a hung connection should fail fast and retry

    sarvam_chat_model: str = "sarvam-105b"
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v4-flash"
    sarvam_tts_speaker: str = "simran_en_customer"
    sarvam_docai_poll_interval_s: float = 3.0
    sarvam_docai_timeout_s: float = 90.0


settings = Settings()
