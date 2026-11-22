from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from jwt import InvalidTokenError
from openai import APIError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencies import bearer_scheme, get_current_user, require_roles
from app.document_service import (
    SUPPORTED_IMAGE_TYPES, create_document, document_checklist,
    normalize_document_type,
)
from app.llm_service import LLMProviderUnavailable, analyze_document
from app.models import (
    AdmissionRequirement, ApplicantProfile, Application, ApplicationDocument, Document, User, UserRole,
)
from app.schemas import (
    DocumentAnalysis, DocumentResponse, DocumentTypeUpdate, ProfileResponse, ProfileUpdate,
)
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
    document_type: str | None = Form(default=None, max_length=100),
    current_user: User = Depends(
        require_roles(UserRole.applicant, UserRole.admissions_staff, UserRole.administrator)
    ),
    db: Session = Depends(get_db),
    legacy_document_type: str | None = Query(default=None, alias="document_type", max_length=100),
) -> Document:
    max_size = get_settings().max_upload_size_bytes
    content = file.file.read(max_size + 1)
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail="File is too large")
    submitted_document_type = document_type if document_type is not None else legacy_document_type
    submitted_document_type = normalize_document_type(db, submitted_document_type)
    try:
        document = create_document(
            db, owner_id=current_user.id, filename=file.filename or "document",
            content_type=file.content_type or "application/octet-stream", content=content,
            document_type=submitted_document_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.patch("/documents/{document_id}/type", response_model=DocumentResponse)
def update_document_type(
    document_id: int,
    payload: DocumentTypeUpdate,
    current_user: User = Depends(
        require_roles(UserRole.applicant, UserRole.admissions_staff, UserRole.administrator)
    ),
    db: Session = Depends(get_db),
) -> Document:
    application_rows = list(db.execute(
        select(Application)
        .join(ApplicationDocument, Application.id == ApplicationDocument.application_id)
        .where(ApplicationDocument.document_id == document_id, Application.applicant_id == current_user.id)
        .order_by(Application.id)
        .with_for_update()
    ).scalars())
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == current_user.id)
        .with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    new_type = normalize_document_type(db, payload.document_type)
    if new_type != document.document_type:
        if any(item.status not in {"draft", "needs_changes"} for item in application_rows):
            raise HTTPException(status_code=409, detail="Document is attached to a submitted application")
        document.document_type = new_type
        db.execute(
            update(ApplicationDocument)
            .where(ApplicationDocument.document_id == document.id)
            .values(review_status=None, review_note=None)
        )
        db.commit()
        db.refresh(document)
    return document


@router.get("/documents/completeness")
def document_completeness(
    current_user: User = Depends(
        require_roles(UserRole.applicant, UserRole.admissions_staff, UserRole.administrator)
    ),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    approved = (
        select(ApplicationDocument.application_id)
        .where(
            ApplicationDocument.document_id == Document.id,
            ApplicationDocument.review_status == "accepted",
        )
        .exists()
    )
    documents = [
        (kind, "accepted" if is_accepted else None)
        for kind, is_accepted in db.execute(
            select(Document.document_type, approved).where(Document.owner_id == current_user.id)
        )
    ]
    profile = db.scalar(select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id))
    requirements = list(
        db.scalars(select(AdmissionRequirement).where(AdmissionRequirement.required.is_(True)))
    )
    program = profile.target_program if profile else None
    basis = profile.admission_basis if profile else None
    applicable: dict[str, dict[str, str]] = {}
    needs_profile = False
    for requirement in requirements:
        if (
            (program and requirement.target_program not in {None, program})
            or (basis and requirement.admission_basis not in {None, basis})
        ):
            continue
        if (requirement.target_program and not program) or (requirement.admission_basis and not basis):
            needs_profile = True
            continue
        applicable[requirement.document_type] = {
            "document_type": requirement.document_type, "title": requirement.title,
        }
    return document_checklist(list(applicable.values()), documents, needs_profile=needs_profile)


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
        result = DocumentAnalysis.model_validate(analyze_document(document.extracted_text))
    except (LLMProviderUnavailable, APIError, ValueError) as exc:
        message = "Не удалось получить структурированный результат анализа документа."
        document.analysis_error = message
        db.commit()
        raise HTTPException(status_code=503, detail=message) from exc

    document.analysis_json = result.model_dump_json()
    document.analysis_error = None
    document.status = "analyzed"
    db.commit()
    return {"document_id": document.id, "analysis": result.model_dump(mode="json")}

