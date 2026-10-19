from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api import chat, voice, events
from backend.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Voice Assistant", version="0.1.0", lifespan=lifespan)

app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(events.router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
