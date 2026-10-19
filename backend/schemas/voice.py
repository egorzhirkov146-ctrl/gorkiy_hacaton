from pydantic import BaseModel, Field


class STTResponse(BaseModel):
    text: str
    language: str = "ru"
    duration_sec: float = 0.0


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str | None = None


class TTSResponse(BaseModel):
    audio_url: str
