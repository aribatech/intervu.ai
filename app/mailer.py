"""Email sending (SMTP) with a console fallback for dev.

If SMTP_HOST is not configured, emails are printed to the console instead of
being sent — so the app works end-to-end without a mail server.
"""
from __future__ import annotations

import asyncio
import smtplib
import socket
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import quote

from .config import get_settings


class _IPv4Only:
    """Force IPv4 DNS during SMTP — avoids 'Network is unreachable' on hosts with
    no IPv6 route (Gmail resolves to IPv6 first). Scoped + restored."""
    def __enter__(self):
        self._orig = socket.getaddrinfo
        socket.getaddrinfo = lambda host, port, family=0, *a, **k: \
            self._orig(host, port, socket.AF_INET, *a, **k)

    def __exit__(self, *exc):
        socket.getaddrinfo = self._orig


def _send_sync(to: str, subject: str, html: str, ics: str | None) -> None:
    s = get_settings()
    if not s.email_enabled:
        extra = "  (+calendar.ics attached)" if ics else ""
        print(f"\n[email:console] to={to} | subject={subject}{extra}\n{_strip(html)}\n")
        return
    msg = EmailMessage()
    msg["From"] = s.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(_strip(html))
    msg.add_alternative(html, subtype="html")
    if ics:
        msg.add_attachment(ics.encode(), maintype="text", subtype="calendar",
                           filename="interview.ics", params={"method": "REQUEST"})

    # SSL (port 465) vs STARTTLS (port 587). STARTTLS implied when smtp_starttls=true.
    use_ssl = not s.smtp_starttls
    SMTPClass = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with _IPv4Only():
        with SMTPClass(s.smtp_host, s.smtp_port, timeout=20) as server:
            if not use_ssl and s.smtp_starttls:
                server.starttls()
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)


def _strip(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


async def send_email(to: str, subject: str, html: str, ics: str | None = None) -> None:
    if not to:
        return
    try:
        await asyncio.to_thread(_send_sync, to, subject, html, ics)
    except Exception as e:  # never let email failure break the request
        print(f"[email:error] to={to}: {e}")


# ---------- calendar helpers ----------

def _floating(dt: datetime) -> str:
    """Local 'floating' calendar time (shown in the viewer's own timezone)."""
    return dt.strftime("%Y%m%dT%H%M%S")


def build_ics(uid: str, title: str, description: str, location: str,
              start: datetime, minutes: int) -> str:
    end = start + timedelta(minutes=minutes)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    desc = description.replace("\n", "\\n")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI Interviewer//EN",
        "CALSCALE:GREGORIAN", "METHOD:REQUEST",
        "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
        f"DTSTART:{_floating(start)}", f"DTEND:{_floating(end)}",
        f"SUMMARY:{title}", f"DESCRIPTION:{desc}", f"URL:{location}",
        f"LOCATION:{location}", "END:VEVENT", "END:VCALENDAR",
    ])


def gcal_link(title: str, details: str, location: str, start: datetime, minutes: int) -> str:
    end = start + timedelta(minutes=minutes)
    q = {
        "action": "TEMPLATE", "text": title,
        "dates": f"{_floating(start)}/{_floating(end)}",
        "details": details, "location": location,
    }
    return "https://calendar.google.com/calendar/render?" + "&".join(
        f"{k}={quote(str(v))}" for k, v in q.items()
    )


# ---------- templates ----------

def _wrap(title: str, body: str) -> str:
    app = get_settings().app_name
    return (
        f'<div style="font-family:system-ui,sans-serif;max-width:520px;margin:auto;'
        f'color:#111;line-height:1.6">'
        f'<h2 style="margin:0 0 12px">{title}</h2>{body}'
        f'<p style="color:#888;font-size:12px;margin-top:24px">— {app}</p></div>'
    )


def invite_email(candidate_name: str, company: str, role: str, join_url: str,
                 scheduled_at: datetime | None = None, minutes: int = 15) -> tuple[str, str]:
    subject = f"Your interview for {role} at {company}"
    when = ""
    cal = ""
    if scheduled_at:
        pretty = scheduled_at.strftime("%A, %d %B %Y at %I:%M %p")
        when = f"<p>It's scheduled for <b>{pretty}</b> (your local time).</p>"
        link = gcal_link(f"Interview — {role} at {company}",
                         f"Join your interview: {join_url}", join_url, scheduled_at, minutes)
        cal = (
            f'<p style="margin-top:8px"><a href="{link}" target="_blank" '
            f'style="color:#2563eb">Add to Google Calendar</a> '
            f'<span style="color:#888;font-size:13px">— or open the attached .ics</span></p>'
        )
    body = (
        f"<p>Hi {candidate_name},</p>"
        f"<p>You've been invited to a short voice interview for the "
        f"<b>{role}</b> role at <b>{company}</b>.</p>"
        f"{when}"
        f"<p>Join here when it's time:</p>"
        f'<p><a href="{join_url}" style="background:#111;color:#fff;padding:10px 18px;'
        f'text-decoration:none;display:inline-block">Join the interview</a></p>'
        f"{cal}"
        f'<p style="font-size:13px;color:#666">Or paste this link: {join_url}</p>'
    )
    return subject, _wrap("You're invited to an interview", body)


def verify_email(name: str, verify_url: str) -> tuple[str, str]:
    subject = "Verify your email"
    body = (
        f"<p>Hi {name},</p>"
        f"<p>Confirm your email to activate your account.</p>"
        f'<p><a href="{verify_url}" style="background:#111;color:#fff;padding:10px 18px;'
        f'text-decoration:none;display:inline-block">Verify email</a></p>'
        f'<p style="font-size:13px;color:#666">Or paste this link: {verify_url}</p>'
    )
    return subject, _wrap("Confirm your email", body)


def candidate_done_email(candidate_name: str, company: str, role: str) -> tuple[str, str]:
    subject = f"Thanks for interviewing for {role} at {company}"
    body = (
        f"<p>Hi {candidate_name},</p>"
        f"<p>Thanks for completing your interview for the <b>{role}</b> role at "
        f"<b>{company}</b>. The team will review your responses and be in touch.</p>"
    )
    return subject, _wrap("Interview complete", body)


def company_done_email(candidate_name: str, role: str, recommendation: str,
                       overall: int | None, report_url: str) -> tuple[str, str]:
    subject = f"Interview complete: {candidate_name} — {role}"
    score = f"{overall}/100" if overall is not None else "n/a"
    body = (
        f"<p><b>{candidate_name}</b> completed the interview for <b>{role}</b>.</p>"
        f"<p>Overall: <b>{score}</b> · Recommendation: <b>{recommendation}</b></p>"
        f'<p><a href="{report_url}" style="background:#111;color:#fff;padding:10px 18px;'
        f'text-decoration:none;display:inline-block">View full report</a></p>'
    )
    return subject, _wrap("Candidate finished their interview", body)
