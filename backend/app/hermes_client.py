import asyncio
import json
import logging
import os
import shlex
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

from acp import PROTOCOL_VERSION, Client, RequestError, connect_to_agent
from acp.schema import (
    AgentMessageChunk,
    ClientCapabilities,
    Implementation,
    HttpHeader,
    HttpMcpServer,
    RequestPermissionResponse,
    ImageContentBlock,
    TextContentBlock,
)

from app.config import get_settings
from app.security import create_trusted_context

logger = logging.getLogger(__name__)


class HermesUnavailableError(RuntimeError):
    """Raised when the configured Hermes ACP process cannot be used."""


#: Instruction prepended to the ACP prompt when an image is attached.
#: Without it, the model may try to locate tooling for opening the image
#: instead of analyzing the inline pixels it already received.
IMAGE_INLINE_INSTRUCTION = (
    "К сообщению прикреплено изображение; оно передано тебе inline — пиксели доступны. "
    "Проанализируй изображение непосредственно, не вызывая инструменты и не читая файлы. "
    "Ответь по его содержимому.\n\n"
)


def with_image_instruction(text: str) -> str:
    """Return the prompt text with the inline-image instruction prepended."""
    return IMAGE_INLINE_INSTRUCTION + text


class HermesCallbacks(Client):
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        if isinstance(update, AgentMessageChunk) and isinstance(update.content, TextContentBlock):
            self.messages.append(update.content.text)

    async def request_permission(self, session_id: str, tool_call: Any, options: Any, **kwargs: Any):
        return RequestPermissionResponse(outcome={"outcome": "cancelled"})

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RequestError.method_not_found(method)

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        raise RequestError.method_not_found(method)


@dataclass
class HermesProcess:
    process: asyncio.subprocess.Process
    connection: Any
    callbacks: HermesCallbacks
    session_id: str
    last_used: float = field(default_factory=monotonic)
    restore_history: bool = False


@dataclass
class SessionLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class HermesSessionLoadError(HermesUnavailableError):
    """The agent explicitly rejected loading a stored session."""


class HermesClientManager:
    def __init__(self) -> None:
        self._processes: dict[int, HermesProcess] = {}
        self._locks: dict[int, SessionLock] = {}
        self._starting = 0

    @asynccontextmanager
    async def _session(self, session_id: int):
        entry = self._locks.setdefault(session_id, SessionLock())
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if not entry.users:
                del self._locks[session_id]

    async def _stop_process(self, process: asyncio.subprocess.Process, connection: Any) -> None:
        if connection is not None:
            with suppress(Exception):
                await asyncio.wait_for(connection.close(), timeout=2)
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()

    async def _start(
        self, user_id: int, app_session_id: int, hermes_session_id: str | None
    ) -> HermesProcess:
        settings = get_settings()
        if settings.acp_transport != "stdio":
            raise HermesUnavailableError("Only ACP stdio transport is supported")
        try:
            command = shlex.split(settings.hermes_command)
        except ValueError as exc:
            raise HermesUnavailableError("Invalid HERMES_COMMAND") from exc
        if not command:
            raise HermesUnavailableError("HERMES_COMMAND is empty")
        cwd = Path(settings.hermes_cwd).resolve()
        if not cwd.is_dir():
            raise HermesUnavailableError(f"Hermes working directory does not exist: {cwd}")

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                # ACP JSON lines can include long tool results and image data.
                limit=50 * 1024 * 1024,
                env=os.environ.copy(),
            )
        except OSError as exc:
            raise HermesUnavailableError("Unable to start Hermes ACP") from exc

        connection = None
        try:
            if process.stdin is None or process.stdout is None:
                raise HermesUnavailableError("Hermes ACP process did not expose stdio pipes")
            callbacks = HermesCallbacks()
            connection = connect_to_agent(
                callbacks, process.stdin, process.stdout, use_unstable_protocol=True
            )
            timeout = settings.acp_startup_timeout_seconds
            await asyncio.wait_for(
                connection.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(name="mai-agent-backend", version="0.1.0"),
                ),
                timeout=timeout,
            )
            trusted_context = create_trusted_context_for_session(user_id, app_session_id)
            mcp_server = HttpMcpServer(
                name="mai-agent",
                url=settings.mcp_public_url,
                headers=[HttpHeader(name="X-MAI-Context", value=trusted_context)],
                type="http",
            )
            if hermes_session_id is None:
                session = await asyncio.wait_for(
                    connection.new_session(cwd=str(cwd), mcp_servers=[mcp_server]),
                    timeout=timeout,
                )
                hermes_session_id = session.session_id
            else:
                try:
                    loaded = await asyncio.wait_for(
                        connection.load_session(
                            cwd=str(cwd),
                            session_id=hermes_session_id,
                            mcp_servers=[mcp_server],
                        ),
                        timeout=timeout,
                    )
                except RequestError as exc:
                    raise HermesSessionLoadError("Hermes rejected the stored session") from exc
                if loaded is None:
                    raise HermesSessionLoadError("Hermes no longer has the stored session")
            return HermesProcess(process, connection, callbacks, hermes_session_id)
        except (HermesUnavailableError, asyncio.CancelledError):
            await self._stop_process(process, connection)
            raise
        except Exception as exc:
            await self._stop_process(process, connection)
            detail = (
                "Hermes ACP startup timed out"
                if isinstance(exc, TimeoutError) else "Hermes ACP startup failed"
            )
            raise HermesUnavailableError(detail) from exc

    async def _open(self, user_id: int, app_session_id: int, previous_id: str | None) -> HermesProcess:
        entry = self._processes.get(app_session_id)
        if entry is not None and entry.process.returncode is None:
            return entry
        await self._close_unlocked(app_session_id)
        await self.close_idle()
        if len(self._processes) + self._starting >= get_settings().hermes_max_processes:
            raise HermesUnavailableError("Hermes is busy. Please retry.")
        self._starting += 1
        try:
            try:
                entry = await self._start(user_id, app_session_id, previous_id)
            except HermesSessionLoadError:
                logger.info("Opening a fresh Hermes session for app session %s", app_session_id)
                entry = await self._start(user_id, app_session_id, None)
                entry.restore_history = True
            self._processes[app_session_id] = entry
            return entry
        finally:
            self._starting -= 1

    async def start_session(self, user_id: int, app_session_id: int) -> str:
        async with self._session(app_session_id):
            return (await self._open(user_id, app_session_id, None)).session_id

    async def prompt(
        self,
        user_id: int,
        app_session_id: int,
        hermes_session_id: str,
        text: str,
        content_blocks: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        async with self._session(app_session_id):
            entry = await self._open(user_id, app_session_id, hermes_session_id)
            entry.callbacks.messages.clear()
            if entry.restore_history:
                text = await asyncio.to_thread(_with_conversation_history, user_id, app_session_id, text)
                entry.restore_history = False
            prompt_blocks: list[Any] = [TextContentBlock(type="text", text=text)]
            if content_blocks is not None:
                prompt_blocks.append(
                    ImageContentBlock(
                        type="image",
                        data=content_blocks["data"],
                        mime_type=content_blocks["mime_type"],
                    )
                )
            try:
                response = await asyncio.wait_for(
                    entry.connection.prompt(session_id=entry.session_id, prompt=prompt_blocks),
                    timeout=get_settings().acp_prompt_timeout_seconds,
                )
            except asyncio.CancelledError:
                await self._close_unlocked(app_session_id)
                raise
            except Exception as exc:
                await self._close_unlocked(app_session_id)
                detail = (
                    "Hermes ACP prompt timed out"
                    if isinstance(exc, TimeoutError) else "Hermes ACP prompt failed"
                )
                raise HermesUnavailableError(detail) from exc
            finally:
                entry.last_used = monotonic()
            if response.stop_reason == "cancelled":
                raise HermesUnavailableError("Hermes ACP prompt was cancelled")
            if response.stop_reason not in ("end_turn", "max_tokens"):
                logger.warning("Hermes ACP prompt stop_reason=%s", response.stop_reason)
            # An empty turn can still have invoked tools. Let the caller show
            # the failure instead of automatically repeating the action.
            return "".join(entry.callbacks.messages).strip(), entry.session_id

    async def _close_unlocked(self, app_session_id: int) -> None:
        entry = self._processes.pop(app_session_id, None)
        if entry is not None:
            await self._stop_process(entry.process, entry.connection)

    async def close_idle(self) -> None:
        deadline = monotonic() - get_settings().hermes_idle_timeout_seconds
        for session_id, entry in list(self._processes.items()):
            if session_id in self._locks or self._processes.get(session_id) is not entry:
                continue
            if entry.process.returncode is not None or entry.last_used <= deadline:
                async with self._session(session_id):
                    await self._close_unlocked(session_id)

    async def reap_idle(self) -> None:
        while True:
            await asyncio.sleep(30)
            await self.close_idle()

    async def close_all(self) -> None:
        for session_id in list(self._processes):
            async with self._session(session_id):
                await self._close_unlocked(session_id)


def _with_conversation_history(user_id: int, app_session_id: int, text: str) -> str:
    """Give a replacement ACP session the previous answered turns as context."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import ChatMessage, ChatSession

    with SessionLocal() as db:
        rows = list(db.execute(
            select(ChatMessage.role, ChatMessage.content)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatSession.id == app_session_id, ChatSession.user_id == user_id)
            .order_by(ChatMessage.id.desc())
            .limit(20)
        ))
    last_answer = next((index for index, row in enumerate(rows) if row.role == "assistant"), None)
    if last_answer is None:
        return text
    history = [
        {"role": row.role, "text": row.content[:1500]}
        for row in reversed(rows[last_answer:])
    ]
    return (
        "Контекст предыдущих сообщений (история для справки):\n"
        + json.dumps(history, ensure_ascii=False)
        + "\n\nТекущее сообщение пользователя:\n"
        + text
    )


def create_trusted_context_for_session(user_id: int, app_session_id: int) -> str:
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise HermesUnavailableError("User no longer exists")
        return create_trusted_context(user, str(app_session_id), ttl_seconds=3600)
    finally:
        db.close()


hermes_manager = HermesClientManager()
