# MAI-Agent

ИИ-агент для Московского авиационного института (МАИ): помощь абитуриентам
по вопросам приёма — направления подготовки, проходные баллы, документы,
сроки. Архитектура — **sessionless**: пользовательских аккаунтов, профилей,
ролей и JWT нет; единственная единица пользовательского контекста — сессия
агента.

## Архитектура

- **Hermes Agent** — единственный агент: диалог, планирование, штатный
  инструментарий (терминал, файловая система, работа с файлами, выполнение
  кода, память `MEMORY.md`, поиск по истории сессий).
- **Backend** — минимальный транспортный мост (FastAPI) между Web, Telegram
  и Hermes через ACP (stdio). Собственной агентной логики не несёт.
- **Web** — простой чат с агентом (React + TypeScript), без регистрации:
  клиент работает с идентификатором сессии.
- **Telegram** — чат с тем же агентом; polling выполняется только в Backend.
  `chat id` используется лишь для сопоставления чата с сессией.
- **Сессии и память** — история диалога и долговременная память хранятся в
  штатных механизмах Hermes (`state.db`, `MEMORY.md`); Backend не дублирует
  их. Сессии восстанавливаются после перезапуска Backend.
- **MCP-сервер** (встроен в Backend, FastMCP) — источники данных для агента:
  1. синтетическая ФИС ГИА (отдельная БД `mai_fis_gia`, источник
     результатов ЕГЭ; только чтение: `search_synthetic_ege_results`,
     `list_synthetic_ege_candidates`, `get_synthetic_ege_results`);
  2. собственная БД агента (`mai_agent`: applicants, ege_scores,
     applications, ratings, knowledge_*) — `sql_query` (произвольные
     SQL-команды: SELECT, INSERT, UPDATE, DELETE, DDL; 500 строк — лимит
     вывода SELECT); агент сам переносит данные из ФИС в свою БД;
  3. интернет — собственные инструменты Hermes (терминал, curl, Python).

Хранилище Backend — PostgreSQL, три независимые БД: `mai_backend`
(служебная: `agent_sessions`, `telegram_checkpoints`), `mai_agent` (своя
БД агента), `mai_fis_gia` (синтетическая ФИС ГИА). Схема служебной БД — в
миграциях Alembic; две остальные создаются `python -m app.init_databases`
при старте backend.

## Технологии

Python, FastAPI, Hermes Agent, ACP, MCP/FastMCP, PostgreSQL, React,
TypeScript, Docker Compose. Модель — `deepseek-v4.1-flash` через MAI relay
(`api-ai.mai.ru/v1`, OpenAI-совместимый API).

Полное описание — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), правила
работы — [AGENTS.md](AGENTS.md), развёртывание — [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Структура проекта

```text
.
├── AGENTS.md
├── README.md
├── docker-compose.yml
├── .env.example
├── backend/            # FastAPI: транспорт, ACP-клиент, MCP, Telegram
│   ├── alembic/        # миграции
│   ├── fixtures/       # синтетический реестр ЕГЭ (ФИС-имитация)
│   └── hermes-profile/ # профиль Hermes: config.yaml, SOUL.md, плагины
├── frontend/           # React + TypeScript: чат с агентом
├── scripts/            # e2e-проверки (e2e_minimal_agent.py)
├── tests/              # pytest (48 тестов)
└── docs/               # архитектура, развёртывание, статус
```

## Локальный запуск

Секреты (ключ MAI API, пароль БД, токен бота) — только в локальном `.env`
(шаблон — `.env.example`):

```powershell
Copy-Item .env.example .env   # вставить LLM_API_KEY, при необходимости POSTGRES_PASSWORD
docker compose up --build -d
```

При старте Backend автоматически применяет миграции Alembic. Веб-интерфейс —
**http://localhost:5173**, backend — `http://localhost:8000`
(`GET /ready` — проверка готовности и текущей ревизии схемы).

Telegram стартует при заданном `TELEGRAM_BOT_TOKEN`; команды бота:
`/start`, `/new` (новый диалог с чистым контекстом), `/help`.

Если `api-ai.mai.ru` использует внутренний сертификат, укажите
`AI_API_CA_BUNDLE=/app/certs/mai-api-ca-chain.pem` (цепочка уже в `certs/`).

## Синтетический реестр ЕГЭ

Агент ищет участников ЕГЭ в синтетическом реестре (имитация ФИС ГИА).
Пример с анкетами и результатами (`SYN-…`) включён в образ; загрузка:

```bash
docker compose exec backend python -m app.synthetic_ege_registry /app/fixtures/synthetic_ege_registry.json
```

ФИС ГИА и ЕСИА как внешние системы в проекте отсутствуют — используется
только синтетическая имитация.

## Проверки

```bash
# unit-тесты (48): SQL-инструмент, сессии, Telegram (включая /new),
# жизненный цикл Hermes, реестр ФИС, ФИС-MCP-инструменты
cd backend
python -m pytest ../tests -q

# сквозной E2E (20 проверок, нужен запущенный стек)
python scripts/e2e_minimal_agent.py
```

Секреты и реальные персональные данные в репозиторий не попадают;
тестовые данные — только синтетические.
