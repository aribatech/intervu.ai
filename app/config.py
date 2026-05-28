"""Application settings, loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI (the interviewer brain)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # ElevenLabs (voice: TTS + STT)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_tts_model: str = "eleven_turbo_v2_5"
    elevenlabs_stt_model: str = "scribe_v1"

    # ElevenLabs Conversational AI (realtime agent)
    elevenlabs_agent_id: str = ""       # created once via: python -m app.setup_agent
    elevenlabs_agent_llm: str = "gpt-4o"

    # Persistence
    database_url: str = "sqlite+aiosqlite:///./mockpilot.db"

    # Public base URL used to build candidate join links.
    # e.g. https://interviews.yourdomain.com  (no trailing slash)
    public_base_url: str = "http://127.0.0.1:8000"

    # How long a created interview stays joinable.
    interview_ttl_minutes: int = 1440  # 24h

    # App / sessions
    app_name: str = "Voxa"
    secret_key: str = "dev-secret-change-me"  # signs session cookies; set a real one in prod

    # Email (SMTP). If smtp_host is empty, emails are logged to the console instead.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    email_from: str = "no-reply@example.com"

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def voice_enabled(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def realtime_enabled(self) -> bool:
        return bool(self.elevenlabs_api_key and self.elevenlabs_agent_id)

    @property
    def brain_enabled(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
