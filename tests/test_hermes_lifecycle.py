"""Unit tests for the Hermes ACP session manager (mocked subprocess/ACPL)."""
import asyncio
from types import SimpleNamespace

import pytest
from acp.schema import (
    AgentMessageChunk,
    LoadSessionResponse,
    TextContentBlock,
    UserMessageChunk,
)

from app import hermes_client


class Process:
    returncode = None

    def __init__(self):
        self.stdin = object()
        self.stdout = object()

    def terminate(self):
        self.returncode = 0

    async def wait(self):
        return self.returncode


class Connection:
    def __init__(self, load_response=None, stop_reason="end_turn", replay=None):
        self.closed = False
        self.prompts = []
        self.load_response = load_response
        self.stop_reason = stop_reason
        self.replay = replay or []

    async def initialize(self, **kwargs):
        return None

    async def load_session(self, **kwargs):
        # Simulate the ACP spec: the stored transcript is streamed back as
        # session_update notifications before the load response returns.
        for role, text in self.replay:
            block = TextContentBlock(type="text", text=text)
            if role == "user":
                update = UserMessageChunk(session_update="user_message_chunk", content=block)
            else:
                update = AgentMessageChunk(session_update="agent_message_chunk", content=block)
            await self._callbacks.session_update("sid", update)
        return self.load_response

    def bind_callbacks(self, callbacks):
        self._callbacks = callbacks

    async def new_session(self, **kwargs):
        return SimpleNamespace(session_id="new-session")

    async def prompt(self, **kwargs):
        self.prompts.append(kwargs["prompt"][0].text)
        return SimpleNamespace(stop_reason=self.stop_reason)

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("load_response", [None, LoadSessionResponse()])
def test_missing_stored_session_reopens(monkeypatch, load_response):
    processes, connections = [], []

    async def spawn(*args, **kwargs):
        process = Process()
        processes.append(process)
        return process

    def connect(callbacks, *args, **kwargs):
        connection = Connection(load_response, "refusal")
        connection.bind_callbacks(callbacks)
        connections.append(connection)
        return connection

    monkeypatch.setattr(hermes_client.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(hermes_client, "connect_to_agent", connect)
    manager = hermes_client.HermesClientManager()

    async def scenario():
        assert await manager.prompt("app-1", "purged-session", "sample") == ("", "new-session")
        assert await manager.prompt("app-1", "new-session", "follow-up") == ("", "new-session")
        assert [connection.prompts for connection in connections] == [[], ["sample", "follow-up"]]
        assert connections[0].closed and processes[0].returncode == 0
        assert manager._locks == {}
        await manager.close_all()

    asyncio.run(scenario())
    assert all(connection.closed for connection in connections)
    assert all(process.returncode == 0 for process in processes)


def test_load_replay_is_captured_as_history(monkeypatch):
    processes, connections = [], []

    async def spawn(*args, **kwargs):
        process = Process()
        processes.append(process)
        return process

    def connect(callbacks, *args, **kwargs):
        connection = Connection(
            LoadSessionResponse(field_meta={"ok": True}),
            replay=[("user", "вечер"), ("assistant", "вечер "), ("assistant", "хорош")],
        )
        connection.bind_callbacks(callbacks)
        connections.append(connection)
        return connection

    monkeypatch.setattr(hermes_client.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(hermes_client, "connect_to_agent", connect)
    manager = hermes_client.HermesClientManager()

    async def scenario():
        history = await manager.history("app-1", "stored-session")
        assert history == [
            {"role": "user", "content": "вечер"},
            {"role": "assistant", "content": "вечер хорош"},
        ]
        # A warm process serves the same history without another load.
        again = await manager.history("app-1", "stored-session")
        assert again == history
        await manager.close_all()

    asyncio.run(scenario())
    assert len(connections) == 1


def test_prompt_appends_turn_to_history(monkeypatch):
    processes, connections = [], []

    async def spawn(*args, **kwargs):
        process = Process()
        processes.append(process)
        return process

    def connect(callbacks, *args, **kwargs):
        connection = Connection(LoadSessionResponse(field_meta={"ok": True}),
            replay=[("user", "old"), ("assistant", "old-answer")])
        connection.bind_callbacks(callbacks)
        connections.append(connection)
        return connection

    monkeypatch.setattr(hermes_client.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(hermes_client, "connect_to_agent", connect)
    manager = hermes_client.HermesClientManager()

    async def scenario():
        async def fake_prompt(self_or_entry, *args, **kwargs):
            pass
        # Make the connection prompt stream an assistant chunk via callbacks.
        original_prompt = connections[0].prompt if connections else None
        entry = await manager._open("app-1", "stored-session")

        async def streaming_prompt(session_id, prompt):
            for chunk_text in ("ok", " done"):
                await entry.callbacks.session_update(
                    session_id,
                    AgentMessageChunk(session_update="agent_message_chunk",
                                      content=TextContentBlock(type="text", text=chunk_text)),
                )
            return SimpleNamespace(stop_reason="end_turn")

        connections[0].prompt = streaming_prompt
        answer, hermes_id = await manager.prompt("app-1", "stored-session", "new question")
        assert answer == "ok done"
        assert entry.history[-2:] == [
            {"role": "user", "content": "new question"},
            {"role": "assistant", "content": "ok done"},
        ]
        await manager.close_all()

    asyncio.run(scenario())


def test_process_quota_and_idle_reaping(monkeypatch):
    monkeypatch.setenv("HERMES_MAX_PROCESSES", "1")
    monkeypatch.setenv("HERMES_IDLE_TIMEOUT_SECONDS", "1")
    from app.config import Settings

    monkeypatch.setattr(hermes_client, "get_settings", Settings)
    manager = hermes_client.HermesClientManager()

    async def start(*args):
        return hermes_client.HermesProcess(Process(), Connection(), hermes_client.HermesCallbacks(), "id")

    monkeypatch.setattr(manager, "_start", start)

    async def scenario():
        assert await manager.start_session("s1") == "id"
        with pytest.raises(hermes_client.HermesUnavailableError, match="busy"):
            await manager.start_session("s2")
        entry = manager._processes["s1"]
        entry.last_used = 0
        await manager.close_idle()
        assert entry.connection.closed
        assert await manager.start_session("s2") == "id"
        await manager.close_all()

    asyncio.run(scenario())
