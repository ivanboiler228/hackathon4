"""Сессия и cookie. Роль всегда определяется на сервере по user_id."""
from __future__ import annotations

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import db
from .config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="fp-session")


def create_session_token(user_id: str, act_as: str | None = None) -> str:
    return _serializer.dumps({"uid": user_id, "act_as": act_as})


def read_session_token(token: str) -> dict | None:
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or not data.get("uid"):
        return None
    return data


def set_session_cookie(response: Response, user_id: str, act_as: str | None = None) -> None:
    response.set_cookie(
        key=settings.session_cookie,
        value=create_session_token(user_id, act_as=act_as),
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
    data = read_session_token(token)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла. Откройте QR-ссылку заново.",
        )

    real = db.get_user(str(data["uid"]))
    if not real:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")

    act_as = data.get("act_as")
    effective = db.get_user(str(act_as)) if act_as else real
    if not effective:
        effective = real
        act_as = None

    effective = dict(effective)
    effective["_real_id"] = real["id"]
    effective["_real_role"] = real["role"]
    effective["_real_name"] = real["name"]
    effective["_real_role_label"] = real["role_label"]
    effective["_act_as"] = act_as
    return effective


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
        "role_label": user["role_label"],
        "dept": user["dept"],
        "acls": user["acls"],
        "email": user["email"],
        "can_switch": user.get("_real_role") == "boss",
        "is_impersonating": bool(user.get("_act_as")),
        "real_name": user.get("_real_name"),
        "real_role_label": user.get("_real_role_label"),
    }
