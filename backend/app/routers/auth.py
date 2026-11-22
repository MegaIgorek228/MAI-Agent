from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    LoginRequest,
    TelegramPairingCodeResponse,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from app.security import create_access_token
from app.services import authenticate_user, get_user_by_email, register_user
from app.dependencies import get_current_user
from app.invite_service import InviteError, mark_invite_used, redeem_staff_invite
from app.models import TelegramIdentity, User, UserRole
from datetime import UTC, datetime, timedelta
import secrets
from sqlalchemy import select

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    if get_user_by_email(db, payload.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    role = UserRole.applicant.value
    invite = None
    invite_code = (payload.invite_code or "").strip()
    if invite_code:
        # Invalid, expired, used and revoked codes are indistinguishable to
        # the caller — the generic message below does not reveal which one it is.
        try:
            invite = redeem_staff_invite(db, invite_code)
        except InviteError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Код приглашения недействителен",
            )
        role = UserRole.admissions_staff.value
    user = register_user(db, payload.email, payload.password, role=role)
    if invite is not None:
        mark_invite_used(db, invite, user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user))


@router.post("/telegram/pairing-code", response_model=TelegramPairingCodeResponse)
def create_telegram_pairing_code(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TelegramPairingCodeResponse:
    code = secrets.token_urlsafe(6).upper()[:8]
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    identity = db.scalar(
        select(TelegramIdentity).where(
            TelegramIdentity.user_id == current_user.id,
            TelegramIdentity.pairing_code.is_not(None),
        )
    )
    if identity is None:
        identity = TelegramIdentity(user_id=current_user.id)
        db.add(identity)
    identity.chat_id = None
    identity.pairing_code = code
    identity.pairing_expires_at = expires_at
    db.commit()
    db.refresh(identity)
    return TelegramPairingCodeResponse(code=code, expires_at=expires_at)
