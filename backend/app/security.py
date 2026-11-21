from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.config import get_settings
from app.models import User
from app.schemas import TrustedContext

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user: User) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user.id), "role": user.role, "type": "access", "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def create_trusted_context(user: User, session_id: str, ttl_seconds: int = 60) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "session_id": session_id,
        "type": "mcp_context",
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_trusted_context(token: str) -> TrustedContext:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "mcp_context":
        raise ValueError("Invalid trusted context type")
    expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    return TrustedContext(
        user_id=int(payload["sub"]),
        role=payload["role"],
        session_id=payload["session_id"],
        expires_at=expires_at,
    )
