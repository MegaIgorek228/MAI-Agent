# Запуск MAI-Agent на другом ПК

Подробная инструкция, как развернуть MAI-Agent с нуля на новой машине (Windows, Linux или macOS). Всё приложение — Backend, Hermes (через ACP), веб-интерфейс и PostgreSQL — работает в Docker Compose. На хосте нужен только Docker; Python/Node не требуются, так как сборка происходит внутри контейнеров.

## Что будет запущено

| Сервис | Образ | Порт на хосте | Назначение |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | бизнес-данные + pgvector |
| `backend` | собирается из `backend/` | 8000 | FastAPI: API, бизнес-логика, ACP-клиент Hermes, MCP-сервер, Telegram polling |
| `frontend` | собирается из `frontend/` | 5173 | nginx + React: сайт абитуриента и кабинет сотрудника |

В образе `backend` уже установлены Hermes Agent 0.19 (включая `hermes-acp`) и ACP SDK 0.9 — отдельная установка Hermes на хосте **не нужна**: Backend запускает `hermes-acp` в stdio-режиме внутри собственного контейнера. Профиль Hermes без секретов копируется в образ из `backend/hermes-profile/`, API-ключ приходит только переменной окружения.

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

## Шаг 4. Первый сотрудник

Публичная регистрация создаёт только аккаунт абитуриента. Кабинет сотрудника появляется после регистрации по одноразовому коду приглашения; коды создаёт операторский CLI (HTTP-эндпоинта для выдачи нет, в БД хранится только SHA-256 хеш):

```powershell
# внутри контейнера backend (нужен DATABASE_URL — он уже там):
docker compose exec backend python -m app.admin_cli staff-invite create --days 7 --note "Имя сотрудника"
```

Вывод: `Invitation #1 created.`, `Code: <код>`, срок действия. Код выводится **один раз**.

Дальше:

1. Открыть http://localhost:5173 → «Зарегистрироваться».
2. Заполнить email/пароль и вставить код приглашения.
3. Войти под этим аккаунтом — вместо зоны абитуриента откроется «Рабочее место сотрудника».

Полезные команды CLI: `python -m app.admin_cli staff-invite list` (статусы), `... staff-invite revoke <id>` (отзыв неиспользованного).

## Шаг 5. Публикация правил приёма

Абитуриенты не могут подать заявление, пока сотрудник не опубликовал редакцию правил (комбо «год кампании + направление + основание» с требованиями к документам и, опционально, минимальным баллам):

1. Кабинет сотрудника → «Правила приёма» → создать редакцию и опубликовать.
2. После этого абитуриент видит направление в «Новое заявление».

Проверка требований при подаче считается по опубликованной редакции.

## Шаг 6. Синтетический реестр ЕГЭ (опционально)

Сверка работает по синтетическим записям с идентификаторами `SYN-`. В образ backend включён пример с анкетами и баллами. Загрузите его командой:

```bash
docker compose exec backend python -m app.synthetic_ege_registry /app/fixtures/synthetic_ege_registry.json
```

Для собственного файла укажите путь внутри контейнера. В локальной разработке выполните команду из каталога `backend` с настроенным `DATABASE_URL`:

```bash
cd backend
python -m app.synthetic_ege_registry fixtures/synthetic_ege_registry.json
```

В JSON анкеты находятся в массиве `candidates`, а баллы в массиве `results`. В кабинете абитуриента откройте черновик заявления, укажите и сохраните тестовый идентификатор `SYN-…`, затем нажмите «Обновить баллы из тестового реестра». В чате ассистент может найти тестовую запись по ФИО и дате рождения и привязать её после подтверждения. Чтобы применить исправление к ранее загруженным тестовым записям, добавьте к команде `--replace-conflicts`.

## Шаг 7. Проверка рабочего сценария

Короткий сценарий для подтверждения, что всё живое:

1. **Абитуриент**: зарегистрироваться → заполнить профиль → загрузить документ → создать заявление по опубликованным правилам → подать.
2. **Сотрудник**: в очереди «Проверка документов» открыть файл, взять заявление на проверку и зафиксировать решение. Если нужен новый файл, оставить комментарий к документу и вернуть заявление на доработку.
3. **Абитуриент**: в заявлении виден статус решения и комментарий; при «Требуются изменения» можно загрузить исправленный документ и отправить снова.
4. **Чат**: в «Салоне» написать вопрос — ответ приходит через Hermes (первый запрос на сессию может занять до минуты: запуск ACP-процесса).

## Обновление после изменений в репозитории

```powershell
git pull
docker compose up --build -d
```

- Миграции применяются автоматически при старте backend.
- Данные живут в именованном volume `postgres_data` и **не сбрасываются** при пересборке. `docker compose down` без `--volumes` данные сохраняет.
- После пересборки фронтенда браузеру не нужно ничего очищать: `index.html` отдаётся с `Cache-Control: no-cache`, ассеты хешируются Vite.

## Резервное копирование БД

```bash
docker exec mai-agent-postgres-1 pg_dump -U mai_agent -d mai_agent > backup_$(date +%F).sql
# восстановление (в пустую БД):
docker exec -i mai-agent-postgres-1 psql -U mai_agent -d mai_agent < backup_2026-11-22.sql
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

Сквозной E2E на Compose-стенде (создаёт собственные синтетические аккаунты и данные; автор рекомендует гонять его на изолированном стенде — нужен Python с `httpx` и `Pillow`):

```powershell
pip install httpx pillow
python scripts/e2e_compose.py
```

Настройки скрипта — переменные `MAI_E2E_BASE_URL` (по умолчанию `http://127.0.0.1:5173`) и `MAI_E2E_BACKEND_CONTAINER` (по умолчанию `mai-agent-backend-1`). Результат пишется в `scripts/e2e_compose_result.json`.

## Чек-лист готовности нового ПК

- [ ] `docker compose ps` показывает запущенный frontend и статус healthy у backend и PostgreSQL.
- [ ] `curl http://localhost:8000/ready` — 200.
- [ ] http://localhost:5173 — открывается сайт приёмной комиссии.
- [ ] Создан и использован код приглашения — сотрудник видит рабочее место.
- [ ] Опубликована редакция правил — абитуриент может подать заявление.
- [ ] Чат отвечает (задан `LLM_API_KEY`).
- [ ] (Опционально) Telegram-бот отвечает.
