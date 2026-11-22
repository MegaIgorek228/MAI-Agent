"""Individual achievement endpoints.

Applicant side: only the owning applicant can see and modify their
achievements; the applicant changes status exclusively through submission —
a confirmed achievement cannot be edited or re-decided by the applicant.

Staff side: admissions staff see the review queue, open the full card with
the applicant, the evidence document and the decision history, and record
confirm/reject/revision decisions (reject and revision require a comment).
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.achievement_schemas import (
    AchievementCreate,
    AchievementDecisionInput,
    AchievementDocument,
    AchievementResponse,
    AchievementReviewResponse,
    AchievementUpdate,
    StaffAchievementApplicant,
    StaffAchievementResponse,
)
from app.achievement_service import (
    achievement_for,
    achievement_history,
    achievement_responses,
    applicant_achievements,
    create_achievement,
    review_achievement,
    staff_achievement_queue,
    submit_achievement,
    update_achievement,
)
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models import ApplicantProfile, Document, IndividualAchievement, User, UserRole

router = APIRouter(prefix="/applicant", tags=["achievements"])
Applicant = Annotated[User, Depends(require_roles(UserRole.applicant))]
Staff = Annotated[User, Depends(require_roles(UserRole.admissions_staff, UserRole.administrator))]
Database = Annotated[Session, Depends(get_db)]


@router.get("/achievements", response_model=list[AchievementResponse])
def list_my_achievements(current_user: Applicant, db: Database) -> list[AchievementResponse]:
    return achievement_responses(db, applicant_achievements(db, current_user.id))


@router.post("/achievements", response_model=AchievementResponse, status_code=status.HTTP_201_CREATED)
def create_my_achievement(
    payload: AchievementCreate, current_user: Applicant, db: Database,
) -> AchievementResponse:
    achievement = create_achievement(db, current_user, payload)
    return achievement_responses(db, [achievement])[0]


@router.get("/achievements/{achievement_id}", response_model=AchievementResponse)
def get_my_achievement(
    achievement_id: int, current_user: Applicant, db: Database,
) -> AchievementResponse:
    achievement = achievement_for(db, achievement_id, applicant_id=current_user.id)
    return achievement_responses(db, [achievement])[0]


@router.patch("/achievements/{achievement_id}", response_model=AchievementResponse)
def update_my_achievement(
    achievement_id: int,
    payload: AchievementUpdate,
    current_user: Applicant,
    db: Database,
) -> AchievementResponse:
    achievement = achievement_for(db, achievement_id, applicant_id=current_user.id, lock=True)
    updated = update_achievement(db, current_user, achievement, payload)
    return achievement_responses(db, [updated])[0]


@router.post("/achievements/{achievement_id}/submit", response_model=AchievementResponse)
def submit_my_achievement(
    achievement_id: int, current_user: Applicant, db: Database,
) -> AchievementResponse:
    achievement = achievement_for(db, achievement_id, applicant_id=current_user.id, lock=True)
    submitted = submit_achievement(db, current_user, achievement)
    return achievement_responses(db, [submitted])[0]


@router.get("/achievements/{achievement_id}/history", response_model=list[AchievementReviewResponse])
def get_my_achievement_history(
    achievement_id: int, current_user: Applicant, db: Database,
) -> list[AchievementReviewResponse]:
    achievement_for(db, achievement_id, applicant_id=current_user.id)
    return achievement_history(db, achievement_id)


# --- Staff: review queue ---------------------------------------------------


@router.get("/staff/achievements", response_model=list[AchievementResponse])
def list_staff_achievements(
    current_user: Staff,
    db: Database,
    ach_status: Annotated[
        str | None, Query(pattern=r"^(draft|pending|confirmed|rejected|needs_revision)$")
    ] = None,
    category: Annotated[str | None, Query(max_length=32)] = None,
    q: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AchievementResponse]:
    items = staff_achievement_queue(
        db, status=ach_status, category=category, query=q, limit=limit, offset=offset,
    )
    return achievement_responses(db, items)


def _achievement_document(db: Session, achievement: IndividualAchievement) -> AchievementDocument | None:
    if achievement.document_id is None:
        return None
    document = db.scalar(
        select(Document).where(Document.id == achievement.document_id).options(defer(Document.content))
    )
    return AchievementDocument.model_validate(document) if document is not None else None


def _staff_achievement_response(
    db: Session, achievement: IndividualAchievement,
) -> StaffAchievementResponse:
    applicant = db.get(User, achievement.applicant_id)
    if applicant is None:
        raise HTTPException(status_code=404, detail="Applicant not found")
    profile = db.scalar(
        select(ApplicantProfile).where(ApplicantProfile.user_id == achievement.applicant_id)
    )
    return StaffAchievementResponse(
        **{field: getattr(achievement, field) for field in (
            "id", "applicant_id", "application_id", "category", "title", "level",
            "achieved_on", "organization", "description", "status", "submitted_at",
            "review_comment", "reviewed_by", "reviewed_at", "created_at", "updated_at",
        )},
        document=_achievement_document(db, achievement),
        applicant=StaffAchievementApplicant(
            id=applicant.id,
            email=applicant.email,
            first_name=profile.first_name if profile else None,
            last_name=profile.last_name if profile else None,
        ),
        history=achievement_history(db, achievement.id),
    )


@router.get("/staff/achievements/{achievement_id}", response_model=StaffAchievementResponse)
def get_staff_achievement(
    achievement_id: int, current_user: Staff, db: Database,
) -> StaffAchievementResponse:
    achievement = achievement_for(db, achievement_id)
    return _staff_achievement_response(db, achievement)


@router.post("/staff/achievements/{achievement_id}/review", response_model=StaffAchievementResponse)
def review_staff_achievement(
    achievement_id: int,
    decision: AchievementDecisionInput,
    current_user: Staff,
    db: Database,
) -> StaffAchievementResponse:
    achievement = achievement_for(db, achievement_id, lock=True)
    reviewed = review_achievement(db, current_user, achievement, decision)
    return _staff_achievement_response(db, reviewed)


@router.get("/staff/achievements/{achievement_id}/document/file")
def download_staff_achievement_document(
    achievement_id: int, current_user: Staff, db: Database,
) -> Response:
    """Serve the evidence file. Ownership is enforced: the document must
    belong to the applicant who declared the achievement."""
    achievement = achievement_for(db, achievement_id)
    if achievement.document_id is None:
        raise HTTPException(status_code=404, detail="Achievement has no attached document")
    document = db.scalar(
        select(Document)
        .where(Document.id == achievement.document_id, Document.owner_id == achievement.applicant_id)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    filename = quote(document.filename, safe="")
    return Response(
        content=document.content,
        media_type=document.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8\'\'{filename}"},
    )
