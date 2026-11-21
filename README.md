# MAI-Agent

ИИ-агент для Московского авиационного института (МАИ). Проект предназначен для помощи абитуриентам и сотрудникам приёмной комиссии: ответы по правилам приёма, работа с профилями, заявлениями и документами, проверка комплектности и сверка результатов ЕГЭ с синтетическим реестром.

## Архитектура

- **Hermes Agent** — готовая среда диалогов, планирования и вызова инструментов.
- **Backend** — FastAPI для HTTP API, бизнес-логики, авторизации и интеграций.
- **ACP** — протокол взаимодействия Backend с Hermes.
- **MCP-сервер** — FastMCP-инструменты МАИ, вызываемые Hermes.
- **Хранилище** — PostgreSQL для бизнес-данных и pgvector для векторного поиска.
- **Web** — React + TypeScript.
- **Каналы доступа** — Web и Telegram. Polling выполняет Backend.

Hermes не обращается к PostgreSQL напрямую. Доступ к данным предоставляется через backend API или MCP-инструменты. Hermes хранит собственные сессии в SQLite. Backend использует PostgreSQL с pgvector в Compose и поддерживает SQLite для локальных тестов.

## Технологии

Python, FastAPI, Hermes Agent, ACP, MCP/FastMCP, PostgreSQL, pgvector, React, TypeScript и Docker Compose.

Compose использует Hermes 0.19, ACP SDK 0.9 и FastMCP 2.14.7. Модель для чата и анализа документов по умолчанию — `deepseek-v4.1-flash`, для эмбеддингов — `bge-m3` (1024 измерения).

## Структура проекта

```text
.
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── backend/            # FastAPI-приложение, бизнес-логика и миграции
│   └── hermes-profile/ # настройки Hermes без секретов
├── frontend/           # React + TypeScript
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
npm ci
npm run dev
```

Docker Compose:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Backend применяет миграции при старте в Compose. Веб-интерфейс доступен на `http://localhost:5173`. Маршрут `/ready` проверяет, что PostgreSQL отвечает и схема обновлена до текущей ревизии.

Для чата и анализа задайте `LLM_API_KEY` в локальном файле `.env`. `HERMES_MODEL` управляет чатом, `DOCUMENT_MODEL` — анализом документов. Векторный поиск включается, если задать `EMBEDDING_BASE_URL` и `EMBEDDING_API_KEY`. При необходимости укажите `AI_API_CA_BUNDLE=/app/certs/mai-api-ca-chain.pem`. Telegram запускается при наличии `TELEGRAM_BOT_TOKEN`.

## Заявления и правила

Сотрудник публикует редакцию правил на экране «Рабочее место». Абитуриент создаёт черновик, выбирает кампанию, код направления и основание, прикладывает документы и подаёт заявление. Сотрудник проверяет полученный пакет и фиксирует результат. Проверка минимальных баллов выполняется по выбранной редакции правил.

Испытательный реестр ЕГЭ заполняется отдельной командой из каталога `backend`. Файл содержит только синтетические результаты и идентификаторы с префиксом `SYN-`.

```sh
python -m app.synthetic_ege_registry /path/to/synthetic-results.json
```

Пример элемента файла:

```json
{"candidate_id":"SYN-DEMO","subject":"Математика","year":2026,"score":85,"status":"valid"}
```

Результат синтетической сверки сохраняется отдельно от баллов, введённых абитуриентом. ФИС ГИА и ЕСИА отсутствуют в архитектуре.

## Поиск по базе знаний

Выдача включает ссылку и редакцию источника. После смены модели эмбеддингов или обновления со старой схемы сотрудник может перестроить векторы через `POST /knowledge/sources/{id}/reindex`. Лексический поиск работает и по источникам, для которых эмбеддинги ещё не построены.

## Проверки

Запустите `python -m pytest tests` из корня после установки `pip install -e './backend[test]'` в тестовое окружение. Скрипт `scripts/e2e_compose.py` проверяет сквозной путь на отдельном стенде с синтетическими данными. Его настройки `MAI_E2E_BASE_URL` и `MAI_E2E_BACKEND_CONTAINER` позволяют выбрать опубликованный Web и контейнер Backend.

## Правила разработки

Правила проекта и архитектурные ограничения находятся в [AGENTS.md](AGENTS.md). Секреты и реальные персональные данные не должны попадать в репозиторий.
