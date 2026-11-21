# Implementation status

Дата обновления: 2026-11-21

## Состояние: v1.0 — рабочий штатный запуск (Docker Compose)

Приложение запускается штатной конфигурацией `docker compose up`: PostgreSQL + Backend + Frontend в одном compose. Полный функциональный контур проверен живым сквозным прогоном (E2E 9/9, интеграционные тесты 19/19 в контейнере).

### Запуск

```bash
# 1. Секреты (ключи НЕ коммитятся)
cp .env.example .env   # заполнить QWEN_API_KEY, TELEGRAM_BOT_TOKEN, JWT_SECRET

# 2. Поднять стек (postgres :5433, backend :8000, frontend :8080)
docker compose up -d --build

# 3. Проверки
docker compose exec backend python -m pytest tests -q   # 19/19
python scripts/e2e_compose.py                           # 9/9 сценариев
```

### Что реализовано

- **Backend (FastAPI)**: учётные записи и роли (applicant/staff/student), JWT, чат-сессии, документы, требования к документам, knowledge base (pgvector + embeddings bge-m3, dim 1024), discovery/синхронизация официальных источников (mai.ru, priem.mai.ru), MCP HTTP-сервер для Hermes.
- **Hermes через ACP** (основной протокол Backend ↔ Hermes): ACP client на SDK `agent-client-protocol==0.9.0` (в версиях 0.10+ отсутствует `ModelInfo`), изолированный профиль Hermes в `backend/hermes-profile/` (без секретов, ключ резолвится из env `OPENAI_API_KEY`), MCP-сервер Backend передаётся через `HttpMcpServer`, доверенный контекст — в заголовке `X-MAI-Context`.
- **LLM**: `deepseek-v4.1-flash` через `https://api-ai.mai.ru/v1` (MAI relay, OpenAI-совместимый; модель выбирается в `backend/hermes-profile/config.yaml` → `model.default`). Vision (анализ изображений) — нативный.
- **Frontend (React/Vite + nginx)**: все 8 location-блоков, загрузка изображений, история чата с картинками, сборка в Docker-образе.
- **Telegram**: polling **только в Backend** (бот `mai_priem_bot`), pairing chat по одноразовому коду, `/start` создаёт технический аккаунт; polling в Hermes Gateway отключён.
- **Данные**: PostgreSQL + pgvector, миграции Alembic до `0005_chat_message_image` (FK `chat_messages.image_document_id → documents.id, ondelete SET NULL` — история чата с картинками).

### Авторизация MAI relay: x-api-key (изменение 2026-11-21)

MAI relay c ~17:30 2026-11-21 принимает **только** заголовок `x-api-key` и отдаёт 401 «Malformed API Key» на любой запрос с `Authorization: Bearer` (включая оба заголовка сразу). TLS-цепочка сертификатов не менялась (совпадает с собранным CA bundle побайтово), mTLS не требуется, ключ валиден.

Исправление в 4 точках (без изменения архитектуры):
1. `backend/app/llm_service.py` — `api_key=""` (подавляет Bearer в openai SDK) + `default_headers={"x-api-key": ...}`.
2. `backend/app/embedding_service.py` — то же.
3. `backend/hermes-profile/plugins/model-providers/custom/__init__.py` (контейнер) — плагин уровня пользователя: in-place patch `openai.OpenAI/AsyncOpenAI.__init__` (перенос ключа в `x-api-key` для MAI-хоста) **и** patch `httpx.Client/AsyncClient.send` — универсальный chokepoint: любой запрос к `api-ai.mai.ru` получает `x-api-key` из env и теряет `Authorization`. Второй слой нужен, т.к. vision-роутер Hermes (`resolve_vision_provider_client`) строит клиентов с пустым ключом (named custom provider не резолвит `key_env` на этом пути).
4. Изолированный профиль хоста (`%LOCALAPPDATA%\MAI-Agent\acp\plugins\model-providers\custom\__init__.py`) — те же два патча.

Также в профиле Hermes: override `reasoning_effort` (MAI relay принимает `xhigh/medium/low`, `none` даёт 400) и aux-слоты → `custom:mai`.

### Поведение агента: скорость, формат, доступ к данным (2026-11-21, вечер)

После стабилизации авторизации устранены три проблемы, отмеченные пользователем: Markdown в ответах, длительность ~90 с и отсутствие данных.

- **Формат — plain text**: `backend/hermes-profile/SOUL.md` (манифест идентичности агента) запрещает весь Markdown (`**`, таблицы, списки, `[..](url)`, бэктиксы), требует 2–5 предложений, запрещает односложные ответы. SOUL.md зеркалируется в изолированный профиль хоста.
- **Скорость**: stock-пресет toolset `hermes-acp` (terminal/file/browser/skills/delegation) заставлял модель «копать» файловую систему контейнера (10+ вызовов модели, 91–118 с + фоновый skill-review ещё ~100 с). `platform_toolsets.acp` в config.yaml в 0.19.0 **игнорируется** ACP-адаптером (хардкод `enabled_toolsets=["hermes-acp"]`). Решение на уровне плагина (без правки исходных): `_install_mai_acp_toolset_override()` в `plugins/model-providers/custom/__init__.py` переопределяет `TOOLSETS["hermes-acp"]` → `tools=["session_search"]`. Итог: 2–4 вызова модели, ~6–30 с на ответ с данными.
- **Доступ к данным — MCP-инструмент `fetch_web_page`** (`backend/app/mcp_tools.py`): Hermes web-инструменты в контейнере неработоспособны (web_extract требует платный extract-бэкенд firecrawl/tavily/exa/parallel; web_search на безключевом ddgs с этой сети не отвечает), поэтому агент открывает официальные страницы через Backend MCP: https-only, SSRF-защита (`getaddrinfo` + `ipaddress.is_global` на каждый IP, ручные редиректы ≤5 с повторной валидацией), timeout 25 с, лимиты 2 МБ тела / 25k символов, HTML→text через lxml. В docstring — навигационная карта страниц priem.mai.ru (проходные баллы `/base/score/`, направления, цены, результаты приёма 2026, дедлайны, календарь).
- **ACP stdio reader 64KB → 50MB** (`backend/app/hermes_client.py::_start`): кадр JSON-RPC с крупным результатом инструмента (страница ~30–60KB, base64-изображения) превышал стандартный лимит StreamReader и ронял соединение (`LimitOverrunError` → 503). Ридер протокола сабпроцесса (`proto.stdout`) заменяется на `StreamReader(limit=50MB)` — тот же лимит, что и в самом acp SDK (`acp.core.DEFAULT_STDIO_BUFFER_LIMIT_BYTES`).
- **Stale-session fallback** (`hermes_client.py`): `prompt()` возвращает `(text, hermes_session_id)`; на пустой ответ создаётся новая сессия и делается одна повторная попытка; новый ID персистится вызывающими (`routers/chat.py`, `telegram_service.py`).
- **Наблюдаемость**: `logging.basicConfig(level=INFO)` в `app/main.py`, INFO-логи telegram-потока (update → prompt → answer, тайминги), stale-update guard (>5 мин — skip).
- **TIRITH отключён** (`TIRITH_ENABLED: "false"` в compose backend environment): автозагрузка бинарника с GitHub в контейнере без egress вешала ход агента на ~10 минут.
- **`ddgs>=9` в `backend/pyproject.toml`**: безключевой search-бэкенд, открывающий гейт `check_web_api_key` (сам toolset web-инструменты не включает).

### Проверенные результаты (2026-11-21, Docker)

- Backend host: `pytest` — **19/19 passed**.
- Backend container: `pytest` — **19/19 passed** (в цепочке после сборки).
- E2E `scripts/e2e_compose.py` — **9/9** (финальный прогон после всех фиксов, включая vision-сценарий: red circle + blue rectangle assertions PASS — подтверждает работу 50MB ACP-ридера на base64-кадрах).
- Live-вопрос «Проходные баллы на ПМИ в 2026» через API: **5.7 с**, ответ с реальными цифрами (01.03.02 «Прикладная математика и информатика»: 289/289/217, сверено с таблицей на priem.mai.ru/base/score/), plain text, корректный вуз (МАИ). До серии фиксов: 91–118 с и/или «данные недоступны».
- Текст-чат без данных: ~13–28 с (2–4 API-вызова); до фикса — 91–118 с (10+ вызовов).
- Ошибок 400 по `reasoning_effort`, 401 по авторизации relay: отсутствуют.
- `hermes acp --check` — успешно.

### Telegram: живая приёмка

- Бот `mai_priem_bot`, токен в `.env`, webhook не установлен; polling активен в backend-контейнере.
- Текст-путь готов к живой приёмке (x-api-key фикс). Vision-путь зафиксирован httpx-патчем (см. выше), финальная живая проверка фото в Telegram — следующий шаг.

## Ограничения

1. ФИС ГИА не реализована (нет официальной документации/контура).
2. MAI relay — внешняя зависимость: смена схемы авторизации (как 2026-11-21) требует повторного фикса в 4 точках (паттерн задокументирован выше).
3. Discovery `mai.ru`/`priem.mai.ru` ограничен сетевым доступом из среды запуска.
