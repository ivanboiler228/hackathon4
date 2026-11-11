from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)


class Source(BaseModel):
    id: str
    title: str
    date: str
    acl: str


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
