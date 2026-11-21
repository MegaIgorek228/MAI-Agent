from app.db import SessionLocal
from app.models import User, UserRole
from io import BytesIO
from PIL import Image
from sqlalchemy import select


def auth_headers(client, email="applicant@example.com"):
    client.post(
        "/auth/register",
        json={"email": email, "password": "secure-password"},
    )
    token = client.post(
        "/auth/login",
        json={"email": email, "password": "secure-password"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_profile_and_document_upload(client):
    headers = auth_headers(client)
    profile = client.put(
        "/applicant/profile",
        headers=headers,
        json={"first_name": "Иван", "target_program": "Aerospace engineering"},
    )
    assert profile.status_code == 200
    assert profile.json()["first_name"] == "Иван"

    upload = client.post(
        "/applicant/documents",
        headers=headers,
        files={"file": ("passport.txt", b"synthetic document text", "text/plain")},
        data={"document_type": "identity"},
    )
    assert upload.status_code == 201
    assert upload.json()["status"] == "extracted"
    assert upload.json()["extracted_text"] == "synthetic document text"

    documents = client.get("/applicant/documents", headers=headers)
    assert documents.status_code == 200
    assert len(documents.json()) == 1


def test_image_upload_validation(client):
    headers = auth_headers(client)
    png_buffer = BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(png_buffer, format="PNG")
    png = png_buffer.getvalue()
    upload = client.post(
        "/applicant/documents",
        headers=headers,
        files={"file": ("photo.png", png, "image/png")},
        data={"document_type": "image"},
    )
    assert upload.status_code == 201
    assert upload.json()["content_type"] == "image/png"

    invalid = client.post(
        "/applicant/documents",
        headers=headers,
        files={"file": ("broken.png", b"not an image", "image/png")},
        data={"document_type": "image"},
    )
    assert invalid.status_code == 422


def test_staff_can_ingest_and_search_knowledge(client):
    headers = auth_headers(client, "staff@example.com")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "staff@example.com"))
        user.role = UserRole.admissions_staff.value
        db.commit()
    finally:
        db.close()

    source = client.post(
        "/knowledge/sources",
        headers=headers,
        json={
            "url": "https://mai.example/admission",
            "title": "Admission rules",
            "text": "Synthetic admission rule for testing.",
        },
    )
    assert source.status_code == 200
    search = client.post("/knowledge/search", json={"query": "admission rule"})
    assert search.status_code == 200
    assert len(search.json()) == 1
