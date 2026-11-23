"""End-to-end test for the minimal MAI-Agent architecture.

Exercises the full chain Web API -> Backend -> ACP -> Hermes Agent:
plain chat, history, image analysis (native vision), file read/write,
terminal execution, the SQL MCP tool, the synthetic ФИС ГИА MCP tool,
native Hermes toolsets, and per-user session isolation.

Usage (needs the docker stack running on the default ports):
    python scripts/e2e_minimal_agent.py [base_url]
"""

from __future__ import annotations

import json
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
REQUEST_TIMEOUT = 900  # Hermes replies with tool calls can be slow

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail[:400]})
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail[:300]}" if detail and not ok else ""), flush=True)


def request(method: str, path: str, token: str | None = None, json_body: dict | None = None,
            raw_body: bytes | None = None, content_type: str | None = None) -> tuple[int, dict]:
    url = BASE + path
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw_body is not None:
        body = raw_body
        if content_type:
            headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read()
            return resp.status, (json.loads(data) if data else {})
    except urllib.error.HTTPError as exc:
        data = exc.read()
        try:
            return exc.code, json.loads(data)
        except Exception:
            return exc.code, {"raw": data[:500].decode("utf-8", "replace")}


def register_login(email: str, password: str) -> str:
    status, _ = request("POST", "/auth/register", json_body={"email": email, "password": password})
    if status not in (200, 201, 409):
        raise RuntimeError(f"register failed: {status}")
    status, body = request("POST", "/auth/login", json_body={"email": email, "password": password})
    if status != 200:
        raise RuntimeError(f"login failed: {status} {body}")
    return body["access_token"]


def chat(token: str, session_id: int, content: str, image_document_id: int | None = None) -> dict:
    status, body = request(
        "POST", f"/chat/sessions/{session_id}/messages", token,
        json_body={"content": content, "image_document_id": image_document_id},
    )
    if status != 200:
        raise RuntimeError(f"chat message failed: {status} {body}")
    return body


def make_png() -> bytes:
    """240x160 RGB PNG: white background, blue rectangle, red circle."""
    width, height = 240, 160
    rows = []
    for y in range(height):
        row = bytearray([0])  # filter byte 0
        for x in range(width):
            if 20 <= x <= 120 and 40 <= y <= 120:
                row += b"\x1e\x5a\xc8"  # blue rectangle
            elif (x - 180) ** 2 + (y - 80) ** 2 <= 40 * 40:
                row += b"\xdc\x28\x28"  # red circle
            else:
                row += b"\xff\xff\xff"
        rows.append(bytes(row))
    raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw, 9)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def upload_image(token: str, png: bytes) -> int:
    boundary = f"----maie2e{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="e2e-image.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode("ascii")
    tail = (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="document_type"\r\n\r\n'
        f"image\r\n--{boundary}--\r\n"
    ).encode("ascii")
    status, body = request(
        "POST", "/applicant/documents", token,
        raw_body=head + png + tail,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    if status not in (200, 201):
        raise RuntimeError(f"image upload failed: {status} {body}")
    return body["id"]


def main() -> int:
    stamp = int(time.time())
    email_a = f"e2e-min-{stamp}@mai-agent.io"
    email_b = f"e2e-min-b-{stamp}@mai-agent.io"
    token_a = register_login(email_a, "Password123!")
    check("register + login (web user)", True)

    status, session = request("POST", "/chat/sessions", token_a, json_body={})
    check("create chat session", status in (200, 201), f"{status} {session}")
    session_id = session["id"]
    hermes_session_a = session.get("hermes_session_id")

    # 1. Plain message and reply.
    reply = chat(token_a, session_id, "Напиши ровно одну строку: MAI_E2E_OK")
    check("plain message -> agent reply", "MAI_E2E_OK" in reply.get("content", ""), str(reply)[:200])

    # 2. History is stored and can be restored through the API.
    status, messages = request("GET", f"/chat/sessions/{session_id}/messages", token_a)
    roles = [m.get("role") for m in messages]
    check("history: user + assistant messages stored",
          status == 200 and "user" in roles and "assistant" in roles, str(roles))
    status, sessions = request("GET", "/chat/sessions", token_a)
    check("history: session listed", status == 200 and any(s.get("id") == session_id for s in sessions), str(sessions)[:200])

    # 3. Image upload + native vision analysis.
    doc_id = upload_image(token_a, make_png())
    check("image uploaded", doc_id > 0, str(doc_id))
    reply = chat(token_a, session_id, "Опиши коротко это изображение: какие фигуры и цвета на нём?", doc_id)
    text = reply.get("content", "").casefold()
    keywords = ("син", "красн", "круг", "прямоуг", "blue", "red", "circle", "rectangle")
    check("image analysed by agent", len(text) > 20 and any(k in text for k in keywords), str(reply)[:250])

    # 4. File create + read (native file tools).
    reply = chat(token_a, session_id,
                 "Создай текстовый файл e2e_note.txt в твоей рабочей директории с содержимым HELLO_FROM_AGENT. "
                 "Затем прочитай этот файл и процитируй его содержимое в ответе.")
    check("file create + read via native tools", "HELLO_FROM_AGENT" in reply.get("content", ""), str(reply)[:250])

    # 5. Terminal command execution.
    reply = chat(token_a, session_id,
                 "Выполни в терминале команду: echo MAI_TERM_OK. Ответь только точным выводом команды.")
    check("terminal command executed", "MAI_TERM_OK" in reply.get("content", ""), str(reply)[:250])

    # 6. SQL data source via the sql_query MCP tool.
    reply = chat(token_a, session_id,
                 "Используй MCP-инструмент sql_query, чтобы посчитать количество строк в таблице "
                 "synthetic_ege_results. Ответь только количеством строк.")
    check("SQL source queried via MCP", re.search(r"\b30\b", reply.get("content", "")) is not None, str(reply)[:250])

    # 7. Synthetic ФИС ГИА via the existing MCP registry tool.
    reply = chat(token_a, session_id,
                 "Найди в синтетическом реестре ЕГЭ участника «Алексей Иванович Иванов» "
                 "(дата рождения 14.03.2008) и назови его результаты ЕГЭ 2026 по каждому предмету.")
    scores = [s for s in ("92", "88", "100") if re.search(rf"\b{s}\b", reply.get("content", ""))]
    check("ФИС ГИА registry queried via MCP", len(scores) >= 2, f"scores seen: {scores} :: {str(reply)[:250]}")

    # 8. Native Hermes toolsets (terminal / file / memory) visible to the agent.
    reply = chat(token_a, session_id,
                 "Перечисли имена всех твоих доступных инструментов (tool names) через запятую. "
                 "Только список имён, без пояснений.")
    tools_text = reply.get("content", "").casefold()
    check("native tools visible: terminal", "terminal" in tools_text, str(reply)[:250])
    check("native tools visible: files", bool(re.search(r"read|write|file", tools_text)), str(reply)[:250])
    check("native tools visible: memory/session", bool(re.search(r"memor|session", tools_text)), str(reply)[:250])

    # 9. Session isolation: a second user gets a separate agent session.
    token_b = register_login(email_b, "Password123!")
    status, sessions_b = request("GET", "/chat/sessions", token_b)
    check("second user: no inherited sessions",
          status == 200 and len(sessions_b) == 0, str(sessions_b)[:200])
    status, session_b = request("POST", "/chat/sessions", token_b, json_body={})
    hermes_session_b = session_b.get("hermes_session_id")
    check("second user: separate Hermes session",
          status in (200, 201) and hermes_session_b and hermes_session_b != hermes_session_a,
          f"a={hermes_session_a} b={hermes_session_b}")
    status, sessions_a = request("GET", "/chat/sessions", token_a)
    check("first user: history untouched by second user",
          status == 200 and any(s.get("id") == session_id for s in sessions_a), str(sessions_a)[:200])

    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    print("accounts to clean up: " + ", ".join((email_a, email_b)))
    out = sys.argv[2] if len(sys.argv) > 2 else None
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"base": BASE, "results": RESULTS}, fh, ensure_ascii=False, indent=2)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
