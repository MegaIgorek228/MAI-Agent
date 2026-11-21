import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import TelegramIdentity, User
from app.telegram_service import TelegramService


def test_register_login_and_current_user(client):
    registration = client.post(
        "/auth/register",
        json={"email": "applicant@example.com", "password": "secure-password"},
    )
    assert registration.status_code == 201
    assert registration.json()["role"] == "applicant"

    login = client.post(
        "/auth/login",
        json={"email": "applicant@example.com", "password": "secure-password"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    current_user = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert current_user.status_code == 200
    assert current_user.json()["email"] == "applicant@example.com"


def test_duplicate_registration_and_invalid_login(client):
    payload = {"email": "duplicate@example.com", "password": "secure-password"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409
    assert client.post(
        "/auth/login",
        json={"email": payload["email"], "password": "wrong-password"},
    ).status_code == 401


def test_telegram_pairing_code_requires_authentication_and_returns_code(client):
    assert client.post("/auth/telegram/pairing-code").status_code == 401

    registration = client.post(
        "/auth/register",
        json={"email": "telegram@example.com", "password": "secure-password"},
    )
    assert registration.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": "telegram@example.com", "password": "secure-password"},
    )
    token = login.json()["access_token"]

    response = client.post(
        "/auth/telegram/pairing-code",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()["code"]) >= 6


def test_telegram_start_creates_direct_account(client):
    service = TelegramService()
    sent: list[str] = []

    async def capture_send(token: str, chat_id: str, text: str) -> None:
        sent.append(text)

    service._send = capture_send
    asyncio.run(service._start_user("test-token", "987654321"))

    db = SessionLocal()
    try:
        identity = db.scalar(
            select(TelegramIdentity).where(TelegramIdentity.chat_id == "987654321")
        )
        assert identity is not None
        user = db.get(User, identity.user_id)
        assert user is not None
        assert user.role == "applicant"
    finally:
        db.close()

    assert sent
    assert "создан автоматически" in sent[-1]
