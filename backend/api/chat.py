from fastapi import APIRouter

from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.dialog_service import dialog_service

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    return dialog_service.handle(req)
