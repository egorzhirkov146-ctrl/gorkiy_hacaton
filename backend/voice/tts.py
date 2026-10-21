import asyncio
import io
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncGenerator

from backend.config import settings

logger = logging.getLogger("voice.tts")

RU_VOICES = {
    "svetlana": "ru-RU-SvetlanaNeural",  # Женский
    "dmitry": "ru-RU-DmitryNeural",      # Мужской
    "dariya": "ru-RU-DariyaNeural",      # Женский мягкий
}


def _generate_gtts_bytes(text: str, slow: bool = False) -> bytes:
    """Резервная генерация MP3 в памяти через Google Translate TTS."""
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        tts = gTTS(text=text, lang="ru", slow=slow)
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.error(f"gTTS fallback error: {e}")
        # Возвращаем минимальный валидный пустой MP3 фрейм
        return b"\xff\xfb\x90d\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"


async def synthesize_stream(
    text: str,
    voice_key: str = "dmitry",
    speed: float = 1.0,
    timeout_sec: float = 10.0
) -> AsyncGenerator[bytes, None]:
    """Потоковая генерация MP3 через edge-tts с автопереключением на gTTS."""
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("EMPTY_TEXT")

    voice_id = RU_VOICES.get(voice_key.lower(), settings.tts_voice)
    rate_percent = int(round((max(0.5, min(2.0, speed)) - 1.0) * 100))
    rate_str = f"{rate_percent:+d}%"

    try:
        import edge_tts
        communicate = edge_tts.Communicate(text=clean_text, voice=voice_id, rate=rate_str)
        stream = communicate.stream()

        has_audio = False
        async for chunk in stream:
            if chunk["type"] == "audio":
                has_audio = True
                yield chunk["data"]

        if not has_audio:
            raise RuntimeError("Пустой ответ от edge-tts")

    except Exception as err:
        logger.warning(f"Сбой edge-tts ({err}), переключение на gTTS...")
        fallback_bytes = await asyncio.wait_for(
            asyncio.to_thread(_generate_gtts_bytes, clean_text, speed < 0.85),
            timeout=timeout_sec
        )
        yield fallback_bytes


async def synthesize_to_file(
    text: str,
    voice_key: str = "dmitry",
    speed: float = 1.0,
) -> str:
    """Генерирует MP3 файл и сохраняет его в директорию tts_output_dir.

    Возвращает URL-путь (например: '/static/tts/abc-123.mp3').
    """
    out_dir = Path(settings.tts_output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex[:12]}.mp3"
    filepath = out_dir / filename

    audio_bytes = bytearray()
    async for chunk in synthesize_stream(text, voice_key=voice_key, speed=speed):
        audio_bytes.extend(chunk)

    with open(filepath, "wb") as f:
        f.write(audio_bytes)

    return f"/static/tts/{filename}"
