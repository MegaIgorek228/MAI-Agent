"""Staff cabinet and individual achievements: end-to-end API tests.

Covers the acceptance checklist:
1.  plain registration creates an applicant;
2.  a valid invitation creates admissions_staff;
3.  expired, used and revoked codes are rejected;
4.  the role cannot be self-assigned through the request;
5.  applicants cannot see or change foreign achievements;
6.  applicants cannot confirm their own achievements;
7.  staff review queue, decisions and mandatory comments;
8.  decision history is persisted with the acting user;
9.  the evidence document is stored and opened by staff;
10. dashboard counts and the applicant card reflect real database rows.
"""

from datetime import UTC, datetime, timedelta
from io import BytesIO

from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.invite_service import (
    create_staff_invite,
    revoke_staff_invite,
    staff_invite_status,
)
from app.models import StaffInvite, User


PASSWORD = "secure-password"


def register(client, email, password=PASSWORD, **extra):
    return client.post("/auth/register", json={"email": email, "password": password, **extra})


def login_headers(client, email, password=PASSWORD):
    token = client.post(
        "/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def make_applicant(client, email, first_name=None, last_name=None):
    created = register(client, email)
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "applicant"
    headers = login_headers(client, email)
    if first_name or last_name:
        profile = client.put(
            "/applicant/profile",
            headers=headers,
            json={"first_name": first_name, "last_name": last_name},
        )
        assert profile.status_code == 200
    return headers


def make_staff_invite(expires_delta: timedelta = timedelta(days=7)) -> tuple[int, str]:
    with SessionLocal() as db:
        invite, code = create_staff_invite(db, expires_at=datetime.now(UTC) + expires_delta)
        db.commit()
        invite_id = invite.id
    return invite_id, code


def make_staff(client, email, **invite_kwargs):
    invite_id, code = make_staff_invite(**invite_kwargs)
    created = register(client, email, invite_code=code)
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "admissions_staff"
    return login_headers(client, email), invite_id


def upload_document(client, headers, name="evidence.png", content_type="image/png"):
    if content_type == "image/png":
        buffer = BytesIO()
        Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
        content = buffer.getvalue()
    else:
        content = b"synthetic evidence text"
    upload = client.post(
        "/applicant/documents",
        headers=headers,
        files={"file": (name, content, content_type)},
        data={"document_type": "evidence"},
    )
    assert upload.status_code == 201, upload.text
    return upload.json(), content


ACHIEVEMENT_PAYLOAD = {
    "category": "olympiad",
    "title": "All-Russian olympiad in informatics — diploma II degree",
    "level": "national",
    "achieved_on": "2025-04-15",
    "organization": "Informatics Research Institute",
    "description": "Diploma, federal stage",
}


def create_achievement(client, headers, **overrides):
    payload = {**ACHIEVEMENT_PAYLOAD, **overrides}
    created = client.post("/applicant/achievements", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    return created.json()


# --- 1-6: invitations --------------------------------------------------------


def test_plain_registration_still_creates_applicant(client):
    created = register(client, "plain@example.com")
    assert created.status_code == 201
    assert created.json()["role"] == "applicant"


def test_valid_invite_creates_staff_and_marks_invite_used(client):
    headers, invite_id = make_staff(client, "staff-1@example.com")
    me = client.get("/users/me", headers=headers).json()
    assert me["role"] == "admissions_staff"
    with SessionLocal() as db:
        invite = db.get(StaffInvite, invite_id)
        assert invite is not None
        assert staff_invite_status(invite) == "used"
        assert invite.used_by is not None
        # The stored value is a 64-char hex hash, never the plaintext code.
        assert len(invite.code_hash) == 64
        assert all(char in "0123456789abcdef" for char in invite.code_hash)


def test_expired_invite_is_rejected_and_creates_no_user(client):
    expired_code = "MAI-EXPIRED-CODE-1"
    with SessionLocal() as db:
        from app.invite_service import hash_invite_code as _hash

        db.add(StaffInvite(
            code_hash=_hash(expired_code),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        ))
        db.commit()
    created = register(client, "expired@example.com", invite_code=expired_code)
    assert created.status_code == 400
    assert "недействителен" in created.json()["detail"]
    login = client.post(
        "/auth/login", json={"email": "expired@example.com", "password": PASSWORD}
    )
    assert login.status_code == 401  # no account was created


def test_invite_cannot_be_reused(client):
    invite_id, code = make_staff_invite()
    first = register(client, "reuse-1@example.com", invite_code=code)
    assert first.status_code == 201
    second = register(client, "reuse-2@example.com", invite_code=code)
    assert second.status_code == 400
    with SessionLocal() as db:
        invite = db.get(StaffInvite, invite_id)
        assert staff_invite_status(invite) == "used"


def test_revoked_invite_is_rejected(client):
    invite_id, code = make_staff_invite()
    with SessionLocal() as db:
        revoke_staff_invite(db, invite_id)
        db.commit()
    created = register(client, "revoked@example.com", invite_code=code)
    assert created.status_code == 400
    login = client.post(
        "/auth/login", json={"email": "revoked@example.com", "password": PASSWORD}
    )
    assert login.status_code == 401


def test_role_cannot_be_self_assigned(client):
    # Unknown fields in the payload are ignored — no "role" field exists.
    created = register(client, "sneaky@example.com", role="admissions_staff")
    assert created.status_code == 201
    assert created.json()["role"] == "applicant"
    # A garbage invite code never yields staff.
    created = register(client, "garbage@example.com", invite_code="MAI-NOT-A-REAL-CODE-1")
    assert created.status_code == 400


def test_all_invite_failures_share_one_generic_error(client):
    # Unknown, expired and used codes are indistinguishable to the caller.
    used_code = "MAI-USED-CODE-1"
    with SessionLocal() as db:
        from app.invite_service import hash_invite_code as _hash

        db.add(StaffInvite(
            code_hash=_hash(used_code),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            used_at=datetime.now(UTC),
        ))
        db.commit()
    unknown = register(client, "a1@example.com", invite_code="MAI-UNKNOWN-1")
    used = register(client, "a2@example.com", invite_code=used_code)
    assert unknown.status_code == used.status_code == 400
    assert unknown.json()["detail"] == used.json()["detail"]


# --- 7-10: achievements ------------------------------------------------------


def test_patch_achievement_rejects_explicit_null_for_required_fields(client):
    headers = make_applicant(client, "partial-achievement@example.com")
    created = create_achievement(client, headers, organization="Original organization")
    path = f"/applicant/achievements/{created['id']}"
    for field in ("category", "title", "achieved_on"):
        assert client.patch(path, headers=headers, json={field: None}).status_code == 422

    update = client.patch(path, headers=headers, json={"organization": None})
    assert update.status_code == 200
    assert update.json()["title"] == created["title"]
    assert update.json()["organization"] is None


def test_applicant_cannot_touch_foreign_achievements(client):
    owner = make_applicant(client, "owner@example.com")
    outsider = make_applicant(client, "outsider@example.com")
    achievement = create_achievement(client, owner)

    got = client.get(f"/applicant/achievements/{achievement['id']}", headers=outsider)
    assert got.status_code == 404
    patch = client.patch(
        f"/applicant/achievements/{achievement['id']}",
        headers=outsider,
        json={"title": "hacked"},
    )
    assert patch.status_code == 404
    submitted = client.post(
        f"/applicant/achievements/{achievement['id']}/submit", headers=outsider
    )
    assert submitted.status_code == 404
    history = client.get(f"/applicant/achievements/{achievement['id']}/history", headers=outsider)
    assert history.status_code == 404


def test_applicant_cannot_confirm_own_achievement(client):
    headers = make_applicant(client, "self-confirm@example.com")
    achievement = create_achievement(client, headers)
    client.post(f"/applicant/achievements/{achievement['id']}/submit", headers=headers)

    # The review endpoint is staff-only even for the owner.
    decision = client.post(
        f"/applicant/staff/achievements/{achievement['id']}/review",
        headers=headers,
        json={"action": "confirmed"},
    )
    assert decision.status_code == 403
    # And the applicant cannot force a status while the review is in flight.
    resubmit = client.post(
        f"/applicant/achievements/{achievement['id']}/submit", headers=headers
    )
    assert resubmit.status_code == 409


def test_staff_review_flow_with_history(client):
    applicant = make_applicant(client, "review-me@example.com", "Петр", "Сидоров")
    staff, _ = make_staff(client, "reviewer@example.com")
    achievement = create_achievement(client, applicant)
    client.post(f"/applicant/achievements/{achievement['id']}/submit", headers=applicant)
    draft = create_achievement(client, applicant, title="Draft for status filter")

    queue = client.get("/applicant/staff/achievements", headers=staff, params={"ach_status": "pending"})
    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()] == [achievement["id"]]
    queue = client.get("/applicant/staff/achievements", headers=staff, params={"status": "pending"})
    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()] == [achievement["id"]]
    drafts = client.get("/applicant/staff/achievements", headers=staff, params={"status": "draft"})
    assert drafts.status_code == 200
    assert [item["id"] for item in drafts.json()] == [draft["id"]]

    card = client.get(f"/applicant/staff/achievements/{achievement['id']}", headers=staff)
    assert card.status_code == 200
    body = card.json()
    assert body["status"] == "pending"
    assert body["applicant"]["first_name"] == "Петр"
    assert [item["action"] for item in body["history"]] == ["created", "submitted"]

    confirmed = client.post(
        f"/applicant/staff/achievements/{achievement['id']}/review",
        headers=staff,
        json={"action": "confirmed", "comment": "Диплом проверен"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["review_comment"] == "Диплом проверен"
    assert body["reviewed_by"] is not None
    actions = [item["action"] for item in body["history"]]
    assert actions == ["created", "submitted", "confirmed"]
    confirmed_entry = body["history"][-1]
    assert confirmed_entry["actor_id"] == body["reviewed_by"]

    # The decision is visible to the applicant with the staff comment.
    own = client.get(f"/applicant/achievements/{achievement['id']}", headers=applicant).json()
    assert own["status"] == "confirmed"
    assert own["review_comment"] == "Диплом проверен"
    # Confirmed achievements are immutable for the applicant.
    assert client.patch(
        f"/applicant/achievements/{achievement['id']}", headers=applicant, json={"title": "x"}
    ).status_code == 409
    assert client.post(
        f"/applicant/achievements/{achievement['id']}/submit", headers=applicant
    ).status_code == 409


def test_reject_requires_comment(client):
    applicant = make_applicant(client, "reject-me@example.com")
    staff, _ = make_staff(client, "rejecter@example.com")
    achievement = create_achievement(client, applicant)
    client.post(f"/applicant/achievements/{achievement['id']}/submit", headers=applicant)

    without_comment = client.post(
        f"/applicant/staff/achievements/{achievement['id']}/review",
        headers=staff,
        json={"action": "rejected"},
    )
    assert without_comment.status_code == 422
    with_comment = client.post(
        f"/applicant/staff/achievements/{achievement['id']}/review",
        headers=staff,
        json={"action": "rejected", "comment": "Номер диплома не читается"},
    )
    assert with_comment.status_code == 200
    assert with_comment.json()["status"] == "rejected"

    # Revision requests need a comment too.
    second = create_achievement(client, applicant, title="Another award")
    client.post(f"/applicant/achievements/{second['id']}/submit", headers=applicant)
    assert client.post(
        f"/applicant/staff/achievements/{second['id']}/review",
        headers=staff,
        json={"action": "needs_revision"},
    ).status_code == 422


def test_needs_revision_allows_controlled_resubmission(client):
    applicant = make_applicant(client, "revise-me@example.com")
    staff, _ = make_staff(client, "reviser@example.com")
    achievement = create_achievement(client, applicant)
    client.post(f"/applicant/achievements/{achievement['id']}/submit", headers=applicant)
    revised = client.post(
        f"/applicant/staff/achievements/{achievement['id']}/review",
        headers=staff,
        json={"action": "needs_revision", "comment": "Приложите scan диплома"},
    )
    assert revised.status_code == 200
    assert revised.json()["status"] == "needs_revision"

    edited = client.patch(
        f"/applicant/achievements/{achievement['id']}",
        headers=applicant,
        json={"description": "Добавлен scan диплома"},
    )
    assert edited.status_code == 200
    resubmitted = client.post(
        f"/applicant/achievements/{achievement['id']}/submit", headers=applicant
    )
    assert resubmitted.status_code == 200
    assert resubmitted.json()["status"] == "pending"

    history = client.get(
        f"/applicant/achievements/{achievement['id']}/history", headers=applicant
    ).json()
    assert [item["action"] for item in history] == [
        "created", "submitted", "needs_revision", "updated", "resubmitted",
    ]


def test_achievement_requires_no_fake_points(client):
    # A confirmed achievement carries no score: counting is a separate
    # admission-rules concern and must not be invented by this feature.
    applicant = make_applicant(client, "points@example.com")
    staff, _ = make_staff(client, "points-staff@example.com")
    achievement = create_achievement(client, applicant)
    client.post(f"/applicant/achievements/{achievement['id']}/submit", headers=applicant)
    confirmed = client.post(
        f"/applicant/staff/achievements/{achievement['id']}/review",
        headers=staff,
        json={"action": "confirmed"},
    ).json()
    assert "points" not in confirmed
    assert "score" not in confirmed


def test_evidence_document_ownership_and_download(client):
    owner = make_applicant(client, "doc-owner@example.com", "Иван", "Документов")
    foreign = make_applicant(client, "doc-foreign@example.com")
    staff, _ = make_staff(client, "doc-staff@example.com")

    # An applicant cannot attach a document that does not belong to them.
    foreign_doc, _ = upload_document(client, foreign)
    blocked = client.post(
        "/applicant/achievements",
        headers=owner,
        json={**ACHIEVEMENT_PAYLOAD, "document_id": foreign_doc["id"]},
    )
    assert blocked.status_code == 422

    own_doc, own_bytes = upload_document(client, owner)
    achievement = create_achievement(client, owner, document_id=own_doc["id"])
    client.post(f"/applicant/achievements/{achievement['id']}/submit", headers=owner)

    downloaded = client.get(
        f"/applicant/staff/achievements/{achievement['id']}/document/file", headers=staff
    )
    assert downloaded.status_code == 200
    assert downloaded.content == own_bytes

    card = client.get(f"/applicant/staff/achievements/{achievement['id']}", headers=staff).json()
    assert card["applicant"]["last_name"] == "Документов"
    assert card["applicant"]["first_name"] == "Иван"
    assert card["document"]["id"] == own_doc["id"]
    assert card["document"]["filename"] == "evidence.png"


def test_achievement_cannot_reference_foreign_application(client):
    owner = make_applicant(client, "app-owner@example.com")
    outsider = make_applicant(client, "app-outsider@example.com")
    application = client.post(
        "/applicant/applications",
        headers=owner,
        json={"campaign_year": 2026, "program": "09.03.01", "admission_basis": "ЕГЭ"},
    )
    assert application.status_code == 201
    blocked = client.post(
        "/applicant/achievements",
        headers=outsider,
        json={**ACHIEVEMENT_PAYLOAD, "application_id": application.json()["id"]},
    )
    assert blocked.status_code == 422


# --- 11: dashboard and applicant card ----------------------------------------


def test_dashboard_counts_and_applicant_card(client):
    applicant_a = make_applicant(client, "dash-a@example.com", "Алексей", "Тестов")
    applicant_b = make_applicant(client, "dash-b@example.com", "Мария", "Тестова")
    staff, _ = make_staff(client, "dash-staff@example.com")

    # Two applicants without profiles shift the applicant_profiles.id sequence
    # away from users.id, proving the staff card looks profiles up by user_id
    # rather than by the profile's own primary key.
    assert register(client, "dash-decoy-1@example.com").status_code == 201
    assert register(client, "dash-decoy-2@example.com").status_code == 201
    make_applicant(client, "dash-c@example.com", "Софья", "Смирнова")

    achievement = create_achievement(client, applicant_a)
    client.post(f"/applicant/achievements/{achievement['id']}/submit", headers=applicant_a)

    dashboard = client.get("/applicant/staff/dashboard", headers=staff).json()
    assert dashboard["applicants_total"] == 5
    assert dashboard["achievements_awaiting_review"] == 1
    assert dashboard["applications_in_work"] == 0
    assert dashboard["documents_awaiting_review"] == 0
    assert dashboard["applications_awaiting_review"] == 0
    # The submitted achievement shows up in the activity feed.
    assert any(
        item["source"] == "achievement" and item["action"] == "submitted"
        for item in dashboard["recent_activity"]
    )

    # Search finds the applicants by surname. (Cyrillic case-insensitivity
    # is exercised on PostgreSQL in the E2E stage; SQLite LIKE is
    # ASCII-only, so the query uses the stored case here.)
    listing = client.get(
        "/applicant/staff/applicants", headers=staff, params={"q": "Тестов"}
    ).json()
    assert len(listing) == 2
    row_a = next(row for row in listing if row["email"] == "dash-a@example.com")
    assert row_a["first_name"] == "Алексей"
    for full_name in ("Тестов Алексей", "Алексей  Тестов"):
        full_name_listing = client.get(
            "/applicant/staff/applicants", headers=staff, params={"q": full_name}
        )
        assert full_name_listing.status_code == 200
        assert [row["id"] for row in full_name_listing.json()] == [row_a["id"]]

    card = client.get(f"/applicant/staff/applicants/{row_a['id']}", headers=staff).json()
    assert card["profile"]["last_name"] == "Тестов"
    assert [a["id"] for a in card["achievements"]] == [achievement["id"]]
    assert any(
        event["source"] == "achievement" and event["action"] == "submitted"
        for event in card["history"]
    )
    assert card["applications"] == []
    assert card["ege"] == []

    # The third applicant's profile row id differs from the user id; the card
    # must still resolve the profile correctly.
    listing_c = client.get(
        "/applicant/staff/applicants", headers=staff, params={"q": "Смирнова"}
    ).json()
    assert len(listing_c) == 1
    card_c = client.get(f"/applicant/staff/applicants/{listing_c[0]['id']}", headers=staff).json()
    assert card_c["profile"]["last_name"] == "Смирнова"
    assert card_c["profile"]["first_name"] == "Софья"

    # Non-applicants are not cards.
    with SessionLocal() as db:
        staff_user = db.scalar(select(User).where(User.email == "dash-staff@example.com"))
    assert staff_user is not None
    denied = client.get(f"/applicant/staff/applicants/{staff_user.id}", headers=staff)
    assert denied.status_code == 404


def test_staff_applications_count_on_dashboard(client):
    applicant = make_applicant(client, "dash-app@example.com")
    staff, _ = make_staff(client, "dash-app-staff@example.com")
    application = client.post(
        "/applicant/applications",
        headers=applicant,
        json={"campaign_year": 2026, "program": "09.03.01", "admission_basis": "ЕГЭ"},
    )
    assert application.status_code == 201
    # Drafts are not "in work" yet.
    assert client.get("/applicant/staff/dashboard", headers=staff).json()["applications_in_work"] == 0

    doc, _ = upload_document(client, applicant, name="app.txt", content_type="text/plain")
    client.patch(
        f"/applicant/applications/{application.json()['id']}",
        headers=applicant,
        json={"document_ids": [doc["id"]]},
    )
    with SessionLocal() as db:
        from app.models import Application

        application_row = db.get(Application, application.json()["id"])
        application_row.status = "submitted"  # bypass rules: review-path test
        db.commit()

    dashboard = client.get("/applicant/staff/dashboard", headers=staff).json()
    assert dashboard["applications_in_work"] == 1
    assert dashboard["applications_awaiting_review"] == 1
    assert dashboard["documents_awaiting_review"] == 1
