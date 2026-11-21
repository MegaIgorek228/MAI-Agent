import asyncio
from types import SimpleNamespace

import pytest

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
    def __init__(self):
        self.closed = False
        self.prompts = 0

    async def initialize(self, **kwargs):
        return None

    async def load_session(self, **kwargs):
        return None

    async def new_session(self, **kwargs):
        return SimpleNamespace(session_id="new-session")

    async def prompt(self, **kwargs):
        self.prompts += 1
        return SimpleNamespace(stop_reason="end_turn")

    async def close(self):
        self.closed = True


def test_missing_stored_session_reopens_and_empty_turn_is_not_replayed(monkeypatch):
    processes, connections = [], []

    async def spawn(*args, **kwargs):
        process = Process()
        processes.append(process)
        return process

    def connect(*args, **kwargs):
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(hermes_client.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(hermes_client, "connect_to_agent", connect)
    monkeypatch.setattr(hermes_client, "create_trusted_context_for_session", lambda *_: "trusted")
    monkeypatch.setattr(hermes_client, "_with_conversation_history", lambda _, __, text: text)
    manager = hermes_client.HermesClientManager()

    async def scenario():
        assert await manager.prompt(1, 1, "purged-session", "sample") == ("", "new-session")
        assert [connection.prompts for connection in connections] == [0, 1]
        assert connections[0].closed and processes[0].returncode == 0
        assert manager._locks == {}
        await manager.close_all()

    asyncio.run(scenario())
    assert all(connection.closed for connection in connections)
    assert all(process.returncode == 0 for process in processes)


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
        assert await manager.start_session(1, 1) == "id"
        with pytest.raises(hermes_client.HermesUnavailableError, match="busy"):
            await manager.start_session(2, 2)
        entry = manager._processes[1]
        entry.last_used = 0
        await manager.close_idle()
        assert entry.connection.closed
        assert await manager.start_session(2, 2) == "id"
        await manager.close_all()

    asyncio.run(scenario())
