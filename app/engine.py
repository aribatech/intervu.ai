from __future__ import annotations

from .clients import brain
from .db import Interview
from .schemas import InterviewReport, LiveNotes

REPORT_SYSTEM = """\
You are an interview evaluator. Score the candidate against the rubric using ONLY \
evidence from the transcript. Every score must cite concrete evidence (quote or \
closely paraphrase what they said). Be fair and consistent; do not invent \
evidence. If something wasn't demonstrated, score it low and say so.

Competencies (0-5 each):
- communication: clarity, structure, listening.
- role_fit: relevance of experience to the role.
- depth: substance and specifics vs. vagueness.
- problem_solving: reasoning about real situations.
- motivation: engagement and interest in the role.
"""

NOTES_SYSTEM = """\
You are a note-taker sitting in on a live interview. From the transcript so far, \
write 3-6 short, factual bullet points capturing the key things the candidate has \
revealed: concrete experience, skills, projects, decisions, and any notable gaps. \
Be neutral and specific - no scoring, no praise, no speculation. If little has been \
said yet, return fewer bullets. Each bullet is one short line.
"""


def _blob_from_turns(turns: list[dict]) -> str:
    lines = "\n".join(f"{t['role']}: {t['text']}" for t in turns)
    return lines or "(no conversation took place)"


def _transcript_blob(itv: Interview) -> str:
    return _blob_from_turns(itv.transcript)


async def build_notes(role: str, job_description: str, turns: list[dict]) -> list[str]:
    user = (
        f"ROLE: {role}\n"
        f"JOB DESCRIPTION:\n{job_description or '(none)'}\n\n"
        f"TRANSCRIPT SO FAR:\n{_blob_from_turns(turns)}\n\n"
        "Write the running notes now."
    )
    result = await brain.parse(
        system=NOTES_SYSTEM, user=user, schema=LiveNotes, max_tokens=800
    )
    return [n.strip() for n in result.notes if n.strip()]


async def build_report(itv: Interview) -> InterviewReport:
    user = (
        f"ROLE: {itv.role}\n"
        f"JOB DESCRIPTION:\n{itv.job_description or '(none)'}\n\n"
        f"FULL TRANSCRIPT:\n{_transcript_blob(itv)}\n\n"
        "Produce the scored report now. overall is 0-100. recommendation is one "
        "of strong_yes, yes, maybe, no. Cite evidence for every competency."
    )
    return await brain.parse(
        system=REPORT_SYSTEM, user=user, schema=InterviewReport, max_tokens=6000
    )
