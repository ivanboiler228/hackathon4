"""Сессия и cookie. Роль всегда определяется на сервере по user_id."""
from __future__ import annotations

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import db
from .config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="fp-session")


def create_session_token(user_id: str) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str) -> str | None:
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return str(uid) if uid else None


def set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=settings.session_cookie,
        value=create_session_token(user_id),
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def current_user(request: Request) -> dict:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нет сессии. Откройте QR-ссылку для входа.",
        )
    user_id = read_session_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла. Откройте QR-ссылку заново.",
        )
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
        "role_label": user["role_label"],
        "dept": user["dept"],
        "acls": user["acls"],
        "email": user["email"],
    }
