import hashlib
import io
from pathlib import Path
from io import BytesIO

from PIL import Image

from docx import Document as DocxDocument
from pypdf import PdfReader


def extract_text(filename: str, content_type: str, content: bytes) -> str | None:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json"} or content_type.startswith("text/"):
        return content.decode("utf-8", errors="replace")
    if suffix == ".pdf" or content_type == "application/pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if suffix == ".docx" or content_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        document = DocxDocument(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    return None


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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
