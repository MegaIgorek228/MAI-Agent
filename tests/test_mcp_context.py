from app.db import SessionLocal
from app.mcp_service import get_authorized_user_for_mcp
from app.models import User
from app.security import create_trusted_context, hash_password


def test_mcp_context_is_verified_by_backend_service():
    db = SessionLocal()
    try:
        user = User(
            email="mcp@example.com",
            password_hash=hash_password("secure-password"),
            role="applicant",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_trusted_context(user, "hermes-session-1")
    finally:
        db.close()

    authorized_user, session_id = get_authorized_user_for_mcp(token)
    assert authorized_user.email == "mcp@example.com"
    assert session_id == "hermes-session-1"
