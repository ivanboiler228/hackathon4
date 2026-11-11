"""Разбор загруженных файлов и писем для базы знаний.

Поддерживаются .txt, .md, .csv, .pdf и .eml. Всё хранится локально;
наружу уходит только маскированный текст при запросе к LLM.
"""
from __future__ import annotations

import io
import re
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

from pypdf import PdfReader

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 200_000


class DocumentError(ValueError):
    pass


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentError("Не удалось определить кодировку файла. Сохраните его в UTF-8.")


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise DocumentError("В файле нет текста.")
    if len(text) > MAX_TEXT_CHARS:
        raise DocumentError(f"Текст больше {MAX_TEXT_CHARS // 1000} тыс. символов.")
    return text


def _email_body(message: Message) -> str:
    if message.is_multipart():
        parts: list[str] = []
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    parts.append(payload.decode(charset, errors="replace"))
                except LookupError:
                    parts.append(payload.decode("utf-8", errors="replace"))
        if parts:
            return "\n\n".join(parts)
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")
    return str(message.get_payload() or "")


def _header(message: Message, name: str, default: str = "") -> str:
    raw = message.get(name)
    if not raw:
        return default
    try:
        return str(make_header(decode_header(str(raw)))).strip()
    except (LookupError, UnicodeDecodeError):
        return str(raw).strip()


def parse_email_bytes(data: bytes) -> tuple[str, str]:
    message = message_from_bytes(data)
    subject = _header(message, "Subject", "Без темы")
    sender = _header(message, "From")
    body = _email_body(message)
    header = f"От: {sender}\nТема: {subject}\n\n" if sender else f"Тема: {subject}\n\n"
    return f"Письмо: {subject[:120]}", _clean(header + body)


def parse_email_text(subject: str, sender: str, body: str) -> tuple[str, str]:
    subject = (subject or "Без темы").strip()
    sender = (sender or "").strip()
    header = f"От: {sender}\nТема: {subject}\n\n" if sender else f"Тема: {subject}\n\n"
    return f"Письмо: {subject[:120]}", _clean(header + body)


def parse_upload(filename: str, content_type: str, data: bytes) -> tuple[str, str]:
    if not data:
        raise DocumentError("Пустой файл.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError("Файл больше 2 МБ.")

    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf" or "pdf" in (content_type or ""):
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # pypdf бросает разные исключения
            raise DocumentError("Не удалось прочитать PDF. Попробуйте текстовый файл.") from exc
        title = Path(filename or "Документ").stem
        return title[:120], _clean(text)

    if suffix == ".eml" or "message/rfc822" in (content_type or ""):
        return parse_email_bytes(data)

    if suffix in {".txt", ".md", ".csv", ".log", ".json"} or (content_type or "").startswith("text/"):
        title = Path(filename or "Документ").stem
        return title[:120], _clean(_decode(data))

    raise DocumentError("Поддерживаются .txt, .md, .csv, .pdf и .eml.")
