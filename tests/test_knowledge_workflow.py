import asyncio

import httpx
from app import knowledge_service
from app.db import SessionLocal
from app.embedding_service import EmbeddingProviderUnavailable
from app.mcp_tools import mcp
from app.models import KnowledgeChunk, User, UserRole
from app.official_materials import extract_html_content
from app.security import create_access_token, create_trusted_context, hash_password
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from sqlalchemy import select


def actor_credentials(role: UserRole, email: str) -> tuple[dict[str, str], str]:
    with SessionLocal() as db:
        user = User(email=email, password_hash=hash_password("example-test-password"), role=role.value)
        db.add(user)
        db.commit()
        return {"Authorization": f"Bearer {create_access_token(user)}"}, create_trusted_context(user, "test-mcp-session")


def test_search_returns_edition_and_finds_russian_inflections(client):
    headers, _ = actor_credentials(UserRole.admissions_staff, "k-staff@example.com")
    payload = {
        "url": "https://priem.mai.ru/example",
        "title": "Правила приёма",
        "text": "Минимальные баллы по математике приведены в таблице.",
    }
    assert client.post("/knowledge/sources", json=payload, headers=headers).status_code == 200
    payload["title"] = "Правила испытательной кампании"
    updated = client.post("/knowledge/sources", json=payload, headers=headers).json()
    assert updated["title"] == payload["title"]
    search = client.post("/knowledge/search", json={"query": "Какой минимум минимальных баллов?"}).json()
    assert len(search) == 1
    assert search[0]["source_url"] == payload["url"]
    assert search[0]["source_title"] == payload["title"]
    assert search[0]["source_content_hash"] == updated["content_hash"]
    assert search[0]["source_updated_at"]
    assert search[0]["match_type"] == "lexical"
    assert client.post("/knowledge/search", json={"query": "метеорология"}).json() == []


def test_reindex_after_unavailable_provider_without_reimporting_text(client, monkeypatch):
    headers, _ = actor_credentials(UserRole.admissions_staff, "reindex@example.com")
    monkeypatch.setattr(knowledge_service, "embeddings_configured", lambda: True)

    def unavailable(texts):
        raise EmbeddingProviderUnavailable("test provider unavailable")

    monkeypatch.setattr(knowledge_service, "embed_texts", unavailable)
    indexed = client.post(
        "/knowledge/sources",
        headers=headers,
        json={"url": "https://priem.mai.ru/another", "title": "Приём", "text": "Синтетический справочник."},
    ).json()
    assert indexed["search_mode"] == "lexical"

    monkeypatch.setattr(knowledge_service, "embed_texts", lambda texts: [[1.0] * 1024 for _ in texts])
    response = client.post(f"/knowledge/sources/{indexed['id']}/reindex", headers=headers)
    assert response.status_code == 200
    assert response.json()["search_mode"] == "hybrid"
    with SessionLocal() as db:
        chunk = db.scalar(select(KnowledgeChunk).where(KnowledgeChunk.source_id == indexed["id"]))
        assert chunk.embedding_model
        assert len(chunk.embedding) == 1024
        assert db.scalar(select(KnowledgeChunk.content)) == "Синтетический справочник."


def test_sync_reports_each_source_in_a_partially_finished_batch(client, monkeypatch):
    headers, _ = actor_credentials(UserRole.admissions_staff, "sync@example.com")
    unavailable = "https://priem.mai.ru/unavailable"
    available = "https://priem.mai.ru/available"

    def fetch(url):
        if url == unavailable:
            raise ValueError("Test source is unavailable")
        return url, "Синтетический источник", "Данные о приёме."

    monkeypatch.setattr("app.routers.knowledge.fetch_official_material", fetch)
    response = client.post("/knowledge/sources/sync", headers=headers, json={"urls": [unavailable, available]})
    assert response.status_code == 200
    assert [(result["url"], result["status"]) for result in response.json()] == [
        (unavailable, "failed"),
        (available, "synced"),
    ]
    assert client.post("/knowledge/search", json={"query": "данные"}).json()[0]["source_url"] == available


def test_official_html_keeps_table_columns_and_rows():
    title, content = extract_html_content(
        """<html><head><title>Баллы</title></head><body>
        <nav>Убрать меню</nav><h1>Кампания 2026</h1><table>
        <tr><th>Код</th><th>Проходной балл</th></tr>
        <tr>
          <td>01.03.02</td><td><span>200</span></td>
        </tr></table></body></html>"""
    )
    assert title == "Баллы"
    assert content.splitlines() == ["Кампания 2026", "Код | Проходной балл", "01.03.02 | 200"]


def test_mcp_http_uses_backend_profile_and_application_workflow():
    _, actor_token = actor_credentials(UserRole.applicant, "mcp-applicant@example.com")

    async def run():
        http_app = mcp.http_app(path="/mcp", json_response=True, stateless_http=True)
        transport = StreamableHttpTransport(
            "http://mcp.test/mcp",
            headers={"X-MAI-Context": actor_token},
            httpx_client_factory=lambda **kwargs: httpx.AsyncClient(
                transport=httpx.ASGITransport(app=http_app), **kwargs,
            ),
        )
        async with http_app.lifespan(http_app), Client(transport) as mcp_client:
            updated = await mcp_client.call_tool("update_applicant_profile", {"payload": {"first_name": "Иван"}})
            assert updated.data["first_name"] == "Иван"
            assert (await mcp_client.call_tool("get_applicant_profile")).data["first_name"] == "Иван"
            created = await mcp_client.call_tool("create_applicant_application", {
                "payload": {"campaign_year": 2026, "program": "01.03.02", "admission_basis": "Общий конкурс"},
            })
            assert created.data["status"] == "draft"
            application_id = created.data["id"]
            result = await mcp_client.call_tool("update_application_ege_scores", {
                "application_id": application_id,
                "payload": {
                    "synthetic_candidate_id": "SYN-TEST",
                    "scores": [{"subject": "Математика", "year": 2026, "score": 83}],
                },
            })
            assert result.data["scores"][0]["score"] == 83
            verification = await mcp_client.call_tool("verify_application_synthetic_ege", {"application_id": application_id})
            assert verification.data["verification"]["status"] == "not_found"
            assert verification.data["verification"]["source"] == "synthetic"
            assert (await mcp_client.call_tool("get_application_ege_scores", {
                "application_id": application_id,
            })).data["scores"][0]["score"] == 83

    asyncio.run(run())
