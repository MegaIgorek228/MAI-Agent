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
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document


class DocumentExtractionError(ValueError):
    """A supported file cannot be read by its parser."""


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
