"""Company-facing web pages: landing, auth, dashboard, interview detail.

Server-rendered (Jinja2) with session-cookie auth — minimal JS by design.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import mailer
from ..accounts import current_company, hash_password, verify_password
from ..config import get_settings
from ..db import Company, Interview, new_token
from ..deps import get_db
from ..schemas import InterviewReport
from ..templating import templates

router = APIRouter(tags=["web"])


def _render(request: Request, template: str, company=None, **ctx) -> HTMLResponse:
    ctx.update(app_name=get_settings().app_name, company=company)
    return templates.TemplateResponse(request, template, ctx)


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---------- public ----------

@router.get("/", response_class=HTMLResponse)
async def landing(request: Request, company: Company | None = Depends(current_company)):
    return _render(request, "landing.html", company=company)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, company: Company | None = Depends(current_company)):
    if company:
        return _redirect("/dashboard")
    return _render(request, "register.html")


def _send_verify(background: BackgroundTasks, company: Company) -> None:
    url = f"{get_settings().public_base_url.rstrip('/')}/verify?token={company.verify_token}"
    subj, html = mailer.verify_email(company.name, url)
    background.add_task(mailer.send_email, company.email, subj, html)


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    background: BackgroundTasks,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    if len(password) < 8:
        return _render(request, "register.html", error="Password must be at least 8 characters.", name=name, email=email)
    exists = (await db.execute(select(Company).where(Company.email == email))).scalar_one_or_none()
    if exists:
        return _render(request, "register.html", error="That email is already registered.", name=name, email=email)
    company = Company(name=name.strip(), email=email, password_hash=hash_password(password),
                      verified=False, verify_token=new_token())
    db.add(company)
    await db.commit()
    _send_verify(background, company)
    return _render(request, "verify_sent.html", email=company.email)


@router.get("/verify")
async def verify(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    if token:
        company = (await db.execute(select(Company).where(Company.verify_token == token))).scalar_one_or_none()
        if company:
            company.verified = True
            company.verify_token = ""
            await db.commit()
            request.session["company_id"] = company.id
            return _redirect("/dashboard")
    return _render(request, "login.html", error="That verification link is invalid or already used.")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, company: Company | None = Depends(current_company)):
    if company:
        return _redirect("/dashboard")
    return _render(request, "login.html")


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    company = (await db.execute(select(Company).where(Company.email == email))).scalar_one_or_none()
    if not company or not verify_password(password, company.password_hash):
        return _render(request, "login.html", error="Wrong email or password.", email=email)
    if not company.verified:
        if not company.verify_token:
            company.verify_token = new_token()
            await db.commit()
        _send_verify(background, company)
        return _render(request, "login.html", email=email,
                       error="Your email isn't verified yet — we just re-sent the link.")
    request.session["company_id"] = company.id
    return _redirect("/dashboard")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return _redirect("/")


# ---------- dashboard (auth required) ----------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, company: Company | None = Depends(current_company),
                    db: AsyncSession = Depends(get_db)):
    if not company:
        return _redirect("/login")
    rows = (await db.execute(
        select(Interview).where(Interview.company_id == company.id).order_by(Interview.created_at.desc())
    )).scalars().all()
    return _render(request, "dashboard.html", company=company, interviews=rows)


@router.post("/interviews/new")
async def create_interview_web(
    request: Request,
    background: BackgroundTasks,
    candidate_name: str = Form(...),
    candidate_email: str = Form(...),
    role: str = Form(...),
    interviewer_name: str = Form(""),
    job_description: str = Form(""),
    language: str = Form("English"),
    max_minutes: int = Form(15),
    scheduled_at: str = Form(""),
    company: Company | None = Depends(current_company),
    db: AsyncSession = Depends(get_db),
):
    if not company:
        return _redirect("/login")

    when = None
    if scheduled_at.strip():
        try:
            when = datetime.fromisoformat(scheduled_at.strip())
        except ValueError:
            when = None

    itv = Interview(
        company_id=company.id,
        client_name=company.name,
        company=company.name,
        candidate_name=candidate_name.strip(),
        candidate_email=candidate_email.strip(),
        interviewer_name=interviewer_name.strip(),
        role=role.strip() or "the role",
        job_description=job_description.strip(),
        language=language.strip() or "English",
        max_minutes=max_minutes,
        scheduled_at=when,
    )
    db.add(itv)
    await db.commit()

    subject, html = mailer.invite_email(
        itv.candidate_name, company.name, itv.role, itv.join_url, when, itv.max_minutes
    )
    ics = None
    if when:
        ics = mailer.build_ics(
            uid=f"{itv.id}@interview", title=f"Interview — {itv.role} at {company.name}",
            description=f"Join your interview: {itv.join_url}", location=itv.join_url,
            start=when, minutes=itv.max_minutes,
        )
    background.add_task(mailer.send_email, itv.candidate_email, subject, html, ics)
    return _redirect("/dashboard")


@router.get("/interviews/{interview_id}", response_class=HTMLResponse)
async def interview_detail(interview_id: str, request: Request,
                           company: Company | None = Depends(current_company),
                           db: AsyncSession = Depends(get_db)):
    if not company:
        return _redirect("/login")
    itv = await db.get(Interview, interview_id)
    if not itv or itv.company_id != company.id:
        return _render(request, "detail.html", company=company, it=None, report=None)
    report = InterviewReport.model_validate(itv.report) if itv.report else None
    return _render(request, "detail.html", company=company, it=itv, report=report)
