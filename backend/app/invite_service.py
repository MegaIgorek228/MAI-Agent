"""One-time, expiring staff registration invitations.

Only SHA-256 hashes of the codes are stored in the database. The plaintext
code is returned exactly once at creation (administrative CLI) and is never
persisted or logged. Validation failures are indistinguishable on purpose:
an unknown, expired, used or revoked code produces the same generic error,
so a request cannot be used to probe whether a given code exists.
"""

from datetime import UTC, datetime
from hashlib import sha256
from secrets import choice
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StaffInvite, User

# Ambiguous-free alphabet (no I, L, O, 0, 1).
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
INVITE_GROUPS = 4
INVITE_GROUP_SIZE = 4


def generate_invite_code() -> str:
    groups = [choice(INVITE_ALPHABET) for _ in range(INVITE_GROUPS * INVITE_GROUP_SIZE)]
    body = "-".join(
        "".join(groups[offset : offset + INVITE_GROUP_SIZE])
        for offset in range(0, len(groups), INVITE_GROUP_SIZE)
    )
    return f"MAI-{body}"


def normalize_invite_code(code: str) -> str:
    return code.strip().upper()


def hash_invite_code(code: str) -> str:
    return sha256(normalize_invite_code(code).encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; compare everything in UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def create_staff_invite(
    db: Session,
    *,
    expires_at: datetime,
    created_by: int | None = None,
    note: str | None = None,
) -> tuple[StaffInvite, str]:
    """Create an invitation and return ``(invite, plaintext_code)``.

    The plaintext code must be shown to the operator once and never stored.
    """
    code = generate_invite_code()
    invite = StaffInvite(
        code_hash=hash_invite_code(code),
        created_by=created_by,
        expires_at=_aware(expires_at),
        note=(note or "").strip() or None,
    )
    db.add(invite)
    db.flush()
    return invite, code


class InviteError(ValueError):
    """Raised for any invitation validation failure (details are intentionally generic)."""


def redeem_staff_invite(db: Session, code: str) -> StaffInvite:
    """Validate a code and mark it used.

    All failure modes (unknown, expired, used, revoked) raise the same
    ``InviteError`` — the caller must not be able to tell them apart.
    """
    if not normalize_invite_code(code):
        raise InviteError("invalid")
    query = select(StaffInvite).where(StaffInvite.code_hash == hash_invite_code(code))
    invite = db.scalar(query.with_for_update())
    now = datetime.now(UTC)
    if (
        invite is None
        or invite.used_at is not None
        or invite.revoked_at is not None
        or _aware(invite.expires_at) <= now
    ):
        raise InviteError("invalid")
    invite.used_at = now
    return invite


def revoke_staff_invite(db: Session, invite_id: int) -> StaffInvite:
    """Revoke an unused invitation. A used or unknown invite cannot be revoked."""
    invite = db.get(StaffInvite, invite_id)
    if invite is None or invite.used_at is not None:
        raise InviteError("not available")
    invite.revoked_at = datetime.now(UTC)
    db.flush()
    return invite


def staff_invite_status(invite: StaffInvite) -> Literal["active", "used", "revoked", "expired"]:
    now = datetime.now(UTC)
    if invite.revoked_at is not None:
        return "revoked"
    if invite.used_at is not None:
        return "used"
    if _aware(invite.expires_at) <= now:
        return "expired"
    return "active"


def mark_invite_used(db: Session, invite: StaffInvite, user: User) -> None:
    invite.used_by = user.id
