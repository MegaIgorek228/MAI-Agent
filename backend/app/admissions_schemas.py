from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.schemas import DocumentResponse

Program = Annotated[str, Field(min_length=1, max_length=255)]
Basis = Annotated[str, Field(min_length=1, max_length=100)]
Subject = Annotated[str, Field(min_length=1, max_length=100)]
CampaignYear = Annotated[int, Field(ge=2000, le=2100)]
Score = Annotated[int, Field(ge=0, le=100)]
SyntheticCandidateId = Annotated[str, Field(pattern=r"^SYN-[A-Z0-9-]{1,44}$")]
DocumentIds = Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=100)]
ReviewNote = Annotated[str, Field(max_length=2000)]
ApplicationStatus = Literal["draft", "submitted", "under_review", "needs_changes", "reviewed"]


def normalize_subject(subject: str) -> str:
    return " ".join(subject.split()).casefold()


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    campaign_year: CampaignYear
    program: Program
    admission_basis: Basis
    document_ids: DocumentIds = Field(default_factory=list)


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    campaign_year: CampaignYear | None = None
    program: Program | None = None
    admission_basis: Basis | None = None
    document_ids: DocumentIds | None = None

    @model_validator(mode="after")
    def disallow_explicit_nulls(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Draft fields cannot be cleared")
        return self


class ApplicationResponse(ApplicationCreate):
    id: int
    applicant_id: int
    status: ApplicationStatus
    review_note: ReviewNote | None
    created_at: datetime
    updated_at: datetime


class DocumentRequirement(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_type: Annotated[str, Field(min_length=1, max_length=100)]
    title: Annotated[str, Field(min_length=1, max_length=255)]


class RuleSetCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    campaign_year: CampaignYear
    program: Program
    admission_basis: Basis
    source_url: HttpUrl | None = None
    document_requirements: list[DocumentRequirement] = Field(default_factory=list, max_length=100)
    subject_minima: dict[Subject, Score] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def normalize_keys(self):
        kinds = {item.document_type for item in self.document_requirements}
        if len(kinds) != len(self.document_requirements):
            raise ValueError("A required document type can only be listed once")
        normalized = {normalize_subject(subject): score for subject, score in self.subject_minima.items()}
        if "" in normalized or len(normalized) != len(self.subject_minima):
            raise ValueError("Each subject must be unique and non-empty")
        self.subject_minima = normalized
        return self


class RuleSetResponse(RuleSetCreate):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: int
    revision: int


class EgeScoreInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: Subject
    year: CampaignYear
    score: Score

    @model_validator(mode="after")
    def normalize_key(self):
        self.subject = normalize_subject(self.subject)
        return self


class EgeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scores: list[EgeScoreInput] = Field(max_length=60)
    synthetic_candidate_id: SyntheticCandidateId | None = None

    @model_validator(mode="after")
    def unique_scores(self):
        if len({(item.subject, item.year) for item in self.scores}) != len(self.scores):
            raise ValueError("A subject and year can only be listed once")
        return self


class SyntheticEgeInput(EgeScoreInput):
    candidate_id: SyntheticCandidateId
    status: Literal["valid", "annulled"] = "valid"


class SyntheticCandidateInput(BaseModel):
    """One synthetic person in the fixture registry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    candidate_id: SyntheticCandidateId
    full_name: Annotated[str, Field(min_length=3, max_length=255)]
    date_of_birth: date

    @model_validator(mode="after")
    def compact_full_name(self):
        self.full_name = " ".join(self.full_name.split())
        return self


class SyntheticEgeConfirmInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    candidate_id: SyntheticCandidateId


class SyntheticEgeMatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    candidate_id: SyntheticCandidateId
    full_name: str
    date_of_birth: date
    results: list[EgeScoreInput]


class SyntheticEgeSearchResponse(BaseModel):
    match_count: int
    ambiguous: bool
    matches: list[SyntheticEgeMatch]


class EgeVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal["match", "mismatch", "not_found", "incomplete"]
    missing_subjects: list[str]
    mismatched_subjects: list[str]
    verified_at: datetime
    source: Literal["synthetic"] = "synthetic"


class EgeResponse(EgeInput):
    verification: EgeVerificationResponse | None


class StaffStatusUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: Literal["under_review", "needs_changes", "reviewed"]
    review_note: ReviewNote | None = None


class StaffDocumentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: Literal["accepted", "rejected", "changes_requested"]
    review_note: ReviewNote | None = None


class ApplicationEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: Literal[
        "draft", "submitted", "under_review", "needs_changes", "reviewed",
        "document_reviewed",
    ]
    note: str | None
    actor_id: int | None
    created_at: datetime


class StaffDocumentQueueItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    application_id: int
    application_status: str
    applicant_id: int
    applicant_email: str
    applicant_name: str | None
    document_id: int
    filename: str
    content_type: str
    size_bytes: int
    document_type: str | None
    document_created_at: datetime
    review_status: str | None
    review_note: str | None
    reviewed_at: datetime | None
    reviewer: str | None


class DocumentChecklistResponse(BaseModel):
    status: Literal[
        "needs_profile", "needs_admission_requirements", "incomplete", "needs_manual_review", "complete",
    ]
    documents_received: int
    missing_documents: list[DocumentRequirement]
    pending_documents: list[DocumentRequirement]
    message: str


class EgeBelowMinimum(BaseModel):
    subject: str
    score: int
    minimum: int


class EgeRulesResponse(BaseModel):
    status: Literal[
        "needs_admission_requirements", "not_required", "incomplete", "below_minimum", "meets_minimum",
    ]
    missing_subjects: list[str] = Field(default_factory=list)
    below_minimum: list[EgeBelowMinimum] = Field(default_factory=list)


class RequirementsResponse(BaseModel):
    documents: DocumentChecklistResponse
    rules: RuleSetResponse | None
    ege: EgeRulesResponse


class StaffApplicantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_active: bool


class StaffApplicationResponse(BaseModel):
    application: ApplicationResponse
    applicant: StaffApplicantResponse
    documents: list[DocumentResponse]
    ege: EgeResponse
    requirements: RequirementsResponse
    history: list[ApplicationEventResponse]
