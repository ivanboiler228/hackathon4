from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db, overview_ai
from app.config import settings
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "overview.db")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    db.init_db()
    with TestClient(app) as test_client:
        test_client.get("/")
        yield test_client


def _task(task_id, title, owner, deadline, status="new", created="anna", co=None):
    return {
        "id": task_id,
        "title": title,
        "owner": owner,
        "co": co or [],
        "deadline": deadline,
        "status": status,
        "prio": "P2",
        "created": created,
    }


def _meeting(meeting_id, title, created_by, summary="Выжимка"):
    return {
        "id": meeting_id,
        "title": title,
        "date": "2026-11-12",
        "summary": summary,
        "created_by": created_by,
        "decisions_count": 1,
        "tasks_count": 2,
        "risks_count": 1,
    }


def test_company_overview_includes_all_tasks(client):
    payload = {
        "question": "Что горит?",
        "tasks": [
            _task("T-1", "Ночная смена", "igor", "2026-11-13"),
            _task("T-2", "SLA", "maria", "2026-11-10"),
            _task("T-3", "Медиаплан", "olga", "2026-11-20", status="review"),
        ],
        "events": [],
        "meetings": [_meeting("E-1", "Планёрка", "anna")],
        "pending_requests": 2,
        "audit_denials": 1,
    }
    data = client.post("/api/overview/advice", json=payload).json()
    assert data["context"]["scope"] == "company"
    assert data["context"]["tasks"] == 3
    assert data["context"]["overdue"] == 1
    assert data["context"]["meetings"] == 1
    assert data["context"]["docs"] >= 20
    assert "Задач" in data["answer"]
    assert data["used_llm"] is False


def test_employee_overview_is_filtered(client):
    client.post("/api/switch-role", json={"user_id": "igor"})
    payload = {
        "question": "Что у меня?",
        "tasks": [
            _task("T-1", "Моя задача", "igor", "2026-11-13"),
            _task("T-2", "Чужая задача", "maria", "2026-11-13"),
        ],
        "events": [],
        "meetings": [
            _meeting("E-1", "Моя встреча", "igor"),
            _meeting("E-2", "Чужая встреча", "anna"),
        ],
        "pending_requests": 0,
        "audit_denials": 0,
    }
    data = client.post("/api/overview/advice", json=payload).json()
    assert data["context"]["scope"] == "personal"
    assert data["context"]["tasks"] == 1
    assert data["context"]["meetings"] == 1
    assert data["context"]["docs"] < 21


def test_overview_is_masked_before_llm(client, monkeypatch):
    captured = {}

    async def fake_chat(system_prompt, user_prompt, max_tokens=None):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return "Ответ для ⟦PERSON_1⟧."

    monkeypatch.setattr(overview_ai.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(overview_ai, "call_chat", fake_chat)

    payload = {
        "question": "Что с Иваном Петровым?",
        "tasks": [_task("T-1", "Позвонить Ивану Петрову", "ivan", "2026-11-12")],
        "events": [
            {
                "id": "E-1",
                "title": "Встреча с Иваном Петровым",
                "date": "2026-11-12",
                "start": 9,
                "end": 10,
                "people": ["ivan"],
                "place": "Офис",
                "cal": "meet",
            }
        ],
        "meetings": [_meeting("E-1", "1:1 с Иваном Петровым", "anna")],
        "pending_requests": 0,
        "audit_denials": 0,
    }
    data = client.post("/api/overview/advice", json=payload).json()
    assert data["used_llm"] is True
    assert "Иван" not in captured["user"]
    assert "⟦PERSON_1⟧" in captured["user"]
    assert "Иван" in data["answer"]
