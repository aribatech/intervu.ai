from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_tts_model: str = "eleven_turbo_v2_5"
    elevenlabs_stt_model: str = "scribe_v1"

    elevenlabs_agent_id: str = ""
    elevenlabs_agent_llm: str = "gpt-4o"

    database_url: str = "sqlite+aiosqlite:///./mockpilot.db"

    public_base_url: str = "http://127.0.0.1:8000"

    interview_ttl_minutes: int = 1440

    app_name: str = "Voxa"
    secret_key: str = "dev-secret-change-me"

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
