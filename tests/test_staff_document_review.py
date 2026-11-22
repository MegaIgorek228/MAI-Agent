"""Staff document review queue, decisions, audit trail and authorization.

Covers:
1. queue lists documents of submitted applications and hides drafts;
2. status filter (pending / accepted / rejected / changes_requested);
3. search by applicant name and email;
4. a decision stores review status, note, reviewed_at and the reviewer;
5. every decision is written to the application event history with the actor;
6. rejection requires a comment (422 without it);
7. the applicant sees the decision and the reason in their own documents;
8. applicants cannot open the queue, review documents or fetch staff files;
9. staff cannot review a document through an application that does not own it.
"""

import pytest

from test_admissions_workflow import APPLICATION, RULES, staff_headers, upload
from test_applicant_features import auth_headers


def _published_rules(client, staff) -> None:
    created = client.post("/applicant/staff/admission-rules", headers=staff, json=RULES)
    assert created.status_code == 201, created.text


def _submitted_application(client, staff, applicant, document_id: int) -> int:
    created = client.post(
        "/applicant/applications",
        headers=applicant,
        json={**APPLICATION, "document_ids": [document_id]},
    )
    assert created.status_code == 201, created.text
    application_id = created.json()["id"]
    submit = client.post(f"/applicant/applications/{application_id}/submit", headers=applicant)
    assert submit.status_code == 200, submit.text
    return application_id


def test_document_queue_filters_search_and_audit(client):
    staff = staff_headers(client)
    applicant = auth_headers(client, "queue-applicant@example.com")
    profile = client.put(
        "/applicant/profile", headers=applicant,
        json={"first_name": "Ольга", "last_name": "Тестова"},
    )
    assert profile.status_code == 200
    staff_email = "admissions-staff@example.com"
    _published_rules(client, staff)

    document = upload(client, applicant).json()
    application_id = _submitted_application(client, staff, applicant, document["id"])
    staff_path = f"/applicant/staff/applications/{application_id}"

    # Draft applications stay out of the queue; submitted ones enter it.
    draft = client.post("/applicant/applications", headers=applicant, json=APPLICATION)
    assert draft.status_code == 201
    rows = client.get("/applicant/staff/documents", headers=staff).json()
    assert [row["application_id"] for row in rows] == [application_id]

    # Pending queue, then search by name and by email.
    pending = client.get("/applicant/staff/documents", headers=staff, params={"status": "pending"}).json()
    assert len(pending) == 1
    item = pending[0]
    assert item["applicant_email"] == "queue-applicant@example.com"
    assert item["applicant_name"] == "Ольга Тестова"
    assert item["document_id"] == document["id"]
    assert item["review_status"] is None and item["reviewed_at"] is None and item["reviewer"] is None
    assert [row["document_id"] for row in client.get(
        "/applicant/staff/documents", headers=staff, params={"q": "Тестова"}).json()] == [document["id"]]
    assert [row["document_id"] for row in client.get(
        "/applicant/staff/documents", headers=staff, params={"q": "queue-applicant@"}).json()] == [document["id"]]
    assert client.get("/applicant/staff/documents", headers=staff, params={"q": "nobody"}).json() == []

    # The review endpoint only works while the application is under review.
    assert client.patch(doc_path := f"{staff_path}/documents/{document['id']}", headers=staff,
                        json={"status": "accepted"}).status_code == 409
    assert client.patch(staff_path + "/status", headers=staff, json={"status": "under_review"}).status_code == 200

    # Acceptance records the decision, the reviewer and the audit event.
    accepted = client.patch(doc_path, headers=staff, json={"status": "accepted"}).json()
    assert accepted["status"] == "accepted"
    assert accepted["reviewed_at"] is not None
    assert accepted["reviewer"] == staff_email
    detail = client.get(staff_path, headers=staff).json()
    assert detail["documents"][0]["reviewed_at"] == accepted["reviewed_at"]
    assert detail["documents"][0]["reviewer"] == staff_email
    assert [event["status"] for event in detail["history"]].count("document_reviewed") == 1
    assert detail["history"][-1]["note"].startswith("Документ «identity.txt»")
    assert detail["history"][-1]["actor_id"] is not None

    # The queue now reports the accepted decision with date and reviewer.
    accepted_row = client.get("/applicant/staff/documents", headers=staff, params={"status": "accepted"}).json()
    assert len(accepted_row) == 1 and accepted_row[0]["reviewed_at"] is not None
    assert accepted_row[0]["reviewer"] == staff_email
    assert client.get("/applicant/staff/documents", headers=staff, params={"status": "pending"}).json() == []

    # Rejection without a comment is rejected; with a comment the applicant
    # sees both the status and the reason.
    assert client.patch(doc_path, headers=staff, json={"status": "rejected"}).status_code == 422
    rejected = client.patch(doc_path, headers=staff, json={
        "status": "rejected", "review_note": "Файл не читается",
    }).json()
    assert rejected["status"] == "rejected" and rejected["review_message"] == "Файл не читается"
    applicant_docs = client.get(
        f"/applicant/applications/{application_id}/documents", headers=applicant).json()
    assert applicant_docs[0]["status"] == "rejected"
    assert applicant_docs[0]["review_message"] == "Файл не читается"
    assert client.get("/applicant/staff/documents", headers=staff, params={"status": "rejected"}).json()[0]["review_note"] == "Файл не читается"

    # Requesting a correction is a first-class decision.
    correction_without_note = client.patch(
        doc_path, headers=staff, json={"status": "changes_requested", "review_note": "  "},
    )
    assert correction_without_note.status_code == 422
    changed = client.patch(doc_path, headers=staff, json={
        "status": "changes_requested", "review_note": "Загрузите обе страницы паспорта",
    }).json()
    assert changed["status"] == "changes_requested"
    assert client.get("/applicant/staff/documents", headers=staff, params={
        "status": "changes_requested"}).json()[0]["document_id"] == document["id"]
    # Every decision landed in the history, newest last.
    history = client.get(staff_path, headers=staff).json()["history"]
    assert [event["status"] for event in history] == [
        "draft", "submitted", "under_review",
        "document_reviewed", "document_reviewed", "document_reviewed",
    ]


def test_pending_queue_and_dashboard_exclude_finalized_applications(client):
    staff = staff_headers(client)
    applicant = auth_headers(client, "pending-finalized@example.com")
    _published_rules(client, staff)
    required = upload(client, applicant).json()
    optional = client.post(
        "/applicant/documents", headers=applicant,
        files={"file": ("optional.txt", b"optional additional file", "text/plain")},
        data={"document_type": "additional"},
    )
    assert optional.status_code == 201, optional.text
    created = client.post(
        "/applicant/applications", headers=applicant,
        json={**APPLICATION, "document_ids": [required["id"], optional.json()["id"]]},
    )
    assert created.status_code == 201, created.text
    application_id = created.json()["id"]
    staff_path = f"/applicant/staff/applications/{application_id}"
    assert client.post(f"/applicant/applications/{application_id}/submit", headers=applicant).status_code == 200
    assert client.patch(f"{staff_path}/status", headers=staff, json={"status": "under_review"}).status_code == 200
    assert client.patch(
        f"{staff_path}/documents/{required['id']}", headers=staff, json={"status": "accepted"},
    ).status_code == 200

    queue_path = "/applicant/staff/documents"
    dashboard_path = "/applicant/staff/dashboard"
    pending = {"status": "pending"}
    assert [row["document_id"] for row in client.get(queue_path, headers=staff, params=pending).json()] == [
        optional.json()["id"],
    ]
    assert client.get(dashboard_path, headers=staff).json()["documents_awaiting_review"] == 1

    assert client.patch(f"{staff_path}/status", headers=staff, json={"status": "reviewed"}).status_code == 200
    assert client.get(queue_path, headers=staff, params=pending).json() == []
    assert client.get(dashboard_path, headers=staff).json()["documents_awaiting_review"] == 0
    assert len(client.get(queue_path, headers=staff).json()) == 2


@pytest.mark.parametrize("edit", ["application", "document_type"])
def test_edit_clears_current_review_but_keeps_history(client, edit):
    staff = staff_headers(client)
    applicant = auth_headers(client, "pending-audit-reset@example.com")
    _published_rules(client, staff)
    document_id = upload(client, applicant).json()["id"]
    application_id = _submitted_application(client, staff, applicant, document_id)
    staff_path = f"/applicant/staff/applications/{application_id}"
    applicant_path = f"/applicant/applications/{application_id}"

    assert client.patch(f"{staff_path}/status", headers=staff, json={"status": "under_review"}).status_code == 200
    decision = client.patch(
        f"{staff_path}/documents/{document_id}", headers=staff,
        json={"status": "changes_requested", "review_note": "Требуется читаемая копия"},
    )
    assert decision.json()["reviewer"] == "admissions-staff@example.com"
    assert client.patch(f"{staff_path}/status", headers=staff, json={"status": "needs_changes"}).status_code == 200
    if edit == "application":
        response = client.patch(applicant_path, headers=applicant, json={"program": "09.03.02"})
    else:
        response = client.patch(f"/applicant/documents/{document_id}/type", headers=applicant, json={"document_type": "passport"})
    assert response.status_code == 200, response.text

    detail = client.get(staff_path, headers=staff).json()
    assert detail["documents"][0]["reviewed_at"] is None
    assert detail["documents"][0]["reviewer"] is None
    assert "document_reviewed" in [item["status"] for item in detail["history"]]
    queue_path = "/applicant/staff/documents"
    assert client.get(queue_path, headers=staff, params={"status": "pending"}).json() == []
    pending_row = client.get(queue_path, headers=staff).json()[0]
    assert pending_row["review_status"] is None
    assert pending_row["review_note"] is None
    assert pending_row["reviewed_at"] is None
    assert pending_row["reviewer"] is None


def test_cannot_review_documents_outside_own_application(client):
    staff = staff_headers(client)
    _published_rules(client, staff)
    owner = auth_headers(client, "owner@example.com")
    stranger = auth_headers(client, "stranger@example.com")

    owner_doc = upload(client, owner).json()
    owner_app = _submitted_application(client, staff, owner, owner_doc["id"])
    client.patch(
        f"/applicant/staff/applications/{owner_app}/status", headers=staff, json={"status": "under_review"},
    )
    stranger_doc = upload(client, stranger).json()
    # The document must not be resolvable through an application that does not attach it.
    assert client.patch(
        f"/applicant/staff/applications/{owner_app}/documents/{stranger_doc['id']}",
        headers=staff, json={"status": "accepted"},
    ).status_code == 404
    assert client.get(
        f"/applicant/staff/applications/{owner_app}/documents/{stranger_doc['id']}/file",
        headers=staff,
    ).status_code == 404


def test_applicants_cannot_touch_staff_document_review(client):
    staff = staff_headers(client)
    _published_rules(client, staff)
    applicant = auth_headers(client, "review-blocked@example.com")
    document = upload(client, applicant).json()
    application_id = _submitted_application(client, staff, applicant, document["id"])
    client.patch(
        f"/applicant/staff/applications/{application_id}/status",
        headers=staff, json={"status": "under_review"},
    )
    assert client.get("/applicant/staff/documents", headers=applicant).status_code == 403
    assert client.patch(
        f"/applicant/staff/applications/{application_id}/documents/{document['id']}",
        headers=applicant, json={"status": "accepted"},
    ).status_code == 403
    assert client.get(
        f"/applicant/staff/applications/{application_id}/documents/{document['id']}/file",
        headers=applicant,
    ).status_code == 403
