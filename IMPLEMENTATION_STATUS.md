# MAI-Agent — статус реализации

## Sessionless-версия (концепция 2026-11-23, ветка `simplification/minimal-agent`)

Актуальность: 2026-11-23 (обновление). Пользовательских аккаунтов, профилей,
ролей и JWT больше нет: единственная единица пользовательского контекста —
**сессия Hermes** (`agent_sessions` → `hermes_session_id`). Подробно — в
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) и [AGENTS.md](AGENTS.md).

Готово и проверено (2026-11-23):

1. **Бэкенд переписан на sessionless**: `models.py` (5 моделей: AgentSession,
   SyntheticEgeCandidate/Result, KnowledgeSource/Chunks), `config.py` (без JWT),
   `hermes_client.py` (пул ACP-процессов на сессию, восстановление через
   `session/load`, прозрачный fallback при потере сессии), `routers/chat.py`
   (без авторизации: POST/GET/DELETE `/chat/sessions*`), `telegram_service.py`
   (chat id ⇄ `agent_sessions.external_id`), `main.py` (`/health`, `/ready`,
   `/chat`, `/mcp`). Legacy-модули (users/roles/invites/applications/documents)
   удалены из кода.
2. **Миграция `0013_sessionless_agents`**: таблица `agent_sessions`; удаление
   legacy-таблиц (в порядке FK-зависимостей); downgrade намеренно не
   реализован — откат только из резервной копии
   (`mai_agent_pre_sessionless_20261123_1217.sql`).
3. **MCP — 5 контекстно-чистых инструментов** (`mcp_tools.py`):
   `fetch_web_page` (HTTPS, SSRF-защита), ФИС ГИА (отдельная БД, только
   чтение): `search_synthetic_ege_results`, `list_synthetic_ege_candidates`,
   `get_synthetic_ege_results`, и `sql_query` (произвольные SQL-команды
   PostgreSQL к собственной БД агента; 500 строк — лимит вывода SELECT).
   Заголовков авторизации нет.
4. **Фронтенд — чат без регистрации**: `App.tsx` (список UUID-сессий в
   `localStorage`, автосоздание, восстановление, удаление),
   `AssistantWorkspace.tsx` (история, переключение, изображения base64),
   `Portal.tsx` → `ChatShell`. Файлы кабинетов и «самолёта» удалены.
5. **Hermes-хранилище вынесено в volume `hermes_home`** (`/root/.hermes`):
   сессии, история и MEMORY.md переживают пересоздание контейнера.
6. **Тесты 48/48** (`python -m pytest ../tests -q` из `backend/`): SQL-инструмент,
   сессии (создание/история/изоляция/повторное открытие при потере сессии),
   Telegram-маппинг (включая `/new`), жизненный цикл Hermes
   (`start_session`/`reset_session`), реестр ФИС, ФИС-MCP-инструменты
   (список/пагинация/результаты по id).
7. **E2E 20/20** (`scripts/e2e_minimal_agent.py`, запущенный стек): создание
   сессии без авторизации, сообщение/ответ, история из Hermes, продолжение
   контекста, изображение (vision), файл, терминал, перенос данных из ФИС
   в собственную БД агента (MCP-чтение + SQL-запись), поиск в ФИС ГИА,
   видимость штатных инструментов, изоляция двух сессий, маппинг Telegram.
8. **Восстановление после перезапуска Backend проверено live**: после
   `docker compose restart backend` история сессии (16 сообщений) восстановлена
   из `state.db` через ACP `session/load`; после перезагрузки Web-страницы
   история восстанавливается из хранилища Hermes.
9. **Исправлена команда `/new` в Telegram** (2026-11-23): `start_session()`
   возвращала уже живой процесс сессии, поэтому `/new` фактически не создавал
   новую сессию. Добавлен `HermesClientManager.reset_session()`: терминация
   текущего процесса и соединения, запуск новой сессии Hermes, обновление
   привязки `agent_sessions.hermes_session_id`. Старая сессия остаётся в
   истории Hermes (`state.db`), но не используется; следующее сообщение
   попадает в новую сессию; повторный `/new` создаёт ещё одну; привязка
   переживает перезапуск Backend (проверено live + тестами, см. 6).
10. **SQL-инструмент открыт на произвольные команды** (2026-11-23): `sql_query`
   выполняет любую одиночную команду PostgreSQL (SELECT, INSERT, UPDATE,
   DELETE, CREATE/ALTER/DROP) — по решению о демонстрационной версии доступ
   к SQL намеренно открыт (без RBAC, фильтров таблиц и ограничений типов
   команд). Лимит 500 строк действует только на вывод результата SELECT,
   не на выполнение; записи коммитятся. Старое ограничение «только
   SELECT/WITH + rollback» удалено. Проверено: unit-тесты
   (`tests/test_sql_tool.py`, 7 тестов, 43/43 в общей сумме) + live-прогон
   INSERT/UPDATE/DELETE/DDL через реальное соединение PostgreSQL в
   контейнере.
11. **Фиксация архитектуры: три независимые БД** (2026-11-24, по решению
   пользователя): синтетическая ФИС ГИА — отдельная БД `mai_fis_gia`
   (источник результатов ЕГЭ, доступу агента только через MCP-инструменты,
   чтение); собственная БД MAI-Agent — отдельная БД `mai_agent`
   (applicants, ege_scores, applications, ratings, knowledge_*), доступу
   агента через `sql_query` (открытый SQL); служебная БД Backend —
   `mai_backend` (agent_sessions, telegram_checkpoints, alembic), ни одному
   MCP-инструменту не видна. Агент сам переносит данные из ФИС в свою БД
   и работает с ними; Backend остаётся транспортным мостом, бизнес-логика —
   в Hermes. Интернет — собственные инструменты Hermes (терминал, curl,
   Python) + `fetch_web_page`. Реализация: `app/init_databases.py`
   (идемпотентное создание `mai_agent`/`mai_fis_gia` + загрузка фикстуры
   ФИС, вызывается в entrypoint перед alembic), `app/db.py` (три движка),
   миграция `0014_drop_external_data` (служебная БД освобождена от внешних
   таблиц), `docker-compose.yml` (имя служебной БД `mai_backend`, шаг
   init в команде), SOUL.md (раздел «Архитектура данных»). Проверено:
   unit 48/48, E2E 20/20 (включая live-перенос данных ФИС → своя БД
   агентом), живые пробы (поиск в ФИС, перенос, изоляция служебной БД).

Ниже — **исторический отчёт** о первом этапе упрощения (до sessionless).
Сохранён без изменений для справки; актуальное состояние — в разделе выше,
противоречия с ним в исторических отчётах намеренно не устраняются.

## Минимальная агентная версия (концепция 2026-11-23, ветка `simplification/minimal-agent`) — ИСТОРИЧЕСКИЙ ОТЧЁТ (этап 1, до sessionless)

Актуальность: 2026-11-23. Текущая целевая архитектура: Hermes Agent — единственный
агент (штатные инструменты: терминал, файлы, память `MEMORY.md`, `session_search`,
`todo`), Backend — минимальный транспорт Web/Telegram ↔ Hermes (ACP stdio),
источники данных — MCP (имитация ФИС ГИА + read-only `sql_query`).
Подробно — в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) и [AGENTS.md](../AGENTS.md).

Готово и проверено:

1. **SQL-инструмент** (`mcp_tools.py`, `sql_query`): одна read-only SELECT/WITH,
   лимит 500 строк, запрет таблиц `users`/`staff_invites`; unit-тесты
   (`tests/test_sql_tool.py`).
2. **Штатные инструменты Hermes в ACP-сессии**: состав пресета `hermes-acp`
   расширен в плагине `backend/hermes-profile/plugins/model-providers/custom`
   (terminal, process, read_file, write_file, patch, search_files, execute_code,
   memory, session_search, todo). Причина: ACP-адаптер хардкодит пресет и
   игнорирует `platform_toolsets` из config.yaml.
3. **Web упрощён до чата**: `App.tsx` — только аутентификация и чат
   (`AssistantWorkspace`, `Workspace chatOnly`); кабинеты, профили и заявления
   из интерфейса исключены.
4. **Telegram** — без изменений: чистый relay (polling только в Backend),
   подтверждено E2E.
5. **E2E** (`scripts/e2e_minimal_agent.py`): **17/17** (2026-11-23):
   сообщение/ответ, история (хранение, список, восстановление), изображение
   (загрузка + нативный vision-анализ), создание/чтение файла, терминальная
   команда, запрос SQL-источника, запрос имитации ФИС ГИА, видимость штатных
   инструментов, разделение сессий двух пользователей.
6. **Тесты backend**: 83/83.

Легаси приёмной кампании (заявления, документы, кабинеты, staff-API, связанные
MCP-инструменты и таблицы) остаётся в коде до явного решения об удалении —
после проверки новой версии. Резервная копия PostgreSQL:
`pre_simplification` (создана 2026-11-23).

---

## Старая версия (статус от 2026-11-21) — ИСТОРИЧЕСКИЙ ОТЧЁТ (архитектура с учётными записями; заменена sessionless-концепцией, см. раздел в начале файла)

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
