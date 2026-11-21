import asyncio
import logging
import secrets
import ssl
import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.document_service import SUPPORTED_IMAGE_TYPES, create_document
from app.hermes_client import (
    HermesUnavailableError,
    hermes_manager,
    with_image_instruction,
)
from app.models import ChatMessage, ChatSession, TelegramIdentity, User
from app.security import hash_password
from app.telegram_checkpoint import read_checkpoint, save_checkpoint

logger = logging.getLogger(__name__)

DOCUMENT_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
} | {suffix: mime for mime, suffix in SUPPORTED_IMAGE_TYPES.items()}
DOCUMENT_MIME_TYPES[".jpeg"] = "image/jpeg"


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
            await self._handle_document(token, chat_id, message["document"])
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
            await self._start_user(token, chat_id)
            return
        if text.startswith("/help"):
            await self._send(
                token,
                chat_id,
                "Команды:\n/start — создать Telegram-аккаунт и начать работу\n"
                "/pair КОД — привязать существующий аккаунт Backend\n"
                "Фото прикрепляются к чату. PDF, DOCX и TXT сохраняются в разделе документов.",
            )
            return
        if text.startswith("/pair"):
            await self._pair(token, chat_id, text)
            return
        await self._answer_user_message(token, chat_id, text)

    async def _start_user(self, token: str, chat_id: str) -> None:
        db = SessionLocal()
        try:
            identity = db.scalar(
                select(TelegramIdentity).where(TelegramIdentity.chat_id == chat_id)
            )
            if identity is not None and identity.user_id is not None:
                await self._send(
                    token,
                    chat_id,
                    "MAI-Agent готов к работе. Напишите вопрос.",
                )
                return

            identity = db.scalar(
                select(TelegramIdentity).where(TelegramIdentity.chat_id == chat_id)
            )
            if identity is None:
                identity = TelegramIdentity(chat_id=chat_id)
                db.add(identity)

            email = f"telegram-{chat_id}@mai-agent.local"
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    email=email,
                    password_hash=hash_password(secrets.token_urlsafe(32)),
                    role="applicant",
                )
                db.add(user)
                db.flush()
            identity.user_id = user.id
            identity.pairing_code = None
            identity.pairing_expires_at = None
            db.commit()
        finally:
            db.close()

        await self._send(
            token,
            chat_id,
            "Аккаунт Telegram создан автоматически. Напишите вопрос.",
        )

    async def _pair(self, token: str, chat_id: str, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            await self._send(token, chat_id, "Формат: /pair КОД")
            return
        code = parts[1].strip().upper()
        db = SessionLocal()
        try:
            identity = db.scalar(
                select(TelegramIdentity).where(TelegramIdentity.pairing_code == code)
            )
            if identity is None:
                await self._send(token, chat_id, "Код не найден.")
                return
            expires_at = identity.pairing_expires_at
            if expires_at is not None:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at is None or expires_at <= datetime.now(UTC):
                identity.pairing_code = None
                identity.pairing_expires_at = None
                db.commit()
                await self._send(token, chat_id, "Код истек.")
                return

            existing = db.scalar(
                select(TelegramIdentity).where(TelegramIdentity.chat_id == chat_id)
            )
            if existing is not None and existing.id != identity.id:
                existing.chat_id = None
                existing.user_id = None
            identity.chat_id = chat_id
            identity.pairing_code = None
            identity.pairing_expires_at = None
            db.commit()
        finally:
            db.close()
        await self._send(token, chat_id, "Аккаунт успешно привязан.")

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

    @staticmethod
    def _linked_user(db: Session, chat_id: str) -> User | None:
        return db.scalar(
            select(User).join(TelegramIdentity, TelegramIdentity.user_id == User.id)
            .where(TelegramIdentity.chat_id == chat_id)
        )

    def _store_document(self, chat_id: str, filename: str, mime: str, content: bytes) -> int | None:
        with SessionLocal() as db:
            user = self._linked_user(db, chat_id)
            if user is None or not user.is_active:
                return None
            document = create_document(
                db, owner_id=user.id, filename=filename, content_type=mime, content=content,
            )
            document_id = document.id
            db.commit()
            return document_id

    async def _handle_document(self, token: str, chat_id: str, metadata: dict[str, Any]) -> None:
        filename = Path(str(metadata.get("file_name", ""))).name[:255]
        mime = DOCUMENT_MIME_TYPES.get(Path(filename).suffix.lower())
        if mime is None:
            await self._send(token, chat_id, "Поддерживаются PDF, DOCX, TXT и изображения.")
            return
        if int(metadata.get("file_size") or 0) > get_settings().max_upload_size_bytes:
            await self._send(token, chat_id, "Файл превышает допустимый размер.")
            return
        downloaded = await self._download_file(token, str(metadata.get("file_id", "")))
        if downloaded is None:
            await self._send(token, chat_id, "Не удалось получить файл.")
            return
        _, content = downloaded
        try:
            document_id = await asyncio.to_thread(self._store_document, chat_id, filename, mime, content)
        except ValueError as exc:
            await self._send(token, chat_id, f"Не удалось сохранить файл. {exc}")
            return
        if document_id is None:
            await self._send(token, chat_id, "Начните работу через /start или привяжите аккаунт через /pair.")
            return
        await self._send(token, chat_id, f"Документ «{filename}» сохранён в вашем профиле. Номер {document_id}.")

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
        mime = DOCUMENT_MIME_TYPES.get(Path(filename).suffix.lower(), "image/jpeg")
        try:
            document_id = await asyncio.to_thread(self._store_document, chat_id, filename, mime, content)
        except ValueError:
            await self._send(token, chat_id, "Файл не является поддерживаемым изображением или слишком большой.")
            return
        if document_id is None:
            await self._send(token, chat_id, "Начните работу через /start или привяжите аккаунт через /pair.")
            return
        content_blocks = {
            "data": base64.b64encode(content).decode("ascii"),
            "mime_type": mime,
        }
        await self._answer_user_message(
            token, chat_id, caption or "Проанализируй прикрепленное изображение.",
            content_blocks=content_blocks,
            image_document_id=document_id,
        )

    async def _answer_user_message(
        self,
        token: str,
        chat_id: str,
        text: str,
        content_blocks: dict[str, str] | None = None,
        image_document_id: int | None = None,
    ) -> None:
        t0 = datetime.now(UTC)
        logger.info(
            "Telegram answer start: chat=%s with_image=%s text=%r",
            chat_id, content_blocks is not None, text[:120],
        )
        db = SessionLocal()
        try:
            identity = db.scalar(
                select(TelegramIdentity).where(TelegramIdentity.chat_id == chat_id)
            )
            if identity is None or identity.user_id is None:
                await self._send(
                    token,
                    chat_id,
                    "Сначала привяжите аккаунт командой /pair КОД.",
                )
                return
            user = db.get(User, identity.user_id)
            if user is None or not user.is_active:
                await self._send(token, chat_id, "Аккаунт недоступен.")
                return

            session = db.scalar(
                select(ChatSession)
                .where(
                    ChatSession.user_id == user.id,
                    ChatSession.channel == "telegram",
                )
                .order_by(ChatSession.created_at.desc())
            )
            if session is None:
                session = ChatSession(user_id=user.id, channel="telegram")
                db.add(session)
                db.commit()
                db.refresh(session)
                try:
                    session.hermes_session_id = await hermes_manager.start_session(user.id, session.id)
                except HermesUnavailableError as exc:
                    db.delete(session)
                    db.commit()
                    await self._send(
                        token,
                        chat_id,
                        f"Агент временно недоступен: {exc}",
                    )
                    return
                db.commit()

            db.add(ChatMessage(
                session_id=session.id, role="user", content=text, image_document_id=image_document_id,
            ))
            db.commit()
            if not session.hermes_session_id:
                await self._send(token, chat_id, "Агентская сессия не инициализирована.")
                return
            prompt_text = (
                with_image_instruction(text) if content_blocks is not None else text
            )
            logger.info("Telegram hermes prompt start: session=%s", session.id)
            t1 = datetime.now(UTC)
            try:
                response, used_hermes_session_id = await hermes_manager.prompt(
                    user.id,
                    session.id,
                    session.hermes_session_id,
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
            if used_hermes_session_id and used_hermes_session_id != session.hermes_session_id:
                # Stale session after a restart: the manager fell back to a
                # fresh hermes session — persist it for the next message.
                session.hermes_session_id = used_hermes_session_id
                db.commit()
                logger.info("Telegram session %s re-bound to hermes session %s", session.id, used_hermes_session_id)
            if not response:
                await self._send(token, chat_id, "Hermes вернул пустой ответ.")
                return
            db.add(ChatMessage(session_id=session.id, role="assistant", content=response))
            db.commit()
        finally:
            db.close()
        await self._send(token, chat_id, response)
        logger.info(
            "Telegram answer complete in %.1fs: chat=%s",
            (datetime.now(UTC) - t0).total_seconds(), chat_id,
        )


telegram_service = TelegramService()
