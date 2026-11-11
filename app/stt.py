"""Локальное распознавание речи (Vosk). Аудио не покидает сервер."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import imageio_ffmpeg
import vosk

from .config import settings

vosk.SetLogLevel(-1)

_model_lock = threading.Lock()
_model: vosk.Model | None = None
_model_path_used: Path | None = None


class STTError(RuntimeError):
    pass


def _ascii_model_path(source: Path) -> Path:
    """Vosk на Windows не открывает модели из путей с кириллицей."""
    if str(source).isascii():
        return source
    cache_root = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir()) / "fotoprint"
    cache = cache_root / source.name
    if not (cache / "am" / "final.mdl").exists():
        cache_root.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)
        shutil.copytree(source, cache)
    return cache


def _get_model() -> vosk.Model:
    global _model, _model_path_used
    with _model_lock:
        if _model is not None:
            return _model
        source = settings.vosk_model_path
        if not source.exists():
            raise STTError(
                "Модель распознавания не найдена. Запустите: python scripts/setup_vosk.py"
            )
        path = _ascii_model_path(source)
        _model = vosk.Model(str(path))
        _model_path_used = path
        return _model


def _convert_to_wav(data: bytes, content_type: str) -> Path:
    suffix = ".webm"
    if "mp4" in content_type or "m4a" in content_type:
        suffix = ".m4a"
    elif "ogg" in content_type:
        suffix = ".ogg"
    elif "wav" in content_type:
        suffix = ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    out = Path(tmp.name).with_suffix(".16k.wav")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", tmp.name, "-ac", "1", "-ar", "16000", "-f", "wav", str(out)],
        capture_output=True,
    )
    try:
        Path(tmp.name).unlink(missing_ok=True)
    except OSError:
        pass
    if proc.returncode != 0 or not out.exists():
        raise STTError("Не удалось конвертировать аудио")
    return out


def transcribe_audio(data: bytes, content_type: str = "") -> tuple[str, float]:
    if not data:
        raise STTError("Пустой аудиофайл")
    model = _get_model()
    wav_path = _convert_to_wav(data, content_type)
    try:
        with wave.open(str(wav_path), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
            duration = frames / rate if rate else 0
            recognizer = vosk.KaldiRecognizer(model, rate)
            parts: list[str] = []
            while True:
                chunk = wf.readframes(8000)
                if not chunk:
                    break
                if recognizer.AcceptWaveform(chunk):
                    result = json.loads(recognizer.Result())
                    if result.get("text"):
                        parts.append(result["text"])
            final = json.loads(recognizer.FinalResult())
            if final.get("text"):
                parts.append(final["text"])
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass

    text = " ".join(parts).strip()
    if not text:
        raise STTError("Речь не распознана — проверьте микрофон и громкость")
    return text, duration


def model_ready() -> bool:
    try:
        _get_model()
        return True
    except STTError:
        return False
