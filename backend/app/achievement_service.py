"""Service layer for individual achievements.

Ownership rules enforced here (and mirrored by the router dependencies):

* an applicant creates and edits only their own achievements;
* a confirmed achievement is immutable for the applicant — a correction goes
  through the controlled "needs_revision" decision and a resubmission;
* only staff (admissions_staff / administrator) review achievements, and a
  rejection or revision request must carry a comment;
* every lifecycle change is written to the append-only ``achievement_reviews``
  table with the acting user.
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, defer, joinedload

from app.achievement_schemas import (
    AchievementCreate,
    AchievementDecisionInput,
    AchievementDocument,
    AchievementResponse,
    AchievementReviewResponse,
    AchievementUpdate,
)
from app.models import (
    AchievementReview,
    Application,
    Document,
    IndividualAchievement,
    User,
)

EDITABLE_STATUSES = {"draft", "rejected", "needs_revision"}
REVIEW_ACTIONS = {"confirmed", "rejected", "needs_revision"}


def achievement_for(
    db: Session,
    achievement_id: int,
    *,
    applicant_id: int | None = None,
    lock: bool = False,
) -> IndividualAchievement:
    query = select(IndividualAchievement).where(IndividualAchievement.id == achievement_id)
    if applicant_id is not None:
        query = query.where(IndividualAchievement.applicant_id == applicant_id)
    if lock:
        query = query.with_for_update()
    achievement = db.scalar(query)
    if achievement is None:
        raise HTTPException(status_code=404, detail="Achievement not found")
    return achievement


def ensure_editable(achievement: IndividualAchievement) -> None:
    if achievement.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Achievement cannot be edited in its current status",
        )


def _check_reference_ownership(
    db: Session,
    user: User,
    application_id: int | None,
    document_id: int | None,
) -> None:
    if application_id is not None:
        application = db.get(Application, application_id)
        if application is None or application.applicant_id != user.id:
            raise HTTPException(status_code=422, detail="Application is unavailable")
    if document_id is not None:
        document = db.get(Document, document_id)
        if document is None or document.owner_id != user.id:
            raise HTTPException(status_code=422, detail="Document is unavailable")


def _log(db: Session, achievement: IndividualAchievement, action: str, actor: User, comment: str | None = None) -> None:
    db.add(AchievementReview(achievement_id=achievement.id, action=action, comment=comment, actor_id=actor.id))


def create_achievement(db: Session, user: User, payload: AchievementCreate) -> IndividualAchievement:
    _check_reference_ownership(db, user, payload.application_id, payload.document_id)
    achievement = IndividualAchievement(
        applicant_id=user.id,
        application_id=payload.application_id,
        category=payload.category,
        title=payload.title,
        level=payload.level,
        achieved_on=payload.achieved_on,
        organization=payload.organization,
        description=payload.description,
        document_id=payload.document_id,
        status="draft",
    )
    db.add(achievement)
    db.flush()
    _log(db, achievement, "created", user)
    db.commit()
    db.refresh(achievement)
    return achievement


def update_achievement(
    db: Session, user: User, achievement: IndividualAchievement, payload: AchievementUpdate,
) -> IndividualAchievement:
    ensure_editable(achievement)
    updates = payload.model_dump(exclude_unset=True)
    new_application = updates.get("application_id")
    new_document = updates.get("document_id")
    _check_reference_ownership(db, user, new_application, new_document)
    changed = any(getattr(achievement, key) != value for key, value in updates.items())
    if not changed:
        return achievement
    for key, value in updates.items():
        setattr(achievement, key, value)
    achievement.updated_at = datetime.now(UTC)
    _log(db, achievement, "updated", user)
    db.commit()
    db.refresh(achievement)
    return achievement


def submit_achievement(
    db: Session, user: User, achievement: IndividualAchievement,
) -> IndividualAchievement:
    """Send a draft or a corrected achievement for staff review."""
    ensure_editable(achievement)
    action = "resubmitted" if achievement.submitted_at is not None else "submitted"
    achievement.status = "pending"
    achievement.submitted_at = datetime.now(UTC)
    achievement.review_comment = None
    achievement.reviewed_by = None
    achievement.reviewed_at = None
    achievement.updated_at = achievement.submitted_at
    _log(db, achievement, action, user)
    db.commit()
    db.refresh(achievement)
    return achievement


def review_achievement(
    db: Session,
    staff: User,
    achievement: IndividualAchievement,
    decision: AchievementDecisionInput,
) -> IndividualAchievement:
    """A staff decision on a pending achievement.

    Only ``pending`` achievements can be decided; ``rejected`` and
    ``needs_revision`` require a comment; the decision is recorded in the
    history with the acting staff member.
    """
    if achievement.status != "pending":
        raise HTTPException(status_code=409, detail="Only achievements awaiting review can be decided")
    if decision.action not in REVIEW_ACTIONS:
        raise HTTPException(status_code=422, detail="Unknown review action")
    comment = (decision.comment or "").strip() or None
    if decision.action in {"rejected", "needs_revision"} and not comment:
        raise HTTPException(status_code=422, detail="A comment is required for this decision")
    achievement.status = decision.action
    achievement.review_comment = comment
    achievement.reviewed_by = staff.id
    achievement.reviewed_at = datetime.now(UTC)
    achievement.updated_at = achievement.reviewed_at
    _log(db, achievement, decision.action, staff, comment)
    db.commit()
    db.refresh(achievement)
    return achievement


def applicant_achievements(db: Session, applicant_id: int) -> list[IndividualAchievement]:
    return list(db.scalars(
        select(IndividualAchievement).where(IndividualAchievement.applicant_id == applicant_id)
        .order_by(IndividualAchievement.created_at.desc(), IndividualAchievement.id.desc())
    ))


def achievement_history(db: Session, achievement_id: int) -> list[AchievementReviewResponse]:
    events = db.scalars(
        select(AchievementReview).where(AchievementReview.achievement_id == achievement_id)
        .order_by(AchievementReview.id)
    )
    return [AchievementReviewResponse.model_validate(event) for event in events]


def achievement_responses(db: Session, items: list[IndividualAchievement]) -> list[AchievementResponse]:
    if not items:
        return []
    documents: dict[int | None, Document | None] = {}
    document_ids = {item.document_id for item in items if item.document_id is not None}
    if document_ids:
        for document in db.scalars(
            select(Document).where(Document.id.in_(document_ids)).options(defer(Document.content))
        ):
            documents[document.id] = document
    responses = []
    for item in items:
        document = documents.get(item.document_id) if item.document_id is not None else None
        responses.append(
            AchievementResponse(
                **{field: getattr(item, field) for field in (
                    "id", "applicant_id", "application_id", "category", "title", "level",
                    "achieved_on", "organization", "description", "status", "submitted_at",
                    "review_comment", "reviewed_by", "reviewed_at", "created_at", "updated_at",
                )},
                document=AchievementDocument.model_validate(document) if document is not None else None,
            )
        )
    return responses


def staff_achievement_queue(
    db: Session,
    *,
    status: str | None = None,
    category: str | None = None,
    query: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> list[IndividualAchievement]:
    from sqlalchemy import or_

    from app.models import ApplicantProfile

    q = select(IndividualAchievement)
    if status:
        q = q.where(IndividualAchievement.status == status)
    if category:
        q = q.where(IndividualAchievement.category == category)
    if query and query.strip():
        term = query.strip()
        profile_match = or_(
            ApplicantProfile.first_name.ilike(f"%{term}%"),
            ApplicantProfile.last_name.ilike(f"%{term}%"),
        )
        q = q.join(User, User.id == IndividualAchievement.applicant_id).join(
            ApplicantProfile, ApplicantProfile.user_id == User.id, isouter=True
        ).where(
            or_(
                IndividualAchievement.title.ilike(f"%{term}%"),
                User.email.ilike(f"%{term}%"),
                profile_match,
            )
        )
    return list(db.scalars(
        q.order_by(IndividualAchievement.submitted_at.desc().nulls_last(),
                   IndividualAchievement.id.desc()).offset(offset).limit(limit)
    ))
