from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserRole
from app.security import hash_password, verify_password


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def register_user(
    db: Session, email: str, password: str, role: str = UserRole.applicant.value
) -> User:
    """Create an account. ``role`` is internal: it is set by the register
    endpoint only after a staff invitation has been validated, so a request
    can never assign a role to itself."""
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
