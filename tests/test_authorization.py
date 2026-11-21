from sqlalchemy import select

from app.db import SessionLocal
from app.models import User, UserRole


def test_staff_area_requires_authentication_and_role(client):
    assert client.get("/users/staff-area").status_code == 401

    client.post(
        "/auth/register",
        json={"email": "applicant@example.com", "password": "secure-password"},
    )
    token = client.post(
        "/auth/login",
        json={"email": "applicant@example.com", "password": "secure-password"},
    ).json()["access_token"]

    response = client.get("/users/staff-area", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_student_can_use_own_profile_and_chat_but_not_staff_area(client):
    registration = client.post(
        "/auth/register",
        json={"email": "student@example.com", "password": "secure-password"},
    )
    assert registration.status_code == 201

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "student@example.com"))
        user.role = UserRole.student.value
        db.commit()
    finally:
        db.close()

    token = client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "secure-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/applicant/profile", headers=headers).status_code == 200
    assert client.get("/users/staff-area", headers=headers).status_code == 403
    assert (
        client.post(
            "/applicant/documents",
            headers=headers,
            files={"file": ("student.txt", b"private document", "text/plain")},
        ).status_code
        == 403
    )
