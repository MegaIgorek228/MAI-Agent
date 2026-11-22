"""Administrative CLI for staff invitations.

This is the only place where invitation codes are created. It is a local
operator tool (run inside the backend container or on the host against the
application database); there is deliberately no public HTTP endpoint for
issuing codes. The plaintext code is printed once at creation time — only
its SHA-256 hash is stored, so the code cannot be recovered from the
database later.

Usage (from the backend directory):
    python -m app.admin_cli staff-invite create [--days 7] [--note "..."]
    python -m app.admin_cli staff-invite list
    python -m app.admin_cli staff-invite revoke INVITE_ID
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, engine
from app.invite_service import (
    InviteError,
    create_staff_invite,
    revoke_staff_invite,
    staff_invite_status,
)
from app.models import StaffInvite


def _connect() -> Session:
    # Ensure the engine is bound to the configured database.
    get_settings()
    return SessionLocal()


def cmd_create(args: argparse.Namespace) -> int:
    with _connect() as db:
        expires_at = datetime.now(UTC) + timedelta(days=args.days)
        invite, code = create_staff_invite(
            db,
            expires_at=expires_at,
            created_by=args.created_by,
            note=args.note,
        )
        db.commit()
        print(f"Invitation #{invite.id} created.")
        print(f"Code: {code}")
        print(f"Expires: {expires_at.isoformat()}")
        print("The code will not be shown again; only its hash is stored.")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    with _connect() as db:
        invites = list(db.scalars(select(StaffInvite).order_by(StaffInvite.id)))
        if not invites:
            print("No invitations found.")
            return 0
        for invite in invites:
            state = staff_invite_status(invite)
            used = f", used by user #{invite.used_by}" if invite.used_by is not None else ""
            note = f", note: {invite.note}" if invite.note else ""
            print(
                f"#{invite.id} [{state}] expires {invite.expires_at.isoformat()}"
                f"{used}{note}"
            )
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    with _connect() as db:
        try:
            invite = revoke_staff_invite(db, args.invite_id)
            db.commit()
        except InviteError:
            print("The invitation cannot be revoked (unknown, already used, or already revoked).")
            return 1
        print(f"Invitation #{invite.id} revoked.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mai-agent admin")
    sub = parser.add_subparsers(dest="command", required=True)

    invite_cmd = sub.add_parser("staff-invite", help="Manage staff registration invitations")
    invite_sub = invite_cmd.add_subparsers(dest="invite_command", required=True)

    create = invite_sub.add_parser("create", help="Create a new invitation (prints the code once)")
    create.add_argument("--days", type=int, default=7, help="Validity period in days (default: 7)")
    create.add_argument("--note", default=None, help="Optional operator note (e.g. the person's name)")
    create.add_argument("--created-by", dest="created_by", type=int, default=None,
                        help="User id of the administrator creating the invite (recorded, optional)")
    create.set_defaults(func=cmd_create)

    listing = invite_sub.add_parser("list", help="List invitations and their status")
    listing.set_defaults(func=cmd_list)

    revoke = invite_sub.add_parser("revoke", help="Revoke an unused invitation by id")
    revoke.add_argument("invite_id", type=int)
    revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # pragma: no cover — operator feedback path
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
