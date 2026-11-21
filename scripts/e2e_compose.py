"""Compose E2E: all app scenarios against the Docker Compose stack
(backend:8000 + postgres + real hermes-acp in the backend container).
"""
import base64
import io
import json
import os
import subprocess
import sys
import time

import httpx
from PIL import Image

BASE = "http://127.0.0.1:8000"
TS = int(time.time())
RESULTS = {}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def section(name):
    log(f"=== {name} ===")


def wait_backend():
    for _ in range(240):
        try:
            if httpx.get(f"{BASE}/health", timeout=2).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("backend not healthy after 480s")


def create_admin_user():
    """Create an administrator user inside the backend container (test user)."""
    email = f"e2e-admin-{TS}@example.com"
    password = "admin-e2e-password-1"
    code = (
        "import sys; sys.path.insert(0, '/app')\n"
        "from app.db import SessionLocal\n"
        "from app.models import User, UserRole\n"
        "from app.security import hash_password\n"
        f"db = SessionLocal()\n"
        f"u = User(email={email!r}, password_hash=hash_password({password!r}), role=UserRole.administrator.value, is_active=True)\n"
        "db.add(u); db.commit(); db.refresh(u); print(u.id); db.close()\n"
    )
    out = subprocess.run(
        ["docker", "exec", "mai-agent-backend-1", "python", "-c", code],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"admin user creation failed: {out.stderr[:400]}")
    log(f"admin user created: {email} (id={out.stdout.strip()})")
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    return email, r.json()["access_token"]


def register_applicant(email):
    r = httpx.post(f"{BASE}/auth/register", json={"email": email, "password": "applicant-e2e-pw-1"}, timeout=30)
    assert r.status_code == 201, r.text
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": "applicant-e2e-pw-1"}, timeout=30)
    return r.json()["access_token"]


def main():
    c = httpx.Client(timeout=600)
    wait_backend()
    log("backend healthy")

    # 1. Registration + auth
    section("1. REGISTRATION + AUTH")
    applicant_email = f"e2e-applicant-{TS}@example.com"
    applicant = register_applicant(applicant_email)
    r = c.get(f"{BASE}/users/me", headers={"Authorization": f"Bearer {applicant}"})
    assert r.status_code == 200 and r.json()["email"] == applicant_email, r.text
    log(f"registered + /users/me OK ({applicant_email})")
    RESULTS["1_auth"] = "PASS"

    # 2. Roles
    section("2. ROLE ENFORCEMENT")
    r = c.get(f"{BASE}/applicant/staff/applicants", headers={"Authorization": f"Bearer {applicant}"})
    assert r.status_code == 403, f"applicant must be 403 on staff API, got {r.status_code}"
    log("applicant -> /applicant/staff/applicants: 403 (correct)")
    admin_email, admin = create_admin_user()
    r = c.get(f"{BASE}/applicant/staff/applicants", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200, r.text
    staff_emails = [x["email"] for x in r.json()]
    assert applicant_email in staff_emails
    log(f"admin -> staff list OK ({len(staff_emails)} applicants)")
    RESULTS["2_roles"] = "PASS"
    H_A = {"Authorization": f"Bearer {applicant}"}
    H_S = {"Authorization": f"Bearer {admin}"}

    # 3. Applicant profile
    section("3. APPLICANT PROFILE")
    r = c.put(f"{BASE}/applicant/profile", headers=H_A, json={
        "first_name": "E2E", "last_name": "Applicant", "phone": "+70000000000",
        "target_program": "Баллистика и баллистика", "admission_basis": "ЕГЭ",
    })
    assert r.status_code == 200, r.text
    r = c.get(f"{BASE}/applicant/profile", headers=H_A)
    assert r.status_code == 200 and r.json()["first_name"] == "E2E"
    log("profile PUT + GET OK")
    RESULTS["3_profile"] = "PASS"

    # 4. Documents
    section("4. DOCUMENTS")
    png = io.BytesIO()
    img = Image.new("RGB", (480, 320), "white")
    # red circle left, blue rectangle right (ground truth for the vision check)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    d.ellipse([45, 75, 215, 245], fill="red")
    d.rectangle([300, 60, 440, 260], fill="blue")
    img.save(png, format="PNG")
    png = png.getvalue()
    r = c.post(f"{BASE}/applicant/documents", headers=H_A,
               files={"file": ("e2e_scene.png", io.BytesIO(png), "image/png")},
               data={"document_type": "image"})
    assert r.status_code == 201, r.text
    image_doc_id = r.json()["id"]
    r = c.post(f"{BASE}/applicant/documents", headers=H_A,
               files={"file": ("note.txt", b"test text document", "text/plain")},
               data={"document_type": "unspecified"})
    assert r.status_code == 201, r.text
    r = c.get(f"{BASE}/applicant/documents", headers=H_A)
    assert r.status_code == 200 and len(r.json()) == 2
    log(f"uploaded image (id={image_doc_id}) + text doc; list OK")
    RESULTS["4_documents"] = "PASS"

    # 5. Text chat through the REAL in-container hermes-acp -> Qwen via MAI
    section("5. TEXT CHAT (real ACP + Qwen)")
    t0 = time.time()
    r = c.post(f"{BASE}/chat/sessions", headers=H_A, json={"channel": "web"})
    assert r.status_code == 201, f"session start failed: {r.status_code} {r.text[:300]}"
    session_id = r.json()["id"]
    hermes_sid = r.json()["hermes_session_id"]
    log(f"session created in {time.time()-t0:.1f}s (hermes={hermes_sid})")
    t0 = time.time()
    r = c.post(f"{BASE}/chat/sessions/{session_id}/messages", headers=H_A,
               json={"content": "Ответь одним словом: ОК"})
    dt = time.time() - t0
    assert r.status_code == 200, f"text chat failed: {r.status_code} {r.text[:300]}"
    answer = r.json()["content"]
    log(f"text answer in {dt:.1f}s: {answer[:120]!r}")
    assert "ОК" in answer.upper() or "ок" in answer.lower()
    RESULTS["5_text_chat"] = "PASS"

    # 6. Image analysis through ACP + Qwen
    section("6. IMAGE ANALYSIS (real ACP + Qwen)")
    t0 = time.time()
    r = c.post(f"{BASE}/chat/sessions/{session_id}/messages", headers=H_A,
               json={"content": "Опиши, что на изображении: какие фигуры, их цвета и где они расположены.",
                     "image_document_id": image_doc_id})
    dt = time.time() - t0
    assert r.status_code == 200, f"image chat failed: {r.status_code} {r.text[:300]}"
    answer = r.json()["content"]
    log(f"image answer in {dt:.1f}s:\n{answer[:600]}")
    ok = ("круг" in answer.lower() and "красн" in answer.lower()
          and ("квадрат" in answer.lower() or "прямоугольн" in answer.lower()) and "син" in answer.lower())
    log(f"vision assertions (red circle + blue rect): {'PASS' if ok else 'FAIL'}")
    RESULTS["6_image"] = "PASS" if ok else "FAIL"

    # 7. History: image link survives, file endpoint works
    section("7. HISTORY + IMAGE ACCESS")
    r = c.get(f"{BASE}/chat/sessions/{session_id}/messages", headers=H_A)
    assert r.status_code == 200
    msgs = r.json()
    user_img_msg = [m for m in msgs if m["role"] == "user" and m.get("image_document_id")]
    assert len(user_img_msg) == 1 and user_img_msg[0]["image_document_id"] == image_doc_id
    assert user_img_msg[0]["image_filename"] == "e2e_scene.png"
    log(f"history: {len(msgs)} messages, user image message linked to doc {image_doc_id}")
    r = c.get(f"{BASE}/applicant/documents/{image_doc_id}/file?access_token={applicant}")
    assert r.status_code == 200 and r.content == png and r.headers["content-type"].startswith("image/png")
    log("file endpoint via access_token query: bytes identical, content-type ok")
    RESULTS["7_history"] = "PASS"

    # 8. Knowledge base search (pgvector + MAI embeddings)
    section("8. KNOWLEDGE SEARCH")
    source_text = (
        "Правила приёма 2026: абитуриенты поступают на основании результатов ЕГЭ. "
        "Для направления Баллистика минимальный проходной балл по профильной математике — 70. "
        "Документы подаются в приёмную комиссию до 20 июля."
    )
    r = c.post(f"{BASE}/knowledge/sources", headers=H_S, json={
        "url": "https://priem.mai.ru/rules-2026", "title": "Правила приёма 2026", "text": source_text,
    })
    assert r.status_code == 200, f"knowledge source failed: {r.status_code} {r.text[:300]}"
    log(f"knowledge source created: {r.json()}")
    r = c.post(f"{BASE}/knowledge/search", headers=H_S, json={"query": "Какой минимальный балл по математике?", "limit": 3})
    assert r.status_code == 200, f"search failed: {r.status_code} {r.text[:300]}"
    chunks = r.json()
    log(f"search returned {len(chunks)} chunk(s): {str(chunks[:1])[:200]}")
    RESULTS["8_knowledge"] = "PASS" if chunks else "FAIL"

    # 9. Staff workspace
    section("9. STAFF WORKSPACE")
    r = c.get(f"{BASE}/applicant/staff/applicants", headers=H_S)
    assert r.status_code == 200
    applicants_list = r.json()
    assert any(a["email"] == applicant_email for a in applicants_list)
    log(f"staff sees {len(applicants_list)} applicant(s), incl. the E2E one")
    RESULTS["9_staff"] = "PASS"

    # Telegram: check backend logs for polling start + absence of errors
    section("TELEGRAM (polling design)")
    out = subprocess.run(["docker", "logs", "mai-agent-backend-1"], capture_output=True, text=True).stdout
    tg_lines = [l for l in out.splitlines() if "elegram" in l or "olling" in l]
    log("telegram/polling-related backend log lines:")
    for l in tg_lines[-8:]:
        log("  " + l[:200])
    RESULTS["telegram_logs"] = "\n".join(tg_lines[-8:]) or "(no telegram log lines)"

    with open(os.path.join(os.path.dirname(__file__), "e2e_compose_result.json"), "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)
    passed = [k for k, v in RESULTS.items() if v == "PASS"]
    failed = [k for k, v in RESULTS.items() if v == "FAIL"]
    log(f"OVERALL: {len(passed)} PASS, {len(failed)} FAIL {failed if failed else ''}")
    for k, v in RESULTS.items():
        log(f"  {k}: {v if isinstance(v, str) and len(str(v)) < 80 else str(v)[:80]}")
    log("E2E DONE")


if __name__ == "__main__":
    main()
