from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


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


class InterviewMeta(BaseModel):
    candidate_name: str
    role: str
    language: str
    max_minutes: int
    status: str


class ConnectResponse(BaseModel):
    signed_url: str
    dynamic_variables: dict


class SessionRequest(BaseModel):
    conversation_id: str = Field(default="", max_length=200)


class CompleteRequest(BaseModel):
    conversation_id: str
    focus_lost_count: int = Field(default=0, ge=0)


class TranscriptTurn(BaseModel):
    role: str = Field(max_length=20)
    text: str = Field(max_length=4000)


class NotesRequest(BaseModel):
    transcript: list[TranscriptTurn] = Field(default_factory=list)


class NotesResponse(BaseModel):
    notes: list[str]


class LiveNotes(BaseModel):
    notes: list[str] = Field(
        description="3-6 short bullet points capturing the key facts, claims, and signals "
        "the candidate has revealed so far. Neutral, factual, no scoring."
    )


class FeedbackRequest(BaseModel):
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    comment: str = Field(default="", max_length=2000)
    focus_lost_count: int = Field(default=0, ge=0)


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


class OpeningPlan(BaseModel):
    opening: str = Field(description="The first spoken line: greet candidate by name, introduce yourself + company, ask the opening question.")
    plan: list[str] = Field(description="3-7 topics/questions to cover, as private guidance. Never read verbatim.")


class InterviewerTurn(BaseModel):
    say: str = Field(description="What the interviewer says aloud next. Natural, concise, one turn.")
    end_interview: bool = Field(default=False, description="True only on the closing turn.")
