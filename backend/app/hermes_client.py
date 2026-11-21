import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acp import PROTOCOL_VERSION, Client, RequestError, connect_to_agent
from acp.schema import (
    AgentMessageChunk,
    ClientCapabilities,
    Implementation,
    RequestPermissionResponse,
    ImageContentBlock,
    TextContentBlock,
)

from app.config import get_settings
from app.security import create_trusted_context


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


class HermesClientManager:
    def __init__(self) -> None:
        self._processes: dict[int, HermesProcess] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, session_id: int) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    async def _start(
        self, user_id: int, app_session_id: int, hermes_session_id: str | None
    ) -> tuple[HermesProcess, str]:
        settings = get_settings()
        if settings.acp_transport != "stdio":
            raise HermesUnavailableError("Only ACP stdio transport is supported")
        command = settings.hermes_command.split()
        if not command:
            raise HermesUnavailableError("HERMES_COMMAND is empty")
        cwd = Path(settings.hermes_cwd).resolve()
        if not cwd.exists():
            raise HermesUnavailableError(f"Configured Hermes working directory does not exist: {cwd}")
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=os.environ.copy(),
            )
        except OSError as exc:
            raise HermesUnavailableError(
                f"Unable to start Hermes ACP command '{settings.hermes_command}'"
            ) from exc
        if process.stdin is None or process.stdout is None:
            raise HermesUnavailableError("Hermes ACP process did not expose stdio pipes")

        callbacks = HermesCallbacks()
        connection = connect_to_agent(
            callbacks, process.stdin, process.stdout, use_unstable_protocol=True
        )
        try:
            await asyncio.wait_for(
                connection.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(name="mai-agent-backend", version="0.1.0"),
                ),
                timeout=settings.acp_startup_timeout_seconds,
            )
        except TimeoutError as exc:
            process.terminate()
            await process.wait()
            raise HermesUnavailableError("Hermes ACP initialization timed out") from exc
        trusted_context = create_trusted_context_for_session(user_id, app_session_id)
        from acp.schema import HttpHeader, HttpMcpServer

        mcp_server = HttpMcpServer(
            name="mai-agent",
            url=settings.mcp_public_url,
            headers=[HttpHeader(name="X-MAI-Context", value=trusted_context)],
            type="http",
        )
        if hermes_session_id:
            try:
                await asyncio.wait_for(
                    connection.load_session(
                        cwd=str(cwd),
                        session_id=hermes_session_id,
                        mcp_servers=[mcp_server],
                    ),
                    timeout=settings.acp_startup_timeout_seconds,
                )
            except TimeoutError as exc:
                process.terminate()
                await process.wait()
                raise HermesUnavailableError("Hermes ACP session loading timed out") from exc
            actual_session_id = hermes_session_id
        else:
            try:
                session = await asyncio.wait_for(
                    connection.new_session(cwd=str(cwd), mcp_servers=[mcp_server]),
                    timeout=settings.acp_startup_timeout_seconds,
                )
            except TimeoutError as exc:
                process.terminate()
                await process.wait()
                raise HermesUnavailableError("Hermes ACP session creation timed out") from exc
            actual_session_id = session.session_id
        return HermesProcess(process, connection, callbacks), actual_session_id

    async def start_session(self, user_id: int, app_session_id: int) -> str:
        async with self._lock_for(app_session_id):
            process_entry, hermes_session_id = await self._start(user_id, app_session_id, None)
            self._processes[app_session_id] = process_entry
            return hermes_session_id

    async def prompt(
        self,
        user_id: int,
        app_session_id: int,
        hermes_session_id: str,
        text: str,
        content_blocks: dict[str, str] | None = None,
    ) -> str:
        async with self._lock_for(app_session_id):
            process_entry = self._processes.get(app_session_id)
            if process_entry is None or process_entry.process.returncode is not None:
                process_entry, hermes_session_id = await self._start(
                    user_id, app_session_id, hermes_session_id
                )
                self._processes[app_session_id] = process_entry
            process_entry.callbacks.messages.clear()
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
                    process_entry.connection.prompt(
                        session_id=hermes_session_id,
                        prompt=prompt_blocks,
                    ),
                    timeout=get_settings().acp_prompt_timeout_seconds,
                )
            except TimeoutError as exc:
                await self.close(app_session_id)
                raise HermesUnavailableError("Hermes ACP prompt timed out") from exc
            except Exception as exc:
                await self.close(app_session_id)
                raise HermesUnavailableError("Hermes ACP prompt failed") from exc
            if response.stop_reason == "cancelled":
                raise HermesUnavailableError("Hermes ACP prompt was cancelled")
            return "".join(process_entry.callbacks.messages).strip()

    async def close(self, app_session_id: int) -> None:
        process_entry = self._processes.pop(app_session_id, None)
        if process_entry is None:
            return
        if process_entry.process.returncode is None:
            process_entry.process.terminate()
            await process_entry.process.wait()


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
