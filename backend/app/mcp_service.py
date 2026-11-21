from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException
from fastmcp.server.dependencies import get_http_headers
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.dependencies import require_roles
from app.models import User, UserRole
from app.security import decode_trusted_context


def _verified_context(db: Session, context_token: str) -> tuple[User, str]:
    context = decode_trusted_context(context_token)
    user = db.get(User, context.user_id)
    if user is None or not user.is_active or user.role != context.role.value:
        raise ValueError("User is not authorized")
    return user, context.session_id


def get_authorized_user_for_mcp(context_token: str) -> tuple[User, str]:
    with SessionLocal() as db:
        return _verified_context(db, context_token)


@contextmanager
def mcp_operation(*roles: UserRole) -> Iterator[tuple[Session, User]]:
    """Run an application operation as the actor identified by the ACP session."""
    context_token = get_http_headers().get("x-mai-context")
    if not context_token:
        raise ValueError("Missing trusted user context")
    with SessionLocal() as db:
        try:
            user, _ = _verified_context(db, context_token)
        except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid trusted user context") from exc
        try:
            if roles:
                require_roles(*roles)(user)
            yield db, user
        except HTTPException as exc:
            raise ValueError(f"Backend returned HTTP {exc.status_code}: {exc.detail}") from exc
