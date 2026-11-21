# Implementation status

Дата обновления: 2026-11-17

## Реализовано

### Roles and access

- Добавлена роль `student` без изменения роли по умолчанию для регистрации (`applicant`).
- Студент может использовать собственный профиль и общий чат.
- Доступ студента к документам абитуриента пока запрещён до отдельного решения о правах.

### Telegram

- Токен Telegram валидирован через Telegram Bot API: бот `mai_priem_bot` доступен.
- В Backend добавлен polling-сервис Telegram с привязкой chat к существующему аккаунту через одноразовый код.
- Сообщения Telegram проходят через тот же `ChatSession` и ACP/Hermes-контур.
- Реальная отправка ответа зависит от настроенного Hermes/ACP provider.
- Telegram polling работает в polling-режиме с одним активным потребителем `getUpdates`.
- `/start` автоматически создаёт технический аккаунт Telegram; отдельная регистрация в Backend для начала работы не обязательна.
- В PostgreSQL подтверждены Telegram identity записи после `/start`.
- Причина отсутствия ответа `/start` устранена: в PostgreSQL применена миграция `0004_telegram_identity`. Telegram-offset обновляется только после успешной обработки update.
- Hermes локальная ACP-проверка проходит (`hermes acp --check`). Реальный handshake и MCP-calls остаются заблокированы отсутствием рабочего inference provider/configuration.
- MCP HTTP endpoint доступен и зарегистрированные tools обнаруживаются через FastMCP; живой вызов Hermes инструмента требует ACP-provider.
- `api-ai.mai.ru` отвечает с Qwen-моделью `qwen3.8-27b` и embeddings-моделью `bge-m3`; из Docker требуется CA bundle для доверия TLS-сертификату.
- CA bundle собран и проверен через `openssl`: `Verify return code: 0 (ok)`.
- В Docker работают chat, embeddings и LLM-анализ документа.

### Agent runtime

- Backend содержит ACP client на официальном Python SDK `agent-client-protocol`.
- Поддержаны операции `initialize`, `session/new`, `session/load` и `session/prompt`.
- Идентификатор Hermes-сессии хранится в `chat_sessions.hermes_session_id`.
- Backend API предоставляет:
  - `POST /chat/sessions`;
  - `GET /chat/sessions`;
  - `GET /chat/sessions/{id}/messages`;
  - `POST /chat/sessions/{id}/messages`.
- Hermes получает MCP-сервер Backend через ACP `HttpMcpServer`.
- Доверенный контекст передаётся в заголовке `X-MAI-Context` и проверяется Backend.
- ACP SDK требует в `HttpMcpServer` поле `type="http"`; оно добавлено в adapter и проверено по реальной schema установленного SDK.

### Qwen-compatible providers

- Добавлен OpenAI-compatible provider для Qwen document analysis.
- Добавлен OpenAI-compatible provider для embeddings.
- Выбрана размерность embeddings `1024`, совместимая с `Qwen/Qwen3-Embedding-0.6B`.
- При отсутствии endpoint или ключей возвращается явная ошибка `503`; фиктивные ответы не используются.

### Knowledge base

- Добавлен cosine similarity search в PostgreSQL/pgvector при настроенном embedding provider.
- Без provider сохраняется только временный lexical fallback для локальной разработки.
- Добавлена синхронизация официальных материалов по явно переданным HTTPS URL.
- URL разрешаются только для доменов из `OFFICIAL_SOURCE_DOMAINS`.
- Добавлен ограниченный discovery ссылок с корневых URL `mai.ru` и `priem.mai.ru`; результаты доступны сотрудникам через `/knowledge/sources/discover` и требуют последующей синхронизации.
- Реализована дедупликация по URL и hash.

### Documents and admission requirements

- Добавлена таблица требований к документам.
- Проверка комплектности учитывает:
  - `document_type`;
  - направление подготовки;
  - основание поступления.
- Добавлен `POST /applicant/documents/{id}/analyze` для анализа через Qwen-compatible endpoint.
- Добавлен административный endpoint создания требований:
  - `POST /knowledge/admission-requirements`.

### Frontend

- Раздел «Агент» теперь создаёт chat session и отправляет сообщения через Backend API.
- Добавлена отрисовка истории текущего диалога.

## Проверки

- Ruff: успешно.
- Pytest: 7 тестов успешно.
- Alembic chain на SQLite: успешно до `0003_agent_integrations`.
- `hermes-acp --check`: успешно.
- Hermes Agent локально установлен, версия `0.23.1`.
- Frontend build через локальный `npm` не выполнен: `npm` отсутствует в PATH текущей среды.
- Backend/Frontend Docker build: успешно.
- Docker Compose PostgreSQL smoke test и migration до `0003_agent_integrations`: успешно.

## Ограничения и блокеры

1. Реальный ACP handshake с установленным Hermes в текущей Windows-среде не завершился: процесс Hermes дошёл до регистрации plugins, но не ответил на `initialize` в течение 30–45 секунд. В Backend добавлен таймаут ACP и явная ошибка вместо бесконечного ожидания. Требуется проверить запуск Hermes через его управляемое окружение/PM и наличие настроенного provider.
2. Qwen endpoint и модель настроены в локальном `.env`; Backend из Docker пока блокируется `CERTIFICATE_VERIFY_FAILED` до подключения `AI_API_CA_BUNDLE`.
3. Embeddings настроены на тот же endpoint (`bge-m3`, размерность 1024); параметр `dimensions` не передается, так как LiteLLM не поддерживает его для этой модели.
4. Официальные домены по умолчанию ограничены `mai.ru` и `priem.mai.ru`; discovery корневых страниц подготовлен. Реальный smoke-тест из текущей среды завершился `httpx.ConnectTimeout`, поэтому получение материалов требует сетевого доступа к сайтам.
5. Telegram Gateway/Bot API ещё не подключён. Официальное описание Hermes подтверждает Gateway как самостоятельную интеграцию Hermes на `python-telegram-bot`, но его связь с JWT-авторизацией Backend и текущим ACP-контуром нужно проверить экспериментально.
6. ФИС ГИА не реализуется без официальной документации, авторизации и тестового контура.

## Следующий этап

- Проверить Hermes ACP в его штатном Python/PM runtime с настроенным provider.
- Подключить Qwen inference и embeddings endpoint.
- Выполнить интеграционный тест: Frontend → Backend → ACP → Hermes → MCP → Backend.
- Повторить discovery/синхронизацию из сети с доступом к `mai.ru` и `priem.mai.ru`, затем загрузить утверждённые admission requirements.
- Настроить Hermes Gateway через `hermes gateway setup` и проверить Telegram до выбора резервного Bot API.
