from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    # Если список задан, ассистент отвечает только по выбранным источникам.
    doc_ids: list[str] | None = None
    # Иначе можно спросить по всей папке или по своим загрузкам.
    folder_id: str | None = None
    mine: bool = False


class Source(BaseModel):
    id: str
    title: str
    date: str
    acl: str
    fragment: str = ""


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    masked_preview: str
    pii_found: dict[str, int] = Field(default_factory=dict)
    placeholders: list[str] = Field(default_factory=list)
    used_llm: bool = False
    llm_error: str | None = None


class SwitchRequest(BaseModel):
    user_id: str | None = None


class AuditItem(BaseModel):
    id: int
    ts: str
    user_id: str
    role: str
    action: str
    obj: str
    result: str
    masked_preview: str
    meta: dict = Field(default_factory=dict)


class FolderCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    acl: str = Field("all", pattern="^(all|fin|hr|prod|mkt|support|legal)$")


class FolderUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=80)
    acl: str | None = Field(None, pattern="^(all|fin|hr|prod|mkt|support|legal)$")


class DocUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    text: str | None = Field(None, min_length=1, max_length=200_000)
    folder_id: str | None = None
    acl: str | None = Field(None, pattern="^(all|fin|hr|prod|mkt|support|legal)$")


class MeetingTaskItem(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    owner: str | None = None
    deadline: str | None = None
    basis: str | None = None


class MeetingTasksRequest(BaseModel):
    items: list[MeetingTaskItem]
    confirm: bool = False


class MeetingProtocol(BaseModel):
    decided: list[str] = Field(default_factory=list)
    proposed: list[str] = Field(default_factory=list)
    discussed: list[str] = Field(default_factory=list)
    needs_clarification: list[str] = Field(default_factory=list)


class MeetingEditRequest(BaseModel):
    transcript: str | None = Field(None, max_length=100_000)
    summary: str | None = Field(None, max_length=10_000)
    protocol: MeetingProtocol | None = None
    tasks: list[dict[str, Any]] | None = None
    risks: list[str] | None = None
    feedback: dict[str, Any] | None = None


class MeetingFeedbackRequest(BaseModel):
    verdict: str = Field(..., pattern="^(useful|inaccurate)$")
    comment: str = Field("", max_length=1000)


class TaskStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(new|progress|review|done)$")
    owner_id: str | None = None


class CalendarEventIn(BaseModel):
    id: str = Field(..., max_length=40)
    title: str = Field(..., max_length=300)
    date: str = Field(..., max_length=10)
    start: float
    end: float
    people: list[str] = Field(default_factory=list)
    place: str = Field("", max_length=300)
    cal: str = Field("meet", max_length=20)


class CalendarTaskIn(BaseModel):
    id: str = Field(..., max_length=40)
    title: str = Field(..., max_length=300)
    owner: str | None = None
    co: list[str] = Field(default_factory=list)
    deadline: str | None = None
    status: str = Field("new", max_length=20)
    prio: str = Field("P3", max_length=4)
    created: str | None = None


class BusyBlockIn(BaseModel):
    person: str = Field(..., max_length=40)
    date: str = Field(..., max_length=10)
    start: float
    end: float


class CalendarAdviceRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1500)
    date_from: str | None = None
    date_to: str | None = None
    focus_event_id: str | None = None
    events: list[CalendarEventIn] = Field(default_factory=list, max_length=500)
    tasks: list[CalendarTaskIn] = Field(default_factory=list, max_length=500)
    busy: list[BusyBlockIn] = Field(default_factory=list, max_length=1000)


class OverviewMeetingIn(BaseModel):
    id: str = Field(..., max_length=40)
    title: str = Field(..., max_length=300)
    date: str = Field("", max_length=10)
    summary: str = Field("", max_length=2000)
    created_by: str = Field("", max_length=40)
    decisions_count: int = 0
    tasks_count: int = 0
    risks_count: int = 0


class OverviewRequest(BaseModel):
    question: str = Field(
        "Дай управленческий обзор: что горит, кто перегружен и что делегировать.",
        min_length=1,
        max_length=1500,
    )
    tasks: list[CalendarTaskIn] = Field(default_factory=list, max_length=500)
    events: list[CalendarEventIn] = Field(default_factory=list, max_length=500)
    meetings: list[OverviewMeetingIn] = Field(default_factory=list, max_length=200)
    pending_requests: int = 0
    audit_denials: int = 0
