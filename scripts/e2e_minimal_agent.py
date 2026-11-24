"""End-to-end test for the sessionless MAI-Agent architecture.

Exercises the full chain Web API -> Backend -> ACP -> Hermes Agent:
session create, plain chat, history, context continuation, image
analysis (native vision), file read/write, terminal execution, SQL MCP
tool, synthetic ФИС ГИА MCP tool, native Hermes toolsets, and
cross-session isolation. No accounts, no tokens: the client is
identified by the session UUID.

Usage (needs the docker stack running on the default ports):
    python scripts/e2e_minimal_agent.py [base_url]
"""

from __future__ import annotations

import base64
import json
import re
import struct
import sys
import urllib.error
import urllib.request
import zlib

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
REQUEST_TIMEOUT = 900  # Hermes replies with tool calls can be slow

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail[:400]})
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail[:300]}" if detail and not ok else ""), flush=True)


def request(method: str, path: str, json_body: dict | None = None) -> tuple[int, dict]:
    url = BASE + path
    headers = {}
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
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


def create_session() -> dict:
    status, body = request("POST", "/chat/sessions", json_body={})
    if status not in (200, 201):
        raise RuntimeError(f"create session failed: {status} {body}")
    return body


def chat(session_id: str, content: str, image: dict | None = None) -> dict:
    status, body = request(
        "POST", f"/chat/sessions/{session_id}/messages",
        json_body={"content": content, "image": image},
    )
    if status != 200:
        raise RuntimeError(f"chat message failed: {status} {body}")
    return body


def history(session_id: str) -> tuple[int, list[dict]]:
    status, body = request("GET", f"/chat/sessions/{session_id}/messages")
    return status, (body if isinstance(body, list) else [])


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


def main() -> int:
    # Health.
    status, _ = request("GET", "/health")
    check("backend /health", status == 200, str(status))

    # 1. Session creation (web, no auth): stable UUID + Hermes session id.
    session = create_session()
    sid = session.get("id", "")
    hermes_a = session.get("hermes_session_id") or ""
    check("session created (no auth), UUID + Hermes id",
          bool(re.fullmatch(r"[0-9a-f-]{36}", sid)) and bool(hermes_a), str(session)[:200])

    status, _ = request("GET", f"/chat/sessions/{sid}")
    check("session readable by UUID", status == 200, str(status))

    # 2. Plain message and reply.
    reply = chat(sid, "Напиши ровно одну строку: MAI_E2E_OK")
    check("plain message -> agent reply", "MAI_E2E_OK" in reply.get("content", ""), str(reply)[:200])

    # 3. History is served back from the Hermes transcript.
    status, messages = history(sid)
    roles = [m.get("role") for m in messages]
    contents = " ".join(m.get("content", "") for m in messages)
    check("history: user + assistant messages from Hermes",
          status == 200 and "user" in roles and "assistant" in roles and "MAI_E2E_OK" in contents,
          f"roles={roles}")

    # 4. Context continuation inside the same session.
    reply = chat(sid, "Какое точное слово я просил написать в прошлом сообщении этого диалога? Ответь только этим словом.")
    check("context continuation in same session", "MAI_E2E_OK" in reply.get("content", ""), str(reply)[:200])

    # 5. Image analysis (native vision): base64 payload in the message body.
    png_b64 = base64.b64encode(make_png()).decode("ascii")
    reply = chat(sid, "Опиши коротко это изображение: какие фигуры и цвета на нём?",
                 image={"data": png_b64, "mime_type": "image/png"})
    text = reply.get("content", "").casefold()
    keywords = ("син", "красн", "круг", "прямоуг", "blue", "red", "circle", "rectangle")
    check("image analysed by agent", len(text) > 20 and any(k in text for k in keywords), str(reply)[:250])

    # 6. File create + read (native file tools).
    reply = chat(sid,
                 "Создай текстовый файл e2e_note.txt в твоей рабочей директории с содержимым HELLO_FROM_AGENT. "
                 "Затем прочитай этот файл и процитируй его содержимое в ответе.")
    check("file create + read via native tools", "HELLO_FROM_AGENT" in reply.get("content", ""), str(reply)[:250])

    # 7. Terminal command execution.
    reply = chat(sid, "Выполни в терминале команду: echo MAI_TERM_OK. Ответь только точным выводом команды.")
    check("terminal command executed", "MAI_TERM_OK" in reply.get("content", ""), str(reply)[:250])

    # 8. Agent transfers data from ФИС into its own database (MCP read + SQL write).
    reply = chat(sid,
                 "Сначала через sql_query удали все строки из таблиц ege_scores и applicants своей БД. "
                 "Затем возьми первого участника синтетической ФИС ГИА (отсортируй по candidate_id, "
                 "возьми первый), прочитай его результаты через MCP-инструменты ФИС и перенеси в свою "
                 "БД: создай запись в applicants и впиши все его результаты в ege_scores "
                 "(applicant_id, candidate_id, subject, year, score). "
                 "Ответь только итоговым количеством строк в ege_scores.")
    check("agent moved ФИС data into own DB (sql_query)",
          re.search(r"\b3\b", reply.get("content", "")) is not None, str(reply)[:250])

    # 9. Synthetic ФИС ГИА via the MCP registry tool.
    reply = chat(sid,
                 "Найди в синтетическом реестре ЕГЭ участника «Алексей Иванович Иванов» "
                 "(дата рождения 14.03.2008) и назови его результаты ЕГЭ 2026 по каждому предмету.")
    scores = [s for s in ("92", "88", "100") if re.search(rf"\b{s}\b", reply.get("content", ""))]
    check("ФИС ГИА registry queried via MCP", len(scores) >= 2, f"scores seen: {scores} :: {str(reply)[:250]}")

    # 10. Native Hermes toolsets visible to the agent.
    reply = chat(sid,
                 "Перечисли имена всех твоих доступных инструментов (tool names) через запятую. "
                 "Только список имён, без пояснений.")
    tools_text = reply.get("content", "").casefold()
    check("native tools visible: terminal", "terminal" in tools_text, str(reply)[:250])
    check("native tools visible: files", bool(re.search(r"read|write|file", tools_text)), str(reply)[:250])
    check("native tools visible: memory/session", bool(re.search(r"memor|session", tools_text)), str(reply)[:250])

    # 11. Cross-session isolation: a second web session does not see the first.
    session_b = create_session()
    sid_b = session_b.get("id", "")
    hermes_b = session_b.get("hermes_session_id") or ""
    check("second session: separate Hermes session",
          bool(hermes_b) and hermes_b != hermes_a, f"a={hermes_a} b={hermes_b}")
    reply = chat(sid_b, "Напиши ровно одну строку: ISO_B_OK")
    check("second session: agent reply", "ISO_B_OK" in reply.get("content", ""), str(reply)[:200])
    _, messages_a = history(sid)
    contents_a = " ".join(m.get("content", "") for m in messages_a)
    check("isolation: session A history has no session B content",
          "ISO_B_OK" not in contents_a, f"len={len(contents_a)}")
    _, messages_b = history(sid_b)
    contents_b = " ".join(m.get("content", "") for m in messages_b)
    check("isolation: session B history has no session A content",
          "MAI_E2E_OK" not in contents_b, f"len={len(contents_b)}")

    # 12. Telegram-side session mapping (source=telegram, external_id -> one session).
    status, tg = request("POST", "/chat/sessions", json_body={"source": "telegram", "external_id": "e2e-chat-1"})
    check("telegram session created from chat id", status in (200, 201) and tg.get("id"), str(tg)[:200])
    status, tg_again = request("POST", "/chat/sessions", json_body={"source": "telegram", "external_id": "e2e-chat-1"})
    check("telegram chat id maps to the same session",
          status in (200, 201) and tg_again.get("id") == tg.get("id"), str(tg_again)[:200])

    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    print(f"sessions created (web): {sid}, {sid_b}; telegram external id: e2e-chat-1 -> {tg.get('id')}")
    out = sys.argv[2] if len(sys.argv) > 2 else None
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"base": BASE, "results": RESULTS, "sessions": {"web_a": sid, "web_b": sid_b, "telegram": tg.get("id")}}, fh, ensure_ascii=False, indent=2)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
