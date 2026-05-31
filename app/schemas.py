"""Pydantic schemas: API shapes + the engine's structured-output contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- B2B: create interview ----------

class CreateInterviewRequest(BaseModel):
    candidate_name: str = Field(default="Candidate", max_length=120)
    company: str = Field(default="", max_length=120,
                         description="Hiring company name. Defaults to the API key's client.")
    interviewer_name: str = Field(default="", max_length=80,
                                  description="The AI interviewer's name. Defaults to 'Alex'.")
    role: str = Field(default="the role", max_length=200,
                      description="Job title the candidate is interviewing for.")
    job_description: str = Field(default="", max_length=8000)
    language: str = Field(default="English", max_length=40)
    max_minutes: int = Field(default=15, ge=3, le=60)
    focus_areas: list[str] = Field(
        default_factory=list,
        description="Optional themes to probe, e.g. ['leadership', 'system design'].",
    )


class InterviewCreated(BaseModel):
    interview_id: str
    join_url: str
    status: str
    expires_at: datetime


# ---------- Candidate: conduct interview ----------

class InterviewMeta(BaseModel):
    """Public info the join page needs (no secrets)."""
    candidate_name: str
    role: str
    language: str
    max_minutes: int
    status: str


class ConnectResponse(BaseModel):
    """What the browser needs to start the realtime ElevenLabs agent session."""
    signed_url: str
    dynamic_variables: dict


class CompleteRequest(BaseModel):
    conversation_id: str


# ---------- B2B: results ----------

class CompetencyScore(BaseModel):
    competency: str
    score: int = Field(ge=0, le=5)
    evidence: str


class InterviewReport(BaseModel):
    overall: int = Field(ge=0, le=100)
    recommendation: Literal["strong_yes", "yes", "maybe", "no"]
    scores: list[CompetencyScore]
    strengths: list[str]
    concerns: list[str]
    summary: str


class InterviewResult(BaseModel):
    interview_id: str
    status: str
    candidate_name: str
    role: str
    transcript: list[dict]
    report: Optional[InterviewReport] = None


# ---------- Engine <-> LLM structured outputs ----------

class OpeningPlan(BaseModel):
    """Generated once at the start: the spoken opening line + a hidden topic plan
    that guides (but doesn't script) the rest of the conversation."""
    opening: str = Field(description="The first spoken line: greet candidate by name, introduce yourself + company, ask the opening question.")
    plan: list[str] = Field(description="3-7 topics/questions to cover, as private guidance. Never read verbatim.")


class InterviewerTurn(BaseModel):
    """The interviewer's next spoken line, reacting to what the candidate said."""
    say: str = Field(description="What the interviewer says aloud next. Natural, concise, one turn.")
    end_interview: bool = Field(default=False, description="True only on the closing turn.")
