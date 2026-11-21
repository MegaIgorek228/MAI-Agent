import asyncio
import logging
import secrets
import ssl
import base64
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.hermes_client import (
    HermesUnavailableError,
    hermes_manager,
    with_image_instruction,
)
from app.models import ChatMessage, ChatSession, TelegramIdentity, User
from app.security import hash_password

logger = logging.getLogger(__name__)


def _telegram_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


class TelegramService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
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
        await self._post(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": text[:4000]},
        )

    async def _poll(self, token: str) -> None:
        offset = 0
        async with httpx.AsyncClient(
            timeout=get_settings().telegram_polling_timeout_seconds + 10,
            verify=_telegram_ssl_context(),
        ) as client:
            while not self._stop.is_set():
                try:
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
                    updates = data.get("result", [])
                    if updates:
                        logger.info(
                            "Telegram getUpdates: %d update(s) (ids %s..%s), local offset was %d",
                            len(updates),
                            updates[0]["update_id"],
                            updates[-1]["update_id"],
                            offset,
                        )
                    for update in updates:
                        update_id = int(update["update_id"])
                        try:
                            await self._handle_update(token, update)
                        except Exception as exc:
                            logger.warning(
                                "Telegram update %s was not processed: %s",
                                update_id,
                                exc,
                            )
                            continue
                        offset = max(offset, update_id + 1)
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
        update_date = int(message.get("date", 0) or 0)
        if photos:
            caption = str(message.get("caption", "")).strip()
            logger.info(
                "Telegram update %s: PHOTO from chat=%s caption=%r",
                update.get("update_id"), chat_id, caption[:80],
            )
            await self._handle_photo(token, chat_id, photos, caption)
            return
        if not chat_id or not text:
            logger.info(
                "Telegram update %s: ignored (chat=%s, no text/photo)",
                update.get("update_id"), chat_id,
            )
            return
        # Защита от повторной обработки истории после рестарта контейнера:
        # getUpdates с offset=0 возвращает всю накопившуюся историю, и каждый
        # старый текст запускает полноценный LLM-вызов, блокируя очередь живых
        # сообщений. Обновения старше 5 минут пропускаем (offset при этом
        # корректно продвигается).
        now_ts = int(datetime.now(UTC).timestamp())
        if update_date and (now_ts - update_date) > 300:
            logger.warning(
                "Telegram update %s skipped: stale (age %ds), text=%r",
                update.get("update_id"), now_ts - update_date, text[:80],
            )
            return
        logger.info(
            "Telegram update %s: TEXT from chat=%s age=%ds text=%r",
            update.get("update_id"), chat_id, now_ts - update_date if update_date else -1, text[:120],
        )

        if text.startswith("/start"):
            await self._start_user(token, chat_id)
            return
        if text.startswith("/help"):
            await self._send(
                token,
                chat_id,
                "Команды:\n/start — создать Telegram-аккаунт и начать работу\n"
                "/pair КОД — привязать существующий аккаунт Backend",
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

    async def _handle_photo(
        self,
        token: str,
        chat_id: str,
        photos: list[dict[str, Any]],
        caption: str,
    ) -> None:
        if not chat_id or not photos:
            return
        largest = max(photos, key=lambda item: int(item.get("file_size", 0)))
        file_id = str(largest.get("file_id", ""))
        if not file_id:
            await self._send(token, chat_id, "Не удалось получить изображение.")
            return
        file_info = await self._post(token, "getFile", {"file_id": file_id})
        file_path = str(file_info.get("result", {}).get("file_path", "")).strip()
        if not file_path:
            await self._send(token, chat_id, "Не удалось получить файл изображения.")
            return
        ssl_context = _telegram_ssl_context()
        async with httpx.AsyncClient(timeout=60, verify=ssl_context) as client:
            response = await client.get(
                f"https://api.telegram.org/file/bot{token}/{file_path}"
            )
            response.raise_for_status()
            content = response.content
        if len(content) > 10 * 1024 * 1024:
            await self._send(token, chat_id, "Изображение слишком большое.")
            return
        mime_type = "image/jpeg"
        if file_path.lower().endswith(".png"):
            mime_type = "image/png"
        elif file_path.lower().endswith(".webp"):
            mime_type = "image/webp"
        elif file_path.lower().endswith(".gif"):
            mime_type = "image/gif"
        try:
            from PIL import Image
            from io import BytesIO

            with Image.open(BytesIO(content)) as image:
                image.verify()
        except Exception:
            await self._send(token, chat_id, "Файл не является поддерживаемым изображением.")
            return
        content_blocks = {
            "data": base64.b64encode(content).decode("ascii"),
            "mime_type": mime_type,
        }
        await self._answer_user_message(
            token,
            chat_id,
            caption or "Проанализируй прикрепленное изображение.",
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

            db.add(ChatMessage(session_id=session.id, role="user", content=text))
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
