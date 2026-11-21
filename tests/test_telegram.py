"""Automated verification of the Telegram integration.

Real code under test: telegram_service (update handling, pairing, photo ->
ImageContentBlock -> ACP, polling ownership). Mocked: the Telegram Bot API
network (`_post` and the file download) and the Hermes ACP layer
(`hermes_manager`). The DB is the real test database.
"""
import asyncio
import base64
import io
from types import SimpleNamespace

from PIL import Image

from app.db import SessionLocal
from app.models import TelegramIdentity, User
from app import telegram_service as tg_module
from app.hermes_client import hermes_manager, IMAGE_INLINE_INSTRUCTION
from app.security import hash_password


def _link_user_and_chat(client, email: str, chat_id: str) -> str:
    """Register a user via the API and link it to a Telegram chat."""
    client.post("/auth/register", json={"email": email, "password": "secure-password"})
    token = client.post(
        "/auth/login", json={"email": email, "password": "secure-password"}
    ).json()["access_token"]
    db = SessionLocal()
    identity = TelegramIdentity(chat_id=chat_id)
    user = db.query(User).filter(User.email == email).first()
    identity.user_id = user.id
    db.add(identity)
    db.commit()
    db.close()
    return token


class _FakeBotAPI:
    """Records Bot API calls and serves file downloads from a byte buffer."""

    def __init__(self, file_content: bytes | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.sent: list[str] = []
        self.file_content = file_content or b""
        self.file_path = "photos/test.png"

    async def post(self, token: str, method: str, payload: dict) -> dict:
        self.calls.append((method, payload))
        if method == "sendMessage":
            self.sent.append(payload["text"])
            return {"ok": True}
        if method == "getFile":
            return {"ok": True, "result": {"file_path": self.file_path}}
        return {"ok": True}

    def sent_messages(self) -> list[str]:
        return self.sent


def _install_fake_bot(monkeypatch, fake: _FakeBotAPI) -> None:
    async def fake_post(token, method, payload):
        # bound on the instance, so no `self` parameter
        return await fake.post(token, method, payload)

    monkeypatch.setattr(tg_module.telegram_service, "_post", fake_post)

    class _FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return _FakeResponse(fake.file_content)

        async def post(self, url, **kwargs):
            raise AssertionError("unexpected real network call: " + url)

    fake_async_client = _FakeClient

    def fake_ssl_context():
        return object()

    import types

    fake_httpx = types.SimpleNamespace(
        AsyncClient=fake_async_client,
    )
    monkeypatch.setattr(tg_module, "httpx", fake_httpx)
    monkeypatch.setattr(tg_module, "_telegram_ssl_context", fake_ssl_context)


def _install_fake_hermes(monkeypatch, captured: dict) -> None:
    async def fake_start_session(user_id: int, app_session_id: int) -> str:
        return "hermes-tg-session"

    async def fake_prompt(
        user_id: int,
        app_session_id: int,
        hermes_session_id: str,
        text: str,
        content_blocks: dict | None = None,
    ) -> str:
        captured["text"] = text
        captured["content_blocks"] = content_blocks
        return "ответ-агента"

    monkeypatch.setattr(hermes_manager, "start_session", fake_start_session)
    monkeypatch.setattr(hermes_manager, "prompt", fake_prompt)


def test_text_message_goes_to_hermes_without_image(client, monkeypatch):
    token = _link_user_and_chat(client, "tg-text@example.com", "1001")
    fake = _FakeBotAPI()
    captured: dict = {}
    _install_fake_bot(monkeypatch, fake)
    _install_fake_hermes(monkeypatch, captured)

    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1001}, "text": "Привет, агент"},
    }
    asyncio.run(tg_module.telegram_service._handle_update("bot-token", update))

    assert captured["content_blocks"] is None
    assert captured["text"] == "Привет, агент"
    assert fake.sent_messages() == ["ответ-агента"]


def test_photo_message_sends_image_content_block(client, monkeypatch):
    png_buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(png_buffer, format="PNG")
    png = png_buffer.getvalue()

    _link_user_and_chat(client, "tg-photo@example.com", "1002")
    fake = _FakeBotAPI(file_content=png)
    captured: dict = {}
    _install_fake_bot(monkeypatch, fake)
    _install_fake_hermes(monkeypatch, captured)

    update = {
        "update_id": 2,
        "message": {
            "chat": {"id": 1002},
            "caption": "Что на фото?",
            "photo": [{"file_id": "F1", "file_size": 10}],
        },
    }
    asyncio.run(tg_module.telegram_service._handle_update("bot-token", update))

    assert fake.calls[0][0] == "getFile"
    blocks = captured["content_blocks"]
    assert blocks is not None
    assert blocks["mime_type"] == "image/png"
    assert base64.b64decode(blocks["data"]) == png
    assert captured["text"].startswith(IMAGE_INLINE_INSTRUCTION)
    assert captured["text"].endswith("Что на фото?")
    assert fake.sent_messages() == ["ответ-агента"]


def test_start_creates_user_and_identity(client, monkeypatch):
    fake = _FakeBotAPI()
    captured: dict = {}
    _install_fake_bot(monkeypatch, fake)
    _install_fake_hermes(monkeypatch, captured)

    update = {
        "update_id": 3,
        "message": {"chat": {"id": 2001}, "text": "/start"},
    }
    asyncio.run(tg_module.telegram_service._handle_update("bot-token", update))

    db = SessionLocal()
    user = db.query(User).filter(User.email == "telegram-2001@mai-agent.local").first()
    identity = db.query(TelegramIdentity).filter(TelegramIdentity.chat_id == "2001").first()
    db.close()
    assert user is not None
    assert identity is not None and identity.user_id == user.id
    assert any("создан" in m.lower() or "готов" in m.lower() for m in fake.sent_messages())


def test_pairing_links_account(client, monkeypatch):
    client.post("/auth/register", json={"email": "tg-pair@example.com", "password": "secure-password"})
    pairing_token = client.post(
        "/auth/login", json={"email": "tg-pair@example.com", "password": "secure-password"}
    ).json()["access_token"]
    pairing_code = client.post(
        "/auth/telegram/pairing-code", headers={"Authorization": f"Bearer {pairing_token}"}
    ).json()["code"]

    fake = _FakeBotAPI()
    captured: dict = {}
    _install_fake_bot(monkeypatch, fake)
    _install_fake_hermes(monkeypatch, captured)

    update = {
        "update_id": 4,
        "message": {"chat": {"id": 3001}, "text": f"/pair {pairing_code}"},
    }
    asyncio.run(tg_module.telegram_service._handle_update("bot-token", update))

    db = SessionLocal()
    identity = db.query(TelegramIdentity).filter(TelegramIdentity.chat_id == "3001").first()
    db.close()
    assert identity is not None and identity.user_id is not None
    assert any("привязан" in m.lower() for m in fake.sent_messages())


def test_polling_loop_owned_by_backend_only(monkeypatch):
    """Without a token no polling task is created; with a token exactly one
    polling loop (the backend's) runs. Hermes is never involved."""
    service = tg_module.telegram_service

    async def scenario_no_token():
        monkeypatch.setattr(
            tg_module, "get_settings", lambda: SimpleNamespace(telegram_bot_token=None)
        )
        await service.start()
        assert service._task is None, "polling must stay disabled without a token"
        await service.stop()

    asyncio.run(scenario_no_token())

    calls = {"getupdates": 0}

    class _PollingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            assert "getUpdates" in url
            calls["getupdates"] += 1
            await asyncio.Event().wait()  # behaves like a long poll; never returns
            return SimpleNamespace(json=lambda: {"ok": True, "result": []})

    async def scenario_with_token():
        monkeypatch.setattr(tg_module, "httpx", SimpleNamespace(AsyncClient=_PollingClient))
        monkeypatch.setattr(
            tg_module,
            "get_settings",
            lambda: SimpleNamespace(
                telegram_bot_token="test-token", telegram_polling_timeout_seconds=1
            ),
        )
        await service.start()
        assert service._task is not None, "backend must own the polling loop"
        for _ in range(400):
            if calls["getupdates"] >= 1:
                break
            await asyncio.sleep(0.05)
        assert calls["getupdates"] >= 1, "the polling loop must call getUpdates"
        await service.stop()
        assert service._task is None, "stop() must cancel the polling loop"

    asyncio.run(scenario_with_token())
