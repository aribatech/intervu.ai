from __future__ import annotations

from .clients import brain
from .db import Interview
from .schemas import InterviewReport

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


def _transcript_blob(itv: Interview) -> str:
    lines = "\n".join(f"{t['role']}: {t['text']}" for t in itv.transcript)
    return lines or "(no conversation took place)"


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
