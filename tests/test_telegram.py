"""Telegram channel tests: chat id -> session mapping, text and photo relay.

Mocked: the Telegram Bot API network and the Hermes ACP layer
(``hermes_manager``). The DB is the real test database.
"""
import base64

import pytest
from app.hermes_client import hermes_manager, IMAGE_INLINE_INSTRUCTION
from app import telegram_service as tg_module
from app.models import AgentSession
from app.db import SessionLocal


class FakeBotAPI:
    """Records Bot API calls and serves file downloads from a byte buffer."""

    def __init__(self, file_content: bytes = b"", file_path: str = "photos/test.png") -> None:
        self.calls: list[tuple[str, dict]] = []
        self.sent: list[str] = []
        self.file_content = file_content
        self.file_path = file_path

    async def post(self, token: str, method: str, payload: dict) -> dict:
        self.calls.append((method, payload))
        if method == "sendMessage":
            self.sent.append(payload["text"])
        return {"ok": True, "result": {"file_path": self.file_path}}


def _install_fake_bot(monkeypatch, fake: FakeBotAPI):
    async def fake_post(token, method, payload):
        return await fake.post(token, method, payload)

    monkeypatch.setattr(tg_module.telegram_service, "_post", fake_post)

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return FakeResponse(fake.file_content)

    monkeypatch.setattr(tg_module.httpx, "AsyncClient", FakeClient)


def _mock_hermes(monkeypatch, hermes_session_id="hermes-tg-1"):
    state = {"started": [], "prompts": []}

    async def fake_start(session_id):
        state["started"].append(session_id)
        return f"{hermes_session_id}-{len(state['started'])}"

    async def fake_prompt(session_id, hermes_session_id, text, content_blocks=None):
        state["prompts"].append((session_id, hermes_session_id, text, content_blocks))
        return "отвечу", hermes_session_id

    monkeypatch.setattr(hermes_manager, "start_session", fake_start)
    monkeypatch.setattr(hermes_manager, "prompt", fake_prompt)
    return state


def _update(update_id: int, chat_id: int, text: str | None = None, photos: bool = False):
    message: dict = {"chat": {"id": chat_id}, "message_id": update_id}
    if text is not None:
        message["text"] = text
    if photos:
        message["photo"] = [{"file_id": "fid-1", "file_size": 10}]
    return {"update_id": update_id, "message": message}


def _telegram_sessions(chat_id: int | None = None) -> list[AgentSession]:
    from sqlalchemy import select

    with SessionLocal() as db:
        query = select(AgentSession).where(AgentSession.source == "telegram")
        if chat_id is not None:
            query = query.where(AgentSession.external_id == str(chat_id))
        return list(db.scalars(query))


def test_start_creates_session_and_greets(client, monkeypatch):
    state = _mock_hermes(monkeypatch)
    fake = FakeBotAPI()
    _install_fake_bot(monkeypatch, fake)

    import asyncio

    asyncio.run(tg_module.telegram_service._handle_update("token", _update(1, 777, "/start")))

    sessions = _telegram_sessions(777)
    assert len(sessions) == 1
    assert sessions[0].hermes_session_id == "hermes-tg-1-1"
    assert fake.sent == ["Чат создан. Напишите вопрос — ответит агент МАИ."]
    # Second /start does not create a second session.
    asyncio.run(tg_module.telegram_service._handle_update("token", _update(2, 777, "/start")))
    assert len(_telegram_sessions(777)) == 1
    assert fake.sent[-1] == "MAI-Agent готов к работе. Напишите вопрос."


def test_text_message_auto_creates_session_and_replies(client, monkeypatch):
    state = _mock_hermes(monkeypatch)
    fake = FakeBotAPI()
    _install_fake_bot(monkeypatch, fake)
    import asyncio

    asyncio.run(
        tg_module.telegram_service._handle_update("token", _update(1, 42, "Привет, МАИ"))
    )

    sessions = _telegram_sessions(42)
    assert len(sessions) == 1
    session = sessions[0]
    assert state["started"] == [str(session.id)]
    (app_session_id, hermes_session_id, text, content_blocks) = state["prompts"][0]
    assert app_session_id == str(session.id)
    assert hermes_session_id == session.hermes_session_id
    assert text == "Привет, МАИ"
    assert content_blocks is None
    assert fake.sent == ["отвечу"]


def test_photo_goes_to_hermes_with_image_blocks(client, monkeypatch):
    state = _mock_hermes(monkeypatch)
    fake = FakeBotAPI(file_content=b"\x89PNG\r\n\x1a\nfake-png")
    _install_fake_bot(monkeypatch, fake)
    import asyncio

    asyncio.run(
        tg_module.telegram_service._handle_update(
            "token", _update(1, 42, None, photos=True)
        )
    )

    sessions = _telegram_sessions(42)
    assert len(sessions) == 1
    (app_session_id, hermes_session_id, text, content_blocks) = state["prompts"][0]
    assert text.startswith(IMAGE_INLINE_INSTRUCTION)
    assert content_blocks is not None
    assert content_blocks["mime_type"] == "image/png"
    assert base64.b64decode(content_blocks["data"]) == b"\x89PNG\r\n\x1a\nfake-png"


def test_two_chats_get_separate_sessions(client, monkeypatch):
    state = _mock_hermes(monkeypatch)
    fake = FakeBotAPI()
    _install_fake_bot(monkeypatch, fake)
    import asyncio

    asyncio.run(tg_module.telegram_service._handle_update("token", _update(1, 100, "a")))
    asyncio.run(tg_module.telegram_service._handle_update("token", _update(2, 200, "b")))

    first = _telegram_sessions(100)
    second = _telegram_sessions(200)
    assert len(first) == 1 and len(second) == 1
    assert first[0].id != second[0].id
    # Prompts were routed to their own session ids.
    session_ids = {prompt[0] for prompt in state["prompts"]}
    assert session_ids == {str(first[0].id), str(second[0].id)}


def test_new_command_rebinds_hermes_session(client, monkeypatch):
    state = _mock_hermes(monkeypatch)
    fake = FakeBotAPI()
    _install_fake_bot(monkeypatch, fake)
    import asyncio

    asyncio.run(tg_module.telegram_service._handle_update("token", _update(1, 300, "hello")))
    old_hermes_id = _telegram_sessions(300)[0].hermes_session_id
    asyncio.run(tg_module.telegram_service._handle_update("token", _update(2, 300, "/new")))
    new_hermes_id = _telegram_sessions(300)[0].hermes_session_id
    assert new_hermes_id != old_hermes_id
    assert len(_telegram_sessions(300)) == 1
    assert "Новый чат начат" in fake.sent[-1]
