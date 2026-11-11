from app import db, meeting_ai


def test_fallback_summary_is_local():
    result = meeting_ai.fallback_summary("Игорь подготовит график смен до пятницы.", "disabled")
    assert result["used_llm"] is False
    assert "Игорь" in result["summary"]
    assert result["llm_error"] == "disabled"


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
