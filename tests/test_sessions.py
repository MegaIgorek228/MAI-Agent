"""Sessionless chat API: sessions are the only unit of user context.

The Hermes ACP layer (``hermes_manager``) is mocked; the database is real.
"""
import base64
from types import SimpleNamespace
from uuid import UUID

import pytest
from app import hermes_client
from app.hermes_client import hermes_manager, with_image_instruction


def _mock_hermes(monkeypatch, hermes_session_id="hermes-abc-123"):
    """Install a scripted hermes_manager: start_session / prompt / history."""
    state = {"hermes_session_id": hermes_session_id, "closed": []}

    async def fake_start(session_id):
        return state["hermes_session_id"]

    async def fake_prompt(session_id, hermes_session_id, text, content_blocks=None):
        if content_blocks is not None:
            return f"answered-image:{content_blocks['mime_type']}", state["hermes_session_id"]
        return f"answered:{text}", state["hermes_session_id"]

    async def fake_history(session_id, hermes_session_id):
        if hermes_session_id is None:
            return []
        return [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answered:first"},
        ]

    async def fake_close(session_id):
        state["closed"].append(session_id)

    monkeypatch.setattr(hermes_manager, "start_session", fake_start)
    monkeypatch.setattr(hermes_manager, "prompt", fake_prompt)
    monkeypatch.setattr(hermes_manager, "history", fake_history)
    monkeypatch.setattr(hermes_manager, "close_session", fake_close)
    return state


def test_create_session_returns_uuid_and_hermes_id(client, monkeypatch):
    _mock_hermes(monkeypatch)
    response = client.post("/chat/sessions", json={})
    assert response.status_code == 201
    body = response.json()
    UUID(body["id"])  # raises if not a UUID
    assert body["source"] == "web"
    assert body["hermes_session_id"] == "hermes-abc-123"


def test_get_session_and_404(client, monkeypatch):
    state = _mock_hermes(monkeypatch)
    session_id = client.post("/chat/sessions", json={}).json()["id"]
    got = client.get(f"/chat/sessions/{session_id}")
    assert got.status_code == 200
    assert got.json()["id"] == session_id
    assert client.get("/chat/sessions/00000000-0000-0000-0000-000000000000").status_code == 404


def test_send_message_replies_and_history_is_served(client, monkeypatch):
    _mock_hermes(monkeypatch)
    session_id = client.post("/chat/sessions", json={}).json()["id"]

    sent = client.post(
        f"/chat/sessions/{session_id}/messages", json={"content": "привет"}
    )
    assert sent.status_code == 200
    assert sent.json() == {"role": "assistant", "content": "answered:привет"}

    history = client.get(f"/chat/sessions/{session_id}/messages")
    assert history.status_code == 200
    assert history.json() == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answered:first"},
    ]


def test_send_message_with_image_passes_content_blocks(client, monkeypatch):
    _mock_hermes(monkeypatch)
    session_id = client.post("/chat/sessions", json={}).json()["id"]
    png_1x1 = base64.b64encode(b"\x89PNG fake image bytes").decode()
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"content": "что это?", "image": {"data": png_1x1, "mime_type": "image/png"}},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "answered-image:image/png"


def test_send_message_rejects_bad_image(client, monkeypatch):
    _mock_hermes(monkeypatch)
    session_id = client.post("/chat/sessions", json={}).json()["id"]
    assert client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"content": "x", "image": {"data": "AAAA", "mime_type": "text/plain"}},
    ).status_code == 422
    assert client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"content": "x", "image": {"data": "!!!not-base64!!!", "mime_type": "image/png"}},
    ).status_code == 422


def test_delete_session(client, monkeypatch):
    state = _mock_hermes(monkeypatch)
    session_id = client.post("/chat/sessions", json={}).json()["id"]
    assert client.delete(f"/chat/sessions/{session_id}").status_code == 204
    assert client.get(f"/chat/sessions/{session_id}").status_code == 404
    assert state["closed"] == [session_id]


def test_telegram_chat_maps_to_single_session(client, monkeypatch):
    _mock_hermes(monkeypatch)
    first = client.post(
        "/chat/sessions", json={"source": "telegram", "external_id": "42"}
    ).json()
    second = client.post(
        "/chat/sessions", json={"source": "telegram", "external_id": "42"}
    ).json()
    assert first["id"] == second["id"]
    assert first["source"] == "telegram"


def test_two_sessions_are_isolated(client, monkeypatch):
    seen = {"prompts": []}

    async def fake_start(session_id):
        return f"hermes-{session_id[:8]}"

    async def fake_prompt(session_id, hermes_session_id, text, content_blocks=None):
        seen["prompts"].append((session_id, text))
        return f"answer-{session_id[:8]}", hermes_session_id

    monkeypatch.setattr(hermes_manager, "start_session", fake_start)
    monkeypatch.setattr(hermes_manager, "prompt", fake_prompt)
    first = client.post("/chat/sessions", json={}).json()
    second = client.post("/chat/sessions", json={}).json()
    assert first["id"] != second["id"]
    client.post(f"/chat/sessions/{first['id']}/messages", json={"content": "a"})
    client.post(f"/chat/sessions/{second['id']}/messages", json={"content": "b"})
    assert [item[1] for item in seen["prompts"]] == ["a", "b"]
    # Each prompt went to its own session id — contexts cannot mix.
    assert len({item[0] for item in seen["prompts"]}) == 2


def test_image_instruction_is_prepended_for_prompts():
    text = with_image_instruction("опиши")
    assert text.startswith("К сообщению прикреплено изображение")
    assert text.endswith("опиши")
