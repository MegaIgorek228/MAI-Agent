import json
from datetime import date
from pathlib import Path

from app.admissions_schemas import SyntheticCandidateInput, SyntheticEgeInput
from app.db import SessionLocal
from app.synthetic_ege_registry import load_candidates, load_results
from test_applicant_features import auth_headers

APPLICATION = {"campaign_year": 2026, "program": "09.03.01", "admission_basis": "ЕГЭ"}
FIXTURE = Path(__file__).parents[1] / "backend" / "fixtures" / "synthetic_ege_registry.json"


def seed_registry(client):
    with SessionLocal() as db:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        people = load_candidates(
            db, [SyntheticCandidateInput.model_validate(item) for item in data["candidates"]]
        )
        results = load_results(
            db, [SyntheticEgeInput.model_validate(item) for item in data["results"]]
        )
    assert people == 10
    assert results == 30


def create_application(client, headers):
    created = client.post("/applicant/applications", headers=headers, json=APPLICATION)
    assert created.status_code == 201
    return created.json()["id"]


def search(client, headers, full_name, date_of_birth):
    return client.get(
        "/applicant/synthetic-ege/search",
        headers=headers,
        params={"full_name": full_name, "date_of_birth": date_of_birth},
    )


def test_fixture_shape_is_stable(client):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(data["candidates"]) == 10
    assert len(data["results"]) == 30
    assert all(item["candidate_id"].startswith("SYN-") for item in data["candidates"])
    assert all(item["candidate_id"].startswith("SYN-") for item in data["results"])
    # Every person in the reference registry is unique by full name + date of birth.
    identities = {(item["full_name"], item["date_of_birth"]) for item in data["candidates"]}
    assert len(identities) == 10
    # Each full name carries a patronymic: surname, first name, patronymic.
    assert all(len(item["full_name"].split()) == 3 for item in data["candidates"])


def test_loaders_are_idempotent_and_reject_conflicts(client):
    seed_registry(client)
    # Re-loading the same fixture changes nothing.
    with SessionLocal() as db:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert load_candidates(
            db, [SyntheticCandidateInput.model_validate(item) for item in data["candidates"]]
        ) == 0
        assert load_results(
            db, [SyntheticEgeInput.model_validate(item) for item in data["results"]]
        ) == 0
    # A conflicting identity for the same id is an error, not an overwrite.
    conflicting = SyntheticCandidateInput(
        candidate_id="SYN-1001", full_name="Чужой Человек", date_of_birth="2009-01-01"
    )
    try:
        with SessionLocal() as db:
            load_candidates(db, [conflicting])
        raise AssertionError("conflicting fixture must be rejected")
    except ValueError:
        pass
    with SessionLocal() as db:
        from app.models import SyntheticEgeCandidate

        person = db.get(SyntheticEgeCandidate, "SYN-1001")
        assert person.full_name == "Алексей Иванович Иванов"


def test_unique_match_found_case_and_whitespace_insensitive(client):
    seed_registry(client)
    headers = auth_headers(client)
    response = search(client, headers, "  алексей    иВАНОВИЧ   иВАНОВ ", "2008-03-14")
    assert response.status_code == 200
    body = response.json()
    assert body["match_count"] == 1
    assert body["ambiguous"] is False
    match = body["matches"][0]
    assert match["candidate_id"] == "SYN-1001"
    scores = {(item["subject"], item["year"]): item["score"] for item in match["results"]}
    assert scores[("русский язык", 2026)] == 88
    assert scores[("математика профильная", 2026)] == 92
    assert scores[("физика", 2026)] == 100


def test_no_match_is_reported(client):
    seed_registry(client)
    headers = auth_headers(client)
    body = search(client, headers, "Алексей Иванович Иванов", "2008-03-15").json()
    assert body["match_count"] == 0
    assert body["matches"] == []
    assert body["ambiguous"] is False


def test_ambiguous_match_is_reported_not_resolved(client):
    seed_registry(client)
    # The reference fixture keeps unique identities; the ambiguity case is
    # created directly in the test database (two distinct candidates, same
    # full name and date of birth).
    with SessionLocal() as db:
        from app.models import SyntheticEgeCandidate, SyntheticEgeResult

        db.add_all([
            SyntheticEgeCandidate(candidate_id="SYN-2001", full_name="Тест Тестов", date_of_birth=date(2005, 1, 1)),
            SyntheticEgeCandidate(candidate_id="SYN-2002", full_name="Тест Тестов", date_of_birth=date(2005, 1, 1)),
        ])
        db.add_all([
            SyntheticEgeResult(candidate_id="SYN-2001", subject="Русский язык", year=2025, score=70),
            SyntheticEgeResult(candidate_id="SYN-2002", subject="Русский язык", year=2025, score=85),
        ])
        db.commit()
    headers = auth_headers(client)
    body = search(client, headers, "Тест Тестов", "2005-01-01").json()
    assert body["match_count"] == 2
    assert body["ambiguous"] is True
    assert {match["candidate_id"] for match in body["matches"]} == {"SYN-2001", "SYN-2002"}


def test_confirm_binds_registry_scores_and_links_profile(client):
    seed_registry(client)
    headers = auth_headers(client)
    application_id = create_application(client, headers)

    confirmed = client.post(
        f"/applicant/applications/{application_id}/ege/synthetic-confirm",
        headers=headers,
        json={"candidate_id": "SYN-1002"},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["synthetic_candidate_id"] == "SYN-1002"
    scores = {(item["subject"], item["year"]): item["score"] for item in body["scores"]}
    assert scores[("русский язык", 2026)] == 94
    assert scores[("математика профильная", 2026)] == 85
    assert scores[("информатика", 2026)] == 90

    # Re-confirming is a no-op: same revision, same scores.
    again = client.post(
        f"/applicant/applications/{application_id}/ege/synthetic-confirm",
        headers=headers,
        json={"candidate_id": "SYN-1002"},
    ).json()
    assert again["scores"] == body["scores"]

    # The registry itself is untouched by the confirmation.
    with SessionLocal() as db:
        from app.models import Application, EgeScore

        application = db.get(Application, application_id)
        assert application.synthetic_candidate_id == "SYN-1002"
        assert application.scores_revision == 1
        declared = {
            (row.subject, row.year): row.score
            for row in db.query(EgeScore).filter_by(application_id=application_id)
        }
        assert declared == scores
        # Registry rows for a different candidate were not modified.
        from app.models import SyntheticEgeResult

        reference = {
            (row.candidate_id, row.subject, row.year): row.score
            for row in db.query(SyntheticEgeResult)
        }
        assert reference[("SYN-1001", "физика", 2026)] == 100


def test_confirm_rejects_unknown_candidate(client):
    seed_registry(client)
    headers = auth_headers(client)
    application_id = create_application(client, headers)
    unknown = client.post(
        f"/applicant/applications/{application_id}/ege/synthetic-confirm",
        headers=headers,
        json={"candidate_id": "SYN-9999"},
    )
    assert unknown.status_code == 404


def test_confirm_rejects_submitted_application(client):
    seed_registry(client)
    headers = auth_headers(client)
    application_id = create_application(client, headers)
    with SessionLocal() as db:
        from app.models import Application

        db.get(Application, application_id).status = "submitted"
        db.commit()
    blocked = client.post(
        f"/applicant/applications/{application_id}/ege/synthetic-confirm",
        headers=headers,
        json={"candidate_id": "SYN-1001"},
    )
    assert blocked.status_code == 409


def test_registry_has_no_write_routes(client):
    """The reference registry is immutable for applicants and agents."""
    from app.main import app

    schema = app.openapi()
    registry_routes = [
        path for path in schema["paths"]
        if "synthetic-ege" in path or "synthetic_ege" in path
    ]
    assert registry_routes, "registry search route missing"
    for path in registry_routes:
        methods = set(schema["paths"][path]) - {"parameters"}
        assert methods == {"get"}, f"registry route allows writes: {methods} {path}"
