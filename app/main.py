"""FastAPI-бэкенд демо: автовход директора, RBAC, PII-маскирование и аудит."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db, documents, meeting_ai, retrieval, stt
from .config import settings
from .llm import LLMError, call_deepseek, fallback_answer, validate_and_restore
from .meeting_ai import MeetingAIError
from .pii import PIIError, PIIMasker
from .rate_limit import RateLimiter
from .schemas import (
    AskRequest,
    AskResponse,
    DocUpdate,
    FolderCreate,
    MeetingEditRequest,
    MeetingFeedbackRequest,
    MeetingTasksRequest,
    Source,
    SwitchRequest,
    TaskStatusUpdate,
)

APP_HTML = settings.base_dir / "fotoprint-ai-assistant (1).html"
limiter = RateLimiter(settings.rate_limit_per_minute)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.static_dir.mkdir(parents=True, exist_ok=True)
    db.init_db()
    yield


app = FastAPI(title="Фотопринт · AI-ассистент", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "llm_enabled": settings.llm_enabled,
        "demo_mode": settings.demo_mode,
        "llm": {
            "provider": "DeepSeek",
            "model": settings.deepseek_model,
            "base_url": settings.deepseek_base_url,
            "enabled": settings.llm_enabled,
        },
        "stt": {
            "engine": "Vosk",
            "model": settings.vosk_model_path.name,
            "local": True,
        },
    }


@app.get("/")
async def index(request: Request):
    token = request.cookies.get(settings.session_cookie)
    data = auth.read_session_token(token) if token else None
    user_id = str(data["uid"]) if data else None
    user = db.get_user(user_id) if user_id else None
    if not user:
        demo = db.get_user(settings.demo_user)
        if not demo:
            raise HTTPException(status_code=503, detail="Демо-пользователь не найден")
        response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        auth.set_session_cookie(response, demo["id"])
        db.log_audit(
            user_id=demo["id"],
            role=demo["role"],
            action="auth.auto",
            result="демо-вход директора",
            meta={"role_label": demo["role_label"]},
        )
        return response
    return FileResponse(APP_HTML)


@app.post("/api/logout")
async def logout(request: Request):
    user: dict | None = None
    token = request.cookies.get(settings.session_cookie)
    if token:
        data = auth.read_session_token(token)
        uid = str(data["uid"]) if data else None
        user = db.get_user(uid) if uid else None
    if user:
        db.log_audit(user_id=user["id"], role=user["role"], action="auth.logout", result="успешно")
    response = JSONResponse({"ok": True})
    auth.clear_session_cookie(response)
    return response


def _switch_options() -> list[dict]:
    return [
        {"id": u["id"], "name": u["name"], "role_label": u["role_label"], "dept": u["dept"]}
        for u in db.list_users()
        if u["role"] == "employee"
    ]


@app.get("/api/me")
async def me(user: dict = Depends(auth.current_user)):
    data = auth.public_user(user)
    if data["can_switch"]:
        data["switch_options"] = _switch_options()
    return data


@app.post("/api/switch-role")
async def switch_role(payload: SwitchRequest, user: dict = Depends(auth.current_user)):
    """Директор может смотреть систему от имени сотрудника и вернуться обратно."""
    if user.get("_real_role") != "boss":
        raise HTTPException(status_code=403, detail="Переключение ролей доступно только директору.")

    real_id = str(user["_real_id"])
    target_id = payload.user_id or real_id
    if target_id == real_id:
        act_as = None
        target = db.get_user(real_id)
    else:
        target = db.get_user(target_id)
        if not target or target["role"] != "employee":
            raise HTTPException(status_code=400, detail="Можно переключиться только на сотрудника.")
        act_as = target_id

    db.log_audit(
        user_id=real_id,
        role="boss",
        action="role.switch",
        obj=target["id"] if target else "",
        result="просмотр как сотрудник" if act_as else "возврат в директора",
        meta={"effective_role": target["role_label"] if target else ""},
    )
    response = JSONResponse({"ok": True, "effective_user": target["id"] if target else real_id})
    auth.set_session_cookie(response, real_id, act_as=act_as)
    return response


VALID_ACLS = {"all", "fin", "hr", "prod", "mkt", "support", "legal"}
ACL_TITLES = {
    "all": "Все руководители",
    "fin": "Только дирекция",
    "hr": "HR + дирекция",
    "prod": "Производство + дирекция",
    "mkt": "Маркетинг + дирекция",
    "support": "Поддержка + дирекция",
    "legal": "Юридическое + дирекция",
}


def _require_boss(user: dict, action: str, obj: str = "") -> None:
    if user["role"] != "boss":
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action=action,
            obj=obj,
            result="ОТКЛОНЕНО: действие доступно только директору",
            meta={"role": user["role"]},
        )
        raise HTTPException(
            status_code=403,
            detail="Действие доступно только директору. Попытка зафиксирована в аудите.",
        )


def _check_folder(user: dict, folder_id: str, acl: str) -> dict:
    folders = {f["id"]: f for f in db.list_folders(user["acls"])}
    if folder_id:
        folder = folders.get(folder_id)
        if not folder:
            raise HTTPException(status_code=400, detail="Папка не найдена или недоступна.")
    else:
        folder = folders.get(db.ACL_FOLDER.get(acl, "F-REG"))
        if not folder:
            raise HTTPException(status_code=400, detail="Папка по умолчанию недоступна.")
    if folder["acl"] != "all" and acl != folder["acl"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Папка «{folder['title']}» имеет доступ «{ACL_TITLES.get(folder['acl'], folder['acl'])}». "
                "Выберите такой же уровень доступа у документа."
            ),
        )
    return folder


@app.get("/api/folders")
async def folders(user: dict = Depends(auth.current_user)):
    return {
        "items": db.list_folders(user["acls"]),
        "can_manage": user["role"] == "boss",
    }


@app.post("/api/folders")
async def folder_create(payload: FolderCreate, user: dict = Depends(auth.current_user)):
    _require_boss(user, "doc.folder_denied")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Название папки пустое.")
    folder = db.create_folder(title, payload.acl, user["id"])
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="doc.folder_create",
        obj=folder["id"],
        result="папка создана",
        meta={"title": _mask_for_audit(title), "acl": payload.acl},
    )
    return folder


@app.get("/api/docs")
async def docs(user: dict = Depends(auth.current_user)):
    keys = ("id", "title", "date", "acl", "folder_id", "source_type", "created_by", "created_at")
    items = [{k: d.get(k, "") for k in keys} for d in db.list_docs(user["acls"])]
    return {"items": items, "role": user["role"], "can_manage": user["role"] == "boss"}


@app.post("/api/docs")
async def doc_upload(
    file: UploadFile | None = File(None),
    email_subject: str = Form(""),
    email_from: str = Form(""),
    email_body: str = Form(""),
    title: str = Form(""),
    acl: str = Form("all"),
    folder_id: str = Form(""),
    user: dict = Depends(auth.current_user),
):
    _require_boss(user, "doc.upload_denied")
    if acl not in VALID_ACLS:
        raise HTTPException(status_code=400, detail="Неизвестный уровень доступа.")

    source_type = "upload"
    try:
        if file is not None and file.filename:
            raw = await file.read()
            doc_title, text = documents.parse_upload(
                file.filename, file.content_type or "", raw
            )
            source_type = "email" if (file.filename or "").lower().endswith(".eml") else "upload"
        elif email_body.strip():
            doc_title, text = documents.parse_email_text(email_subject, email_from, email_body)
            source_type = "email"
        else:
            raise HTTPException(status_code=400, detail="Приложите файл или вставьте текст письма.")
    except documents.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    final_title = title.strip() or doc_title
    target_folder = _check_folder(user, folder_id, acl)
    doc = db.create_doc(
        title=final_title[:200],
        text=text,
        acl=acl,
        folder_id=target_folder["id"],
        source_type=source_type,
        created_by=user["id"],
    )
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="doc.upload",
        obj=doc["id"],
        result="документ добавлен",
        meta={
            "title": _mask_for_audit(final_title)[:120],
            "acl": acl,
            "folder": target_folder["id"],
            "source_type": source_type,
            "chars": len(text),
        },
    )
    return doc


@app.patch("/api/docs/{doc_id}")
async def doc_update(doc_id: str, payload: DocUpdate, user: dict = Depends(auth.current_user)):
    _require_boss(user, "doc.edit_denied", doc_id.upper())
    doc = db.get_doc(doc_id.upper())
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if not doc.get("created_by"):
        raise HTTPException(
            status_code=400,
            detail="Встроенные документы менять нельзя. Загрузите свою версию.",
        )
    folder = payload.folder_id or doc.get("folder_id")
    new_acl = payload.acl or doc["acl"]
    if folder:
        folder = _check_folder(user, folder, new_acl)["id"]
    updated = db.update_doc(
        doc["id"],
        title=payload.title.strip() if payload.title else None,
        text=payload.text.strip() if payload.text else None,
        folder_id=folder,
        acl=payload.acl,
    )
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="doc.edit",
        obj=doc["id"],
        result="документ изменён",
        meta={"fields": [k for k in ("title", "text", "folder_id", "acl") if getattr(payload, k, None)]},
    )
    return updated


@app.delete("/api/docs/{doc_id}")
async def doc_delete(doc_id: str, user: dict = Depends(auth.current_user)):
    _require_boss(user, "doc.delete_denied", doc_id.upper())
    doc = db.get_doc(doc_id.upper())
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if not doc.get("created_by"):
        raise HTTPException(status_code=400, detail="Встроенные документы удалить нельзя.")
    db.delete_doc(doc["id"])
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="doc.delete",
        obj=doc["id"],
        result="документ удалён",
        meta={"title": _mask_for_audit(doc["title"])},
    )
    return {"ok": True, "deleted": doc["id"]}


@app.get("/api/docs/{doc_id}")
async def doc_detail(doc_id: str, user: dict = Depends(auth.current_user)):
    doc = db.get_doc(doc_id.upper())
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if not retrieval.can_access(doc, user["acls"]):
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="doc.access_denied",
            obj=doc["id"],
            result="ОТКЛОНЕНО: нет прав роли",
            meta={"role": user["role"]},
        )
        raise HTTPException(status_code=403, detail="Нет доступа. Документ закрыт для вашей роли.")
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="doc.view",
        obj=doc["id"],
        result="успешно",
        meta={"acl": doc["acl"]},
    )
    return doc


def _meeting_for_user(event_id: str, user: dict) -> dict:
    item = db.get_meeting_ai(event_id)
    if not item:
        raise HTTPException(status_code=404, detail="AI-выжимки для этой встречи нет")
    if user["role"] != "boss" and item.get("created_by") != user["id"]:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="meeting.access_denied",
            obj=event_id,
            result="ОТКЛОНЕНО: запись создана другим сотрудником",
            meta={"created_by": item.get("created_by", "")},
        )
        raise HTTPException(status_code=403, detail="Нет доступа к записи другой роли.")
    return item


def _resolve_owner(name: str | None) -> str | None:
    if not name:
        return None
    key = str(name).strip().lower()
    for user in db.list_users():
        first = user["name"].split()[0].lower()
        if key == user["id"] or key == first or key in user["name"].lower():
            return user["id"]
    return None


def _mask_for_audit(value: str, limit: int = 200) -> str:
    try:
        return PIIMasker().mask(str(value)).masked[:limit]
    except PIIError:
        return "[скрыто: не удалось обезличить]"


@app.get("/api/meetings/ai")
async def meeting_ai_list(user: dict = Depends(auth.current_user)):
    return {"items": db.list_meeting_ai(user)}


@app.get("/api/meetings/{event_id}/ai")
async def meeting_ai_get(event_id: str, user: dict = Depends(auth.current_user)):
    return _meeting_for_user(event_id, user)


@app.put("/api/meetings/{event_id}/ai")
async def meeting_ai_edit(
    event_id: str,
    payload: MeetingEditRequest,
    user: dict = Depends(auth.current_user),
):
    item = _meeting_for_user(event_id, user)
    protocol = payload.protocol.model_dump() if payload.protocol else None
    if protocol is not None:
        protocol = {k: [str(x).strip() for x in v if str(x).strip()] for k, v in protocol.items()}
    tasks = None
    if payload.tasks is not None:
        tasks = [t for t in payload.tasks if str(t.get("title") or "").strip()][:50]
    updated = db.update_meeting_ai(
        event_id,
        transcript=payload.transcript,
        summary=payload.summary,
        protocol=protocol,
        tasks=tasks,
        risks=payload.risks,
        feedback=payload.feedback,
    )
    try:
        preview = PIIMasker().mask(str(payload.summary or item["summary"])).masked[:1500]
    except PIIError:
        preview = ""
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="meeting.edit",
        obj=event_id,
        result="выжимка исправлена пользователем",
        meta={
            "fields": [
                key
                for key in ("transcript", "summary", "protocol", "tasks", "risks", "feedback")
                if getattr(payload, key, None) is not None
            ]
        },
        masked_preview=preview,
    )
    return updated


@app.post("/api/meetings/{event_id}/feedback")
async def meeting_feedback(
    event_id: str,
    payload: MeetingFeedbackRequest,
    user: dict = Depends(auth.current_user),
):
    _meeting_for_user(event_id, user)
    feedback = {"verdict": payload.verdict, "comment": payload.comment.strip(), "user": user["id"]}
    updated = db.update_meeting_ai(event_id, feedback=feedback)
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="meeting.feedback",
        obj=event_id,
        result=f"оценка: {payload.verdict}",
        meta={"comment_chars": len(payload.comment)},
    )
    return updated


@app.delete("/api/meetings/{event_id}/ai")
async def meeting_ai_delete(event_id: str, user: dict = Depends(auth.current_user)):
    _meeting_for_user(event_id, user)
    db.delete_meeting_ai(event_id)
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="meeting.delete",
        obj=event_id,
        result="запись встречи удалена",
    )
    return {"ok": True, "deleted": event_id}


@app.post("/api/meetings/{event_id}/tasks")
async def meeting_tasks_create(
    event_id: str,
    payload: MeetingTasksRequest,
    user: dict = Depends(auth.current_user),
):
    if not payload.confirm:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="meeting.tasks_confirm_required",
            obj=event_id,
            result="ОТКЛОНЕНО: нет подтверждения пользователя",
            meta={"titles": [_mask_for_audit(t.title) for t in payload.items][:20]},
        )
        raise HTTPException(
            status_code=400,
            detail="Создание задач требует подтверждения после предварительного просмотра.",
        )
    item = _meeting_for_user(event_id, user)
    items = [t.model_dump() for t in payload.items][:50]
    if not items:
        raise HTTPException(status_code=400, detail="Нет задач для создания.")
    result = db.create_meeting_tasks(
        event_id=event_id,
        event_title=item["title"],
        items=items,
        created_by=user["id"],
        resolve_owner=_resolve_owner,
    )
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="meeting.tasks_create",
        obj=event_id,
        result=f"создано {len(result['created'])}, пропущено {len(result['skipped'])}",
        meta={
            "confirm": payload.confirm,
            "titles": [_mask_for_audit(t["title"]) for t in result["created"]][:20],
        },
    )
    return result


def _task_for_user(task_id: str, user: dict) -> dict:
    task = db.get_meeting_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    if user["role"] != "boss" and task.get("owner_id") != user["id"] and task.get("created_by") != user["id"]:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="task.access_denied",
            obj=task_id,
            result="ОТКЛОНЕНО: задача другой роли",
        )
        raise HTTPException(status_code=403, detail="Нет доступа к задаче другой роли.")
    return task


@app.patch("/api/tasks/{task_id}")
async def task_update(task_id: str, payload: TaskStatusUpdate, user: dict = Depends(auth.current_user)):
    _task_for_user(task_id, user)
    if payload.owner_id and not db.get_user(payload.owner_id):
        raise HTTPException(status_code=400, detail="Неизвестный владелец задачи.")
    updated = db.update_meeting_task_status(task_id, payload.status, payload.owner_id)
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="task.status",
        obj=task_id,
        result=f"статус: {payload.status}",
        meta={"owner_id": payload.owner_id or ""},
    )
    return updated


@app.delete("/api/tasks/{task_id}")
async def task_delete(task_id: str, user: dict = Depends(auth.current_user)):
    task = _task_for_user(task_id, user)
    if user["role"] != "boss" and task.get("created_by") != user["id"]:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="task.delete_denied",
            obj=task_id,
            result="ОТКЛОНЕНО: удаляет только постановщик",
        )
        raise HTTPException(status_code=403, detail="Удалить задачу может постановщик или директор.")
    db.delete_meeting_task(task_id)
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="task.delete",
        obj=task_id,
        result="задача удалена",
        meta={"title": _mask_for_audit(task["title"])},
    )
    return {"ok": True, "deleted": task_id}


@app.get("/api/tasks")
async def tasks_list(user: dict = Depends(auth.current_user)):
    return {"items": db.list_meeting_tasks(user)}


@app.post("/api/meetings/{event_id}/record")
async def meeting_record(
    event_id: str,
    audio: UploadFile = File(...),
    consent: bool = Form(False),
    title: str = Form("Встреча"),
    user: dict = Depends(auth.current_user),
):
    if not consent:
        raise HTTPException(status_code=400, detail="Нужно подтвердить согласие участников на запись.")

    existing = db.get_meeting_ai(event_id)
    if existing and user["role"] != "boss" and existing.get("created_by") != user["id"]:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="meeting.record_denied",
            obj=event_id,
            result="ОТКЛОНЕНО: попытка перезаписать чужую выжимку",
            meta={"created_by": existing.get("created_by", "")},
        )
        raise HTTPException(
            status_code=403,
            detail="Нельзя перезаписать запись встречи, созданную другой ролью.",
        )

    data = await audio.read()
    max_bytes = settings.meeting_max_audio_mb * 1024 * 1024
    if not data:
        raise HTTPException(status_code=400, detail="Пустой аудиофайл.")
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Аудио больше {settings.meeting_max_audio_mb} МБ. Сократите запись.",
        )

    try:
        transcript, duration = await asyncio.to_thread(
            stt.transcribe_audio, data, audio.content_type or ""
        )
    except stt.STTError as exc:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="meeting.transcribe",
            obj=event_id,
            result="ошибка распознавания",
            meta={"size_mb": round(len(data) / 1024 / 1024, 2)},
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    llm_error = None
    try:
        result = await meeting_ai.summarize(transcript, title)
    except MeetingAIError as exc:
        llm_error = str(exc)
        result = meeting_ai.fallback_summary(transcript, llm_error)

    saved = db.save_meeting_ai(
        event_id,
        title,
        transcript,
        result,
        stt_engine="vosk",
        created_by=user["id"],
    )
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="meeting.record",
        obj=event_id,
        result="выжимка сохранена" if result.get("used_llm") else "локальная выжимка",
        meta={
            "duration_sec": round(duration, 1),
            "size_mb": round(len(data) / 1024 / 1024, 2),
            "chars": len(transcript),
            "used_llm": bool(result.get("used_llm")),
            "llm_error": llm_error,
        },
    )
    saved["llm_error"] = llm_error
    saved["duration_sec"] = round(duration, 1)
    return saved


@app.post("/api/assistant/ask", response_model=AskResponse)
async def ask(payload: AskRequest, user: dict = Depends(auth.current_user)):
    query = payload.q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Пустой запрос")

    key = f"{user['id']}:ask"
    if not limiter.allow(key):
        retry = limiter.retry_after(key)
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="assistant.rate_limited",
            result="отклонено",
            meta={"retry_after": retry},
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Слишком много запросов. Подождите немного.", "retry_after": retry},
            headers={"Retry-After": str(retry)},
        )

    # Явный запрос закрытого документа — отказ + аудит, без раскрытия содержимого.
    explicit = retrieval.explicit_doc(query)
    if explicit and not retrieval.can_access(explicit, user["acls"]):
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="assistant.doc_denied",
            obj=explicit["id"],
            result="ОТКЛОНЕНО: нет прав роли",
            meta={"role": user["role"]},
        )
        raise HTTPException(
            status_code=403,
            detail="Нет доступа: документ закрыт для вашей роли. Запрос зафиксирован в аудите.",
        )

    docs = []
    selection = "search"
    if payload.doc_ids is not None:
        selection = "manual"
        seen: set[str] = set()
        ordered: list[str] = []
        for raw_id in payload.doc_ids:
            doc_id = str(raw_id).strip().upper()
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                ordered.append(doc_id)
        if len(ordered) > 8:
            raise HTTPException(
                status_code=400,
                detail="Можно выбрать не более 8 источников для одного вопроса.",
            )
        for doc_id in ordered:
            doc = db.get_doc(doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail=f"Документ {doc_id} не найден.")
            if not retrieval.can_access(doc, user["acls"]):
                db.log_audit(
                    user_id=user["id"],
                    role=user["role"],
                    action="assistant.doc_denied",
                    obj=doc["id"],
                    result="ОТКЛОНЕНО: выбран недоступный источник",
                    meta={"role": user["role"], "selection": "manual"},
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Нет доступа к {doc['id']}. Выбор источника зафиксирован в аудите.",
                )
            docs.append(doc)
    else:
        docs = retrieval.search(query, user["acls"], limit=4)
        if explicit:
            docs = [explicit] + [d for d in docs if d["id"] != explicit["id"]]

    masker = PIIMasker()
    try:
        masked_question = masker.mask(query).masked
        masked_docs: list[dict[str, str]] = []
        for doc in docs:
            masked_docs.append(
                {
                    "id": doc["id"],
                    "title": masker.mask(doc["title"]).masked,
                    "date": doc["date"],
                    # Ограничиваем контекст, чтобы большой PDF не переполнил модель.
                    "text": masker.mask(doc["text"]).masked[:6000],
                    "acl": doc["acl"],
                }
            )
        preview = f"Вопрос: {masked_question}\n\nКонтекст:\n" + "\n".join(
            f"[{d['id']}] {d['title']}: {d['text']}" for d in masked_docs
        )
        masker.assert_clean(preview)
    except PIIError as exc:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="assistant.pii_block",
            result="ОТКЛОНЕНО: не удалось безопасно обезличить",
            meta={"error": exc.__class__.__name__},
            masked_preview="",
        )
        raise HTTPException(status_code=422, detail="Не удалось безопасно обезличить запрос.") from exc

    sources = [
        Source(
            id=d["id"],
            title=d["title"],
            date=d["date"],
            acl=d["acl"],
            fragment=retrieval.best_fragment(query, d["text"]),
        )
        for d in docs
    ]
    used_llm = False
    llm_error: str | None = None
    answer: str

    if docs and settings.llm_enabled:
        try:
            raw = await call_deepseek(masked_question, masked_docs)
            answer = validate_and_restore(raw, masker)
            used_llm = True
        except (LLMError, PIIError) as exc:
            llm_error = exc.__class__.__name__
            answer = fallback_answer(masked_question, masked_docs)
            answer = validate_and_restore(answer, masker)
    else:
        if docs and not settings.llm_enabled:
            llm_error = "disabled"
        answer = fallback_answer(masked_question, masked_docs)
        answer = validate_and_restore(answer, masker)

    if not docs:
        answer = "В доступных документах ответа нет."
        llm_error = llm_error or "no_context"

    result = "ok" if docs else "no_data"
    if llm_error and used_llm is False and docs:
        result = "fallback"
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="assistant.ask",
        obj=", ".join(d["id"] for d in docs),
        result=result,
        meta={
            "used_llm": used_llm,
            "llm_error": llm_error,
            "pii_found": dict(masker.found),
            "sources": [d["id"] for d in docs],
            "selection": selection,
        },
        masked_preview=preview,
    )

    return AskResponse(
        answer=answer,
        sources=sources,
        masked_preview=preview[:1800],
        pii_found=dict(masker.found),
        placeholders=list(masker.mapping.keys()),
        used_llm=used_llm,
        llm_error=llm_error,
    )


@app.get("/api/audit")
async def audit(limit: int = Query(30, ge=1, le=100), user: dict = Depends(auth.current_user)):
    items = db.list_audit(user, limit=limit)
    return {"items": items, "scope": "all" if user["role"] == "boss" else "own"}
