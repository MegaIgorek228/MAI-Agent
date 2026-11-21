from app.routers import chat as chat_router
from io import BytesIO
from PIL import Image


def test_chat_session_and_message_lifecycle(client, monkeypatch):
    client.post(
        "/auth/register",
        json={"email": "chat@example.com", "password": "secure-password"},
    )
    token = client.post(
        "/auth/login",
        json={"email": "chat@example.com", "password": "secure-password"},
    ).json()["access_token"]

    async def start_session(user_id: int, app_session_id: int) -> str:
        return "hermes-session-1"

    async def prompt(
        user_id: int,
        app_session_id: int,
        hermes_session_id: str,
        text: str,
        content_blocks: dict[str, str] | None = None,
    ) -> str:
        if content_blocks is not None:
            assert content_blocks["mime_type"] == "image/png"
            assert content_blocks["data"]
            return "Агент получил изображение"
        return f"Ответ: {text}"

    monkeypatch.setattr(chat_router.hermes_manager, "start_session", start_session)
    monkeypatch.setattr(chat_router.hermes_manager, "prompt", prompt)

    session = client.post(
        "/chat/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": "web"},
    )
    assert session.status_code == 201
    session_id = session.json()["id"]

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "Какие документы нужны?"},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "Ответ: Какие документы нужны?"

    png_buffer = BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(png_buffer, format="PNG")
    png = png_buffer.getvalue()
    uploaded = client.post(
        "/applicant/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.png", png, "image/png")},
        data={"document_type": "image"},
    )
    assert uploaded.status_code == 201

    image_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": "Что на изображении?",
            "image_document_id": uploaded.json()["id"],
        },
    )
    assert image_response.status_code == 200
    assert image_response.json()["content"] == "Агент получил изображение"

    messages = client.get(
        f"/chat/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert [item["role"] for item in messages.json()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_image_prompt_uses_inline_instruction(client, monkeypatch):
    """When an image is attached, the ACP prompt text must carry the explicit
    inline-image instruction, while the stored user message stays clean."""
    from app.hermes_client import IMAGE_INLINE_INSTRUCTION

    client.post(
        "/auth/register",
        json={"email": "img@example.com", "password": "secure-password"},
    )
    token = client.post(
        "/auth/login",
        json={"email": "img@example.com", "password": "secure-password"},
    ).json()["access_token"]

    captured: dict = {}

    async def start_session(user_id: int, app_session_id: int) -> str:
        return "hermes-session-img"

    async def prompt(
        user_id: int,
        app_session_id: int,
        hermes_session_id: str,
        text: str,
        content_blocks: dict[str, str] | None = None,
    ) -> str:
        captured["text"] = text
        captured["content_blocks"] = content_blocks
        return "ок"

    monkeypatch.setattr(chat_router.hermes_manager, "start_session", start_session)
    monkeypatch.setattr(chat_router.hermes_manager, "prompt", prompt)

    session = client.post(
        "/chat/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": "web"},
    )
    session_id = session.json()["id"]

    png_buffer = BytesIO()
    Image.new("RGB", (2, 2), (0, 0, 255)).save(png_buffer, format="PNG")
    uploaded = client.post(
        "/applicant/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.png", png_buffer.getvalue(), "image/png")},
        data={"document_type": "image"},
    )
    assert uploaded.status_code == 201

    # With an image: prompt text gets the instruction, stored message does not.
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "Что на изображении?", "image_document_id": uploaded.json()["id"]},
    )
    assert response.status_code == 200
    assert captured["text"].startswith(IMAGE_INLINE_INSTRUCTION)
    assert captured["text"].endswith("Что на изображении?")
    assert captured["content_blocks"] is not None
    assert captured["content_blocks"]["mime_type"] == "image/png"

    # Without an image: plain text, no instruction.
    client.post(
        f"/chat/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "Привет"},
    )
    assert captured["text"] == "Привет"
    assert captured["content_blocks"] is None

    stored = client.get(
        f"/chat/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    user_texts = [item["content"] for item in stored if item["role"] == "user"]
    assert user_texts == ["Что на изображении?", "Привет"]


def test_with_image_instruction_helper():
    from app.hermes_client import with_image_instruction

    assert with_image_instruction("вопрос").endswith("вопрос")
    assert "inline" in with_image_instruction("вопрос")


def test_image_history_and_file_endpoint(client, monkeypatch):
    """A user message keeps its image document link; the history returns it;
    the file endpoint enforces auth, ownership, image type and role."""
    from app.db import SessionLocal
    from app.models import User
    from app.security import create_access_token, hash_password

    client.post("/auth/register", json={"email": "hist-a@example.com", "password": "secure-password"})
    token_a = client.post("/auth/login", json={"email": "hist-a@example.com", "password": "secure-password"}).json()["access_token"]
    h_a = {"Authorization": f"Bearer {token_a}"}

    async def start_session(user_id: int, app_session_id: int) -> str:
        return "hermes-session-hist"

    async def prompt(
        user_id: int,
        app_session_id: int,
        hermes_session_id: str,
        text: str,
        content_blocks: dict[str, str] | None = None,
    ) -> str:
        return "ок"

    monkeypatch.setattr(chat_router.hermes_manager, "start_session", start_session)
    monkeypatch.setattr(chat_router.hermes_manager, "prompt", prompt)

    session = client.post("/chat/sessions", headers=h_a, json={"channel": "web"})
    session_id = session.json()["id"]

    png_buffer = BytesIO()
    Image.new("RGB", (3, 3), (10, 20, 30)).save(png_buffer, format="PNG")
    png = png_buffer.getvalue()
    uploaded = client.post(
        "/applicant/documents",
        headers=h_a,
        files={"file": ("hist.png", png, "image/png")},
        data={"document_type": "image"},
    )
    doc_id = uploaded.json()["id"]

    sent = client.post(
        f"/chat/sessions/{session_id}/messages",
        headers=h_a,
        json={"content": "Что это?", "image_document_id": doc_id},
    )
    assert sent.status_code == 200

    # History: the user message carries the image link, the assistant one does not.
    messages = client.get(f"/chat/sessions/{session_id}/messages", headers=h_a).json()
    user_msg = next(m for m in messages if m["role"] == "user")
    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert user_msg["image_document_id"] == doc_id
    assert user_msg["image_filename"] == "hist.png"
    assert "image_document_id" not in assistant_msg

    # File endpoint: owner via Bearer header.
    r = client.get(f"/applicant/documents/{doc_id}/file", headers=h_a)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == png

    # File endpoint: owner via access_token query parameter (plain <img> use case).
    r2 = client.get(f"/applicant/documents/{doc_id}/file?access_token={token_a}")
    assert r2.status_code == 200
    assert r2.content == png

    # File endpoint: no token at all.
    assert client.get(f"/applicant/documents/{doc_id}/file").status_code == 401

    # File endpoint: another user's document -> 404 (no cross-user leaks).
    client.post("/auth/register", json={"email": "hist-b@example.com", "password": "secure-password"})
    token_b = client.post("/auth/login", json={"email": "hist-b@example.com", "password": "secure-password"}).json()["access_token"]
    assert client.get(f"/applicant/documents/{doc_id}/file", headers={"Authorization": f"Bearer {token_b}"}).status_code == 404

    # File endpoint: non-image document -> 422.
    text_doc = client.post(
        "/applicant/documents",
        headers=h_a,
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"document_type": "unspecified"},
    )
    assert client.get(f"/applicant/documents/{text_doc.json()['id']}/file", headers=h_a).status_code == 422

    # File endpoint: student role is outside the allowed set -> 403.
    db = SessionLocal()
    student = User(email="hist-student@example.com", password_hash=hash_password("secure-password"), role="student")
    db.add(student)
    db.commit()
    db.refresh(student)
    db.close()
    student_token = create_access_token(student)
    assert client.get(f"/applicant/documents/{doc_id}/file", headers={"Authorization": f"Bearer {student_token}"}).status_code == 403
