"""Async SQLAlchemy setup + ORM models.

Two tables:
  api_keys  — B2B credentials. Only a SHA-256 hash is stored; the raw key is
              shown once at issue time.
  interviews — one verbal interview session, created by a B2B client and joined
              by a candidate via an unguessable token.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _uuid() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verify_token: Mapped[str] = mapped_column(String, default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    client_name: Mapped[str] = mapped_column(String)
    key_prefix: Mapped[str] = mapped_column(String)   # shown for identification
    key_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    join_token: Mapped[str] = mapped_column(String, unique=True, index=True, default=new_token)

    # Who created it. Either a company (web dashboard) or an API key (programmatic).
    company_id: Mapped[str] = mapped_column(String, index=True, default="")
    api_key_id: Mapped[str] = mapped_column(String, index=True, default="")
    client_name: Mapped[str] = mapped_column(String, default="")

    # Interview configuration
    candidate_name: Mapped[str] = mapped_column(String, default="Candidate")
    candidate_email: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="")
    interviewer_name: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="the role")
    job_description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String, default="English")
    max_minutes: Mapped[int] = mapped_column(Integer, default=15)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String, default="created")  # created|in_progress|completed|expired
    _transcript: Mapped[str] = mapped_column("transcript", Text, default="[]")
    _report: Mapped[str] = mapped_column("report", Text, default="null")
    _questions: Mapped[str] = mapped_column("questions", Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: now() + timedelta(minutes=get_settings().interview_ttl_minutes),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)  # completion emails sent

    # --- JSON accessors ---
    @property
    def transcript(self) -> list[dict]:
        return json.loads(self._transcript or "[]")

    @transcript.setter
    def transcript(self, value: list[dict]) -> None:
        self._transcript = json.dumps(value)

    @property
    def report(self) -> dict | None:
        return json.loads(self._report or "null")

    @report.setter
    def report(self, value: dict | None) -> None:
        self._report = json.dumps(value)

    @property
    def questions(self) -> list[str]:
        return json.loads(self._questions or "[]")

    @questions.setter
    def questions(self, value: list[str]) -> None:
        self._questions = json.dumps(value)

    def add_turn(self, role: str, text: str) -> None:
        """role is 'interviewer' or 'candidate'."""
        t = self.transcript
        t.append({"role": role, "text": text})
        self.transcript = t

    @property
    def is_expired(self) -> bool:
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now() > exp

    @property
    def join_url(self) -> str:
        return f"{get_settings().public_base_url.rstrip('/')}/i/{self.join_token}"


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # lightweight migrations for pre-existing DBs (no-op if column exists)
        for col, ddl in [
            ("questions", "ALTER TABLE interviews ADD COLUMN questions TEXT DEFAULT '[]'"),
            ("company", "ALTER TABLE interviews ADD COLUMN company TEXT DEFAULT ''"),
            ("interviewer_name", "ALTER TABLE interviews ADD COLUMN interviewer_name TEXT DEFAULT ''"),
            ("company_id", "ALTER TABLE interviews ADD COLUMN company_id TEXT DEFAULT ''"),
            ("candidate_email", "ALTER TABLE interviews ADD COLUMN candidate_email TEXT DEFAULT ''"),
            ("notified", "ALTER TABLE interviews ADD COLUMN notified BOOLEAN DEFAULT 0"),
            ("scheduled_at", "ALTER TABLE interviews ADD COLUMN scheduled_at DATETIME"),
            # companies — existing rows default to verified so they aren't locked out
            ("c_verified", "ALTER TABLE companies ADD COLUMN verified BOOLEAN DEFAULT 1"),
            ("c_token", "ALTER TABLE companies ADD COLUMN verify_token TEXT DEFAULT ''"),
        ]:
            try:
                await conn.exec_driver_sql(ddl)
            except Exception:
                pass
