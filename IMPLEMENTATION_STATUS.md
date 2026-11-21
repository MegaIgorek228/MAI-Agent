# MAI-Agent — статус реализации

Актуальность: 2026-11-21 (финальная интеграционная проверка).

## Архитектура (закреплена, не пересматривается)

- Hermes Agent — агентная среда (диалог, планирование, инструменты).
- FastAPI — центральный Backend: авторизация, роли, профили, документы, чат, база знаний, Telegram.
- ACP — обязательный протокол Backend ↔ Hermes (stdio).
- MCP/FastMCP — инструменты МАИ, встроенные в Backend (`/mcp`).
- PostgreSQL + pgvector — основная БД и векторный поиск.
- React + TypeScript — веб-интерфейс.
- Docker Compose — postgres + backend + frontend.
- MAI API — Qwen `qwen3.8-27b` (модель, эмбеддинги bge-m3).

## Готовые функции

### 1. Авторизация и роли
- Регистрация, вход (JWT), `/users/me`.
- Роли: `applicant`, `student`, `admissions_staff`, `administrator`.
- Разграничение: staff-API закрыто для non-staff ролей (403), документы — только владелец.

### 2. Профиль абитуриента
- `GET/PUT /applicant/profile` (имена, телефон, программа, основание приёма).

### 3. Документы
- `POST /applicant/documents` — загрузка (лимит 10 МБ; изображения валидируются PIL, допустимы JPEG/PNG/WebP/GIF).
- `GET /applicant/documents` — список.
- `GET /applicant/documents/{id}/file` — бинарь изображения (владелец; `access_token` query-param для `<img>` в истории чата).
- `POST /applicant/documents/{id}/analyze` — LLM-анализ извлечённого текста.

### 4. Чат с агентом (Web)
- `POST /chat/sessions` — запуск ACP-сессии (Backend спавнит `hermes-acp`, stdio).
- `POST /chat/sessions/{id}/messages` — текст и/или изображение (`image_document_id`).
- Изображение передаётся модели как `ImageContentBlock` (base64) → Hermes `image_input_mode: native` → Qwen видит пиксели.
- При прикреплении изображения Backend добавляет к промпту явную inline-инструкцию (модель анализирует изображение напрямую, без tool-детура в exec-аппрувы).
- История сообщений сохраняет привязку `ChatMessage.image_document_id` (миграция `0005_chat_message_image`); после перезагрузки страницы изображение отображается из истории.

### 5. База знаний (pgvector)
- `POST /knowledge/sources` (staff/admin) — источник → чанки → эмбеддинги MAI (bge-m3, 1024d) → pgvector.
- `POST /knowledge/search` — векторный поиск.
- `POST /knowledge/admission-requirements`, `/sources/sync`, `/sources/discover`.

### 6. Workspace сотрудников
- `GET /applicant/staff/applicants` (staff/admin).
- Комплектность документов: `GET /applicant/documents/completeness`.

### 7. Telegram
- Backend — единственный владелец polling (Hermes Telegram Gateway не используется).
- Привязка аккаунта: `/pair КОД` через `POST /auth/telegram/pairing-code`.
- Текст: `_answer_user_message` → ACP.
- Фото: скачивание через Bot API → валидация PIL → `ImageContentBlock` → ACP (тот же механизм, что у Web); caption к фото передаётся в промпт (раньше терялся — передавалось `message.text` вместо `message.caption`, исправлено 2026-11-21).

## Изменения по итогам финальной интеграционной проверки (2026-11-21)

1. **История изображений**: `ChatMessage.image_document_id` (FK, SET NULL, index) + alembic-миграция `0005_chat_message_image`; `list_messages` отдаёт `image_document_id`/`image_filename`; endpoint `GET /applicant/documents/{id}/file`; Frontend отображает изображение в истории и предпросмотр перед отправкой.
2. **Inline-инструкция для модели** (при изображении): `IMAGE_INLINE_INSTRUCTION`/`with_image_instruction` в `hermes_client.py`, применение в `chat.py` и `telegram_service.py`.
3. **Nginx-прокси фронтенда**: добавлены `location /applicant/`, `/chat/`, `/knowledge/` (раньше веб-UI в compose не мог обращаться к этим API — только `/auth`, `/users`, `/health`, `/mcp`).
4. **Vite dev-прокси**: аналогично дополнены `/applicant`, `/chat`, `/knowledge`.
5. **Telegram caption fix**: `_handle_update` передавал `_handle_photo` значение `message.text` (пустое для фото с подписью); теперь передаётся `message.caption` — подпись пользователя больше не теряется.
6. **ACP SDK в Docker (критичная починка)**: в образе backend `hermes-agent==0.19.0` (PyPI) тянет `acp_adapter`, который импортирует `ModelInfo` из `acp.schema`. `ModelInfo` удалён из `acp.schema` начиная с 0.10.x: скан wheel'ей PyPI (0.11.0/0.11.1/0.12.0/0.12.1/1.0.0rc1-rc3/1.0.0) показал, что ни одна из этих версий не содержит `ModelInfo` (первоначально выбранная 0.11.1 тоже не подошла — `ImportError` подтверждён контейнерной проверкой). 0.9.0 — самый новый релиз, где есть и `ModelInfo`, и всё, что импортирует backend (`HttpHeader`, `HttpMcpServer`, `ImageContentBlock`, `TextContentBlock`, `connect_to_agent`, `PROTOCOL_VERSION=1`); это же окружение (acp 0.9.0) использует рабочий хостовый PM-venv. Проверено одноразовым контейнером: `hermes-agent 0.19.0 + acp 0.9.0` → `acp_adapter.entry/server` импортируются. Минимальное исправление: фиксация `agent-client-protocol==0.9.0` в Dockerfile. Хостовая конфигурация не тронута.
7. **`reasoning_effort=none` 400 на MAI-реле (исправлено, проверено живым прогоном)**: вспомогательные вызовы (в т.ч. генерация заголовка сессии) отключают reasoning; встроенный `CustomProfile` в Hermes проецирует «выключенный reasoning» как `reasoning_effort="none"`, а MAI-рель (`api-ai.mai.ru`, LiteLLM) принимает только `xhigh`/`medium`/`low` → HTTP 400 «Unexpected reasoning effort none». Минимальное исправление без изменения исходников Hermes: (а) в изолированном профиле (`MAI-Agent\acp\plugins\model-providers\custom\`) добавлен user-level override провайдера — для MAI-базового URL выключенный reasoning проецируется как `medium`, для прочих — поведение без изменений; (б) в `config.yaml` изолированного профиля добавлен именованный провайдер `providers.mai` и все auxiliary-слоты переключены с `provider: main` на `provider: custom:mai`. Проверка живым прогоном 2026-11-21: ACP-сессия через изолированный `hermes-acp` (main loop → Qwen, ответ «ОК» за 3.1s) + фоновая генерация заголовка пошла через `custom:mai` (agent.log), заголовок сохранён, в errors.log после исправления ни одной 400. Основной профиль Hermes и его Gateway не тронуты.
8. **Hermes-профиль в контейнере (compose)**: `hermes-agent 0.19.0` в контейнере не читает env-переменные `HERMES_PROVIDER`/`OPENAI_*` — без `config.yaml` в своём home он резолвит дефолтный провайдер `openrouter` (пустая модель) и все вызовы падают с «API call failed … Connection error». Минимальное исправление: в репозиторий добавлен `backend/hermes-profile/` (`config.yaml` — та же форма, что у хостового изолированного профиля, без секретов: ключ через `key_env: OPENAI_API_KEY`; плюс 0.19.0-совместимый вариант плагина-override из п. 7 — без модуля `agent.reasoning_effort`, которого нет в 0.19.0), Dockerfile кладёт его в `/root/.hermes`. Compose-конфиг не менялся: `HERMES_HOME` не нужен (HOME=/root → дефолтный home), ключ уже инжектится через env. Дополнительно устранена ошибка `session/new` → 500 (`RuntimeError: No LLM provider configured`): у `hermes-agent 0.19.0` нет встроенного провайдера `openai` (`resolve_runtime_provider('openai')` → Unknown provider), поэтому модель основного прогона в контейнерном профиле завязана на именованный `custom:mai` (резолвится в OpenAI-совместимый клиент на MAI-рель с явным base_url+ключом, передаваемыми AIAgent). TLS: реле MAI предъявляет сертификат российского национального CA (Russian Trusted Sub CA → Russian Trusted Root CA), которого нет в стандартном Mozilla-бандле `python:slim` — это закрывает штатный механизм проекта (`certs/`-volume + `AI_API_CA_BUNDLE` → `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`), проверка TLS не ослаблялась.

## Проверенные результаты

- Backend: 19/19 pytest (auth, роли, профиль, документы, чат, изображения: инструкция, история, file-endpoint; Telegram: текст → ACP, фото → ImageContentBlock, `/start`, `/pair`, ownership polling).
- Alembic: 0001→0005 применены к PostgreSQL (pgvector/pgvector:pg16), downgrade/upgrade 0005 проверен, данные не затронуты.
- E2E через изолированный Hermes (хост, v0.23.1): изображение реально обработано Qwen через MAI API (11.9s, ответ корректен), текстовый чат 4.6s.
- Docker: backend-образ собран (`hermes-agent==0.19.0` + `acp 0.9.0` + `fastmcp==2.14.7` + `hermes-profile` из п. 8); frontend собран (`tsc` + `vite`), nginx-роуты проверены в образе. Контейнерные проверки (2026-11-21): critical imports, **19/19 pytest внутри контейнера**, compose up (postgres+backend+frontend), `/health` — все PASS. Compose-E2E (9 сценариев, 2026-11-21 20:15): **9/9 PASS**, включая реальные ACP+Qwen из контейнера: текстовый чат (сессия 18.3s, ответ «ОК» 4.0s), анализ изображения (8.7s — модель корректно распознала красный круг и синий квадрат, vision-ассерты PASS), история с привязкой изображения к документу, база знаний (bge-m3 + pgvector), workspace staff. В логах backend и контейнера Hermes ни одной 400 `reasoning_effort=none`.

## Известные ограничения

- Версия `hermes-acp` в Docker-образе backend (`hermes-agent==0.19.0` с PyPI, адаптер `acp_adapter`) отличается от хостового Hermes (v0.23.1, source-install). Это допустимо: каждая связка самодостаточна (в контейнере: backend-код + acp 0.9.0 + адаптер 0.19.0; на хосте: backend-код + адаптер v0.23.1 с acp 0.9.0 в своём окружении). ACP — wire-протокол (JSON-RPC, PROTOCOL_VERSION=1), совместимость пар подтверждена сквозным прогоном.
- Frontend не имеет автотестов (нет test-скрипта в package.json) — контроль: `tsc -b` (типы) + `vite build` (пройдены на хосте и в Docker-сборке).
- Живой Telegram-сценарий (реальный Bot API) проверяется в пределах возможности: polling-ownership и обработка обновлений покрыты автотестами (5 тестов), реальный polling стартует штатно в compose (token из .env); отправка сообщений «от имени пользователя» без внешнего доступа невозможна (ограничение Bot API).
- Локально (этот хост) порт 5432 занят нативным postgres; для compose-проверки postgres опубликован на 5433 (override-файл вне репозитория). Внутри compose Backend подключается штатно к `postgres:5432`.
