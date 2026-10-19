import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from voice import init_stt_model, transcribe_audio_bytes, synthesize_stream, RU_VOICES

#uvicorn main:app --host 0.0.0.0 --port 8000 --reload запуск сервера для разработки
#проверка tts: curl -X POST "http://localhost:8000/tts" -H "accept: application/json" -H "Content-Type: application/json" -d "{\"text\":\"Привет, как дела?\",\"voice\":\"svetlana\",\"speed\":1.0}" --output output.mp3
#еще tts: curl -X POST "http://localhost:8000/tts" -H "Content-Type: application/json" -d '{"text": "Добавил встречу с командой на завтра в 15:00.", "voice": "dmitry", "speed": 1.1}' --output response.mp3
#проверка sst: curl -X POST "http://localhost:8000/stt" -F "file=@output.mp3"
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Кэшируем модель Whisper при старте сервера
    init_stt_model(
        model_size=os.getenv("WHISPER_MODEL", "small"),
        device=os.getenv("WHISPER_DEVICE", "cpu"),
        compute_type=os.getenv("WHISPER_COMPUTE", "int8")
    )
    yield


app = FastAPI(title="Voice Module", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        res = await transcribe_audio_bytes(audio_bytes, filename=file.filename or "audio.webm")
        return {"status": "ok", "text": res["text"], "duration_sec": res["duration"]}
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"error": str(e), "fallback_to_text": True, "message": "Не удалось распознать речь."}
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={"error": "TIMEOUT", "fallback_to_text": True, "message": "Таймаут распознавания."}
        )


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str = "dmitry"
    speed: float = 1.0


@app.post("/tts")
async def text_to_speech(req: TTSRequest):
    return StreamingResponse(
        synthesize_stream(req.text, voice_key=req.voice, speed=req.speed),
        media_type="audio/mpeg"
    )
