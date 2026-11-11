from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app import db, documents
from app.config import settings
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "docs.db")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    db.init_db()
    with TestClient(app) as test_client:
        test_client.get("/")
        yield test_client


def _switch(client: TestClient, user_id: str) -> None:
    r = client.post("/api/switch-role", json={"user_id": user_id})
    assert r.status_code == 200


def test_health_reports_llm_and_stt(client):
    data = client.get("/health").json()
    assert data["llm"]["provider"] == "DeepSeek"
    assert data["llm"]["model"] == settings.deepseek_model
    assert data["stt"]["local"] is True


def test_docs_have_folders_and_respect_acl(client):
    items = client.get("/api/docs").json()["items"]
    assert len(items) >= 20
    assert any(item["id"] == "D-01" and item["folder_id"] for item in items)

    _switch(client, "igor")
    employee_items = client.get("/api/docs").json()["items"]
    assert all(item["id"] != "D-12" for item in employee_items)
    folders = client.get("/api/folders").json()["items"]
    assert all(folder["id"] != "F-FIN" for folder in folders)


def test_boss_uploads_edits_and_deletes_document(client):
    response = client.post(
        "/api/docs",
        files={"file": ("note.txt", "Ночная смена стартует в неделю 48.".encode(), "text/plain")},
        data={"acl": "prod", "folder_id": "F-PROD", "title": "Заметка о смене"},
    )
    assert response.status_code == 200
    doc = response.json()
    assert doc["id"].startswith("U-")
    assert doc["source_type"] == "upload"
    assert doc["created_by"] == "anna"

    edited = client.patch(f"/api/docs/{doc['id']}", json={"title": "Заметка о ночной смене"})
    assert edited.status_code == 200
    assert edited.json()["title"] == "Заметка о ночной смене"

    deleted = client.delete(f"/api/docs/{doc['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/docs/{doc['id']}").status_code == 404


def test_employee_cannot_upload_or_create_folder(client):
    _switch(client, "igor")
    upload = client.post(
        "/api/docs",
        files={"file": ("note.txt", b"text", "text/plain")},
        data={"acl": "all"},
    )
    assert upload.status_code == 403
    folder = client.post("/api/folders", json={"title": "Секреты", "acl": "all"})
    assert folder.status_code == 403


def test_sample_email_subject_and_body_are_decoded():
    data = (Path(__file__).resolve().parent.parent / "sample_docs" / "08_client_email.eml").read_bytes()
    title, text = documents.parse_email_bytes(data)
    assert "Сроки поставки" in title
    assert "Иван Петров" in text
    assert "+375291112233" in text
    assert "=?utf-8?" not in text


def test_boss_creates_folder(client):
    response = client.post("/api/folders", json={"title": "Договоры", "acl": "legal"})
    assert response.status_code == 200
    folder = response.json()
    assert folder["title"] == "Договоры"
    assert folder["acl"] == "legal"
    folders = client.get("/api/folders").json()["items"]
    assert any(item["id"] == folder["id"] for item in folders)


def test_each_builtin_folder_accepts_matching_documents(client):
    pairs = [
        ("F-REG", "all"),
        ("F-SUP", "support"),
        ("F-PROD", "prod"),
        ("F-MKT", "mkt"),
        ("F-FIN", "fin"),
        ("F-HR", "hr"),
        ("F-LEGAL", "legal"),
    ]
    created = []
    for index, (folder_id, acl) in enumerate(pairs):
        response = client.post(
            "/api/docs",
            files={"file": (f"note{index}.txt", b"text", "text/plain")},
            data={"acl": acl, "folder_id": folder_id, "title": f"Документ {folder_id}"},
        )
        assert response.status_code == 200, response.text
        doc = response.json()
        assert doc["folder_id"] == folder_id
        created.append(doc["id"])

    client.post("/api/switch-role", json={"user_id": "igor"})
    visible = {item["id"] for item in client.get("/api/docs").json()["items"]}
    assert created[0] in visible  # all
    assert created[1] not in visible  # support
    assert created[2] in visible  # prod
    assert created[3] not in visible  # mkt
    assert created[4] not in visible  # fin
    assert created[5] not in visible  # hr
    assert created[6] not in visible  # legal


def test_folder_can_be_renamed_and_deleted_when_empty(client):
    folder = client.post("/api/folders", json={"title": "Временная", "acl": "all"}).json()
    renamed = client.patch(f"/api/folders/{folder['id']}", json={"title": "Постоянная", "acl": "legal"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Постоянная"
    assert renamed.json()["acl"] == "legal"
    deleted = client.delete(f"/api/folders/{folder['id']}")
    assert deleted.status_code == 200
    assert client.patch(f"/api/folders/{folder['id']}", json={"title": "Нет"}).status_code == 404


def test_folder_with_documents_cannot_change_acl_or_be_deleted(client):
    folder = client.post("/api/folders", json={"title": "С документами", "acl": "all"}).json()
    client.post(
        "/api/docs",
        files={"file": ("note.txt", b"text", "text/plain")},
        data={"acl": "all", "folder_id": folder["id"]},
    )
    blocked_acl = client.patch(f"/api/folders/{folder['id']}", json={"acl": "fin"})
    assert blocked_acl.status_code == 400
    blocked_delete = client.delete(f"/api/folders/{folder['id']}")
    assert blocked_delete.status_code == 400
    renamed = client.patch(f"/api/folders/{folder['id']}", json={"title": "Переименована"})
    assert renamed.status_code == 200


def test_email_becomes_source_in_mail_folder(client):
    response = client.post(
        "/api/docs",
        data={
            "email_subject": "Сроки поставки",
            "email_from": "client@example.by",
            "email_body": "Просим подтвердить отгрузку до пятницы.",
            "folder_id": "F-MAIL",
            "acl": "all",
        },
    )
    assert response.status_code == 200
    doc = response.json()
    assert doc["source_type"] == "email"
    assert doc["folder_id"] == "F-MAIL"
    assert "client@example.by" in doc["text"]


def test_assistant_uses_only_selected_sources(client):
    uploaded = client.post(
        "/api/docs",
        files={"file": ("pick.txt", "Запуск ночной смены в неделю 48. Ответственный Игорь.".encode(), "text/plain")},
        data={"acl": "prod", "folder_id": "F-PROD"},
    ).json()
    response = client.post(
        "/api/assistant/ask",
        json={"q": "Когда запускается ночная смена?", "doc_ids": [uploaded["id"]]},
    )
    assert response.status_code == 200
    data = response.json()
    assert [source["id"] for source in data["sources"]] == [uploaded["id"]]
    assert data["sources"][0]["fragment"]
    assert "48" in data["answer"]


def test_assistant_can_analyze_folder_and_my_uploads(client):
    folder = client.post("/api/folders", json={"title": "Анализ папки", "acl": "all"}).json()
    uploaded = client.post(
        "/api/docs",
        files={"file": ("inside.txt", "В папке лежит регламент ночной смены недели 48.".encode(), "text/plain")},
        data={"acl": "all", "folder_id": folder["id"], "title": "Документ внутри папки"},
    ).json()

    by_folder = client.post(
        "/api/assistant/ask",
        json={"q": "Проанализируй документы в этой папке", "folder_id": folder["id"]},
    )
    assert by_folder.status_code == 200
    assert [source["id"] for source in by_folder.json()["sources"]] == [uploaded["id"]]
    assert "Документ внутри папки" in by_folder.json()["answer"]
    assert uploaded["id"] not in by_folder.json()["answer"]

    mine = client.post(
        "/api/assistant/ask",
        json={"q": "Что в моих загрузках?", "mine": True},
    )
    assert mine.status_code == 200
    assert uploaded["id"] in [source["id"] for source in mine.json()["sources"]]

    empty = client.post("/api/folders", json={"title": "Пустая папка", "acl": "all"}).json()
    empty_answer = client.post(
        "/api/assistant/ask",
        json={"q": "Что тут?", "folder_id": empty["id"]},
    )
    assert empty_answer.status_code == 200
    assert "пока нет документов" in empty_answer.json()["answer"]


def test_custom_document_citation_is_humanized(client, monkeypatch):
    uploaded = client.post(
        "/api/docs",
        files={"file": ("named.txt", "Регламент ночной смены.".encode(), "text/plain")},
        data={"acl": "all", "folder_id": "F-REG", "title": "Ночная смена: регламент"},
    ).json()

    async def fake_deepseek(question, docs, note=""):
        return f"Смотри документ [{uploaded['id']}]."

    monkeypatch.setattr("app.main.call_deepseek", fake_deepseek)
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")

    response = client.post(
        "/api/assistant/ask",
        json={"q": "Что в регламенте?", "doc_ids": [uploaded["id"]]},
    )
    assert response.status_code == 200
    answer = response.json()["answer"]
    assert uploaded["id"] not in answer
    assert "Ночная смена: регламент" in answer


def test_employee_cannot_analyze_closed_folder(client):
    _switch(client, "igor")
    response = client.post(
        "/api/assistant/ask",
        json={"q": "Что в финансах?", "folder_id": "F-FIN"},
    )
    assert response.status_code == 403


def test_selected_forbidden_source_is_denied_and_audited(client):
    _switch(client, "igor")
    response = client.post(
        "/api/assistant/ask",
        json={"q": "Что в финплане?", "doc_ids": ["D-12"]},
    )
    assert response.status_code == 403
    audit = client.get("/api/audit").json()["items"]
    assert any(item["action"] == "assistant.doc_denied" for item in audit)


def test_audit_meta_masks_document_title(client):
    doc = client.post(
        "/api/docs",
        files={"file": ("note.txt", b"text", "text/plain")},
        data={"acl": "all", "folder_id": "F-REG", "title": "Заметка Ивана Петрова"},
    ).json()
    audit = client.get("/api/audit").json()["items"]
    upload = next(item for item in audit if item["action"] == "doc.upload" and item["obj"] == doc["id"])
    assert "Иван" not in str(upload["meta"])
    assert "⟦PERSON_1⟧" in str(upload["meta"])


def test_employee_cannot_overwrite_foreign_meeting(client):
    db.save_meeting_ai(
        "E-FOREIGN",
        "Чужая встреча",
        "Текст",
        {"summary": "Оригинал", "decisions": [], "tasks": [], "risks": [], "open_questions": [], "used_llm": False},
        created_by="anna",
    )
    _switch(client, "igor")
    response = client.post(
        "/api/meetings/E-FOREIGN/record",
        files={"audio": ("a.webm", b"not-audio", "audio/webm")},
        data={"consent": "true", "title": "Подмена"},
    )
    assert response.status_code == 403
    assert db.get_meeting_ai("E-FOREIGN")["summary"] == "Оригинал"


def test_folder_acl_must_match_document_acl(client):
    mismatch = client.post(
        "/api/docs",
        files={"file": ("note.txt", b"text", "text/plain")},
        data={"acl": "all", "folder_id": "F-FIN"},
    )
    assert mismatch.status_code == 400
    match = client.post(
        "/api/docs",
        files={"file": ("note.txt", b"text", "text/plain")},
        data={"acl": "fin", "folder_id": "F-FIN"},
    )
    assert match.status_code == 200
    changed = client.patch(f"/api/docs/{match.json()['id']}", json={"acl": "all"})
    assert changed.status_code == 400


def test_task_status_and_delete_are_persisted(client):
    db.save_meeting_ai(
        "E-TASKS",
        "Задачи",
        "Текст",
        {"summary": "Выжимка", "decisions": [], "tasks": [], "risks": [], "open_questions": [], "used_llm": False},
        created_by="anna",
    )
    created = client.post(
        "/api/meetings/E-TASKS/tasks",
        json={"items": [{"title": "Проверить график", "owner": "Игорь"}], "confirm": True},
    ).json()["created"][0]
    task_id = created["id"]

    updated = client.patch(f"/api/tasks/{task_id}", json={"status": "progress", "owner_id": "igor"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "progress"
    assert updated.json()["owner_id"] == "igor"

    _switch(client, "igor")
    denied = client.delete(f"/api/tasks/{task_id}")
    assert denied.status_code == 403
    _switch(client, None)

    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 200
    assert client.get("/api/tasks").json()["items"] == []


def test_meeting_edit_and_tasks_are_confirmed_and_idempotent(client):
    db.save_meeting_ai(
        "E-TEST",
        "Тестовая встреча",
        "Решили запустить смену. Игорь подготовит график.",
        {
            "summary": "Коротко.",
            "decisions": ["Запустить смену"],
            "protocol": {
                "decided": ["Запустить смену"],
                "proposed": [],
                "discussed": [],
                "needs_clarification": [],
            },
            "tasks": [{"title": "Подготовить график", "owner": "Игорь", "deadline": None, "basis": "Игорь подготовит график"}],
            "risks": [],
            "open_questions": [],
            "used_llm": False,
        },
        created_by="anna",
    )
    edited = client.put(
        "/api/meetings/E-TEST/ai",
        json={
            "summary": "Исправленная выжимка",
            "protocol": {
                "decided": ["Запустить смену"],
                "proposed": ["Проверить третью смену"],
                "discussed": [],
                "needs_clarification": ["Дата запуска"],
            },
            "tasks": [{"title": "Подготовить график", "owner": "Игорь", "deadline": "до пятницы", "basis": "цитата"}],
            "risks": [],
        },
    )
    assert edited.status_code == 200
    assert edited.json()["summary"] == "Исправленная выжимка"
    assert edited.json()["protocol"]["proposed"] == ["Проверить третью смену"]
    assert edited.json()["edited_at"]

    no_confirm = client.post(
        "/api/meetings/E-TEST/tasks",
        json={"items": [{"title": "Подготовить график", "owner": "Игорь"}], "confirm": False},
    )
    assert no_confirm.status_code == 400

    created = client.post(
        "/api/meetings/E-TEST/tasks",
        json={"items": [{"title": "Подготовить график", "owner": "Игорь"}], "confirm": True},
    )
    assert created.status_code == 200
    assert len(created.json()["created"]) == 1
    assert created.json()["created"][0]["owner_id"] == "igor"

    again = client.post(
        "/api/meetings/E-TEST/tasks",
        json={"items": [{"title": "Подготовить график", "owner": "Игорь"}], "confirm": True},
    )
    assert again.status_code == 200
    assert again.json()["created"] == []
    assert again.json()["skipped"]

    tasks = client.get("/api/tasks").json()["items"]
    assert len(tasks) == 1


def test_employee_cannot_edit_another_meeting(client):
    db.save_meeting_ai(
        "E-BOSS",
        "Встреча директора",
        "Текст",
        {"summary": "Выжимка", "decisions": [], "tasks": [], "risks": [], "open_questions": [], "used_llm": False},
        created_by="anna",
    )
    _switch(client, "igor")
    response = client.put("/api/meetings/E-BOSS/ai", json={"summary": "Подмена"})
    assert response.status_code == 403
    assert db.get_meeting_ai("E-BOSS")["summary"] == "Выжимка"
