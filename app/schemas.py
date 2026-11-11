from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    # Если список задан, ассистент отвечает только по выбранным источникам.
    doc_ids: list[str] | None = None


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
