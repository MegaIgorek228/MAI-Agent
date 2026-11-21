from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencies import bearer_scheme, get_current_user, require_roles
from app.document_service import SUPPORTED_IMAGE_TYPES, content_hash, extract_text, validate_image
from app.llm_service import LLMProviderUnavailable, analyze_document
from app.models import AdmissionRequirement, ApplicantProfile, Document, User, UserRole
from app.schemas import DocumentResponse, ProfileResponse, ProfileUpdate
from app.security import decode_access_token

router = APIRouter(prefix="/applicant", tags=["applicant"])


def get_current_user_with_token_param(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    access_token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Auth for the document file endpoint: Bearer header (standard) or an
    ``access_token`` query parameter so that plain ``<img>`` tags can load
    attached images from the chat history without custom headers."""
    token = credentials.credentials if credentials is not None else access_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token"
        ) from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


@router.get("/profile", response_model=ProfileResponse)
def get_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApplicantProfile:
    profile = db.scalar(select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id))
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.put("/profile", response_model=ProfileResponse)
def update_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicantProfile:
    profile = db.scalar(select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id))
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        db.add(profile)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    document_type: str | None = None,
    current_user: User = Depends(
        require_roles(UserRole.applicant, UserRole.admissions_staff, UserRole.administrator)
    ),
    db: Session = Depends(get_db),
) -> Document:
    max_size = get_settings().max_upload_size_bytes
    content = file.file.read(max_size + 1)
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail="File is too large")
    if (file.content_type or "").startswith("image/"):
        try:
            validate_image(
                file.content_type or "",
                content,
                get_settings().max_image_size_bytes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    extracted = extract_text(file.filename or "document", file.content_type or "", content)
    document = Document(
        owner_id=current_user.id,
        filename=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        sha256=content_hash(content),
        content=content,
        document_type=document_type,
        status="extracted" if extracted is not None else "needs_manual_review",
        extracted_text=extracted,
        review_message=None if extracted is not None else "Формат файла не поддерживается для извлечения текста.",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    current_user: User = Depends(
        require_roles(UserRole.applicant, UserRole.admissions_staff, UserRole.administrator)
    ),
    db: Session = Depends(get_db),
) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.owner_id == current_user.id)
            .order_by(Document.created_at.desc())
        )
    )


@router.get("/documents/{document_id}/file")
def download_document_file(
    document_id: int,
    current_user: User = Depends(get_current_user_with_token_param),
    db: Session = Depends(get_db),
) -> Response:
    """Return the raw bytes of an image document owned by the current user.

    Supports the ``access_token`` query parameter so chat-history ``<img>``
    tags can load the image without custom headers. Only image documents are
    served; ownership is enforced per user.
    """
    if current_user.role not in {
        UserRole.applicant.value,
        UserRole.admissions_staff.value,
        UserRole.administrator.value,
    }:
        raise HTTPException(status_code=403, detail="Insufficient role")
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.content_type not in SUPPORTED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="Document is not a supported image")
    return Response(
        content=document.content,
        media_type=document.content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/documents/completeness")
def document_completeness(
    current_user: User = Depends(
        require_roles(UserRole.applicant, UserRole.admissions_staff, UserRole.administrator)
    ),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    documents = list(db.scalars(select(Document).where(Document.owner_id == current_user.id)))
    profile = db.scalar(select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id))
    requirements = list(
        db.scalars(select(AdmissionRequirement).where(AdmissionRequirement.required.is_(True)))
    )
    if not requirements:
        return {
            "status": "needs_admission_requirements",
            "documents_received": len(documents),
            "missing_documents": [],
            "message": "Требования к комплекту документов ещё не загружены для данной ситуации поступления.",
        }
    applicable = [
        requirement
        for requirement in requirements
        if (requirement.target_program is None or requirement.target_program == profile.target_program)
        and (requirement.admission_basis is None or requirement.admission_basis == profile.admission_basis)
    ]
    document_types = {document.document_type for document in documents if document.document_type}
    missing = [
        {"document_type": item.document_type, "title": item.title}
        for item in applicable
        if item.document_type not in document_types
    ]
    return {
        "status": "incomplete" if missing else "complete",
        "documents_received": len(documents),
        "missing_documents": missing,
        "message": "Комплект документов проверен по загруженным требованиям.",
    }


@router.post("/documents/{document_id}/analyze")
def analyze_uploaded_document(
    document_id: int,
    current_user: User = Depends(
        require_roles(UserRole.applicant, UserRole.admissions_staff, UserRole.administrator)
    ),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == current_user.id)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.extracted_text:
        raise HTTPException(status_code=422, detail="Document has no extracted text")
    try:
        result = analyze_document(document.extracted_text)
    except (LLMProviderUnavailable, ValueError) as exc:
        document.analysis_error = str(exc)
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    import json

    document.analysis_json = json.dumps(result, ensure_ascii=False)
    document.analysis_error = None
    document.status = "analyzed"
    db.commit()
    return {"document_id": document.id, "analysis": result}


@router.get("/staff/applicants")
def list_applicants(
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    users = list(db.scalars(select(User).where(User.role == UserRole.applicant.value)))
    return [{"id": user.id, "email": user.email, "is_active": user.is_active} for user in users]
