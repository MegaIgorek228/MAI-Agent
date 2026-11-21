# MAI-Agent

ИИ-агент для Московского авиационного института (МАИ). Проект предназначен для помощи абитуриентам и сотрудникам приёмной комиссии: ответы по правилам приёма, работа с документами и профилями, проверка комплектности документов и получение официальных результатов экзаменов.

## Архитектура

- **Hermes Agent** — готовая среда диалогов, планирования и вызова инструментов.
- **Backend** — FastAPI для HTTP API, бизнес-логики, авторизации и интеграций.
- **ACP** — протокол взаимодействия Backend с Hermes.
- **MCP-сервер** — FastMCP-инструменты МАИ, вызываемые Hermes.
- **Хранилище** — PostgreSQL для бизнес-данных и pgvector для векторного поиска.
- **Web** — React + TypeScript.
- **Каналы доступа** — Web и Telegram; совместимость Telegram с выбранными компонентами требует проверки.

Hermes не обращается к PostgreSQL напрямую. Доступ к данным предоставляется через backend API или MCP-инструменты. SQLite используется только для внутреннего состояния Hermes.

## Технологии

Python, FastAPI, Hermes Agent, ACP, MCP/FastMCP, PostgreSQL, pgvector, React, TypeScript и Docker Compose.

Конкретные версии, зависимости и способы запуска будут определены после проверки официальной документации и закрытия технических вопросов.

## Структура проекта

```text
.
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── backend/            # FastAPI-приложение, бизнес-логика и миграции
├── mcp_server/         # MCP-сервер инструментов МАИ
├── frontend/           # React + TypeScript
├── hermes/             # конфигурация Hermes без секретов
├── docs/               # архитектура, решения и открытые вопросы
└── tests/              # тесты проекта
```

## Локальный запуск

Backend:

```powershell
cd backend
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -e ".[test]"
$env:DATABASE_URL = "sqlite:///./mai-agent.db"
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Docker Compose:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Для Docker-маршрута миграции выполняются отдельно после запуска PostgreSQL:

```powershell
docker compose run --rm backend alembic upgrade head
```

## Статус разработки

Этап 3: реализованы ACP client на официальном Python SDK, lifecycle chat-сессий, MCP HTTP server configuration с доверенным контекстом, Qwen-compatible document analysis, pgvector semantic search при настроенном embedding provider, синхронизация официальных HTTPS-материалов по allowlist, admission requirements и chat UI. Полный ACP smoke test требует штатно настроенного Hermes provider; конкретные Qwen endpoints, официальные домены МАИ, Telegram и ФИС ГИА остаются внешними ограничениями. Подробный статус находится в [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).

Доступные Backend-маршруты включают `/auth/register`, `/auth/login`, `/users/me`, `/applicant/profile`, `/applicant/documents`, `/applicant/documents/completeness`, `/knowledge/sources` и `/knowledge/search`.

## Правила разработки

Правила проекта и архитектурные ограничения находятся в [AGENTS.md](AGENTS.md). Секреты и реальные персональные данные не должны попадать в репозиторий.
