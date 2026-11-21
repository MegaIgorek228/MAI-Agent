import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_roles
from app.knowledge_service import IndexedSource, reindex_source, search_knowledge, upsert_source
from app.models import AdmissionRequirement, User, UserRole
from app.official_materials import discover_official_urls, fetch_official_material

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeSourceCreate(BaseModel):
    url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    text: str


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1)


class AdmissionRequirementCreate(BaseModel):
    document_type: str
    title: str
    target_program: str | None = None
    admission_basis: str | None = None
    required: bool = True
    source_url: HttpUrl | None = None


class OfficialMaterialSyncRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=20)


def source_result(result: IndexedSource) -> dict[str, object]:
    source = result.source
    return {
        "id": source.id,
        "url": source.url,
        "title": source.title,
        "updated_at": source.updated_at,
        "content_hash": source.content_hash,
        "search_mode": result.search_mode,
    }


@router.post("/sources")
def create_source(
    payload: KnowledgeSourceCreate,
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        return source_result(upsert_source(db, str(payload.url), payload.title, payload.text))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Source changed concurrently. Retry the import.") from exc


@router.post("/search")
def search_sources(payload: KnowledgeSearchRequest, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return search_knowledge(db, payload.query, min(payload.limit, 20))


@router.post("/sources/{source_id}/reindex")
def reindex_knowledge_source(
    source_id: int,
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    result = reindex_source(db, source_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    return source_result(result)


@router.get("/admission-requirements")
def list_admission_requirements(
    target_program: str | None = None,
    admission_basis: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    def applies(column, value):
        if value is None:
            return column.is_(None)
        return or_(column.is_(None), func.lower(func.trim(column)) == value.strip().lower())

    requirements = db.scalars(
        select(AdmissionRequirement)
        .where(
            applies(AdmissionRequirement.target_program, target_program),
            applies(AdmissionRequirement.admission_basis, admission_basis),
        )
        .order_by(AdmissionRequirement.id)
    )
    return [
        {
            "id": rule.id,
            "document_type": rule.document_type,
            "title": rule.title,
            "target_program": rule.target_program,
            "admission_basis": rule.admission_basis,
            "required": rule.required,
            "source_url": rule.source_url,
        }
        for rule in requirements
    ]


@router.post("/admission-requirements", status_code=201)
def create_admission_requirement(
    payload: AdmissionRequirementCreate,
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    requirement = AdmissionRequirement(
        document_type=payload.document_type,
        title=payload.title,
        target_program=payload.target_program,
        admission_basis=payload.admission_basis,
        required=payload.required,
        source_url=str(payload.source_url) if payload.source_url else None,
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return {
        "id": requirement.id,
        "document_type": requirement.document_type,
        "title": requirement.title,
        "required": requirement.required,
    }


@router.post("/sources/sync")
def sync_official_sources(
    payload: OfficialMaterialSyncRequest,
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for url in payload.urls:
        requested_url = str(url)
        try:
            final_url, title, text = fetch_official_material(requested_url)
            source = source_result(upsert_source(db, final_url, title, text))
        except IntegrityError:
            db.rollback()
            results.append({"url": requested_url, "status": "failed", "detail": "Source changed concurrently"})
        except (ValueError, httpx.HTTPError) as exc:
            db.rollback()
            results.append({"url": requested_url, "status": "failed", "detail": str(exc)})
        else:
            results.append({**source, "requested_url": requested_url, "status": "synced"})
    if all(result["status"] == "failed" for result in results):
        raise HTTPException(status_code=502, detail=results)
    return results


@router.post("/sources/discover")
def discover_sources(
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
) -> list[str]:
    try:
        return discover_official_urls()
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=f"Unable to discover official sources: {exc}") from exc
