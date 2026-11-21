from io import BytesIO

from docx import Document as WordDocument
from pypdf import PdfWriter
from sqlalchemy import select

from app.admissions_schemas import SyntheticEgeInput
from app.db import SessionLocal
from app.models import EgeVerification, SyntheticEgeResult, User, UserRole
from app.synthetic_ege_registry import load_results
from test_applicant_features import auth_headers

APPLICATION = {"campaign_year": 2026, "program": "09.03.01", "admission_basis": "ЕГЭ"}
RULES = {
    **APPLICATION,
    "source_url": "https://priem.mai.ru/",
    "document_requirements": [{"document_type": "identity", "title": "Удостоверение"}],
    "subject_minima": {"Математика": 60},
}


def staff_headers(client):
    email = "admissions-staff@example.com"
    headers = auth_headers(client, email)
    with SessionLocal() as db:
        staff = db.scalar(select(User).where(User.email == email))
        staff.role = UserRole.admissions_staff.value
        db.commit()
    return headers


def upload(client, headers, *, name="identity.txt", content=b"synthetic", content_type="text/plain"):
    return client.post(
        "/applicant/documents", headers=headers,
        files={"file": (name, content, content_type)},
        data={"document_type": "identity"},
    )


def test_document_form_extractors_and_missing_applicable_requirements(client):
    applicant = auth_headers(client)
    staff = staff_headers(client)
    rule = client.post("/knowledge/admission-requirements", headers=staff, json={
        "document_type": "identity", "title": "Удостоверение", "target_program": "09.03.01",
    })
    assert rule.status_code == 201
    assert client.get("/applicant/documents/completeness", headers=applicant).json()["status"] == "needs_profile"
    client.put("/applicant/profile", headers=applicant, json={"target_program": "10.03.01"})
    result = client.get("/applicant/documents/completeness", headers=applicant).json()
    assert result["status"] == "needs_admission_requirements"

    assert upload(client, applicant).json()["document_type"] == "identity"
    malformed = upload(
        client, applicant, name="bad.pdf", content_type="application/pdf", content=b"not a pdf",
    )
    assert malformed.status_code == 422
    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=144, height=144)
    writer.write(pdf)
    scan = upload(
        client, applicant, name="blank.pdf", content_type="application/pdf", content=pdf.getvalue(),
    ).json()
    assert scan["status"] == "needs_manual_review"
    assert scan["extracted_text"] is None
    client.put("/applicant/profile", headers=applicant, json={"target_program": "09.03.01"})
    pending = client.get("/applicant/documents/completeness", headers=applicant).json()
    assert pending["status"] == "needs_manual_review"
    assert pending["pending_documents"][0]["document_type"] == "identity"

    word = WordDocument()
    word.add_table(rows=1, cols=1).cell(0, 0).text = "Синтетическое поле"
    contents = BytesIO()
    word.save(contents)
    table_doc = upload(
        client, applicant, name="table.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=contents.getvalue(),
    ).json()
    assert table_doc["extracted_text"] == "Синтетическое поле"
    renamed = client.patch(f"/applicant/documents/{table_doc['id']}/type", headers=applicant,
                           json={"document_type": "education"})
    assert renamed.json()["document_type"] == "education"


def test_application_staff_review_and_pinned_rules(client):
    staff = staff_headers(client)
    headers = auth_headers(client)
    other = auth_headers(client, "other-applicant@example.com")
    created_rule = client.post("/applicant/staff/admission-rules", headers=staff, json=RULES)
    assert created_rule.status_code == 201, created_rule.text
    assert created_rule.json()["revision"] == 1
    document = upload(client, headers).json()
    create = client.post(
        "/applicant/applications", headers=headers, json={**APPLICATION, "document_ids": [document["id"]]},
    )
    assert create.status_code == 201, create.text
    application_id = create.json()["id"]
    applicant_path = f"/applicant/applications/{application_id}"
    staff_path = f"/applicant/staff/applications/{application_id}"
    assert client.get(applicant_path, headers=other).status_code == 404
    assert client.get(staff_path, headers=staff).status_code == 404
    assert client.post(f"{applicant_path}/submit", headers=headers).json()["status"] == "submitted"
    assert client.post(f"{applicant_path}/submit", headers=headers).status_code == 200
    assert client.patch(applicant_path, headers=headers, json={"program": "09.03.02"}).status_code == 409
    second_rule = client.post(
        "/applicant/staff/admission-rules", headers=staff, json={**RULES, "subject_minima": {"math": 65}},
    )
    assert second_rule.json()["revision"] == 2
    assert client.get("/applicant/admission-rules", headers=headers).json()[0]["revision"] == 2
    assert client.get(f"{applicant_path}/requirements", headers=headers).json()["rules"]["revision"] == 1

    assert client.patch(f"{staff_path}/status", headers=staff, json={"status": "under_review"}).status_code == 200
    assert client.patch(f"{staff_path}/status", headers=staff, json={"status": "reviewed"}).status_code == 409
    doc_path = f"{staff_path}/documents/{document['id']}"
    downloaded = client.get(f"{doc_path}/file", headers=staff)
    assert downloaded.content == b"synthetic"
    assert client.patch(doc_path, headers=staff, json={"status": "rejected", "review_note": "Переделать"}).status_code == 200
    own_docs = client.get(f"{applicant_path}/documents", headers=headers).json()
    assert own_docs[0]["status"] == "rejected"
    assert own_docs[0]["review_message"] == "Переделать"
    assert client.patch(doc_path, headers=staff, json={"status": "accepted"}).status_code == 200
    assert client.patch(f"{staff_path}/status", headers=staff, json={"status": "reviewed"}).status_code == 200
    queue = client.get("/applicant/staff/applications", headers=staff, params={"status": "reviewed", "q": "09.03"})
    assert [item["id"] for item in queue.json()] == [application_id]
    application = client.get(staff_path, headers=staff).json()
    assert application["requirements"]["documents"]["status"] == "complete"
    assert [event["status"] for event in application["history"]] == ["draft", "submitted", "under_review", "reviewed"]


def test_synthetic_ege_separate_from_declared_scores_and_rules(client):
    staff = staff_headers(client)
    headers = auth_headers(client)
    assert client.post("/applicant/staff/admission-rules", headers=staff, json=RULES).status_code == 201
    application_id = client.post("/applicant/applications", headers=headers, json=APPLICATION).json()["id"]
    base = f"/applicant/applications/{application_id}"
    ege = f"{base}/ege"
    payload = {
        "scores": [{"subject": "Математика", "year": 2025, "score": 50}],
        "synthetic_candidate_id": "SYN-TEST",
    }
    assert client.put(ege, headers=headers, json=payload).status_code == 200
    assert client.post(f"{ege}/verify", headers=headers).json()["verification"]["status"] == "not_found"

    sample = SyntheticEgeInput(candidate_id="SYN-TEST", subject="математика", year=2025, score=75)
    with SessionLocal() as db:
        assert load_results(db, [sample]) == 1
        assert load_results(db, [sample]) == 0
    checked = client.post(f"{ege}/verify", headers=headers).json()
    assert checked["verification"]["source"] == "synthetic"
    assert checked["verification"]["status"] == "mismatch"
    assert checked["scores"][0]["score"] == 50
    assert client.post(f"{ege}/verify", headers=headers).json() == checked
    ege_requirements = client.get(f"{base}/requirements", headers=headers).json()["ege"]
    assert ege_requirements == {
        "status": "below_minimum", "missing_subjects": [],
        "below_minimum": [{"subject": "математика", "score": 50, "minimum": 60}],
    }
    payload["scores"][0]["score"] = 75
    assert client.put(ege, headers=headers, json=payload).json()["verification"] is None
    assert client.post(f"{ege}/verify", headers=headers).json()["verification"]["status"] == "match"
    with SessionLocal() as db:
        assert db.get(SyntheticEgeResult, ("SYN-TEST", "математика", 2025)).score == 75
        assert len(list(db.scalars(select(EgeVerification)))) == 3
