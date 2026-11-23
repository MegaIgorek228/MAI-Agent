"""Chat transport: sessionless, no authentication.

The client identifies itself solely by the session UUID it obtains from
``POST /chat/sessions`` (web) — or, for Telegram, the backend maps the chat
id to a session internally. The transcript is owned by Hermes and is served
back through the ACP ``session/load`` replay.
"""

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from app.config import get_settings
from app.db import get_db
from app.hermes_client import HermesUnavailableError, hermes_manager, with_image_instruction
from app.models import AgentSession

router = APIRouter(prefix="/chat", tags=["chat"])

_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class SessionCreate(BaseModel):
    source: str = Field(default="web", pattern="^(web|telegram)$")
    external_id: str | None = Field(default=None, max_length=64)


class ImagePayload(BaseModel):
    data: str = Field(min_length=1, max_length=20_000_000)
    mime_type: str = Field(min_length=3, max_length=100)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    image: ImagePayload | None = None


def _session_or_404(db: Session, session_id: UUID) -> AgentSession:
    session = db.get(AgentSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _session_dict(session: AgentSession) -> dict[str, object]:
    return {
        "id": str(session.id),
        "source": session.source,
        "hermes_session_id": session.hermes_session_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    if payload.source == "telegram" and payload.external_id:
        # Telegram chat id maps to exactly one session.
        existing = db.scalar(
            select(AgentSession).where(
                AgentSession.source == "telegram",
                AgentSession.external_id == payload.external_id,
            )
        )
        if existing is not None:
            return _session_dict(existing)
    session = AgentSession(source=payload.source, external_id=payload.external_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    try:
        session.hermes_session_id = await hermes_manager.start_session(str(session.id))
    except HermesUnavailableError as exc:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.commit()
    return _session_dict(session)


@router.get("/sessions/{session_id}")
def get_session(session_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    return _session_dict(_session_or_404(db, session_id))


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: UUID, db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    session = _session_or_404(db, session_id)
    if not session.hermes_session_id:
        return []
    try:
        return await hermes_manager.history(str(session.id), session.hermes_session_id)
    except HermesUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: UUID,
    payload: MessageCreate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    session = _session_or_404(db, session_id)
    if not session.hermes_session_id:
        raise HTTPException(status_code=409, detail="Hermes session is not initialized")

    content_blocks = None
    prompt_text = payload.content
    if payload.image is not None:
        if payload.image.mime_type.lower() not in _IMAGE_MIME_TYPES:
            raise HTTPException(status_code=422, detail="Unsupported image type")
        try:
            raw_size = base64.b64decode(payload.image.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Image data is not valid base64") from exc
        if len(raw_size) > get_settings().max_image_size_bytes:
            raise HTTPException(status_code=413, detail="Image is too large")
        content_blocks = {"data": payload.image.data, "mime_type": payload.image.mime_type}
        prompt_text = with_image_instruction(payload.content)

    try:
        response, used_hermes_session_id = await hermes_manager.prompt(
            str(session.id),
            session.hermes_session_id,
            prompt_text,
            content_blocks=content_blocks,
        )
    except HermesUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if used_hermes_session_id and used_hermes_session_id != session.hermes_session_id:
        # Stale session after a restart: the manager fell back to a fresh
        # Hermes session — persist it for the next message.
        session.hermes_session_id = used_hermes_session_id
    db.commit()
    if not response:
        raise HTTPException(status_code=502, detail="Hermes returned an empty response")
    return {"role": "assistant", "content": response}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: UUID, db: Session = Depends(get_db)) -> None:
    session = _session_or_404(db, session_id)
    db.delete(session)
    db.commit()
    await hermes_manager.close_session(str(session_id))
