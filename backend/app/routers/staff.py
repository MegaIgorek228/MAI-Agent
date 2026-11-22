"""Staff cabinet endpoints: dashboard, applicant list and applicant card.

Everything here is read-only aggregate data plus the review endpoints that
already exist elsewhere (application review, document review, achievement
review). Counts are computed from the same tables the applicant-facing
features write to — no separate bookkeeping, no demo numbers.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.achievement_schemas import (
    StaffActivityItem,
    StaffApplicantApplication,
    StaffApplicantCard,
    StaffApplicantEvent,
    StaffApplicantProfile,
    StaffApplicantRow,
    StaffDashboard,
)
from app.achievement_service import applicant_achievements, achievement_responses
from app.admissions_service import DOCUMENT_REVIEW_QUEUE_STATUSES, ege_response, ordered_scores
from app.db import get_db
from app.dependencies import require_roles
from app.models import (
    AchievementReview,
    Application,
    ApplicationDocument,
    ApplicationEvent,
    ApplicantProfile,
    IndividualAchievement,
    User,
    UserRole,
)

router = APIRouter(prefix="/applicant/staff", tags=["staff"])
Staff = Annotated[User, Depends(require_roles(UserRole.admissions_staff, UserRole.administrator))]
Database = Annotated[Session, Depends(get_db)]

IN_WORK_STATUSES = ("submitted", "under_review", "needs_changes")


@router.get("/dashboard", response_model=StaffDashboard)
def staff_dashboard(current_user: Staff, db: Database) -> StaffDashboard:
    applicants_total = db.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.applicant.value)
    ) or 0
    applications_in_work = db.scalar(
        select(func.count()).select_from(Application).where(Application.status.in_(IN_WORK_STATUSES))
    ) or 0
    applications_awaiting_review = db.scalar(
        select(func.count()).select_from(Application).where(Application.status == "submitted")
    ) or 0
    documents_awaiting_review = db.scalar(
        select(func.count())
        .select_from(ApplicationDocument)
        .join(Application, Application.id == ApplicationDocument.application_id)
        .where(
            ApplicationDocument.review_status.is_(None),
            Application.status.in_(DOCUMENT_REVIEW_QUEUE_STATUSES),
        )
    ) or 0
    achievements_awaiting_review = db.scalar(
        select(func.count()).select_from(IndividualAchievement)
        .where(IndividualAchievement.status == "pending")
    ) or 0

    app_events = list(db.scalars(
        select(ApplicationEvent).order_by(ApplicationEvent.id.desc()).limit(50)
    ))
    ach_events = list(db.scalars(
        select(AchievementReview).order_by(AchievementReview.id.desc()).limit(50)
    ))
    merged: list[tuple[datetime, int, StaffActivityItem]] = []
    for event in app_events:
        merged.append((
            event.created_at,
            event.id,
            StaffActivityItem(
                source="application",
                reference_id=event.application_id,
                action=event.status,
                note=event.note,
                actor_id=event.actor_id,
                created_at=event.created_at,
            ),
        ))
    for event in ach_events:
        merged.append((
            event.created_at,
            event.id,
            StaffActivityItem(
                source="achievement",
                reference_id=event.achievement_id,
                action=event.action,
                note=event.comment,
                actor_id=event.actor_id,
                created_at=event.created_at,
            ),
        ))
    # Newest first; id breaks ties between the two tables.
    merged.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return StaffDashboard(
        applicants_total=int(applicants_total),
        applications_in_work=int(applications_in_work),
        applications_awaiting_review=int(applications_awaiting_review),
        documents_awaiting_review=int(documents_awaiting_review),
        achievements_awaiting_review=int(achievements_awaiting_review),
        recent_activity=[item for _, _, item in merged[:10]],
    )


def _applicant_applications(db: Session, applicant_id: int) -> list[StaffApplicantApplication]:
    applications = list(db.scalars(
        select(Application).where(Application.applicant_id == applicant_id)
        .order_by(Application.updated_at.desc(), Application.id.desc())
    ))
    if not applications:
        return []
    links = list(db.execute(
        select(ApplicationDocument.application_id, ApplicationDocument.review_status)
        .where(ApplicationDocument.application_id.in_([item.id for item in applications]))
    ))
    counts: dict[int, tuple[int, int]] = {item.id: (0, 0) for item in applications}
    for application_id, review_status in links:
        total, pending = counts[application_id]
        counts[application_id] = (total + 1, pending + (1 if review_status is None else 0))
    return [
        StaffApplicantApplication(
            id=item.id,
            campaign_year=item.campaign_year,
            program=item.program,
            admission_basis=item.admission_basis,
            status=item.status,
            document_count=counts[item.id][0],
            documents_pending=counts[item.id][1],
            updated_at=item.updated_at,
        )
        for item in applications
    ]


@router.get("/applicants", response_model=list[StaffApplicantRow])
def staff_applicants(
    current_user: Staff,
    db: Database,
    q: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[StaffApplicantRow]:
    """Applicant directory with search (name or email) and application data."""
    query = select(User).where(User.role == UserRole.applicant.value)
    if q and (words := q.split()):
        profile_match = select(ApplicantProfile.user_id).where(
            *(
                or_(
                    ApplicantProfile.first_name.icontains(word, autoescape=True),
                    ApplicantProfile.last_name.icontains(word, autoescape=True),
                )
                for word in words
            )
        )
        query = query.where(or_(User.email.icontains(q.strip(), autoescape=True), User.id.in_(profile_match)))
    users = list(db.scalars(query.order_by(User.id).offset(offset).limit(limit)))
    if not users:
        return []
    profiles = {
        profile.user_id: profile
        for profile in db.scalars(
            select(ApplicantProfile).where(ApplicantProfile.user_id.in_([user.id for user in users]))
        )
    }
    return [
        StaffApplicantRow(
            id=user.id,
            email=user.email,
            is_active=user.is_active,
            first_name=profiles[user.id].first_name if user.id in profiles else None,
            last_name=profiles[user.id].last_name if user.id in profiles else None,
            created_at=user.created_at,
            applications=_applicant_applications(db, user.id),
        )
        for user in users
    ]


@router.get("/applicants/{applicant_id}", response_model=StaffApplicantCard)
def staff_applicant_card(
    applicant_id: int, current_user: Staff, db: Database,
) -> StaffApplicantCard:
    """Full applicant card: personal data, applications, EGE scores,
    achievements and the merged activity history."""
    user = db.get(User, applicant_id)
    if user is None or user.role != UserRole.applicant.value:
        raise HTTPException(status_code=404, detail="Applicant not found")
    profile = db.scalar(
        select(ApplicantProfile).where(ApplicantProfile.user_id == applicant_id)
    )
    applications = list(db.scalars(
        select(Application).where(Application.applicant_id == applicant_id)
        .order_by(Application.updated_at.desc(), Application.id.desc())
    ))
    ege = []
    for application in applications:
        scores = ordered_scores(db, application.id)
        ege_data = ege_response(db, application)
        ege.append({
            "application_id": application.id,
            "synthetic_candidate_id": application.synthetic_candidate_id,
            "scores": [
                {"subject": item.subject, "year": item.year, "score": item.score}
                for item in scores
            ],
            "verification": (
                ege_data.verification.model_dump(mode="json")
                if ege_data.verification
                else None
            ),
        })
    history: list[tuple[datetime, int, StaffApplicantEvent]] = []
    for application in applications:
        for event in db.scalars(
            select(ApplicationEvent).where(ApplicationEvent.application_id == application.id)
        ):
            history.append((
                event.created_at,
                event.id,
                StaffApplicantEvent(
                    source="application",
                    reference_id=application.id,
                    action=event.status,
                    note=event.note,
                    actor_id=event.actor_id,
                    created_at=event.created_at,
                ),
            ))
    achievements = applicant_achievements(db, applicant_id)
    for achievement in achievements:
        for event in db.scalars(
            select(AchievementReview).where(AchievementReview.achievement_id == achievement.id)
        ):
            history.append((
                event.created_at,
                event.id,
                StaffApplicantEvent(
                    source="achievement",
                    reference_id=achievement.id,
                    action=event.action,
                    note=event.comment,
                    actor_id=event.actor_id,
                    created_at=event.created_at,
                ),
            ))
    history.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return StaffApplicantCard(
        profile=StaffApplicantProfile(
            id=user.id,
            email=user.email,
            is_active=user.is_active,
            first_name=profile.first_name if profile else None,
            last_name=profile.last_name if profile else None,
            phone=profile.phone if profile else None,
            target_program=profile.target_program if profile else None,
            admission_basis=profile.admission_basis if profile else None,
        ),
        applications=_applicant_applications(db, applicant_id),
        ege=ege,
        achievements=achievement_responses(db, achievements),
        history=[item for _, _, item in history],
    )
