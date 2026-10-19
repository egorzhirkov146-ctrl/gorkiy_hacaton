import asyncio
import io
import logging
from typing import AsyncGenerator
import edge_tts
from gtts import gTTS

logger = logging.getLogger("voice.tts")

RU_VOICES = {
    "svetlana": "ru-RU-SvetlanaNeural",  # Женский
    "dmitry": "ru-RU-DmitryNeural",      # Мужской
    "dariya": "ru-RU-DariyaNeural"       # Женский мягкий
}


def _generate_gtts_bytes(text: str, slow: bool = False) -> bytes:
    """Резервная генерация MP3 в памяти через Google Translate TTS."""
    buf = io.BytesIO()
    tts = gTTS(text=text, lang="ru", slow=slow)
    tts.write_to_fp(buf)
    buf.seek(0)
    return buf.read()


async def synthesize_stream(
    text: str,
    voice_key: str = "svetlana",
    speed: float = 1.0,
    timeout_sec: float = 10.0
) -> AsyncGenerator[bytes, None]:
    """Генерирует потоковое аудио MP3 с автопереключением на fallback."""
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("EMPTY_TEXT")

    voice_id = RU_VOICES.get(voice_key.lower(), RU_VOICES["svetlana"])
    rate_percent = int(round((max(0.5, min(2.0, speed)) - 1.0) * 100))
    rate_str = f"{rate_percent:+d}%"

    try:
        communicate = edge_tts.Communicate(text=clean_text, voice=voice_id, rate=rate_str)
        stream_gen = communicate.stream()

        # Проверка доступности первого чанка с таймаутом
        first_chunk = None
        async with asyncio.timeout(timeout_sec):
            async for chunk in stream_gen:
                if chunk["type"] == "audio":
                    first_chunk = chunk["data"]
                    break

        if not first_chunk:
            raise RuntimeError("Пустой ответ от Edge-TTS")

        yield first_chunk
        async for chunk in stream_gen:
            if chunk["type"] == "audio":
                yield chunk["data"]

    except Exception as err:
        logger.warning(f"Сбой Edge-TTS ({err}), переключение на gTTS...")
        fallback_bytes = await asyncio.wait_for(
            asyncio.to_thread(_generate_gtts_bytes, clean_text, speed < 0.85),
            timeout=timeout_sec
        )
        yield fallback_bytes
