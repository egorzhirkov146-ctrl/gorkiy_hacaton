import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import settings
from backend.api import chat, voice, events
from backend.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    Path(settings.tts_output_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Voice Assistant", version="0.1.0", lifespan=lifespan)

app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(events.router)

tts_dir = Path(settings.tts_output_dir)
tts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/tts", StaticFiles(directory=str(tts_dir)), name="tts")

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="frontend_static")

    @app.get("/", tags=["frontend"])
    def index():
        index_file = frontend_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"status": "ok", "app": "Voice Assistant"}


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
