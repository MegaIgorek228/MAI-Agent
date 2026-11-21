from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TrustedContext(BaseModel):
    user_id: int
    role: UserRole
    session_id: str
    expires_at: datetime


class ProfileUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    target_program: str | None = None
    admission_basis: str | None = None


class ProfileResponse(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    updated_at: datetime


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    size_bytes: int
    document_type: str | None
    status: str
    extracted_text: str | None
    review_message: str | None
    analysis_json: str | None
    analysis_error: str | None
    created_at: datetime


class TelegramPairingCodeResponse(BaseModel):
    code: str
    expires_at: datetime
