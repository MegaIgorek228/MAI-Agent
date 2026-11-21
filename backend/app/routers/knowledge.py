import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_roles
from app.knowledge_service import search_knowledge, upsert_source
from app.models import AdmissionRequirement, User, UserRole
from app.official_materials import discover_official_urls, fetch_official_material

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeSourceCreate(BaseModel):
    url: HttpUrl
    title: str
    text: str


class KnowledgeSearchRequest(BaseModel):
    query: str
    limit: int = 5


class AdmissionRequirementCreate(BaseModel):
    document_type: str
    title: str
    target_program: str | None = None
    admission_basis: str | None = None
    required: bool = True
    source_url: HttpUrl | None = None


class OfficialMaterialSyncRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=20)


@router.post("/sources")
def create_source(
    payload: KnowledgeSourceCreate,
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    source = upsert_source(db, str(payload.url), payload.title, payload.text)
    return {"id": source.id, "url": source.url, "title": source.title}


@router.post("/search")
def search_sources(payload: KnowledgeSearchRequest, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    chunks = search_knowledge(db, payload.query, min(payload.limit, 20))
    return [
        {"source_id": chunk.source_id, "ordinal": chunk.ordinal, "content": chunk.content}
        for chunk in chunks
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
    synced: list[dict[str, object]] = []
    for url in payload.urls:
        try:
            final_url, title, text = fetch_official_material(str(url))
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(status_code=502, detail=f"Unable to fetch {url}: {exc}") from exc
        source = upsert_source(db, final_url, title, text)
        synced.append({"id": source.id, "url": source.url, "title": source.title})
    return synced


@router.post("/sources/discover")
def discover_sources(
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
) -> list[str]:
    try:
        return discover_official_urls()
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=f"Unable to discover official sources: {exc}") from exc
