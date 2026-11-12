"""FastAPI-бэкенд демо: автовход директора, RBAC, PII-маскирование и аудит."""
from __future__ import annotations

import asyncio
import gzip
import json
import math
import re

try:
    import brotli
except ImportError:  # brotli не обязателен: без него остаётся gzip
    brotli = None
from contextlib import asynccontextmanager
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from . import auth, calendar_ai, db, documents, meeting_ai, overview_ai, retrieval, stt
from .config import settings
from .llm import LLMError, call_deepseek, fallback_answer, validate_and_restore
from .meeting_ai import MeetingAIError
from .pii import PIIError, PIIMasker
from .rate_limit import RateLimiter
from .schemas import (
    AskRequest,
    AskResponse,
    CalendarAdviceRequest,
    DocUpdate,
    FolderCreate,
    FolderUpdate,
    MeetingEditRequest,
    MeetingFeedbackRequest,
    MeetingTasksRequest,
    OverviewRequest,
    Source,
    SwitchRequest,
    TaskStatusUpdate,
)

APP_HTML = settings.base_dir / "fotoprint-ai-assistant (1).html"
limiter = RateLimiter(settings.rate_limit_per_minute)
_html_cache: dict[int, tuple[bytes, bytes, bytes | None]] = {}


def _html_payload() -> tuple[bytes, bytes, bytes | None]:
    stamp = APP_HTML.stat().st_mtime_ns
    payload = _html_cache.get(stamp)
    if payload is None:
        raw = APP_HTML.read_bytes()
        compressed = brotli.compress(raw, quality=11) if brotli else None
        payload = (raw, gzip.compress(raw, 6), compressed)
        _html_cache.clear()
        _html_cache[stamp] = payload
    return payload


def html_response(request: Request, cache_control: str | None = None) -> Response:
    """Отдаёт HTML с предварительным сжатием и явным Content-Length.

    Туннели (Tunnelmole) надёжнее принимают ответы с Content-Length,
    чем chunked-поток, поэтому сжимаем один раз и кешируем по mtime.
    """
    raw, gz, br = _html_payload()
    accepts = (request.headers.get("accept-encoding") or "").lower()
    if br is not None and "br" in accepts:
        body, encoding = br, "br"
    elif "gzip" in accepts:
        body, encoding = gz, "gzip"
    else:
        body, encoding = raw, None
    response = Response(content=body, media_type="text/html; charset=utf-8")
    if encoding:
        response.headers["Content-Encoding"] = encoding
        response.headers["Vary"] = "Accept-Encoding"
    if cache_control:
        response.headers["Cache-Control"] = cache_control
    return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.static_dir.mkdir(parents=True, exist_ok=True)
    db.init_db()
    if APP_HTML.exists():
        try:
            raw = APP_HTML.read_bytes()
            _html_cache[APP_HTML.stat().st_mtime_ns] = (
                raw,
                gzip.compress(raw, 6),
                brotli.compress(raw, quality=11) if brotli else None,
            )
        except OSError:
            pass
    yield


app = FastAPI(title="Фотопринт · AI-ассистент", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    path = request.url.path
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif "cache-control" not in response.headers:
        if path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        elif path == "/":
            response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=30"
    return response


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "llm_enabled": settings.llm_enabled,
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
        response = html_response(request, cache_control="no-store")
        auth.set_session_cookie(response, demo["id"])
        db.log_audit(
            user_id=demo["id"],
            role=demo["role"],
            action="auth.auto",
            result="демо-вход директора",
            meta={"role_label": demo["role_label"]},
        )
        return response
    return html_response(request)


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


@app.get("/api/bootstrap")
async def bootstrap(user: dict = Depends(auth.current_user)):
    """Один запрос для старта: пользователь, выжимки, задачи и аудит."""
    data = auth.public_user(user)
    if data["can_switch"]:
        data["switch_options"] = _switch_options()
    return {
        "user": data,
        "meetings": db.list_meeting_ai(user),
        "tasks": db.list_meeting_tasks(user),
        "audit": db.list_audit(user, limit=100),
    }


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
FOLDER_META_RE = re.compile(
    r"(папк|содержим|что лежит|проанализ|обзор|о ч[её]м|список документ|какие документ)",
    re.IGNORECASE,
)
CUSTOM_DOC_RE = re.compile(r"(?<![A-Za-z0-9])(U-[A-Za-z0-9]{3,})(?![A-Za-z0-9])", re.IGNORECASE)
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


WORK_START = 9.0
WORK_END = 18.0
MIN_SLOT = 0.5


def _calendar_date(value: str | None, label: str, default: date_cls) -> date_cls:
    if not value:
        return default
    try:
        return date_cls.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Некорректная дата: {label}.") from exc


def _fmt_hour(value: float) -> str:
    hour = int(value)
    minute = int(round((value - hour) * 60))
    if minute == 60:
        hour += 1
        minute = 0
    return f"{hour:02d}:{minute:02d}"


def _person_name(person_id: str) -> str:
    user = db.get_user(person_id)
    if user:
        return user["name"].split()[0]
    return {
        "anna": "Анна",
        "igor": "Игорь",
        "maria": "Мария",
        "olga": "Ольга",
        "pavel": "Павел",
        "dima": "Дмитрий",
        "irina": "Ирина",
    }.get(person_id, person_id)


STATUS_LABELS = {
    "new": "новая",
    "progress": "в работе",
    "review": "на проверке",
    "done": "готово",
}


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        start = max(WORK_START, start)
        end = min(WORK_END, end)
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


MINSK_TZ = timezone(timedelta(hours=3), "Europe/Minsk")


def _free_slots(
    events: list,
    busy: list,
    date_from: date_cls,
    date_to: date_cls,
    participants: list[str],
) -> list[dict]:
    if not participants:
        return []
    people = set(participants)
    slots: list[dict] = []
    # Минск — UTC+3 без перехода на летнее время. Прошедшие окна не предлагаем.
    now = datetime.now(MINSK_TZ)
    today = now.date()
    now_hour = now.hour + now.minute / 60
    day = max(date_from, today)
    while day <= date_to and len(slots) < 8:
        if day.weekday() < 5:
            iso_day = day.isoformat()
            intervals = [
                (e.start, e.end)
                for e in events
                if e.date == iso_day and people.intersection(e.people)
            ]
            intervals += [
                (b.start, b.end)
                for b in busy
                if b.date == iso_day and b.person in people
            ]
            cursor = WORK_START
            if day == today:
                cursor = max(cursor, math.ceil(now_hour * 2) / 2)
            for start, end in _merge_intervals(intervals):
                if start - cursor >= MIN_SLOT:
                    slots.append(
                        {"date": iso_day, "start": cursor, "end": start}
                    )
                cursor = max(cursor, end)
            if WORK_END - cursor >= MIN_SLOT:
                slots.append({"date": iso_day, "start": cursor, "end": WORK_END})
        day += timedelta(days=1)
    return slots[:8]


@app.post("/api/calendar/advice")
async def calendar_advice(
    payload: CalendarAdviceRequest,
    user: dict = Depends(auth.current_user),
):
    key = f"{user['id']}:calendar"
    if not limiter.allow(key):
        retry = limiter.retry_after(key)
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="calendar.rate_limited",
            result="отклонено",
            meta={"retry_after": retry},
        )
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много запросов к AI-советнику. Повторите через {retry} сек.",
        )

    today = date_cls.today()
    date_from = _calendar_date(payload.date_from, "начало", today)
    date_to = _calendar_date(payload.date_to, "конец", date_from + timedelta(days=13))
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="Конец периода раньше начала.")
    if (date_to - date_from).days > 60:
        date_to = date_from + timedelta(days=60)
    range_text = f"{date_from.isoformat()}..{date_to.isoformat()}"

    is_boss = user["role"] == "boss"
    events = [
        e
        for e in payload.events
        if date_from.isoformat() <= e.date <= date_to.isoformat()
        and (is_boss or user["id"] in e.people)
    ]
    events = sorted(events, key=lambda e: (e.date, e.start))[:200]
    tasks = [
        t
        for t in payload.tasks
        if is_boss or t.owner == user["id"] or t.created == user["id"] or user["id"] in t.co
    ]
    tasks = sorted(tasks, key=lambda t: (t.deadline or "9999-12-31", t.prio))[:120]
    busy = [
        b
        for b in payload.busy
        if is_boss or b.person == user["id"]
    ][:400]

    focus = next((e for e in events if e.id == payload.focus_event_id), None)
    participants = list(focus.people) if focus else [user["id"]]
    free_slots = _free_slots(events, busy, date_from, date_to, participants)

    open_tasks = [t for t in tasks if t.status != "done"]
    overdue = [t for t in open_tasks if t.deadline and t.deadline < today.isoformat()]
    due_soon = [
        t
        for t in open_tasks
        if t.deadline
        and today.isoformat() <= t.deadline <= (today + timedelta(days=3)).isoformat()
    ]
    days = []
    day = date_from
    while day <= date_to:
        iso_day = day.isoformat()
        day_events = [e for e in events if e.date == iso_day]
        days.append(
            {
                "date": iso_day,
                "events": len(day_events),
                "hours": round(sum(max(0.0, e.end - e.start) for e in day_events), 1),
            }
        )
        day += timedelta(days=1)

    conflicts = []
    for index, first in enumerate(events):
        for second in events[index + 1 :]:
            if first.date != second.date:
                continue
            if first.start < second.end and second.start < first.end:
                shared = sorted(set(first.people).intersection(second.people))
                if shared and len(conflicts) < 15:
                    conflicts.append(
                        {
                            "date": first.date,
                            "first": first.title,
                            "second": second.title,
                            "people": shared,
                            "start": max(first.start, second.start),
                            "end": min(first.end, second.end),
                        }
                    )

    context = {
        "owner": {
            "id": user["id"],
            "name": user["name"],
            "role": user["role_label"],
            "dept": user["dept"],
        },
        "range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "today": today.isoformat(),
        "stats": {
            "events": len(events),
            "events_hours": round(sum(max(0.0, e.end - e.start) for e in events), 1),
            "tasks_open": len(open_tasks),
            "tasks_overdue": len(overdue),
            "tasks_due_soon": len(due_soon),
            "conflicts": len(conflicts),
        },
        "days": days,
        "events": [
            {
                "id": e.id,
                "date": e.date,
                "start": e.start,
                "end": e.end,
                "title": e.title,
                "people": [_person_name(p) for p in e.people],
                "place": e.place,
                "cal": e.cal,
            }
            for e in events
        ],
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "owner": _person_name(t.owner) if t.owner else None,
                "deadline": t.deadline,
                "status": STATUS_LABELS.get(t.status, t.status),
                "prio": t.prio,
            }
            for t in tasks
        ],
        "conflicts": conflicts,
        "free_slots": free_slots,
        "focus": (
            {
                "id": focus.id,
                "title": focus.title,
                "date": focus.date,
                "start": focus.start,
                "end": focus.end,
                "people": [_person_name(p) for p in focus.people],
            }
            if focus
            else None
        ),
    }

    masker = PIIMasker()
    try:
        masked_question = masker.mask(payload.question).masked
        context["owner"]["name"] = masker.mask(context["owner"]["name"]).masked
        for event in context["events"]:
            event["title"] = masker.mask(event["title"]).masked
            event["place"] = masker.mask(event["place"]).masked
            event["people"] = [masker.mask(person).masked for person in event["people"]]
        for task in context["tasks"]:
            task["title"] = masker.mask(task["title"]).masked
            if task["owner"]:
                task["owner"] = masker.mask(task["owner"]).masked
        if context["focus"]:
            context["focus"]["title"] = masker.mask(context["focus"]["title"]).masked
            context["focus"]["people"] = [
                masker.mask(person).masked for person in context["focus"]["people"]
            ]
        for conflict in context["conflicts"]:
            conflict["first"] = masker.mask(conflict["first"]).masked
            conflict["second"] = masker.mask(conflict["second"]).masked
        preview = (
            f"Вопрос: {masked_question}\n"
            + json.dumps(context, ensure_ascii=False)[:1600]
        )
        masker.assert_clean(preview)
    except PIIError as exc:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="calendar.pii_block",
            result="ОТКЛОНЕНО: не удалось обезличить контекст",
            meta={"error": exc.__class__.__name__},
        )
        raise HTTPException(status_code=422, detail="Не удалось безопасно обезличить календарь.") from exc

    answer_masked, used_llm, llm_error = await calendar_ai.advise(masked_question, context)
    try:
        answer = validate_and_restore(answer_masked, masker)
    except (LLMError, PIIError):
        used_llm = False
        llm_error = "validation"
        answer = validate_and_restore(
            calendar_ai.fallback_advice(context, masked_question), masker
        )

    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="calendar.advice",
        obj=range_text,
        result="ok" if used_llm else "fallback",
        meta={
            "events": len(events),
            "tasks": len(tasks),
            "free_slots": len(free_slots),
            "focus": payload.focus_event_id or "",
            "used_llm": used_llm,
            "llm_error": llm_error,
        },
        masked_preview=preview[:1800],
    )
    return {
        "answer": answer,
        "used_llm": used_llm,
        "llm_error": llm_error,
        "context": {
            "range": context["range"],
            "events": len(events),
            "tasks": len(tasks),
            "free_slots": free_slots,
            "overdue": len(overdue),
            "conflicts": len(conflicts),
            "focus": context["focus"],
        },
    }


@app.post("/api/overview/advice")
async def overview_advice(
    payload: OverviewRequest,
    user: dict = Depends(auth.current_user),
):
    key = f"{user['id']}:overview"
    if not limiter.allow(key):
        retry = limiter.retry_after(key)
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="overview.rate_limited",
            result="отклонено",
            meta={"retry_after": retry},
        )
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много запросов к AI-обзору. Повторите через {retry} сек.",
        )

    today = date_cls.today()
    is_boss = user["role"] == "boss"
    tasks = [
        t
        for t in payload.tasks
        if is_boss or t.owner == user["id"] or t.created == user["id"] or user["id"] in t.co
    ][:300]
    events = [
        e for e in payload.events if is_boss or user["id"] in e.people
    ][:300]
    meetings = [
        m for m in payload.meetings if is_boss or m.created_by == user["id"]
    ][:40]

    open_tasks = [t for t in tasks if t.status != "done"]
    overdue = [
        t for t in open_tasks if t.deadline and t.deadline < today.isoformat()
    ]
    due_soon = [
        t
        for t in open_tasks
        if t.deadline
        and today.isoformat() <= t.deadline <= (today + timedelta(days=3)).isoformat()
    ]
    unassigned = [t for t in open_tasks if not t.owner]

    owner_stats: dict[str, dict[str, Any]] = {}
    for task in tasks:
        owner = _person_name(task.owner) if task.owner else "Без владельца"
        item = owner_stats.setdefault(owner, {"owner": owner, "open": 0, "overdue": 0, "done": 0})
        if task.status == "done":
            item["done"] += 1
        else:
            item["open"] += 1
            if task.deadline and task.deadline < today.isoformat():
                item["overdue"] += 1
    by_owner = sorted(owner_stats.values(), key=lambda item: (-item["open"], item["owner"]))[:15]

    docs = db.list_docs(user["acls"])
    audit = db.list_audit(user, 200)
    denials = sum(
        1
        for item in audit
        if "ОТКЛОН" in str(item.get("result", ""))
        or str(item.get("action", "")).endswith(("denied", "block", "required"))
    )

    context = {
        "scope": "company" if is_boss else "personal",
        "owner": {
            "name": user["name"],
            "role": user["role_label"],
            "dept": user["dept"],
        },
        "today": today.isoformat(),
        "stats": {
            "tasks_total": len(tasks),
            "tasks_open": len(open_tasks),
            "tasks_done": sum(1 for task in tasks if task.status == "done"),
            "tasks_review": sum(1 for task in tasks if task.status == "review"),
            "overdue": len(overdue),
            "unassigned": len(unassigned),
            "due_soon": len(due_soon),
            "meetings": len(meetings),
            "meetings_with_summary": sum(1 for meeting in meetings if meeting.summary),
            "meeting_tasks": sum(meeting.tasks_count for meeting in meetings),
            "meeting_risks": sum(meeting.risks_count for meeting in meetings),
            "docs_total": len(docs),
            "pending_requests": payload.pending_requests,
            "audit_denials": denials,
        },
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "owner": _person_name(task.owner) if task.owner else None,
                "deadline": task.deadline,
                "status": STATUS_LABELS.get(task.status, task.status),
                "prio": task.prio,
            }
            for task in tasks
        ],
        "overdue": [
            {
                "title": task.title,
                "owner": _person_name(task.owner) if task.owner else None,
                "deadline": task.deadline,
                "prio": task.prio,
            }
            for task in overdue[:15]
        ],
        "by_owner": by_owner,
        "events": [
            {
                "title": event.title,
                "date": event.date,
                "start": event.start,
                "end": event.end,
                "people": [_person_name(person) for person in event.people],
                "place": event.place,
            }
            for event in events[:40]
        ],
        "meetings": [
            {
                "title": meeting.title,
                "date": meeting.date,
                "summary": meeting.summary,
                "decisions": meeting.decisions_count,
                "tasks": meeting.tasks_count,
                "risks": meeting.risks_count,
            }
            for meeting in meetings[:12]
        ],
        "docs": [
            {"id": doc["id"], "title": doc["title"], "date": doc["date"], "acl": doc["acl"]}
            for doc in docs[:8]
        ],
        "recent_audit": [
            {"action": item["action"], "obj": item["obj"], "result": item["result"]}
            for item in audit[:6]
        ],
    }

    masker = PIIMasker()
    try:
        masked_question = masker.mask(payload.question).masked
        context["owner"]["name"] = masker.mask(context["owner"]["name"]).masked
        for task in context["tasks"]:
            task["title"] = masker.mask(task["title"]).masked
            if task["owner"]:
                task["owner"] = masker.mask(task["owner"]).masked
        for task in context["overdue"]:
            task["title"] = masker.mask(task["title"]).masked
            if task["owner"]:
                task["owner"] = masker.mask(task["owner"]).masked
        for item in context["by_owner"]:
            item["owner"] = masker.mask(item["owner"]).masked
        for event in context["events"]:
            event["title"] = masker.mask(event["title"]).masked
            event["place"] = masker.mask(event["place"]).masked
            event["people"] = [masker.mask(person).masked for person in event["people"]]
        for meeting in context["meetings"]:
            meeting["title"] = masker.mask(meeting["title"]).masked
            meeting["summary"] = masker.mask(meeting["summary"]).masked
        for doc in context["docs"]:
            doc["title"] = masker.mask(doc["title"]).masked
        preview = (
            f"Вопрос: {masked_question}\n"
            + json.dumps(context, ensure_ascii=False)[:1800]
        )
        masker.assert_clean(preview)
    except PIIError as exc:
        db.log_audit(
            user_id=user["id"],
            role=user["role"],
            action="overview.pii_block",
            result="ОТКЛОНЕНО: не удалось обезличить обзор",
            meta={"error": exc.__class__.__name__},
        )
        raise HTTPException(status_code=422, detail="Не удалось безопасно обезличить обзор.") from exc

    answer_masked, used_llm, llm_error = await overview_ai.advise(masked_question, context)
    try:
        answer = validate_and_restore(answer_masked, masker)
    except (LLMError, PIIError):
        used_llm = False
        llm_error = "validation"
        answer = validate_and_restore(overview_ai.fallback_overview(context), masker)

    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="overview.advice",
        obj=context["scope"],
        result="ok" if used_llm else "fallback",
        meta={
            "tasks": len(tasks),
            "meetings": len(meetings),
            "docs": len(docs),
            "overdue": len(overdue),
            "used_llm": used_llm,
            "llm_error": llm_error,
        },
        masked_preview=preview[:1800],
    )
    return {
        "answer": answer,
        "used_llm": used_llm,
        "llm_error": llm_error,
        "context": {
            "scope": context["scope"],
            "tasks": len(tasks),
            "open": len(open_tasks),
            "overdue": len(overdue),
            "unassigned": len(unassigned),
            "meetings": len(meetings),
            "docs": len(docs),
            "audit_denials": denials,
        },
    }


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


@app.patch("/api/folders/{folder_id}")
async def folder_update(
    folder_id: str,
    payload: FolderUpdate,
    user: dict = Depends(auth.current_user),
):
    _require_boss(user, "doc.folder_edit_denied", folder_id)
    folder = db.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Папка не найдена.")
    if not folder.get("created_by"):
        raise HTTPException(status_code=400, detail="Встроенную папку менять нельзя.")
    if payload.acl and payload.acl != folder["acl"] and db.count_folder_docs(folder_id):
        raise HTTPException(
            status_code=400,
            detail="В папке есть документы. Сначала перенесите их, потом меняйте доступ.",
        )
    updated = db.update_folder(
        folder_id,
        title=payload.title.strip() if payload.title else None,
        acl=payload.acl,
    )
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="doc.folder_edit",
        obj=folder_id,
        result="папка изменена",
        meta={"fields": [k for k in ("title", "acl") if getattr(payload, k, None)]},
    )
    return updated


@app.delete("/api/folders/{folder_id}")
async def folder_delete(folder_id: str, user: dict = Depends(auth.current_user)):
    _require_boss(user, "doc.folder_delete_denied", folder_id)
    folder = db.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Папка не найдена.")
    if not folder.get("created_by"):
        raise HTTPException(status_code=400, detail="Встроенную папку удалить нельзя.")
    if db.count_folder_docs(folder_id):
        raise HTTPException(
            status_code=400,
            detail="В папке есть документы. Сначала перенесите или удалите их.",
        )
    db.delete_folder(folder_id)
    db.log_audit(
        user_id=user["id"],
        role=user["role"],
        action="doc.folder_delete",
        obj=folder_id,
        result="папка удалена",
        meta={"title": _mask_for_audit(folder["title"])},
    )
    return {"ok": True, "deleted": folder_id}


def _doc_snippet(text: str, pos: int, qlen: int, radius: int = 60) -> str:
    start = max(0, pos - radius)
    end = min(len(text), pos + qlen + radius)
    # Не обрезаем слова посередине.
    while start > 0 and not text[start - 1].isspace():
        start -= 1
        if pos - start > radius + 20:
            break
    while end < len(text) and not text[end].isspace():
        end += 1
    snippet = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


@app.get("/api/docs")
async def docs(
    q: str = Query("", max_length=200),
    user: dict = Depends(auth.current_user),
):
    keys = ("id", "title", "date", "acl", "folder_id", "source_type", "created_by", "created_at")
    query = retrieval.normalize(q).strip()
    items = []
    # Доступ проверяется в SQL до поиска: закрытые документы в выдачу не попадают.
    for d in db.list_docs(user["acls"]):
        item = {k: d.get(k, "") for k in keys}
        if len(query) >= 2:
            title = retrieval.normalize(d.get("title", ""))
            text = d.get("text", "") or ""
            pos = retrieval.normalize(text).find(query)
            if query not in title and pos < 0:
                continue
            item["snippet"] = _doc_snippet(text, pos, len(query)) if pos >= 0 else ""
        items.append(item)
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


def _folder_overview(masked_docs: list[dict[str, str]], scope: str) -> str:
    lines = [f"В области «{scope}» {len(masked_docs)} документ(ов):"]
    for doc in masked_docs:
        first = re.split(r"(?<=[.!?])\s+", doc["text"].strip(), maxsplit=1)[0]
        if len(first) > 170:
            first = first[:167].rstrip() + "…"
        lines.append(f"• «{doc['title']}» ({doc['date']}) — {first}")
    return "\n".join(lines)


def _humanize_citations(answer: str, docs: list[dict[str, Any]]) -> str:
    """Убирает технические U-идентификаторы из ответа, оставляя названия."""
    titles = {str(doc["id"]).upper(): doc["title"] for doc in docs}

    def replace(match: re.Match) -> str:
        title = titles.get(match.group(1).upper())
        return f"«{title}»" if title else ""

    answer = CUSTOM_DOC_RE.sub(replace, answer)
    answer = re.sub(r"\*\*«(.+?)»\*\*\s*—\s*«\1»", r"**«\1»**", answer)
    answer = re.sub(r"«(.+?)»\s*—\s*«\1»", r"«\1»", answer)
    return answer


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
    scope_note = ""
    no_docs_answer = "В доступных документах ответа нет."
    if payload.doc_ids:
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
    elif payload.folder_id or payload.mine:
        allowed = db.list_docs(user["acls"])
        if payload.folder_id:
            folder = db.get_folder(payload.folder_id)
            if not folder:
                raise HTTPException(status_code=404, detail="Папка не найдена.")
            if folder["acl"] != "all" and folder["acl"] not in user["acls"]:
                db.log_audit(
                    user_id=user["id"],
                    role=user["role"],
                    action="assistant.folder_denied",
                    obj=folder["id"],
                    result="ОТКЛОНЕНО: папка недоступна роли",
                    meta={"acl": folder["acl"], "role": user["role"]},
                )
                raise HTTPException(
                    status_code=403,
                    detail="Нет доступа к этой папке. Попытка зафиксирована в аудите.",
                )
            selection = "folder"
            scope_note = f"папка «{folder['title']}»"
            no_docs_answer = f"В папке «{folder['title']}» пока нет документов."
            docs = [doc for doc in allowed if doc.get("folder_id") == folder["id"]]
            docs.sort(key=lambda doc: doc.get("date", ""), reverse=True)
            truncated = len(docs) > 8
            docs = docs[:8]
            scope_note = f"папка «{folder['title']}», документов: {len(docs)}"
            if truncated:
                scope_note += " (первые 8 по дате)"
        else:
            selection = "mine"
            no_docs_answer = "В «Моих загрузках» пока нет документов."
            docs = [doc for doc in allowed if doc.get("created_by") == user["id"]]
            docs.sort(key=lambda doc: doc.get("date", ""), reverse=True)
            docs = docs[:8]
            scope_note = f"мои загрузки, документов: {len(docs)}"
    else:
        docs = retrieval.search(query, user["acls"], limit=4)
        if explicit:
            docs = [explicit] + [d for d in docs if d["id"] != explicit["id"]]

    masker = PIIMasker()
    try:
        masked_question = masker.mask(query).masked
        masked_scope = masker.mask(scope_note).masked if scope_note else ""
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
        if masked_scope:
            preview = f"Область: {masked_scope}\n" + preview
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
            raw = await call_deepseek(masked_question, masked_docs, masked_scope)
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
        answer = no_docs_answer
        llm_error = llm_error or "no_context"

    if (
        docs
        and selection in ("folder", "mine")
        and FOLDER_META_RE.search(query)
        and (
            not used_llm
            or re.search(
                r"нет сведений|ответа нет|не найдено|нет информации|не содержится|не удалось найти|не указано",
                answer,
                re.IGNORECASE,
            )
        )
    ):
        answer = masker.unmask(_folder_overview(masked_docs, masked_scope))
        used_llm = False
        llm_error = llm_error or "folder_fallback"

    if docs:
        answer = _humanize_citations(answer, docs)

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
            "folder_id": payload.folder_id or "",
            "mine": payload.mine,
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

