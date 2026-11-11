from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import calendar_ai, db
from app.config import settings
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "calendar.db")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    db.init_db()
    with TestClient(app) as test_client:
        test_client.get("/")
        yield test_client


def _event(event_id, title, day, start, end, people, cal="meet"):
    return {
        "id": event_id,
        "title": title,
        "date": day,
        "start": start,
        "end": end,
        "people": people,
        "place": "",
        "cal": cal,
    }


def _task(task_id, title, owner, deadline, status="new"):
    return {
        "id": task_id,
        "title": title,
        "owner": owner,
        "co": [],
        "deadline": deadline,
        "status": status,
        "prio": "P2",
        "created": "anna",
    }


def test_calendar_advice_returns_context_and_slots(client):
    payload = {
        "question": "Где найти два часа на фокус?",
        "date_from": "2026-11-12",
        "date_to": "2026-11-13",
        "events": [
            _event("E-1", "Планёрка", "2026-11-12", 9, 10, ["anna", "igor"]),
            _event("E-2", "Бюджет", "2026-11-12", 14, 16, ["anna"]),
        ],
        "tasks": [_task("T-1", "Свести отчёт", "anna", "2026-11-12")],
        "busy": [],
    }
    response = client.post("/api/calendar/advice", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["context"]["events"] == 2
    assert data["context"]["tasks"] == 1
    assert data["context"]["free_slots"]
    assert "Свободные окна" in data["answer"]
    assert data["used_llm"] is False


def test_employee_calendar_context_is_filtered(client):
    client.post("/api/switch-role", json={"user_id": "igor"})
    payload = {
        "question": "Что у меня на неделе?",
        "date_from": "2026-11-12",
        "date_to": "2026-11-13",
        "events": [
            _event("E-1", "Планёрка директора", "2026-11-12", 9, 10, ["anna"]),
            _event("E-2", "Смена", "2026-11-12", 8, 12, ["igor"]),
        ],
        "tasks": [
            _task("T-1", "Чужая задача", "anna", "2026-11-12"),
            _task("T-2", "Моя задача", "igor", "2026-11-13"),
        ],
        "busy": [
            {"person": "anna", "date": "2026-11-12", "start": 10, "end": 11},
            {"person": "igor", "date": "2026-11-12", "start": 12, "end": 13},
        ],
    }
    data = client.post("/api/calendar/advice", json=payload).json()
    assert data["context"]["events"] == 1
    assert data["context"]["tasks"] == 1
    assert data["context"]["free_slots"]


def test_calendar_context_is_masked_before_llm(client, monkeypatch):
    captured = {}

    async def fake_chat(system_prompt, user_prompt, max_tokens=None):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return "Совет для ⟦PERSON_1⟧ готов."

    monkeypatch.setattr(calendar_ai.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(calendar_ai, "call_chat", fake_chat)

    payload = {
        "question": "Что обсудить с Иваном Петровым?",
        "date_from": "2026-11-12",
        "date_to": "2026-11-12",
        "events": [
            _event("E-1", "1:1 с Иваном Петровым", "2026-11-12", 9, 10, ["anna"]),
        ],
        "tasks": [],
        "busy": [],
    }
    data = client.post("/api/calendar/advice", json=payload).json()
    assert data["used_llm"] is True
    assert "Иван" not in captured["user"]
    assert "⟦PERSON_1⟧" in captured["user"]
    assert "Иван" in data["answer"]


def test_calendar_rejects_bad_range(client):
    response = client.post(
        "/api/calendar/advice",
        json={
            "question": "Что делать?",
            "date_from": "2026-11-15",
            "date_to": "2026-11-12",
            "events": [],
            "tasks": [],
            "busy": [],
        },
    )
    assert response.status_code == 400
