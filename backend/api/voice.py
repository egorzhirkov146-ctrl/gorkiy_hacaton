from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.schemas.voice import STTResponse, TTSRequest, TTSResponse

router = APIRouter(tags=["voice"])


@router.post("/stt", response_model=STTResponse)
async def stt(audio: UploadFile = File(...)) -> STTResponse:
    # TODO(C): заменить на voice_service.transcribe
    if not audio.filename:
        raise HTTPException(status_code=400, detail="empty audio")
    return STTResponse(text="[stub] распознанный текст", language="ru", duration_sec=0.0)


@router.post("/tts", response_model=TTSResponse)
def tts(req: TTSRequest) -> TTSResponse:
    # TODO(C): заменить на voice_service.synthesize
    return TTSResponse(audio_url="/static/tts/stub.mp3")
