"""FastAPI-бэкенд демо: автовход директора, RBAC, PII-маскирование и аудит."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db, retrieval
from .config import settings
from .llm import LLMError, call_deepseek, fallback_answer, validate_and_restore
from .pii import PIIError, PIIMasker
from .rate_limit import RateLimiter
from .schemas import AskRequest, AskResponse, Source, SwitchRequest

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
    return {"status": "ok", "llm_enabled": settings.llm_enabled, "demo_mode": settings.demo_mode}


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


@app.get("/api/docs")
async def docs(user: dict = Depends(auth.current_user)):
    items = [
        {k: d[k] for k in ("id", "title", "date", "acl")}
        for d in db.list_docs(user["acls"])
    ]
    return {"items": items, "role": user["role"]}


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
                    "text": masker.mask(doc["text"]).masked,
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

    sources = [Source(id=d["id"], title=d["title"], date=d["date"], acl=d["acl"]) for d in docs]
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
