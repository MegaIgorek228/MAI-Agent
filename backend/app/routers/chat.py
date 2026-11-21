import base64

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.hermes_client import (
    HermesUnavailableError,
    hermes_manager,
    with_image_instruction,
)
from app.models import ChatMessage, ChatSession, Document, User

router = APIRouter(prefix="/chat", tags=["chat"])


class SessionCreate(BaseModel):
    channel: str = Field(default="web", max_length=32)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    image_document_id: int | None = None


def get_owned_session(db: Session, user: User, session_id: int) -> ChatSession:
    session = db.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    session = ChatSession(user_id=current_user.id, channel=payload.channel)
    db.add(session)
    db.commit()
    db.refresh(session)
    try:
        session.hermes_session_id = await hermes_manager.start_session(current_user.id, session.id)
    except HermesUnavailableError as exc:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.commit()
    return {"id": session.id, "channel": session.channel, "hermes_session_id": session.hermes_session_id}


@router.get("/sessions")
def list_sessions(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    sessions = db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.created_at.desc())
    )
    return [{"id": item.id, "channel": item.channel, "created_at": item.created_at} for item in sessions]


@router.get("/sessions/{session_id}/messages")
def list_messages(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    get_owned_session(db, current_user, session_id)
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    results = []
    for item in messages:
        entry: dict[str, object] = {
            "role": item.role,
            "content": item.content,
            "created_at": item.created_at,
        }
        if item.image_document_id is not None:
            document = db.get(Document, item.image_document_id)
            entry["image_document_id"] = item.image_document_id
            entry["image_filename"] = document.filename if document is not None else None
        results.append(entry)
    return results


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    session = get_owned_session(db, current_user, session_id)
    if not session.hermes_session_id:
        raise HTTPException(status_code=409, detail="Hermes session is not initialized")

    content_blocks = None
    prompt_text = payload.content
    if payload.image_document_id is not None:
        document = db.scalar(
            select(Document).where(
                Document.id == payload.image_document_id,
                Document.owner_id == current_user.id,
            )
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Image document not found")
        if document.content_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/gif",
        }:
            raise HTTPException(status_code=422, detail="Document is not a supported image")
        content_blocks = {
            "data": base64.b64encode(document.content).decode("ascii"),
            "mime_type": document.content_type,
            "text": payload.content,
        }
        prompt_text = with_image_instruction(payload.content)

    db.add(
        ChatMessage(
            session_id=session.id,
            role="user",
            content=payload.content,
            image_document_id=payload.image_document_id,
        )
    )
    db.commit()
    try:
        response = await hermes_manager.prompt(
            current_user.id,
            session.id,
            session.hermes_session_id,
            prompt_text,
            content_blocks=content_blocks,
        )
    except HermesUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not response:
        raise HTTPException(status_code=502, detail="Hermes returned an empty response")
    db.add(ChatMessage(session_id=session.id, role="assistant", content=response))
    db.commit()
    return {"role": "assistant", "content": response}
