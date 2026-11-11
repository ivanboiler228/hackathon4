"""FastAPI-бэкенд демо: QR-вход, RBAC, PII-маскирование и аудит."""
from __future__ import annotations

import html
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db, retrieval
from .config import settings
from .llm import LLMError, call_deepseek, fallback_answer, validate_and_restore
from .pii import PIIError, PIIMasker
from .rate_limit import RateLimiter
from .schemas import AskRequest, AskResponse, Source

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
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _login_page(message: str = "") -> HTMLResponse:
    msg = f"<p class='msg'>{html.escape(message)}</p>" if message else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вход · Фотопринт</title>
<style>
  *{{box-sizing:border-box}} body{{margin:0;min-height:100vh;display:grid;place-items:center;
  font-family:Inter,Roboto,system-ui,sans-serif;color:#1d1d1f;
  background:radial-gradient(120% 60% at 15% 108%,#86b45e 0,#9fc779 30%,transparent 62%),
             radial-gradient(110% 55% at 85% 112%,#7fae58 0,#a8cd82 34%,transparent 64%),
             linear-gradient(180deg,#9fbfdc 0%,#c4d7e6 28%,#e3ebe8 52%,#cfe1bf 74%,#b3d18e 100%)}}
  .card{{width:min(440px,calc(100vw - 32px));background:rgba(255,255,255,.68);border:1px solid rgba(255,255,255,.85);
  border-radius:28px;padding:32px;text-align:center;backdrop-filter:blur(26px);box-shadow:0 20px 60px rgba(40,64,40,.16)}}
  h1{{font-size:28px;margin:0 0 8px;font-weight:650;letter-spacing:-.02em}} p{{color:#55595e;line-height:1.5;margin:10px 0}}
  .ico{{font-size:38px;margin-bottom:8px}} .msg{{color:#b42318;background:#fef3f2;border-radius:12px;padding:10px;font-size:14px}}
  .hint{{font-size:13px;color:#6b706f;margin-top:18px}}
</style>
<body><div class="card"><div class="ico">▣</div><h1>Вход по QR</h1>
<p>Отсканируйте QR-код, который выдал организатор демо. Он одноразовый и задаёт вашу роль.</p>
<p>После сканирования вы вернётесь в ассистента.</p>{msg}
<p class="hint">Если QR нет — запросите его у команды на стенде.</p></div></body></html>"""
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "llm_enabled": settings.llm_enabled, "demo_mode": settings.demo_mode}


@app.get("/login")
async def login_page() -> HTMLResponse:
    return _login_page()


@app.get("/")
async def index(request: Request):
    token = request.cookies.get(settings.session_cookie)
    user_id = auth.read_session_token(token) if token else None
    user = db.get_user(user_id) if user_id else None
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return FileResponse(APP_HTML)


@app.get("/auth/qr")
async def auth_qr(code: str = Query(..., min_length=8)):
    user_id = db.consume_qr_token(code)
    if not user_id:
        return HTMLResponse(
            "<h1>Ссылка недействительна</h1><p>QR-код уже использован или истёк. Запросите новый у организатора.</p>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user = db.get_user(user_id)
    if not user:
        return HTMLResponse("<h1>Пользователь не найден</h1>", status_code=status.HTTP_400_BAD_REQUEST)
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="auth.qr",
        obj="сессия",
        result="успешно",
        meta={"role_label": user["role_label"]},
    )
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    auth.set_session_cookie(response, user["id"])
    return response


@app.post("/api/logout")
async def logout(request: Request):
    user: dict | None = None
    token = request.cookies.get(settings.session_cookie)
    if token:
        uid = auth.read_session_token(token)
        user = db.get_user(uid) if uid else None
    if user:
        db.log_audit(user_id=user["id"], role=user["role"], action="auth.logout", result="успешно")
    response = JSONResponse({"ok": True})
    auth.clear_session_cookie(response)
    return response


@app.get("/api/me")
async def me(user: dict = Depends(auth.current_user)):
    return auth.public_user(user)


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
