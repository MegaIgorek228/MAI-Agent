# Архитектура MAI-Agent

Концепция от 2026-11-23 (рабочая). Полное описание правил — в [AGENTS.md](../AGENTS.md),
развёртывание — в [DEPLOYMENT.md](DEPLOYMENT.md).

## Обобщённая схема

```text
   Web (чат)                 Telegram (бот)
      │                          │
      ▼                          ▼
┌─────────────────────────────────────────────┐
│ Backend (FastAPI)                           │
│  • авторизация (JWT)                        │
│  • /chat — транспорт сессий и сообщений     │
│  • Telegram polling (только здесь)          │
│  • /mcp — FastMCP-сервер (встроен)          │
│  • hermes_client.py — пул процессов ACP    │
└──────────────┬──────────────────────────────┘
               │ ACP (stdio), сессия на пользователя
               ▼
┌─────────────────────────────────────────────┐
│ Hermes Agent (hermes-acp 0.19.0, в образе)  │
│  • диалог, планирование, память MEMORY.md   │
│  • штатные инструменты:                     │
│    terminal, process, read_file, write_file,│
│    patch, search_files, execute_code,       │
│    memory, session_search, todo             │
│  • изображения — нативный vision модели     │
└──────┬──────────────────────────────────────┘
       │ MCP (сессия)
       ▼
┌─────────────────────────────────────────────┐
│ MCP-инструменты (внутри Backend)            │
│  • sql_query — read-only SQL (источник 2)   │
│  • имитация ФИС ГИА — synthetic_ege_*      │
│  • fetch_web_page — веб-страницы МАИ        │
│  • legacy: инструменты приёмной кампании    │
└──────────────┬──────────────────────────────┘
               ▼
        PostgreSQL (users, chat_sessions,
        synthetic_ege_*, knowledge_*, ...)
```

## Компоненты

### Backend (FastAPI)
Транспортный мост, не несёт агентной логики:
- авторизация и пользователи (JWT);
- `/chat/sessions`, `/chat/sessions/{id}/messages` — приём сообщения, передача в Hermes
  через ACP, сохранение сообщений (история диалогов для UI);
- Telegram: polling и обработка сообщений/фото в `app/telegram_service.py`;
  каждому чату автоматически создаётся пользователь (роль `applicant`);
- `/mcp` — FastMCP-сервер (`app/mcp_tools.py`), доступ по доверенному контексту
  (заголовок `x-mai-context`, выдаётся Backend'ом на сессию ACP);
- `app/hermes_client.py` — пул процессов `hermes-acp` (stdio), сессия ACP на
  пользователя, восстановление сессий Hermes (`load_session`).

### Hermes Agent
- пакет `hermes-agent` 0.19.0, процесс `hermes-acp` внутри образа backend
  (`/usr/local/bin/hermes-acp`), профиль — `backend/hermes-profile`
  (запечён в `/root/.hermes`);
- модель: `deepseek-v4.1-flash` через MAI relay (OpenAI-совместимый API,
  именованный провайдер `custom:mai`, плагин `plugins/model-providers/custom`);
- изображения от пользователей идут нативно в модель (`agent.image_input_mode: native`);
- память — штатная `MEMORY.md` и сессии Hermes (SQLite в профиле);
- **важная особенность**: ACP-адаптер хардкодит набор инструментов пресетом
  `hermes-acp` и игнорирует `platform_toolsets` из config.yaml. Состав пресета
  задаётся плагинном `plugins/model-providers/custom` (`_install_mai_acp_toolset_override`):
  терминал, файлы, execute_code, memory, session_search, todo.
  Web-инструменты Hermes (web_search/web_extract) в пресете намеренно отсутствуют
  (нет платных ключей поисковых бэкендов) — за страницами агент ходит через MCP
  `fetch_web_page`.

### Web (React + TypeScript)
Простой чат с агентом:
- `App.tsx` — аутентификация и единственный экран `SessionWorkspace`
  (режим `Workspace chatOnly`: шапка с брендом, пользователем и выходом, без
  навигации по кабинетам);
- `AssistantWorkspace.tsx` — история диалогов, сообщения, прикрепление изображений;
- компоненты кабинетов (Applications, Documents, Achievements, Staff) в бандле
  не используются (файлы пока остаются — см. «Легаси»).

### Telegram
- бот работает через Telegram Bot API, polling только в Backend
  (в Hermes gateway polling отключён);
- текст/фото → пользователь → сессия чата → Hermes → ответ в чат;
- профиль и роли не требуются: аккаунт создаётся автоматически при первом сообщении.

### Источники данных (через MCP)
1. **Имитация ФИС ГИА** — таблицы `synthetic_ege_candidates` / `synthetic_ege_results`,
   фикстура `backend/fixtures/synthetic_ege_registry.json`, загрузка фикстуры —
   CLI `synthetic_ege_registry`. Инструменты: поиск по ФИО + дате рождения,
   результаты, подтверждение.
2. **SQL-хранилище** — инструмент `sql_query`: одна read-only SELECT/WITH-команда,
   лимит 500 строк, доступ к `knowledge_*` (официальные материалы приёма) и данным
   приёмной кампании; таблицы `users` и `staff_invites` запрещены.

## Сессии и разделение пользователей
- каждый пользователь (Web или Telegram) имеет собственные чат-сессии Backend
  и собственную сессию Hermes (маппинг `chat_sessions.hermes_session_id`);
- Web и Telegram используют одного агента (один профиль Hermes), но сессии
  изолированы: история одного пользователя не видна другому.

## Легаси (удаляется после проверки новой версии)
В коде ещё остаются компоненты старого сценария приёмной кампании:
- backend: `admissions_service.py`, `document_service.py`, `achievement_service.py`,
  роутеры заявлений/документов/достижений, связанные MCP-инструменты,
  таблицы `applications`, `documents`, `individual_achievements` и миграции;
- frontend: файлы `Admissions.tsx`, `Documents.tsx`, `Achievements.tsx`,
  `StaffApplications.tsx`, `Cockpit.tsx` (не включены в бандл чата).

Удаление этих модулей, инструментов и таблиц — отдельный этап по явному решению
владельца проекта, после успешной эксплуатации упрощённой версии.

## Проверки
- `python -m pytest ../tests -q` (из `backend/`);
- `python scripts/e2e_minimal_agent.py` — сквозной E2E (нужен запущенный стек):
  сообщение/ответ, история, изображение, файл, терминал, SQL, ФИС-имитация,
  видимость штатных инструментов, разделение сессий двух пользователей.
