# Запуск MAI-Agent на другом ПК

Подробная инструкция, как развернуть MAI-Agent с нуля на новой машине (Windows, Linux или macOS). Всё приложение — Backend, Hermes (через ACP), веб-интерфейс и PostgreSQL — работает в Docker Compose. На хосте нужен только Docker; Python/Node не требуются, так как сборка происходит внутри контейнеров.

## Что будет запущено

| Сервис | Образ | Порт на хосте | Назначение |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | бизнес-данные + pgvector |
| `backend` | собирается из `backend/` | 8000 | FastAPI: минимальный транспортный мост Web/Telegram ↔ Hermes (ACP), встроенный MCP-сервер (источники данных для агента), Telegram polling. Собственной предметной бизнес-логики нет — решения и действия выполняет Hermes |
| `frontend` | собирается из `frontend/` | 5173 | nginx + React: чат с агентом |

В образе `backend` уже установлены Hermes Agent 0.19 (включая `hermes-acp`) и ACP SDK 0.9 — отдельная установка Hermes на хосте **не нужна**: Backend запускает `hermes-acp` в stdio-режиме внутри собственного контейнера. Профиль Hermes без секретов копируется в образ из `backend/hermes-profile/`, API-ключ приходит только переменной окружения.

Целевая архитектура (sessionless): **Hermes — единственный агент** (штатный инструментарий: терминал, файлы, память `MEMORY.md`) и среда выполнения агентных задач; **Backend — минимальный транспортный мост** между Web, Telegram и Hermes через ACP — без собственной предметной бизнес-логики и без самостоятельных решений за агента; **MCP и SQL — внешние источники и инструменты**, доступные Hermes; **Web и Telegram — две поверхности** взаимодействия с одним Hermes, каждая с независимыми сессиями.

## Требования к машине

- Docker Desktop (Windows/macOS) или Docker Engine + Compose plugin (Linux), версия Compose v2.
- Доступ в интернет (сборка образов, вызовы LLM API `api-ai.mai.ru`).
- ~10–15 ГБ свободного места, 4+ ГБ RAM для комфортной сборки.
- Свободные порты: 5432, 8000, 5173.
- Опционально для тестов: Python 3.12+ (unit-тесты и E2E-скрипт).

## Шаг 1. Клонирование репозитория

Основная ветка — `master` (единственная «боевая»; рабочие ветки создаются от неё).

```powershell
git clone https://github.com/MegaIgorek228/MAI-Agent.git
cd MAI-Agent
```

Для разработки создайте собственную ветку от `master`, например:

```powershell
git switch -c fixes/<название-задачи>
```

## Шаг 2. Файл окружения `.env`

В корне лежит `.env.example`. Создайте на его основе локальный файл (он в `.gitignore`, в репозиторий не попадает):

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
# Linux/macOS
cp .env.example .env
```

Минимум, что нужно поменять:

| Переменная | Что сделать | Зачем |
|---|---|---|
| `LLM_API_KEY` | вставить ключ MAI API (`api-ai.mai.ru`) | чат с ассистентом и анализ документов; без него приложение поднимется, но ИИ-функции не будут работать |
| `POSTGRES_PASSWORD` | задать своё случайное URL-безопасное значение | пароль БД подставляется в строку подключения (по умолчанию `change_me`) |

Авторизации нет (sessionless-архитектура): `JWT_SECRET_KEY` больше не требуется.

Опциональные:

- `TELEGRAM_BOT_TOKEN` — токен бота; polling выполняется **только** Backend (в Hermes Telegram-канал отключён). Пустое значение — Telegram просто не стартует.
- `AI_API_CA_BUNDLE` — путь к CA-цепочке внутри контейнера, если `api-ai.mai.ru` использует внутренний сертификат: `AI_API_CA_BUNDLE=/app/certs/mai-api-ca-chain.pem`. В каталоге `certs/` (монтируется в `/app/certs`) уже лежит готовая цепочка; в публичных сетях обычно достаточно оставить пустым.
- `HERMES_MODEL` — по умолчанию `deepseek-v4.1-flash`; `HERMES_REASONING_EFFORT=low`.

Пример минимального `.env`:

```ini
APP_ENV=development
POSTGRES_DB=mai_agent
POSTGRES_USER=mai_agent
POSTGRES_PASSWORD=<свой-пароль>
LLM_BASE_URL=https://api-ai.mai.ru/v1
LLM_API_KEY=<ключ MAI API>
HERMES_MODEL=deepseek-v4.1-flash
HERMES_BASE_URL=https://api-ai.mai.ru/v1
HERMES_REASONING_EFFORT=low
TELEGRAM_BOT_TOKEN=
```

## Шаг 3. Сборка и запуск

```powershell
docker compose up --build -d
```

Первая сборка занимает несколько минут (устанавливаются зависимости Python и сборка React). При старте Backend автоматически применяет миграции Alembic (`alembic upgrade head` в команде контейнера) — вручную миграции запускать не нужно.

Проверка готовности:

```powershell
# HTTP 200 = PostgreSQL отвечает и схема на текущей ревизии
curl http://localhost:8000/ready
# {"status":"ready"}
curl http://localhost:8000/health
```

Состояние контейнеров:

```powershell
docker compose ps
```

Все три сервиса должны быть `healthy`/`running`. Веб-интерфейс: **http://localhost:5173**.

## Шаг 4. Синтетический реестр ЕГЭ (ФИС ГИА)

Синтетическая ФИС ГИА — отдельная БД `mai_fis_gia` на том же PostgreSQL.
Базовая фикстура (участники `SYN-*` с баллами) создаётся **автоматически
при старте backend** (`python -m app.init_databases`, вызывается в
entrypoint до миграций): если реестр пуст — загружается `fixtures/synthetic_ege_registry.json`.

Для обновления или собственного файла:

```bash
docker compose exec backend python -m app.synthetic_ege_registry /app/fixtures/synthetic_ege_registry.json
```

Команда пишет именно в БД `mai_fis_gia` (не в служебную). В локальной
разработке — из каталога `backend` с настроенным `DATABASE_URL`:

```bash
cd backend
python -m app.synthetic_ege_registry fixtures/synthetic_ege_registry.json
```

В JSON анкеты находятся в массиве `candidates`, а баллы в массиве `results`. Агент находит тестовую запись по ФИО и дате рождения через MCP-инструмент `search_synthetic_ege_results`, листает реестр через `list_synthetic_ege_candidates` / `get_synthetic_ege_results` и переносит данные в собственную БД (`sql_query`). Чтобы применить исправление к ранее загруженным записям, добавьте к команде `--replace-conflicts`.

## Шаг 5. Проверка рабочего сценария

Короткий сценарий для подтверждения, что всё живое:

1. **Web**: открыть http://localhost:5173 — страница чата без регистрации (сессия создаётся автоматически). Написать вопрос — ответ приходит через Hermes (первый запрос на сессию может занять до минуты: запуск ACP-процесса). Отправить изображение — агент проанализирует его нативным vision.
2. **Источники данных**: попросить агента показать результаты ЕГЭ тестового участника (например, «Алексей Иванович Иванов», 14.03.2008) — ответ придёт из синтетической ФИС ГИА; попросить перенести данные участника в его собственную БД — агент прочтёт ФИС через MCP и запишет через `sql_query` (таблицы `applicants`/`ege_scores` в БД `mai_agent`).
3. **Telegram**: отправить боту `/start`, затем вопрос — ответ от того же агента. Команда `/new` начинает новый диалог с чистым контекстом (создаётся новая сессия Hermes, предыдущая история не переносится).
4. **Восстановление**: после `docker compose restart backend` история диалога восстанавливается — она хранится в хранилище Hermes (volume `hermes_home`), а не в памяти процесса.

## Обновление после изменений в репозитории

```powershell
git pull
docker compose up --build -d
```

- Миграции применяются автоматически при старте backend.
- Данные живут в именованном volume `postgres_data` и **не сбрасываются** при пересборке. `docker compose down` без `--volumes` данные сохраняет.
- После пересборки фронтенда браузеру не нужно ничего очищать: `index.html` отдаётся с `Cache-Control: no-cache`, ассеты хешируются Vite.

## Резервное копирование БД

На сервере PostgreSQL живут три независимые БД: `mai_backend` (служебная),
`mai_agent` (собственная БД агента), `mai_fis_gia` (синтетическая ФИС ГИА).
Каждую копируйте отдельно:

```bash
for db in mai_backend mai_agent mai_fis_gia; do
  docker exec mai-agent-postgres-1 pg_dump -U mai_agent -d "$db" > "backup_${db}_$(date +%F).sql"
done
# восстановление (в пустую БД):
docker exec -i mai-agent-postgres-1 psql -U mai_agent -d mai_agent < backup_mai_agent_2026-11-24.sql
```

## Устранение неполадок

| Симптом | Причина / решение |
|---|---|
| `port is already allocated` при `up` | Освободите занятый порт или измените порт слева в соответствующей записи `ports` файла `docker-compose.yml`. Например, `"5433:5432"` публикует PostgreSQL на 5433. |
| Backend в цикле перезапусков, в логах ошибка миграции | `docker logs mai-agent-backend-1` — обычно видна конкретная причина (например, конфликт ревизий). Миграции транзакционные, БД не повреждается. |
| Чат отвечает ошибкой про провайдера/модель | Не задан `LLM_API_KEY` в `.env` (после правки — `docker compose up -d backend`). Без ключа Hermes падает на дефолтный провайдер. |
| Ошибки TLS при вызовах LLM | Установить `AI_API_CA_BUNDLE=/app/certs/mai-api-ca-chain.pem` в `.env` и пересоздать backend. |
| Первый ответ чата очень долгий | Это нормальный запуск ACP-процесса (`ACP_STARTUP_TIMEOUT_SECONDS=180`); последующие ответы в сессии быстрее. |
| Telegram не отвечает | Проверить `TELEGRAM_BOT_TOKEN`; логи: `docker logs mai-agent-backend-1 \| findstr telegram` (Windows) / `grep telegram` (Linux). Polling только в Backend — параллельный polling из других клиентов дублирует сообщения. |
| Фронтенд «пустой»/старый JS | Жёсткая перезагрузка страницы (Ctrl+Shift+R). Нормально — только что после деплоя браузер мог держать старый `index.html` до обновления кэша. |
| Нужны логи Hermes | `docker logs mai-agent-backend-1` — ACP-журнал пишется туда же. |

## Тесты на новой машине

Unit/API-тесты (нужен только Python, Docker не требуется — `tests/conftest.py` подставляет тестовую SQLite-БД):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows; в Linux/macOS: source .venv/bin/activate
pip install -e ".[test]"
python -m pytest ../tests -q
```

Сквозной E2E на Compose-стенде (20 проверок: сессии, контекст, MCP-инструменты,
штатные инструменты Hermes, изоляция сессий, Telegram-привязка; нужен только
Python со стандартной библиотекой):

```powershell
python scripts/e2e_minimal_agent.py
```

Скрипт создаёт собственные тестовые сессии (не удаляет их — при желании
они удаляются из `agent_sessions` вручную). Результат пишется в
`scripts/e2e_minimal_agent_result.json`.

## Чек-лист готовности нового ПК

- [ ] `docker compose ps` показывает запущенный frontend и статус healthy у backend и PostgreSQL.
- [ ] `curl http://localhost:8000/ready` — 200.
- [ ] http://localhost:5173 — открывается чат с агентом (без регистрации).
- [ ] Чат отвечает (задан `LLM_API_KEY`): Web и Telegram.
- [ ] Telegram-бот: `/new` начинает новый диалог.
- [ ] `python scripts/e2e_minimal_agent.py` — 20/20 PASS.
