import json
from collections import defaultdict
from datetime import UTC, date, datetime
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from app.admissions_schemas import (
    ApplicationEventResponse,
    ApplicationResponse,
    EgeInput,
    EgeResponse,
    EgeRulesResponse,
    EgeScoreInput,
    EgeVerificationResponse,
    RequirementsResponse,
    StaffApplicantResponse,
    StaffApplicationResponse,
    SyntheticEgeMatch,
    SyntheticEgeSearchResponse,
)
from app.document_service import document_checklist
from app.models import (
    AdmissionRuleSet,
    Application,
    ApplicationDocument,
    ApplicationEvent,
    Document,
    EgeScore,
    EgeVerification,
    SyntheticEgeCandidate,
    SyntheticEgeResult,
    User,
)
from app.schemas import DocumentResponse

EDITABLE_STATUSES = {"draft", "needs_changes"}
STAFF_TRANSITIONS = {
    "submitted": {"under_review", "needs_changes"},
    "under_review": {"needs_changes", "reviewed"},
}


def application_for(
    db: Session,
    application_id: int,
    *,
    applicant_id: int | None = None,
    lock: bool = False,
) -> Application:
    query = select(Application).where(Application.id == application_id)
    if applicant_id is not None:
        query = query.where(Application.applicant_id == applicant_id)
    if lock:
        query = query.with_for_update()
    application = db.scalar(query)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def application_responses(db: Session, applications: list[Application]) -> list[ApplicationResponse]:
    if not applications:
        return []
    ids = defaultdict(list)
    for application_id, document_id in db.execute(
        select(ApplicationDocument.application_id, ApplicationDocument.document_id)
        .where(ApplicationDocument.application_id.in_([item.id for item in applications]))
        .order_by(ApplicationDocument.document_id)
    ):
        ids[application_id].append(document_id)
    return [
        ApplicationResponse(
            id=item.id, applicant_id=item.applicant_id, campaign_year=item.campaign_year,
            program=item.program, admission_basis=item.admission_basis, status=item.status,
            document_ids=ids[item.id], review_note=item.review_note,
            created_at=item.created_at, updated_at=item.updated_at,
        )
        for item in applications
    ]


def ensure_editable(application: Application) -> None:
    if application.status not in EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Application cannot be edited in its current status")


def set_application_documents(db: Session, application: Application, document_ids: list[int]) -> None:
    requested = set(document_ids)
    if requested:
        owned = set(db.scalars(
            select(Document.id).where(
                Document.owner_id == application.applicant_id,
                Document.id.in_(requested),
            ).order_by(Document.id).with_for_update()
        ))
        if owned != requested:
            raise HTTPException(status_code=422, detail="One or more documents are unavailable")
    links = list(db.scalars(
        select(ApplicationDocument).where(ApplicationDocument.application_id == application.id)
    ))
    for link in links:
        if link.document_id not in requested:
            db.delete(link)
    db.add_all([
        ApplicationDocument(application_id=application.id, document_id=document_id)
        for document_id in sorted(requested.difference(link.document_id for link in links))
    ])


def transition(
    db: Session, application: Application, actor_id: int, status: str, note: str | None = None,
) -> None:
    application.status = status
    application.review_note = note
    db.add(ApplicationEvent(application_id=application.id, actor_id=actor_id, status=status, note=note))


def application_history(db: Session, application_id: int) -> list[ApplicationEventResponse]:
    events = db.scalars(
        select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.id)
    )
    return [ApplicationEventResponse.model_validate(event) for event in events]


def matching_rule(db: Session, application: Application) -> AdmissionRuleSet | None:
    if application.rules_id is not None:
        return db.get(AdmissionRuleSet, application.rules_id)
    return db.scalar(
        select(AdmissionRuleSet).where(
            AdmissionRuleSet.campaign_year == application.campaign_year,
            AdmissionRuleSet.program == application.program,
            AdmissionRuleSet.admission_basis == application.admission_basis,
        ).order_by(AdmissionRuleSet.revision.desc()).limit(1)
    )


def ordered_scores(db: Session, application_id: int) -> list[EgeScore]:
    return list(db.scalars(
        select(EgeScore).where(EgeScore.application_id == application_id)
        .order_by(EgeScore.subject, EgeScore.year.desc())
    ))


def eligibility(rules: AdmissionRuleSet | None, scores: list[EgeScore]) -> EgeRulesResponse:
    if rules is None:
        return EgeRulesResponse(status="needs_admission_requirements")
    if not rules.subject_minima:
        return EgeRulesResponse(status="not_required")

    # Input can contain results from several exam years. Select the best declared
    # result per required subject. Synthetic comparison still checks each exact year.
    best_scores: dict[str, int] = {}
    for item in scores:
        best_scores[item.subject] = max(best_scores.get(item.subject, 0), item.score)
    missing = sorted(rules.subject_minima.keys() - best_scores.keys())
    below = [
        {"subject": subject, "score": best_scores[subject], "minimum": minimum}
        for subject, minimum in sorted(rules.subject_minima.items())
        if subject in best_scores and best_scores[subject] < minimum
    ]
    status = "incomplete" if missing else ("below_minimum" if below else "meets_minimum")
    return EgeRulesResponse.model_validate({
        "status": status,
        "missing_subjects": missing,
        "below_minimum": below,
    })


def requirements_for(db: Session, application: Application) -> RequirementsResponse:
    rules = matching_rule(db, application)
    typed_documents = list(db.execute(
        select(Document.document_type, ApplicationDocument.review_status)
        .join(ApplicationDocument, ApplicationDocument.document_id == Document.id)
        .where(ApplicationDocument.application_id == application.id)
    ))
    return RequirementsResponse.model_validate({
        "rules": rules,
        "documents": document_checklist(
            rules.document_requirements if rules else [],
            typed_documents,
            rules_configured=rules is not None,
        ),
        "ege": eligibility(rules, ordered_scores(db, application.id)),
    })


def ege_response(db: Session, application: Application) -> EgeResponse:
    result = db.scalar(
        select(EgeVerification).where(
            EgeVerification.application_id == application.id,
            EgeVerification.scores_revision == application.scores_revision,
        ).order_by(EgeVerification.id.desc()).limit(1)
    )
    return EgeResponse(
        scores=[
            EgeScoreInput(subject=item.subject, year=item.year, score=item.score)
            for item in ordered_scores(db, application.id)
        ],
        synthetic_candidate_id=application.synthetic_candidate_id,
        verification=EgeVerificationResponse.model_validate(result) if result is not None else None,
    )


def replace_scores(db: Session, application: Application, payload: EgeInput) -> None:
    ensure_editable(application)
    if any(item.year > application.campaign_year for item in payload.scores):
        raise HTTPException(status_code=422, detail="Exam year cannot exceed the campaign year")
    existing = {(row.subject, row.year): row for row in ordered_scores(db, application.id)}
    requested = {(row.subject, row.year): row.score for row in payload.scores}
    if (
        requested == {key: row.score for key, row in existing.items()}
        and application.synthetic_candidate_id == payload.synthetic_candidate_id
    ):
        return
    for key, row in existing.items():
        if key in requested:
            row.score = requested.pop(key)
        else:
            db.delete(row)
    db.add_all([
        EgeScore(application_id=application.id, subject=subject, year=year, score=score)
        for (subject, year), score in requested.items()
    ])
    application.synthetic_candidate_id = payload.synthetic_candidate_id
    application.scores_revision += 1


def normalize_full_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def search_synthetic_candidates(
    db: Session, full_name: str, date_of_birth: date
) -> SyntheticEgeSearchResponse:
    """Look the person up in the synthetic registry by full name and date of birth.

    Case- and whitespace-insensitive name comparison; exact date of birth.
    Returns 0, 1 or several matches — ambiguity is reported, never resolved
    by guessing a record.
    """
    needle = normalize_full_name(full_name)
    if not needle:
        raise HTTPException(status_code=422, detail="Full name is required")
    candidates = db.scalars(
        select(SyntheticEgeCandidate).where(
            SyntheticEgeCandidate.date_of_birth == date_of_birth
        )
    )
    matched = [
        candidate
        for candidate in candidates
        if normalize_full_name(candidate.full_name) == needle
    ]
    matches = [
        SyntheticEgeMatch(
            candidate_id=item.candidate_id,
            full_name=item.full_name,
            date_of_birth=item.date_of_birth,
            results=[
                EgeScoreInput(subject=row.subject, year=row.year, score=row.score)
                for row in db.scalars(
                    select(SyntheticEgeResult)
                    .where(
                        SyntheticEgeResult.candidate_id == item.candidate_id,
                        SyntheticEgeResult.status == "valid",
                    )
                    .order_by(SyntheticEgeResult.subject, SyntheticEgeResult.year.desc())
                )
            ],
        )
        for item in sorted(matched, key=lambda candidate: candidate.candidate_id)
    ]
    return SyntheticEgeSearchResponse(
        match_count=len(matches), ambiguous=len(matches) > 1, matches=matches,
    )


def bind_synthetic_results(
    db: Session, application: Application, candidate_id: str
) -> None:
    """Bind the registry's results for a confirmed candidate to the application.

    Only values read from the immutable registry are written: the caller can
    never supply scores here. Rebinding the same candidate is a no-op.
    """
    ensure_editable(application)
    candidate = db.get(SyntheticEgeCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=404, detail="Candidate not found in the synthetic registry"
        )
    rows = list(db.scalars(
        select(SyntheticEgeResult).where(
            SyntheticEgeResult.candidate_id == candidate_id,
            SyntheticEgeResult.status == "valid",
        )
    ))
    if not rows:
        raise HTTPException(
            status_code=422, detail="Candidate has no valid results in the registry"
        )
    if any(row.year > application.campaign_year for row in rows):
        raise HTTPException(
            status_code=422, detail="Registry result year cannot exceed the campaign year"
        )
    requested = {(row.subject, row.year): row.score for row in rows}
    existing = {(row.subject, row.year): row for row in ordered_scores(db, application.id)}
    if (
        requested == {key: row.score for key, row in existing.items()}
        and application.synthetic_candidate_id == candidate_id
    ):
        return
    for key, row in existing.items():
        if key in requested:
            row.score = requested.pop(key)
        else:
            db.delete(row)
    db.add_all([
        EgeScore(application_id=application.id, subject=subject, year=year, score=score)
        for (subject, year), score in requested.items()
    ])
    application.synthetic_candidate_id = candidate_id
    application.scores_revision += 1


def verify_ege(db: Session, application: Application) -> EgeResponse:
    existing = ege_response(db, application)
    missing: set[str] = set()
    mismatched: set[str] = set()
    observed: dict[tuple[str, int], int] = {}
    if not existing.scores or application.synthetic_candidate_id is None:
        status = "incomplete"
    else:
        observed = {
            (item.subject, item.year): item.score
            for item in db.scalars(
                select(SyntheticEgeResult).where(
                    SyntheticEgeResult.candidate_id == application.synthetic_candidate_id,
                    SyntheticEgeResult.status == "valid",
                )
            )
        }
        for item in existing.scores:
            expected = observed.get((item.subject, item.year))
            if expected is None:
                missing.add(item.subject)
            elif expected != item.score:
                mismatched.add(item.subject)
        if not observed:
            status = "not_found"
        elif mismatched:
            status = "mismatch"
        elif missing:
            status = "incomplete"
        else:
            status = "match"
    reference = [(subject, year, score) for (subject, year), score in sorted(observed.items())]
    digest = sha256(json.dumps(reference, ensure_ascii=False).encode()).hexdigest()
    saved = db.scalar(select(EgeVerification).where(
        EgeVerification.application_id == application.id,
        EgeVerification.scores_revision == application.scores_revision,
        EgeVerification.reference_digest == digest,
    ))
    if saved is not None:
        existing.verification = EgeVerificationResponse.model_validate(saved)
        return existing
    result = EgeVerification(
        application_id=application.id,
        scores_revision=application.scores_revision,
        reference_digest=digest,
        status=status,
        missing_subjects=sorted(missing),
        mismatched_subjects=sorted(mismatched),
        verified_at=datetime.now(UTC),
    )
    db.add(result)
    db.commit()
    return ege_response(db, application)


def application_documents(db: Session, application: Application) -> list[DocumentResponse]:
    return [
        DocumentResponse.model_validate(document).model_copy(update={
            "status": link.review_status or document.status,
            "review_message": link.review_note if link.review_status else document.review_message,
        })
        for document, link in db.execute(
            select(Document, ApplicationDocument)
            .join(ApplicationDocument, ApplicationDocument.document_id == Document.id)
            .where(ApplicationDocument.application_id == application.id)
            .options(defer(Document.content))
            .order_by(Document.id)
        )
    ]


def staff_application_response(db: Session, application: Application) -> StaffApplicationResponse:
    applicant = db.get(User, application.applicant_id)
    if applicant is None:
        raise HTTPException(status_code=404, detail="Applicant not found")
    return StaffApplicationResponse(
        application=application_responses(db, [application])[0],
        applicant=StaffApplicantResponse.model_validate(applicant),
        documents=application_documents(db, application),
        ege=ege_response(db, application),
        requirements=requirements_for(db, application),
        history=application_history(db, application.id),
    )
