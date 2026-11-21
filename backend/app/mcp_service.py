from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import User
from app.security import decode_trusted_context


def get_authorized_user_for_mcp(context_token: str) -> tuple[User, str]:
    context = decode_trusted_context(context_token)
    db: Session = SessionLocal()
    try:
        user = db.get(User, context.user_id)
        if user is None or not user.is_active or user.role != context.role.value:
            raise ValueError("User is not authorized")
        return user, context.session_id
    finally:
        db.close()
