from typing import Optional, AsyncGenerator
from backend.voice.stt import transcribe_audio_bytes
from backend.voice.tts import synthesize_to_file, synthesize_stream


class VoiceService:
    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm",
        timeout_sec: float = 15.0,
    ) -> dict:
        return await transcribe_audio_bytes(
            audio_bytes=audio_bytes,
            filename=filename,
            timeout_sec=timeout_sec,
        )

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> str:
        return await synthesize_to_file(text=text, voice_key=voice or "dmitry", speed=speed)

    async def stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> AsyncGenerator[bytes, None]:
        async for chunk in synthesize_stream(text=text, voice_key=voice or "dmitry", speed=speed):
            yield chunk


voice_service = VoiceService()
