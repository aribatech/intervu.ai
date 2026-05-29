"""Verbal AI Interviewer — FastAPI app entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from . import audio_store
from .config import get_settings
from .db import init_db
from .routers import interviews, web

STATIC_DIR = Path(__file__).parent.parent / "static"
INTERVIEW_PAGE = STATIC_DIR / "interview.html"
LOGO = STATIC_DIR / "logo.svg"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title=get_settings().app_name, version="0.3.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key,
                   https_only=False, same_site="lax")
app.include_router(web.router)
app.include_router(interviews.router)


@app.get("/logo.svg")
async def logo() -> FileResponse:
    return FileResponse(LOGO, media_type="image/svg+xml")


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(LOGO, media_type="image/svg+xml")


@app.get("/healthz")
async def health() -> dict:
    s = get_settings()
    return {
        "ok": True,
        "brain_enabled": s.brain_enabled,
        "voice_enabled": s.voice_enabled,
        "realtime_enabled": s.realtime_enabled,
        "agent_id_set": bool(s.elevenlabs_agent_id),
        "email_enabled": s.email_enabled,
        "model": s.openai_model,
    }


@app.get("/audio/{clip_id}")
async def get_audio(clip_id: str) -> Response:
    clip = audio_store.get(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip expired or not found")
    return Response(content=clip, media_type="audio/mpeg")


@app.get("/i/{token}")
async def join_page(token: str) -> FileResponse:
    """Candidate join page. The token is read client-side from the URL path."""
    if not INTERVIEW_PAGE.exists():
        raise HTTPException(500, "interview page missing")
    return FileResponse(INTERVIEW_PAGE)
