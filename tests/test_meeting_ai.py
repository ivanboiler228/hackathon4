import asyncio
import json

from app import db, meeting_ai


def test_meeting_title_is_masked_before_deepseek(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Коротко.",
                                    "decided": [],
                                    "proposed": [],
                                    "discussed": [],
                                    "needs_clarification": [],
                                    "tasks": [],
                                    "risks": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(meeting_ai.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(meeting_ai.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(
        meeting_ai.summarize(
            "Коллеги, Иван подготовит график на +375291112233.",
            "Встреча с Иваном Петровым",
        )
    )
    user_text = captured["payload"]["messages"][-1]["content"]
    assert "Иван" not in user_text
    assert "+375291112233" not in user_text
    assert "⟦PERSON_1⟧" in user_text
    assert "⟦PHONE_1⟧" in user_text
    assert result["used_llm"] is True


def test_fallback_summary_is_local():
    result = meeting_ai.fallback_summary("Игорь подготовит график смен до пятницы.", "disabled")
    assert result["used_llm"] is False
    assert "Игорь" in result["summary"]
    assert result["llm_error"] == "disabled"


def test_new_recording_resets_previous_edits_and_feedback(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.db_path", tmp_path / "meetings2.db")
    db.init_db()
    base = {
        "summary": "Черновик",
        "decisions": [],
        "tasks": [],
        "risks": [],
        "open_questions": [],
        "used_llm": False,
    }
    db.save_meeting_ai("E-RESET", "Встреча", "Текст", base, created_by="anna")
    db.update_meeting_ai(
        "E-RESET",
        summary="Исправлено",
        feedback={"verdict": "useful", "comment": "ок"},
    )
    db.save_meeting_ai("E-RESET", "Встреча", "Новый текст", base, created_by="anna")
    item = db.get_meeting_ai("E-RESET")
    assert item["summary"] == "Черновик"
    assert item["edited_at"] == ""
    assert item["feedback"] == {}


def test_meeting_ai_is_saved_and_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.db_path", tmp_path / "meetings.db")
    db.init_db()
    result = {
        "summary": "Обсудили запуск ночной смены.",
        "decisions": ["Запустить смену"],
        "tasks": [{"title": "Подготовить график", "owner": "Игорь", "deadline": None}],
        "risks": [],
        "open_questions": ["Кто сверит бумагу?"],
        "used_llm": True,
        "llm_error": None,
    }
    saved = db.save_meeting_ai("E-99", "Тестовая встреча", "Расшифровка", result)
    assert saved["event_id"] == "E-99"
    assert saved["used_llm"] is True
    loaded = db.get_meeting_ai("E-99")
    assert loaded["tasks"][0]["owner"] == "Игорь"
    assert loaded["open_questions"] == ["Кто сверит бумагу?"]
