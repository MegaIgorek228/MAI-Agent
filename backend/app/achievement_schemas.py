"""Schemas for individual achievements (applicant declarations + staff review).

Declared achievement, staff review and admission scoring are separate
concepts: these schemas model the first two only. Nothing here assigns
admission points — a confirmed achievement may be counted later by separate
admission rules.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

AchievementCategory = Literal["olympiad", "sport", "gto", "volunteering", "creative", "other"]
AchievementLevel = Literal["school", "municipal", "regional", "national", "international"]
AchievementStatus = Literal["draft", "pending", "confirmed", "rejected", "needs_revision"]
AchievementDecision = Literal["confirmed", "rejected", "needs_revision"]

Title = Annotated[str, Field(min_length=1, max_length=255)]
Organization = Annotated[str | None, Field(max_length=255)]
Description = Annotated[str | None, Field(max_length=2000)]


class AchievementCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: AchievementCategory
    title: Title
    level: AchievementLevel | None = None
    achieved_on: date
    organization: Organization = None
    description: Description = None
    # Optional link to the applicant's own application; the backend verifies
    # ownership. A supporting document (the applicant's own upload) too.
    application_id: Annotated[int | None, Field(gt=0)] = None
    document_id: Annotated[int | None, Field(gt=0)] = None


class AchievementUpdate(BaseModel):
    """Fields editable while the achievement is in draft/rejected/needs_revision."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: AchievementCategory | None = None
    title: Title | None = None
    level: AchievementLevel | None = None
    achieved_on: date | None = None
    organization: Organization = None
    description: Description = None
    application_id: Annotated[int | None, Field(gt=0)] = None
    document_id: Annotated[int | None, Field(gt=0)] = None


class AchievementDocument(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class AchievementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    applicant_id: int
    application_id: int | None
    category: AchievementCategory
    title: str
    level: AchievementLevel | None
    achieved_on: date
    organization: str | None
    description: str | None
    status: AchievementStatus
    document: AchievementDocument | None
    submitted_at: datetime | None
    review_comment: str | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AchievementUpdateResult(BaseModel):
    achievement: AchievementResponse


class AchievementReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    comment: str | None
    actor_id: int | None
    created_at: datetime


class AchievementDecisionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    action: AchievementDecision
    # Required for "rejected" and "needs_revision" (enforced by the service).
    comment: Description = None


class StaffAchievementApplicant(BaseModel):
    id: int
    email: str
    first_name: str | None
    last_name: str | None


class StaffAchievementResponse(AchievementResponse):
    applicant: StaffAchievementApplicant
    history: list[AchievementReviewResponse]


# --- Staff cabinet ---------------------------------------------------------


class StaffApplicantApplication(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_year: int
    program: str
    admission_basis: str
    status: str
    document_count: int
    documents_pending: int
    updated_at: datetime


class StaffApplicantRow(BaseModel):
    id: int
    email: str
    is_active: bool
    first_name: str | None
    last_name: str | None
    created_at: datetime
    applications: list[StaffApplicantApplication]


class StaffApplicantProfile(BaseModel):
    id: int
    email: str
    is_active: bool
    first_name: str | None
    last_name: str | None
    phone: str | None
    target_program: str | None
    admission_basis: str | None


class StaffApplicantEvent(BaseModel):
    """One entry of the merged applicant activity history."""

    source: Literal["application", "achievement"]
    reference_id: int
    action: str
    note: str | None
    actor_id: int | None
    created_at: datetime


class StaffApplicantCard(BaseModel):
    profile: StaffApplicantProfile
    applications: list[StaffApplicantApplication]
    ege: list[dict[str, object]]
    achievements: list[AchievementResponse]
    history: list[StaffApplicantEvent]


class StaffActivityItem(BaseModel):
    source: Literal["application", "achievement", "invite"]
    reference_id: int
    action: str
    note: str | None
    actor_id: int | None
    created_at: datetime


class StaffDashboard(BaseModel):
    applicants_total: int
    applications_in_work: int
    applications_awaiting_review: int
    documents_awaiting_review: int
    achievements_awaiting_review: int
    recent_activity: list[StaffActivityItem]
