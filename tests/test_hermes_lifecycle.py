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


class UniqueConnection(Connection):
    """Connection whose new_session returns a unique id per instance."""

    _counter = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        UniqueConnection._counter += 1
        self.session_number = UniqueConnection._counter

    async def new_session(self, **kwargs):
        return SimpleNamespace(session_id=f"hermes-live-{self.session_number}")


def _reset_fakes(monkeypatch, processes, connections):
    async def spawn(*args, **kwargs):
        process = Process()
        processes.append(process)
        return process

    def connect(callbacks, *args, **kwargs):
        connection = UniqueConnection()
        connection.bind_callbacks(callbacks)
        connections.append(connection)
        return connection

    monkeypatch.setattr(hermes_client.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(hermes_client, "connect_to_agent", connect)
    return hermes_client.HermesClientManager()


def test_start_session_keeps_live_process(monkeypatch):
    """Documented semantics that /new must NOT rely on: while a process is
    alive, start_session returns the SAME Hermes session."""
    UniqueConnection._counter = 0
    processes, connections = [], []
    manager = _reset_fakes(monkeypatch, processes, connections)

    async def scenario():
        first = await manager.start_session("app")
        again = await manager.start_session("app")
        assert first == again == "hermes-live-1"
        assert len(connections) == 1
        await manager.close_all()

    asyncio.run(scenario())


def test_reset_session_replaces_live_session(monkeypatch):
    UniqueConnection._counter = 0
    processes, connections = [], []
    manager = _reset_fakes(monkeypatch, processes, connections)

    async def scenario():
        first = await manager.start_session("app")
        await manager.prompt("app", first, "old question")

        second = await manager.reset_session("app")
        assert second != first
        # The previous live process is terminated, not leaked.
        assert connections[0].closed
        assert processes[0].returncode == 0

        # The next prompt goes to the NEW Hermes session.
        answer, used = await manager.prompt("app", second, "new question")
        assert used == second
        assert connections[0].prompts == ["old question"]
        assert connections[1].prompts == ["new question"]
        await manager.close_all()

    asyncio.run(scenario())


def test_reset_session_twice_and_no_process_leak(monkeypatch):
    UniqueConnection._counter = 0
    processes, connections = [], []
    manager = _reset_fakes(monkeypatch, processes, connections)

    async def scenario():
        first = await manager.start_session("app")
        second = await manager.reset_session("app")
        third = await manager.reset_session("app")
        assert len({first, second, third}) == 3
        # Exactly one live process for the app session.
        live = [p for p in processes if p.returncode is None]
        assert len(live) == 1
        assert connections[0].closed and connections[1].closed
        assert not connections[2].closed
        # The latest session serves prompts.
        _, used = await manager.prompt("app", third, "after two resets")
        assert used == third
        assert connections[2].prompts == ["after two resets"]
        await manager.close_all()

    asyncio.run(scenario())


def test_reset_session_without_live_process_starts_fresh(monkeypatch):
    UniqueConnection._counter = 0
    processes, connections = [], []
    manager = _reset_fakes(monkeypatch, processes, connections)

    async def scenario():
        # No prior process: reset simply creates the first session.
        first = await manager.reset_session("app")
        assert first == "hermes-live-1"
        assert len(connections) == 1
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
