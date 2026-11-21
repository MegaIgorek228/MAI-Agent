from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admissions_schemas import (
    ApplicationCreate,
    ApplicationEventResponse,
    ApplicationResponse,
    ApplicationStatus,
    ApplicationUpdate,
    CampaignYear,
    EgeInput,
    EgeResponse,
    RequirementsResponse,
    RuleSetCreate,
    RuleSetResponse,
    StaffApplicationResponse,
    StaffDocumentUpdate,
    StaffStatusUpdate,
)
from app.admissions_service import (
    STAFF_TRANSITIONS,
    application_documents,
    application_for,
    application_history,
    application_responses,
    ege_response,
    ensure_editable,
    matching_rule,
    ordered_scores,
    replace_scores,
    requirements_for,
    set_application_documents,
    staff_application_response,
    transition,
    verify_ege,
)
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models import AdmissionRuleSet, Application, ApplicationDocument, Document, User, UserRole
from app.schemas import DocumentResponse

router = APIRouter(prefix="/applicant", tags=["admissions"])
Applicant = Annotated[User, Depends(require_roles(UserRole.applicant))]
Staff = Annotated[User, Depends(require_roles(UserRole.admissions_staff, UserRole.administrator))]
SignedIn = Annotated[User, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]


@router.get("/applications")
def list_applications(current_user: Applicant, db: Database) -> list[ApplicationResponse]:
    applications = list(db.scalars(
        select(Application).where(Application.applicant_id == current_user.id)
        .order_by(Application.updated_at.desc(), Application.id.desc())
    ))
    return application_responses(db, applications)


@router.post("/applications", status_code=201)
def create_application(
    payload: ApplicationCreate, current_user: Applicant, db: Database,
) -> ApplicationResponse:
    application = Application(
        applicant_id=current_user.id, **payload.model_dump(exclude={"document_ids"}),
    )
    db.add(application)
    db.flush()
    set_application_documents(db, application, payload.document_ids)
    transition(db, application, current_user.id, "draft")
    db.commit()
    return application_responses(db, [application])[0]


@router.get("/applications/{application_id}")
def get_application(application_id: int, current_user: Applicant, db: Database) -> ApplicationResponse:
    application = application_for(db, application_id, applicant_id=current_user.id)
    return application_responses(db, [application])[0]


@router.patch("/applications/{application_id}")
def update_application(
    application_id: int, payload: ApplicationUpdate, current_user: Applicant, db: Database,
) -> ApplicationResponse:
    application = application_for(db, application_id, applicant_id=current_user.id, lock=True)
    ensure_editable(application)
    updates = payload.model_dump(exclude_unset=True, exclude={"document_ids"})
    if payload.campaign_year is not None and any(
        item.year > payload.campaign_year for item in ordered_scores(db, application.id)
    ):
        raise HTTPException(status_code=422, detail="Campaign year cannot precede a declared exam year")
    if any(getattr(application, key) != value for key, value in updates.items()):
        application.rules_id = None
        db.execute(
            update(ApplicationDocument)
            .where(ApplicationDocument.application_id == application.id)
            .values(review_status=None, review_note=None)
        )
    for key, value in updates.items():
        setattr(application, key, value)
    if payload.document_ids is not None:
        set_application_documents(db, application, payload.document_ids)
    if updates or payload.document_ids is not None:
        application.updated_at = datetime.now(UTC)
    db.commit()
    return application_responses(db, [application])[0]


@router.post("/applications/{application_id}/submit")
def submit_application(application_id: int, current_user: Applicant, db: Database) -> ApplicationResponse:
    application = application_for(db, application_id, applicant_id=current_user.id, lock=True)
    if application.status == "submitted":
        return application_responses(db, [application])[0]
    ensure_editable(application)
    rules = matching_rule(db, application)
    if rules is None:
        raise HTTPException(status_code=409, detail="Admission requirements are not published")
    application.rules_id = rules.id
    transition(db, application, current_user.id, "submitted")
    db.commit()
    return application_responses(db, [application])[0]


@router.get("/applications/{application_id}/events")
def get_application_events(
    application_id: int, current_user: Applicant, db: Database,
) -> list[ApplicationEventResponse]:
    application = application_for(db, application_id, applicant_id=current_user.id)
    return application_history(db, application.id)


@router.get("/applications/{application_id}/documents")
def list_application_documents(
    application_id: int, current_user: Applicant, db: Database,
) -> list[DocumentResponse]:
    application = application_for(db, application_id, applicant_id=current_user.id)
    return application_documents(db, application)


@router.get("/applications/{application_id}/requirements")
def get_application_requirements(
    application_id: int, current_user: Applicant, db: Database,
) -> RequirementsResponse:
    return requirements_for(db, application_for(db, application_id, applicant_id=current_user.id))


@router.get("/applications/{application_id}/ege")
def get_application_ege(application_id: int, current_user: Applicant, db: Database) -> EgeResponse:
    return ege_response(db, application_for(db, application_id, applicant_id=current_user.id))


@router.put("/applications/{application_id}/ege")
def put_application_ege(
    application_id: int, payload: EgeInput, current_user: Applicant, db: Database,
) -> EgeResponse:
    application = application_for(db, application_id, applicant_id=current_user.id, lock=True)
    replace_scores(db, application, payload)
    db.commit()
    return ege_response(db, application)


@router.post("/applications/{application_id}/ege/verify")
def verify_application_ege(application_id: int, current_user: Applicant, db: Database) -> EgeResponse:
    application = application_for(db, application_id, applicant_id=current_user.id, lock=True)
    return verify_ege(db, application)


@router.get("/admission-rules")
def list_admission_rules(
    current_user: SignedIn, db: Database, campaign_year: CampaignYear | None = None,
) -> list[RuleSetResponse]:
    scope = select(
        AdmissionRuleSet.campaign_year, AdmissionRuleSet.program, AdmissionRuleSet.admission_basis,
        func.max(AdmissionRuleSet.revision).label("revision"),
    ).group_by(AdmissionRuleSet.campaign_year, AdmissionRuleSet.program, AdmissionRuleSet.admission_basis)
    if campaign_year is not None:
        scope = scope.where(AdmissionRuleSet.campaign_year == campaign_year)
    matching = scope.subquery()
    rules = db.scalars(
        select(AdmissionRuleSet).join(
            matching,
            and_(
                AdmissionRuleSet.campaign_year == matching.c.campaign_year,
                AdmissionRuleSet.program == matching.c.program,
                AdmissionRuleSet.admission_basis == matching.c.admission_basis,
                AdmissionRuleSet.revision == matching.c.revision,
            ),
        ).order_by(AdmissionRuleSet.campaign_year.desc(), AdmissionRuleSet.program, AdmissionRuleSet.admission_basis)
    )
    return [RuleSetResponse.model_validate(item) for item in rules]


@router.post("/staff/admission-rules", status_code=201)
def publish_admission_rule(
    payload: RuleSetCreate, current_user: Staff, db: Database,
) -> RuleSetResponse:
    current_revision = db.scalar(select(func.max(AdmissionRuleSet.revision)).where(
        AdmissionRuleSet.campaign_year == payload.campaign_year,
        AdmissionRuleSet.program == payload.program,
        AdmissionRuleSet.admission_basis == payload.admission_basis,
    ))
    rule = AdmissionRuleSet(**payload.model_dump(mode="json"), revision=(current_revision or 0) + 1)
    db.add(rule)
    try:
        db.commit()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Rule set changed concurrently. Please retry.") from exc
    return RuleSetResponse.model_validate(rule)


@router.get("/staff/applications")
def list_staff_applications(
    current_user: Staff,
    db: Database,
    status: ApplicationStatus | None = None,
    applicant_id: Annotated[int | None, Query(gt=0)] = None,
    q: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ApplicationResponse]:
    # The staff queue begins when an application has actually been submitted.
    query = select(Application).where(Application.status != "draft")
    if status is not None:
        query = query.where(Application.status == status)
    if applicant_id is not None:
        query = query.where(Application.applicant_id == applicant_id)
    if q and q.strip():
        term = q.strip()
        query = query.join(User, User.id == Application.applicant_id).where(or_(
            Application.program.icontains(term, autoescape=True),
            User.email.icontains(term, autoescape=True),
        ))
    applications = list(db.scalars(
        query.order_by(Application.updated_at.desc(), Application.id.desc()).offset(offset).limit(limit)
    ))
    return application_responses(db, applications)


def _staff_application(db: Session, application_id: int, *, lock: bool = False) -> Application:
    application = application_for(db, application_id, lock=lock)
    if application.status == "draft":
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@router.get("/staff/applications/{application_id}")
def get_staff_application(
    application_id: int, current_user: Staff, db: Database,
) -> StaffApplicationResponse:
    return staff_application_response(db, _staff_application(db, application_id))


@router.patch("/staff/applications/{application_id}/status")
def update_staff_application(
    application_id: int, payload: StaffStatusUpdate, current_user: Staff, db: Database,
) -> ApplicationResponse:
    application = _staff_application(db, application_id, lock=True)
    if application.status == payload.status and application.review_note == payload.review_note:
        return application_responses(db, [application])[0]
    if payload.status not in STAFF_TRANSITIONS.get(application.status, set()):
        raise HTTPException(status_code=409, detail="Status transition is not available")
    if payload.status == "reviewed" and requirements_for(db, application).documents.status != "complete":
        raise HTTPException(status_code=409, detail="Complete the required document checks first")
    transition(db, application, current_user.id, payload.status, payload.review_note)
    db.commit()
    return application_responses(db, [application])[0]


def _attached_document(
    db: Session, application: Application, document_id: int,
) -> tuple[Document, ApplicationDocument]:
    found = db.execute(
        select(Document, ApplicationDocument)
        .join(ApplicationDocument, ApplicationDocument.document_id == Document.id)
        .where(
            ApplicationDocument.application_id == application.id,
            Document.id == document_id,
            Document.owner_id == application.applicant_id,
        )
    ).first()
    if not found:
        raise HTTPException(status_code=404, detail="Document not found")
    document, link = found
    return document, link


@router.get("/staff/applications/{application_id}/documents/{document_id}/file")
def download_staff_document(
    application_id: int, document_id: int, current_user: Staff, db: Database,
) -> Response:
    application = _staff_application(db, application_id)
    document, _ = _attached_document(db, application, document_id)
    filename = quote(document.filename, safe="")
    return Response(
        content=document.content, media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.patch("/staff/applications/{application_id}/documents/{document_id}")
def review_staff_document(
    application_id: int, document_id: int, payload: StaffDocumentUpdate,
    current_user: Staff, db: Database,
) -> DocumentResponse:
    application = _staff_application(db, application_id, lock=True)
    if application.status != "under_review":
        raise HTTPException(status_code=409, detail="Application is not under review")
    document, link = _attached_document(db, application, document_id)
    link.review_status = payload.status
    link.review_note = payload.review_note
    application.updated_at = datetime.now(UTC)
    db.commit()
    return DocumentResponse.model_validate(document).model_copy(update={
        "status": link.review_status, "review_message": link.review_note,
    })
