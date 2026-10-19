from fastapi import APIRouter

from backend.schemas.chat import ChatRequest, ChatResponse, ActionOut

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    # TODO(A): заменить на dialog_service.handle(req)
    return ChatResponse(
        session_id=req.session_id,
        reply_text=f"[stub] получено: {req.text}",
        action=ActionOut(type="error", status="pending"),
        needs_clarification=False,
    )
