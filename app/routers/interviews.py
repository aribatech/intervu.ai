from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
    FeedbackRequest,
    InterviewCreated,
    InterviewMeta,
    InterviewReport,
    InterviewResult,
    NotesRequest,
    NotesResponse,
    SessionRequest,
)

router = APIRouter(tags=["interviews"])


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


@router.post("/v1/join/{token}/session")
async def save_session(
    token: str, req: SessionRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Persist the ElevenLabs conversation_id so the server can recover/finalize
    the interview even if the candidate's browser never calls /complete."""
    itv = await _load_joinable(db, token)
    if req.conversation_id and not itv.conversation_id:
        itv.conversation_id = req.conversation_id
        await db.commit()
    return {"ok": True}


@router.post("/v1/join/{token}/notes", response_model=NotesResponse)
async def live_notes(
    token: str, req: NotesRequest, db: AsyncSession = Depends(get_db)
) -> NotesResponse:
    """Generate running AI notes from the transcript captured so far."""
    itv = await _load_joinable(db, token)
    turns = [{"role": t.role, "text": t.text} for t in req.transcript if t.text.strip()]
    if not turns or not get_settings().brain_enabled:
        return NotesResponse(notes=itv.notes)
    try:
        notes = await engine.build_notes(itv.role, itv.job_description, turns)
        itv.notes = notes
        await db.commit()
    except Exception:
        notes = itv.notes
    return NotesResponse(notes=notes)


@router.post("/v1/join/{token}/feedback")
async def submit_feedback(
    token: str, req: FeedbackRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Candidate's feedback about the interview experience (+ integrity signal)."""
    itv = await _load_joinable(db, token)
    if req.rating is not None:
        itv.feedback_rating = req.rating
    if req.comment.strip():
        itv.feedback_text = req.comment.strip()
    if req.focus_lost_count:
        itv.focus_lost_count = max(itv.focus_lost_count, req.focus_lost_count)
    await db.commit()
    return {"ok": True}


async def _notify_complete(itv: Interview, db: AsyncSession, background: BackgroundTasks) -> None:
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
    itv = await _load_joinable(db, token)
    if req.focus_lost_count:
        itv.focus_lost_count = max(itv.focus_lost_count, req.focus_lost_count)
    if req.conversation_id and not itv.conversation_id:
        itv.conversation_id = req.conversation_id
    if itv.status == "completed":
        await db.commit()
        return {"ok": True, "status": "completed"}

    conversation_id = req.conversation_id or itv.conversation_id
    turns: list[dict] = []
    for _ in range(6):
        try:
            conv = await elevenlabs.get_conversation(conversation_id)
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


@router.post("/v1/join/{token}/finish")
async def finish(token: str, background: BackgroundTasks,
                 db: AsyncSession = Depends(get_db)) -> dict:
    itv = await _load_joinable(db, token)
    if itv.status != "completed":
        if not itv.transcript and itv.conversation_id:
            try:
                conv = await elevenlabs.get_conversation(itv.conversation_id)
                turns = [
                    {"role": "interviewer" if m.get("role") == "agent" else "candidate",
                     "text": (m.get("message") or "").strip()}
                    for m in (conv.get("transcript") or []) if (m.get("message") or "").strip()
                ]
                if turns:
                    itv.transcript = turns
            except elevenlabs.ElevenLabsError:
                pass
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
