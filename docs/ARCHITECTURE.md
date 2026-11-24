# Архитектура MAI-Agent

Концепция от 2026-11-23, **sessionless**: пользовательских аккаунтов, профилей,
ролей и JWT нет. Единственная единица пользовательского контекста —
**сессия Hermes**. Полное описание правил — в [AGENTS.md](../AGENTS.md),
развёртывание — в [DEPLOYMENT.md](DEPLOYMENT.md).

## Обобщённая схема

```text
   Web (чат, session UUID)      Telegram (бот, chat id)
      │                               │
      ▼                               ▼
┌────────────────────────────────────────────────────────┐
│ Backend (FastAPI) — минимальный транспортный мост      │
│  • /chat/sessions — создание сессий БЕЗ аутентификации │
│  • Telegram polling (только здесь)                     │
│  • /mcp — FastMCP-сервер (встроен)                     │
│  • hermes_client.py — пул процессов ACP                │
│  • telegram_service.py — chat id ⇄ agent_sessions      │
└──────────────────────┬─────────────────────────────────┘
                       │ ACP (stdio), сессия на диалог
                       ▼
┌────────────────────────────────────────────────────────┐
│ Hermes Agent (hermes-acp 0.19.0, в образе backend)     │
│  • диалог, планирование, память MEMORY.md              │
│  • история — state.db (SQLite), восстановление через   │
│    ACP session/load replay                             │
│  • штатные инструменты:                                │
│    terminal, process, read_file, write_file, patch,    │
│    search_files, execute_code, memory, session_search, │
│    todo                                                │
│  • изображения — нативный vision модели                │
└──────────────┬─────────────────────────────────────────┘
               │ MCP (без привязки к профилям)
               ▼
┌────────────────────────────────────────────────────────┐
│ MCP-инструменты (внутри Backend)                       │
│  • fetch_web_page — веб-страницы                       │
│  • search_synthetic_ege_results — ФИС ГИА (чтение)     │
│  • list_synthetic_ege_candidates — ФИС ГИА (чтение)    │
│  • get_synthetic_ege_results — ФИС ГИА (чтение)        │
│  • sql_query — произвольный SQL, своя БД агента        │
│    (500 строк — лимит вывода SELECT)                   │
└──────────────┬─────────────────────────────────────────┘
               ▼
   Три независимые БД PostgreSQL:
   mai_fis_gia (синтетическая ФИС ГИА: synthetic_ege_*)
   mai_agent   (своя БД агента: applicants, ege_scores,
                applications, ratings, knowledge_*)
   mai_backend (служебная: agent_sessions,
                telegram_checkpoints; MCP не видит)
```

## Компоненты

### Backend (FastAPI)
Транспортный мост без собственной агентной логики и без авторизации:
- `POST /chat/sessions` — создание сессии (web или telegram по `external_id`),
  возвращает стабильный UUID; клиент идентифицируется только им;
- `POST /chat/sessions/{id}/messages` — передача текста/изображения в Hermes
  через ACP, ответ — содержимое реплики;
- `GET /chat/sessions/{id}/messages` — история **из хранилища Hermes**
  (ACP `session/load` replay), Backend её не дублирует;
- `DELETE /chat/sessions/{id}` — удаление сессии и закрытие процесса Hermes;
- Telegram: polling и обработка текста/фото в `app/telegram_service.py`;
  `chat id` используется только для сопоставления с `agent_sessions.external_id`,
  профили не создаются;
- `/mcp` — FastMCP-сервер (`app/mcp_tools.py`), инструменты контекстно-чистые
  (без заголовков авторизации);
- `app/hermes_client.py` — пул процессов `hermes-acp` (stdio), по одному
  процессу на сессию, восстановление по `hermes_session_id` (`load_session`),
  при потере сессии — прозрачный переход на новую (ID сохраняется в БД).

### Hermes Agent
- пакет `hermes-agent` 0.19.0, процесс `hermes-acp` внутри образа backend
  (`/usr/local/bin/hermes-acp`), профиль — `backend/hermes-profile`
  (в контейнере — `/root/.hermes`, вынесен в volume `hermes_home`, чтобы
  сессии и MEMORY.md переживали пересоздание контейнера);
- модель: `deepseek-v4.1-flash` через MAI relay (OpenAI-совместимый API,
  именованный провайдер `custom:mai`, плагин `plugins/model-providers/custom`);
- изображения от пользователей идут нативно в модель;
- память — штатная `MEMORY.md` и сессии Hermes (`state.db`, SQLite):
  Backend ничего из этого не дублирует;
- **важная особенность**: ACP-адаптер хардкодит набор инструментов пресетом
  `hermes-acp`. Состав пресета задаётся в плагине
  `plugins/model-providers/custom`
  (`_install_mai_acp_toolset_override`): полный реестр инструментов Hermes
  резолвится в момент сборки сессии (все штатные инструменты, включая
  terminal/файлы/execute_code; web_search/web_extract доступны, но в среде
  не работают — см. SOUL.md). Интернет — через собственные инструменты
  Hermes (терминал, curl, Python) и MCP `fetch_web_page`.

### Web (React + TypeScript)
Простой чат без регистрации и токенов:
- `App.tsx` — список сессий (UUID) хранится в `localStorage`, при первом
  входе сессия создаётся; восстановление активной сессии по UUID;
- `AssistantWorkspace.tsx` — история диалогов, переключение, удаление,
  сообщения, прикрепление изображений (base64 в теле запроса);
- `Portal.tsx` — `ChatShell`: шапка с брендом, без меню и аккаунта.

### Telegram
- бот работает через Telegram Bot API, polling только в Backend;
- текст/фото → `agent_sessions` (по `chat id`) → Hermes → ответ в чат;
- `/start` — начало чата; `/help` — справка;
- `/new` — новый диалог с чистым контекстом: `HermesClientManager
  .reset_session()` закрывает текущий ACP-процесс чата (терминация процесса
  и соединения), открывает новую сессию Hermes и обновляет привязку в
  `agent_sessions`. Старая сессия остаётся в истории Hermes (`state.db`), но
  больше не используется; следующее сообщение чата попадает именно в новую
  сессию; повторный `/new` создаёт ещё одну сессию. Привязка хранится в
  PostgreSQL, поэтому переживает перезапуск Backend;
- аккаунты и роли не создаются — только маппинг чата на сессию.

### Источники данных (фиксация архитектуры от 2026-11-24)

Три независимые БД на одном PostgreSQL-сервере + интернет:

1. **Синтетическая ФИС ГИА** — отдельная БД `mai_fis_gia` (таблицы
   `synthetic_ege_candidates` / `synthetic_ege_results`). Источник
   результатов ЕГЭ; доступна агенту ТОЛЬКО через MCP-инструменты и
   только для чтения: `search_synthetic_ege_results` (ФИО + дата
   рождения), `list_synthetic_ege_candidates` (список участников),
   `get_synthetic_ege_results` (результаты по `candidate_id`). Фикстура
   `backend/fixtures/synthetic_ege_registry.json`, загрузка — CLI
   `synthetic_ege_registry` (пишет в `mai_fis_gia`), автозагрузка при
   старте — `python -m app.init_databases`.
2. **Своя БД MAI-Agent** — отдельная БД `mai_agent`: абитуриенты
   `applicants`, баллы ЕГЭ `ege_scores`, заявления `applications`,
   рейтинги `ratings`, материалы приёма `knowledge_*`. Доступ агента —
   `sql_query`: произвольная SQL-команда PostgreSQL (SELECT, INSERT,
   UPDATE, DELETE, CREATE/ALTER/DROP и другие; в демонстрационной версии
   доступ намеренно открыт — без RBAC и ограничений по типам команд);
   одна команда на вызов; лимит 500 строк действует только на вывод
   результата SELECT, не на выполнение. Агент сам переносит данные из
   ФИС (через MCP) в свою БД (через SQL) и работает с ними.
3. **Интернет** — собственные инструменты Hermes: терминал, curl, Python
   (requests/urllib); для готовых страниц официального сайта удобнее
   `fetch_web_page` (HTTPS GET с SSRF-защитой, возврат текста страницы).

Служебная БД `mai_backend` (agent_sessions, telegram_checkpoints, alembic)
доступна только Backend и ни одному MCP-инструменту не видна.

## Сессии и их изоляция
- сессия (`agent_sessions`) — единственная сущность контекста:
  `id` (UUID, внешний идентификатор для Web), `source` (web|telegram),
  `external_id` (chat id для telegram), `hermes_session_id`;
- Web и Telegram используют **одного** агента (один профиль Hermes), но
  у каждой сессии — свой процесс ACP и своя сессия Hermes; контекст
  разных сессий не смешивается;
- восстановление: `hermes_session_id` стабилен; после перезапуска Backend
  сессия восстанавливается через `session/load` (replay истории из
  `state.db`); если сессия в хранилище Hermes потеряна — прозрачно
  создаётся новая, новый ID фиксируется в БД.

## Легаси
Система пользователей, ролей, приглашений, профилей, заявлений, документов и
достижений удалена из кода и БД (миграция `0013_sessionless_agents`);
старые файлы фронтенда (кабинеты, «самолёт») из бандла исключены.
Резервная копия БД до миграции: `mai_agent_pre_sessionless_*.sql`.
Откат — только восстановлением из резервной копии (downgrade намеренно
не реализован).

## Проверки
- `python -m pytest ../tests -q` (из `backend/`) — 39 тестов: SQL-инструмент,
  сессии (создание/история/изоляция/потеря сессии), Telegram-маппинг
  (включая `/new`: новая сессия, маршрутизация сообщений, повторный `/new`,
  персистентность привязки, E2E на реальном менеджере процессов),
  жизненный цикл Hermes (`start_session`/`reset_session`), реестр ФИС;
- `python scripts/e2e_minimal_agent.py` — сквозной E2E (нужен запущенный стек):
  создание сессии без авторизации, сообщение/ответ, история из Hermes,
  продолжение контекста, изображение, файл, терминал, SQL, ФИС-имитация,
  видимость штатных инструментов, изоляция сессий, маппинг Telegram.
