"""Telegram channel: a thin relay from bot chats to Hermes sessions.

No user accounts exist: a Telegram chat id is only a mapping key to the
chat's agent session (``agent_sessions.external_id``). Text and photos go
to Hermes; the answer is sent back to the chat. Polling lives only here —
the Hermes gateway's Telegram polling is not used.
"""

import asyncio
import logging
import base64
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.hermes_client import (
    HermesUnavailableError,
    hermes_manager,
    with_image_instruction,
)
from app.models import AgentSession
from app.telegram_checkpoint import read_checkpoint, save_checkpoint

logger = logging.getLogger(__name__)

IMAGE_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _telegram_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


class TelegramService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        token = get_settings().telegram_bot_token
        if not token:
            logger.info("Telegram polling is disabled: TELEGRAM_BOT_TOKEN is not configured")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._poll(token), name="mai-agent-telegram-polling")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _post(self, token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=60,
            verify=_telegram_ssl_context(),
        ) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/{method}",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data}")
            return data

    async def _send(self, token: str, chat_id: str, text: str) -> None:
        while text:
            end = min(len(text), 4000)
            if end < len(text):
                split = max(text.rfind("\n", 2000, end), text.rfind(" ", 2000, end))
                if split >= 0:
                    end = split + 1
            await self._post(
                token, "sendMessage", {"chat_id": chat_id, "text": text[:end]}
            )
            text = text[end:]

    async def _process_updates(
        self, token: str, bot_id: str, updates: list[dict[str, Any]],
        offset: int, failed_attempts: int,
    ) -> tuple[int, int]:
        for update in sorted(updates, key=lambda item: int(item["update_id"])):
            update_id = int(update["update_id"])
            if update_id < offset:
                continue
            if update_id != offset:
                failed_attempts = 0
            try:
                await self._handle_update(token, update)
            except Exception as exc:
                failed_attempts += 1
                logger.warning(
                    "Telegram update %s was not processed on attempt %s: %s",
                    update_id, failed_attempts, exc,
                )
                if failed_attempts < 3:
                    # Keep the failed update unconfirmed before processing later ones.
                    await asyncio.to_thread(save_checkpoint, bot_id, update_id, failed_attempts)
                    return update_id, failed_attempts
                logger.error("Giving up on Telegram update %s after three attempts", update_id)
            offset, failed_attempts = update_id + 1, 0
            await asyncio.to_thread(save_checkpoint, bot_id, offset, failed_attempts)
        return offset, failed_attempts

    async def _poll(self, token: str) -> None:
        bot_id = token.partition(":")[0]
        async with httpx.AsyncClient(
            timeout=get_settings().telegram_polling_timeout_seconds + 10,
            verify=_telegram_ssl_context(),
        ) as client:
            while not self._stop.is_set():
                try:
                    offset, failed_attempts = await asyncio.to_thread(read_checkpoint, bot_id)
                    response = await client.post(
                        f"https://api.telegram.org/bot{token}/getUpdates",
                        json={
                            "offset": offset,
                            "timeout": get_settings().telegram_polling_timeout_seconds,
                            "allowed_updates": ["message"],
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    if not data.get("ok"):
                        logger.error("Telegram getUpdates returned an error")
                        await asyncio.sleep(2)
                        continue
                    _, failed_attempts = await self._process_updates(
                        token, bot_id, data.get("result", []), offset, failed_attempts
                    )
                    if failed_attempts:
                        await asyncio.sleep(2)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Telegram polling failed: %s", exc)
                    await asyncio.sleep(3)

    # ── session mapping ────────────────────────────────────────────────────

    @staticmethod
    def _find_session(db: Session, chat_id: str) -> AgentSession | None:
        return db.scalar(
            select(AgentSession).where(
                AgentSession.source == "telegram",
                AgentSession.external_id == chat_id,
            )
        )

    async def _ensure_session(self, chat_id: str) -> tuple[str, str] | None:
        """Return (app_session_id, hermes_session_id) for the chat, creating
        them if needed. Returns None when Hermes is unavailable."""
        db = SessionLocal()
        try:
            session = self._find_session(db, chat_id)
            if session is None:
                session = AgentSession(source="telegram", external_id=chat_id)
                db.add(session)
                db.commit()
                db.refresh(session)
            if not session.hermes_session_id:
                try:
                    session.hermes_session_id = await hermes_manager.start_session(str(session.id))
                except HermesUnavailableError as exc:
                    db.delete(session)
                    db.commit()
                    logger.warning("Telegram: unable to start Hermes session for chat %s: %s", chat_id, exc)
                    return None
                db.commit()
            return str(session.id), session.hermes_session_id
        finally:
            db.close()

    @staticmethod
    def _rebind_session(app_session_id: str, hermes_session_id: str) -> None:
        with SessionLocal() as db:
            db.execute(
                update(AgentSession)
                .where(AgentSession.id == UUID(app_session_id))
                .values(hermes_session_id=hermes_session_id)
            )
            db.commit()

    # ── update handling ────────────────────────────────────────────────────

    async def _handle_update(self, token: str, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = str(message.get("text", "")).strip()
        photos = message.get("photo") or []
        if photos:
            caption = str(message.get("caption", "")).strip()
            logger.info(
                "Telegram update %s: PHOTO from chat=%s caption=%r",
                update.get("update_id"), chat_id, caption[:80],
            )
            await self._handle_photo(token, chat_id, photos, caption)
            return
        if message.get("document") and chat_id:
            await self._send(
                token, chat_id, "Пока поддерживаются только текст и изображения."
            )
            return
        if not chat_id or not text:
            logger.info(
                "Telegram update %s: ignored (chat=%s, no text/photo)",
                update.get("update_id"), chat_id,
            )
            return
        logger.info(
            "Telegram update %s: TEXT from chat=%s text=%r",
            update.get("update_id"), chat_id, text[:120],
        )

        if text.startswith("/start"):
            await self._start_chat(token, chat_id)
            return
        if text.startswith("/help"):
            await self._send(
                token,
                chat_id,
                "Команды:\n/start — начать работу\n/new — начать новый чат (с чистым контекстом)\n/help — эта справка\n\n"
                "Напишите вопрос текстом или отправьте фото — его проанализирует агент.",
            )
            return
        if text.startswith("/new"):
            await self._new_chat(token, chat_id)
            return
        await self._answer_user_message(token, chat_id, text)

    async def _start_chat(self, token: str, chat_id: str) -> None:
        db = SessionLocal()
        try:
            existed = self._find_session(db, chat_id) is not None
        finally:
            db.close()
        if await self._ensure_session(chat_id) is None:
            await self._send(token, chat_id, "Агент временно недоступен: попробуйте позже.")
            return
        if not existed:
            await self._send(
                token, chat_id,
                "Чат создан. Напишите вопрос — ответит агент МАИ.",
            )
        else:
            await self._send(token, chat_id, "MAI-Agent готов к работе. Напишите вопрос.")

    async def _new_chat(self, token: str, chat_id: str) -> None:
        with SessionLocal() as db:
            session = self._find_session(db, chat_id)
            if session is None:
                session = AgentSession(source="telegram", external_id=chat_id)
                db.add(session)
                db.commit()
                db.refresh(session)
            try:
                session.hermes_session_id = await hermes_manager.start_session(str(session.id))
            except HermesUnavailableError as exc:
                db.commit()
                await self._send(token, chat_id, f"Агент временно недоступен: {exc}")
                return
            db.commit()
        await self._send(token, chat_id, "Новый чат начат. Напишите вопрос.")

    async def _download_file(self, token: str, file_id: str) -> tuple[str, bytes] | None:
        if not file_id:
            return None
        file_info = await self._post(token, "getFile", {"file_id": file_id})
        path = str(file_info.get("result", {}).get("file_path", "")).strip()
        if not path:
            return None
        async with httpx.AsyncClient(timeout=60, verify=_telegram_ssl_context()) as client:
            response = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
            response.raise_for_status()
            return path, response.content

    async def _handle_photo(
        self, token: str, chat_id: str, photos: list[dict[str, Any]], caption: str
    ) -> None:
        if not chat_id or not photos:
            return
        largest = max(photos, key=lambda item: int(item.get("file_size", 0)))
        if int(largest.get("file_size") or 0) > get_settings().max_image_size_bytes:
            await self._send(token, chat_id, "Изображение слишком большое.")
            return
        downloaded = await self._download_file(token, str(largest.get("file_id", "")))
        if downloaded is None:
            await self._send(token, chat_id, "Не удалось получить изображение.")
            return
        file_path, content = downloaded
        filename = Path(file_path).name[:255]
        mime = IMAGE_MIME_BY_SUFFIX.get(Path(filename).suffix.lower(), "image/jpeg")
        if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            await self._send(token, chat_id, "Не поддерживаемый тип изображения.")
            return
        content_blocks = {
            "data": base64.b64encode(content).decode("ascii"),
            "mime_type": mime,
        }
        await self._answer_user_message(
            token, chat_id, caption or "Проанализируй прикрепленное изображение.",
            content_blocks=content_blocks,
        )

    async def _answer_user_message(
        self,
        token: str,
        chat_id: str,
        text: str,
        content_blocks: dict[str, str] | None = None,
    ) -> None:
        t0 = datetime.now(UTC)
        logger.info(
            "Telegram answer start: chat=%s with_image=%s text=%r",
            chat_id, content_blocks is not None, text[:120],
        )
        session_ids = await self._ensure_session(chat_id)
        if session_ids is None:
            await self._send(token, chat_id, "Агент временно недоступен: попробуйте позже.")
            return
        app_session_id, hermes_session_id = session_ids
        prompt_text = with_image_instruction(text) if content_blocks is not None else text
        logger.info("Telegram hermes prompt start: session=%s", app_session_id)
        t1 = datetime.now(UTC)
        try:
            response, used_hermes_session_id = await hermes_manager.prompt(
                app_session_id,
                hermes_session_id,
                prompt_text,
                content_blocks=content_blocks,
            )
        except HermesUnavailableError as exc:
            logger.warning(
                "Telegram hermes prompt failed after %s: %s",
                (datetime.now(UTC) - t1).total_seconds(), exc,
            )
            await self._send(token, chat_id, f"Агент временно недоступен: {exc}")
            return
        logger.info(
            "Telegram hermes prompt done in %.1fs, response_len=%d",
            (datetime.now(UTC) - t1).total_seconds(), len(response or ""),
        )
        if used_hermes_session_id and used_hermes_session_id != hermes_session_id:
            self._rebind_session(app_session_id, used_hermes_session_id)
            logger.info(
                "Telegram session %s re-bound to hermes session %s",
                app_session_id, used_hermes_session_id,
            )
        if not response:
            await self._send(token, chat_id, "Hermes вернул пустой ответ.")
            return
        await self._send(token, chat_id, response)
        logger.info(
            "Telegram answer complete in %.1fs: chat=%s",
            (datetime.now(UTC) - t0).total_seconds(), chat_id,
        )


telegram_service = TelegramService()
