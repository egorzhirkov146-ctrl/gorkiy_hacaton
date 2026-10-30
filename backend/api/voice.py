from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse

from backend.schemas.voice import STTResponse, TTSRequest, TTSResponse
from backend.services.voice_service import voice_service

router = APIRouter(tags=["voice"])


@router.post("/stt", response_model=STTResponse)
async def stt(audio: UploadFile = File(...)) -> STTResponse:
    if not audio.filename:
        return STTResponse(text="", language="ru", duration_sec=0.0)

    content = await audio.read()
    if len(content) < 50:
        return STTResponse(text="", language="ru", duration_sec=0.0)

    try:
        result = await voice_service.transcribe(content, filename=audio.filename)
        return STTResponse(
            text=result.get("text", ""),
            language="ru",
            duration_sec=float(result.get("duration", 0.0)),
        )
    except Exception:
        return STTResponse(text="", language="ru", duration_sec=0.0)


@router.post("/tts", response_model=TTSResponse)
async def tts(req: TTSRequest) -> TTSResponse:
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Текст для синтеза не может быть пустым.")
    try:
        audio_url = await voice_service.synthesize(text=req.text, voice=req.voice)
        return TTSResponse(audio_url=audio_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")


@router.get("/tts/stream")
async def tts_stream(text: str, voice: str = "dmitry", speed: float = 1.0):
    if not text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    return StreamingResponse(
        voice_service.stream(text=text, voice=voice, speed=speed),
        media_type="audio/mpeg",
    )
