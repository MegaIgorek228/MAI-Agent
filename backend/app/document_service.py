import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from PIL import Image
from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from lxml.etree import XMLSyntaxError
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AdmissionRuleSet, Document


class DocumentExtractionError(ValueError):
    """A supported file cannot be read by its parser."""


# Fallback names for the most common documents, used when no admission rule
# declaring the title exists. Values are the machine codes rules use.
DOCUMENT_TYPE_ALIASES = {
    "паспорт": "passport",
    "аттестат": "education",
    "документ об образовании": "education",
}


def normalize_document_type(db: Session, raw: str | None) -> str | None:
    """Map a user-supplied document type onto the machine code of a rule.

    The interface shows the Russian titles from the published rules, while
    the requirement check matches the codes. Accept a code (case-insensitive)
    or a rule title and return the canonical code; unknown values pass
    through trimmed so free-text types keep working.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    code = value.lower()
    latest = (
        select(
            AdmissionRuleSet.campaign_year,
            AdmissionRuleSet.program,
            AdmissionRuleSet.admission_basis,
            func.max(AdmissionRuleSet.revision).label("revision"),
        )
        .group_by(
            AdmissionRuleSet.campaign_year,
            AdmissionRuleSet.program,
            AdmissionRuleSet.admission_basis,
        )
        .subquery()
    )
    requirement_rows = list(db.scalars(
        select(AdmissionRuleSet.document_requirements)
        .join(
            latest,
            and_(
                AdmissionRuleSet.campaign_year == latest.c.campaign_year,
                AdmissionRuleSet.program == latest.c.program,
                AdmissionRuleSet.admission_basis == latest.c.admission_basis,
                AdmissionRuleSet.revision == latest.c.revision,
            ),
        )
    ))
    canonical: dict[str, str] = {}
    title_to_code: dict[str, str] = {}
    for requirements in requirement_rows:
        for item in requirements or []:
            item_code = str(item.get("document_type") or "").strip()
            item_title = str(item.get("title") or "").strip()
            if item_code:
                canonical.setdefault(item_code.lower(), item_code)
            if item_code and item_title:
                title_to_code.setdefault(item_title.lower(), item_code)
    if code in canonical:
        return canonical[code]
    if code in title_to_code:
        return title_to_code[code]
    return DOCUMENT_TYPE_ALIASES.get(code, value)


def _docx_text(container) -> str:
    blocks = []
    for item in container.iter_inner_content():
        if isinstance(item, Table):
            blocks.extend(
                "\t".join(_docx_text(cell) for cell in row.cells)
                for row in item.rows
            )
        else:
            blocks.append(item.text)
    return "\n".join(blocks)


def extract_text(filename: str, content_type: str, content: bytes) -> str | None:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json"} or content_type.startswith("text/"):
        return content.decode("utf-8", errors="replace")
    if suffix == ".pdf" or content_type == "application/pdf":
        try:
            reader = PdfReader(BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except (PyPdfError, ValueError, NotImplementedError, OSError) as exc:
            raise DocumentExtractionError("Не удалось прочитать файл PDF.") from exc
    if suffix == ".docx" or content_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        try:
            return _docx_text(DocxDocument(BytesIO(content))).strip()
        except (BadZipFile, KeyError, PackageNotFoundError, ValueError, XMLSyntaxError) as exc:
            raise DocumentExtractionError("Не удалось прочитать файл DOCX.") from exc
    return None


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def document_checklist(
    requirements: list[dict[str, str]],
    documents: list[tuple[str | None, str | None]],
    *,
    needs_profile: bool = False,
    rules_configured: bool | None = None,
) -> dict[str, object]:
    accepted_types = {kind for kind, review in documents if review == "accepted"}
    pending_types = {kind for kind, review in documents if review is None}
    missing = [
        required for required in requirements
        if required["document_type"] not in accepted_types | pending_types
    ]
    pending = [
        required for required in requirements
        if required["document_type"] in pending_types - accepted_types
    ]
    if needs_profile:
        status = "needs_profile"
        message = "Укажите направление и основание приёма, чтобы выбрать требования."
    elif rules_configured is False or (rules_configured is None and not requirements):
        status = "needs_admission_requirements"
        message = "Для этой ситуации поступления требования к документам ещё не настроены."
    elif missing:
        status = "incomplete"
        message = "Дозагрузите отсутствующие или отклонённые документы."
    elif pending:
        status = "needs_manual_review"
        message = "Файлы получены и ожидают проверки сотрудником."
    else:
        status = "complete"
        message = "Все обязательные документы проверены сотрудником."
    return {
        "status": status,
        "documents_received": len(documents),
        "missing_documents": missing,
        "pending_documents": pending,
        "message": message,
    }


SUPPORTED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def validate_image(content_type: str, content: bytes, max_size_bytes: int) -> tuple[str, str]:
    if content_type not in SUPPORTED_IMAGE_TYPES:
        raise ValueError("Only JPEG, PNG, WebP and GIF images are supported")
    if len(content) > max_size_bytes:
        raise ValueError("Image is too large")
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("Uploaded file is not a valid image") from exc
    return SUPPORTED_IMAGE_TYPES[content_type], content_type


def create_document(
    db: Session,
    *,
    owner_id: int,
    filename: str,
    content_type: str,
    content: bytes,
    document_type: str | None = None,
) -> Document:
    settings = get_settings()
    if len(content) > settings.max_upload_size_bytes:
        raise ValueError("File is too large")
    if content_type.startswith("image/"):
        validate_image(content_type, content, settings.max_image_size_bytes)
    extracted = extract_text(filename, content_type, content)
    if extracted is None:
        review_message = "Для этого формата требуется ручная проверка файла."
    elif not extracted.strip():
        extracted = None
        review_message = "В файле нет извлекаемого текста. Требуется ручная проверка."
    else:
        review_message = None
    document = Document(
        owner_id=owner_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        sha256=content_hash(content),
        content=content,
        document_type=(document_type or "").strip() or None,
        status="extracted" if extracted is not None else "needs_manual_review",
        extracted_text=extracted,
        review_message=review_message,
    )
    db.add(document)
    db.flush()
    return document
