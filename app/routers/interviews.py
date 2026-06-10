"""Interview endpoints.

B2B (API-key protected):
  POST /v1/interviews              -> create, returns a candidate join_url
  GET  /v1/interviews/{id}         -> status + transcript + report

Candidate (join-token, no API key — the token IS the access):
  GET  /v1/join/{token}            -> public interview meta for the join page
  POST /v1/join/{token}/connect    -> signed URL + personalization for the realtime agent
  POST /v1/join/{token}/snapshot   -> proctoring photo
  POST /v1/join/{token}/complete   -> conversation ended -> fetch transcript -> score
  POST /v1/join/{token}/finish     -> end early (no conversation)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import engine, mailer
from ..auth import require_api_key
from ..clients import elevenlabs
from ..config import get_settings
from ..db import ApiKey, Company, Interview, now
from ..deps import get_db
from ..schemas import (
    CompleteRequest,
    ConnectResponse,
    CreateInterviewRequest,
    InterviewCreated,
    InterviewMeta,
    InterviewReport,
    InterviewResult,
)

router = APIRouter(tags=["interviews"])

SNAPSHOT_DIR = Path(__file__).parent.parent.parent / "snapshots"
SNAPSHOT_DIR.mkdir(exist_ok=True)


# ===================== B2B (protected) =====================

@router.post("/v1/interviews", response_model=InterviewCreated)
async def create_interview(
    req: CreateInterviewRequest,
    key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> InterviewCreated:
    if not get_settings().brain_enabled:
        raise HTTPException(503, "OPENAI_API_KEY not configured")

    jd = req.job_description.strip()
    if req.focus_areas:
        jd = (jd + "\n\nFocus areas: " + ", ".join(req.focus_areas)).strip()

    itv = Interview(
        api_key_id=key.id,
        client_name=key.client_name,
        candidate_name=req.candidate_name,
        company=req.company.strip() or key.client_name,
        interviewer_name=req.interviewer_name.strip(),
        role=req.role,
        job_description=jd,
        language=req.language,
        max_minutes=req.max_minutes,
    )
    db.add(itv)
    await db.commit()
    return InterviewCreated(
        interview_id=itv.id,
        join_url=itv.join_url,
        status=itv.status,
        expires_at=itv.expires_at,
    )


@router.get("/v1/interviews/{interview_id}", response_model=InterviewResult)
async def get_interview(
    interview_id: str,
    key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> InterviewResult:
    itv = await db.get(Interview, interview_id)
    if not itv or itv.api_key_id != key.id:
        raise HTTPException(404, "Unknown interview")
    report = InterviewReport.model_validate(itv.report) if itv.report else None
    return InterviewResult(
        interview_id=itv.id,
        status=itv.status,
        candidate_name=itv.candidate_name,
        role=itv.role,
        transcript=itv.transcript,
        report=report,
    )


# ===================== Candidate (join token) =====================

async def _load_joinable(db: AsyncSession, token: str) -> Interview:
    itv = (
        await db.execute(select(Interview).where(Interview.join_token == token))
    ).scalar_one_or_none()
    if not itv:
        raise HTTPException(404, "Interview not found")
    if itv.is_expired:
        raise HTTPException(410, "This interview link has expired")
    return itv


def _dynamic_vars(itv: Interview) -> dict:
    """Personalization injected into the shared agent at connect time."""
    return {
        "candidate_name": itv.candidate_name or "the candidate",
        "company": (itv.company or itv.client_name or "the company"),
        "interviewer_name": (itv.interviewer_name or "Alex"),
        "role": itv.role or "the role",
        "job_description": (itv.job_description or "").strip() or "(no detailed description provided)",
        "language": itv.language or "English",
    }


@router.get("/v1/join/{token}", response_model=InterviewMeta)
async def join_meta(token: str, db: AsyncSession = Depends(get_db)) -> InterviewMeta:
    itv = await _load_joinable(db, token)
    return InterviewMeta(
        candidate_name=itv.candidate_name,
        role=itv.role,
        language=itv.language,
        max_minutes=itv.max_minutes,
        status=itv.status,
    )


@router.post("/v1/join/{token}/connect", response_model=ConnectResponse)
async def connect(token: str, db: AsyncSession = Depends(get_db)) -> ConnectResponse:
    """Hand the browser a short-lived signed URL + personalization so it can open a
    realtime voice session directly with the ElevenLabs agent."""
    itv = await _load_joinable(db, token)
    if itv.status == "completed":
        raise HTTPException(409, "This interview is already completed")
    s = get_settings()
    if not s.realtime_enabled:
        raise HTTPException(
            503,
            "Realtime agent not configured. Run `python -m app.setup_agent` and set "
            "ELEVENLABS_AGENT_ID in .env.",
        )
    try:
        signed_url = await elevenlabs.get_signed_url(s.elevenlabs_agent_id)
    except elevenlabs.ElevenLabsError as e:
        raise HTTPException(502, f"Could not start agent session: {e}") from e

    if itv.status == "created":
        itv.status = "in_progress"
        itv.started_at = now()
        await db.commit()

    return ConnectResponse(signed_url=signed_url, dynamic_variables=_dynamic_vars(itv))


async def _notify_complete(itv: Interview, db: AsyncSession, background: BackgroundTasks) -> None:
    """Email the candidate and (if created via dashboard) the company — once."""
    if itv.notified:
        return
    itv.notified = True
    if itv.candidate_email:
        subj, html = mailer.candidate_done_email(itv.candidate_name, itv.company or "the company", itv.role)
        background.add_task(mailer.send_email, itv.candidate_email, subj, html)
    if itv.company_id:
        comp = await db.get(Company, itv.company_id)
        if comp:
            rep = itv.report or {}
            url = f"{get_settings().public_base_url.rstrip('/')}/interviews/{itv.id}"
            subj, html = mailer.company_done_email(
                itv.candidate_name, itv.role, rep.get("recommendation") or "n/a", rep.get("overall"), url
            )
            background.add_task(mailer.send_email, comp.email, subj, html)


@router.post("/v1/join/{token}/complete")
async def complete(
    token: str,
    req: CompleteRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Conversation ended: pull the transcript from ElevenLabs, store it, score it."""
    itv = await _load_joinable(db, token)
    if itv.status == "completed":
        return {"ok": True, "status": "completed"}

    # transcript may take a few seconds to be ready after the call ends
    turns: list[dict] = []
    for _ in range(6):
        try:
            conv = await elevenlabs.get_conversation(req.conversation_id)
        except elevenlabs.ElevenLabsError:
            conv = {}
        raw = conv.get("transcript") or []
        turns = [
            {"role": "interviewer" if m.get("role") == "agent" else "candidate",
             "text": (m.get("message") or "").strip()}
            for m in raw if (m.get("message") or "").strip()
        ]
        if turns and conv.get("status") in (None, "done", "processed", "completed"):
            break
        await asyncio.sleep(2)

    if turns:
        itv.transcript = turns
        try:
            report = await engine.build_report(itv)
            itv.report = report.model_dump()
        except Exception:
            pass
    itv.status = "completed"
    itv.completed_at = now()
    await _notify_complete(itv, db, background)
    await db.commit()
    return {"ok": True, "status": "completed"}


@router.post("/v1/join/{token}/snapshot")
async def snapshot(
    token: str,
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Candidate proctoring photo, captured at join (or when camera turns on)."""
    itv = await _load_joinable(db, token)
    data = await image.read()
    if not data:
        raise HTTPException(422, "Empty image")
    (SNAPSHOT_DIR / f"{itv.id}.jpg").write_bytes(data)
    return {"ok": True}


@router.get("/v1/interviews/{interview_id}/photo")
async def get_photo(
    interview_id: str,
    key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    itv = await db.get(Interview, interview_id)
    if not itv or itv.api_key_id != key.id:
        raise HTTPException(404, "Unknown interview")
    path = SNAPSHOT_DIR / f"{itv.id}.jpg"
    if not path.exists():
        raise HTTPException(404, "No photo captured")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/v1/join/{token}/finish")
async def finish(token: str, background: BackgroundTasks,
                 db: AsyncSession = Depends(get_db)) -> dict:
    """End the call early (candidate left) and generate the scored report."""
    itv = await _load_joinable(db, token)
    if itv.status != "completed":
        if itv.transcript:
            try:
                report = await engine.build_report(itv)
                itv.report = report.model_dump()
            except Exception:
                pass
        itv.status = "completed"
        itv.completed_at = now()
        await _notify_complete(itv, db, background)
        await db.commit()
    return {"ok": True, "status": "completed"}
