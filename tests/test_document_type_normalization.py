"""Document type normalization: Russian titles in the UI, machine codes in storage."""

from test_admissions_workflow import staff_headers
from test_applicant_features import auth_headers

BASE = {"campaign_year": 2026, "program": "01.03.02", "admission_basis": "Бюджетные места"}


def publish_rules(client, staff, requirements, minima=None):
    payload = {
        **BASE,
        "source_url": "https://priem.mai.ru/",
        "document_requirements": requirements,
        "subject_minima": minima or {},
    }
    response = client.post("/applicant/staff/admission-rules", headers=staff, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, headers, document_type):
    return client.post(
        "/applicant/documents", headers=headers,
        files={"file": ("scan.txt", b"synthetic", "text/plain")},
        data={"document_type": document_type},
    )


def test_upload_stores_rule_code_for_russian_title(client):
    applicant = auth_headers(client)
    staff = staff_headers(client)
    publish_rules(client, staff, [
        {"document_type": "passport", "title": "Паспорт"},
        {"document_type": "education", "title": "Документ об образовании"},
    ])
    assert upload(client, applicant, "Паспорт").json()["document_type"] == "passport"
    assert (
        upload(client, applicant, "Документ об образовании").json()["document_type"]
        == "education"
    )


def test_upload_accepts_case_insensitive_code(client):
    applicant = auth_headers(client)
    staff = staff_headers(client)
    publish_rules(client, staff, [{"document_type": "passport", "title": "Паспорт"}])
    assert upload(client, applicant, "PASSPORT").json()["document_type"] == "passport"
    assert upload(client, applicant, "Passport").json()["document_type"] == "passport"


def test_upload_keeps_unknown_type_without_rules(client):
    applicant = auth_headers(client)
    assert upload(client, applicant, "СНИЛС").json()["document_type"] == "СНИЛС"


def test_common_russian_names_map_to_codes_without_rules(client):
    applicant = auth_headers(client)
    assert upload(client, applicant, "Аттестат").json()["document_type"] == "education"
    assert upload(client, applicant, "паспорт").json()["document_type"] == "passport"


def test_evidence_type_is_not_touched(client):
    applicant = auth_headers(client)
    assert upload(client, applicant, "evidence").json()["document_type"] == "evidence"


def test_update_type_normalizes(client):
    applicant = auth_headers(client)
    staff = staff_headers(client)
    publish_rules(client, staff, [
        {"document_type": "passport", "title": "Паспорт"},
        {"document_type": "education", "title": "Документ об образовании"},
    ])
    created = upload(client, applicant, "Паспорт")
    assert created.status_code == 201
    document_id = created.json()["id"]

    updated = client.patch(
        f"/applicant/documents/{document_id}/type", headers=applicant,
        json={"document_type": "Документ об образовании"},
    )
    assert updated.status_code == 200
    assert updated.json()["document_type"] == "education"

    unknown = client.patch(
        f"/applicant/documents/{document_id}/type", headers=applicant,
        json={"document_type": "СНИЛС"},
    )
    assert unknown.status_code == 200
    assert unknown.json()["document_type"] == "СНИЛС"


def test_requirements_count_normalized_types(client):
    """End-to-end: a document uploaded with a Russian title satisfies the rule."""
    applicant = auth_headers(client)
    staff = staff_headers(client)
    publish_rules(client, staff, [
        {"document_type": "passport", "title": "Паспорт"},
        {"document_type": "education", "title": "Документ об образовании"},
    ])
    created = client.post("/applicant/applications", headers=applicant, json={**BASE})
    assert created.status_code == 201, created.text
    application_id = created.json()["id"]

    passport = upload(client, applicant, "Паспорт").json()
    education = upload(client, applicant, "Аттестат").json()
    saved = client.patch(
        f"/applicant/applications/{application_id}", headers=applicant,
        json={"document_ids": [passport["id"], education["id"]]},
    )
    assert saved.status_code == 200, saved.text

    requirements = client.get(
        f"/applicant/applications/{application_id}/requirements", headers=applicant
    ).json()
    documents = requirements["documents"]
    assert documents["missing_documents"] == []
    assert sorted(item["document_type"] for item in documents["pending_documents"]) == [
        "education", "passport"
    ]
