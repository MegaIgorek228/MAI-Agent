# MAI-Agent — итоговый отчёт и пакет передачи

> **Устаревший документ (исторический).** Описание относится к старой
> пользовательской архитектуре (аккаунты, роли, JWT, кабинеты). Актуальная
> sessionless-концепция: [ARCHITECTURE.md](ARCHITECTURE.md),
> [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). Документ сохранён для
> истории, не является инструкцией.

Актуальность: 2026-11-21 (после финальной контейнерной интеграционной проверки).

## 1. Состав репозитория

| Путь | Назначение |
|---|---|
| `backend/` | FastAPI: авторизация/роли, профиль абитуриента, документы, чат (ACP), база знаний (pgvector), workspace сотрудников, Telegram polling |
| `backend/hermes-profile/` | Hermes home для контейнера (без секретов): `config.yaml` + override-плагин провайдера (reasoning-фикс для MAI) |
| `backend/alembic/` | Миграции 0001–0005 |
| `frontend/` | React + TypeScript (Vite); nginx в Docker-образе |
| `tests/` | 19 автотестов бэкенда (auth, роли, профиль, документы, чат, изображения, Telegram) |
| `scripts/e2e_compose.py` | E2E из 9 сценариев против поднятого compose-стека (живые ACP+Qwen) |
| `docker-compose.yml` | postgres (`pgvector:pg16`) + backend + frontend |
| `certs/mai-api-ca-chain.pem` | Публичная цепочка CA MAI-реле (Russian Trusted Root CA) — обязательна для TLS, приватных ключей не содержит |
| `docs/` | ARCHITECTURE, TECHNICAL_DECISIONS, IMPLEMENTATION_STATUS, HANDOFF (этот отчёт) |
| `.env.example` | Шаблон окружения (только плейсхолдеры, без секретов) |
| `IMPLEMENTATION_STATUS.md` | Детализация реализованного и всех исправлений финальной проверки |

## 2. Запуск из чистого клона

```bash
cp .env.example .env
# Заполнить в .env:
#   QWEN_API_KEY=<ключ MAI API>              — обязателен (чат, анализ, эмбеддинги)
#   POSTGRES_PASSWORD=<сложный пароль>       — обязателен
#   JWT_SECRET_KEY=<случайная строка>        — обязателен
#   TELEGRAM_BOT_TOKEN=<токен>               — опционально (без токена Telegram-модуль не стартует)
#   AI_API_CA_BUNDLE=/app/certs/mai-api-ca-chain.pem   — обязателен для MAI-реле

docker compose up -d --build
docker compose exec backend alembic upgrade head

# Проверка:
curl http://localhost:8000/health          # -> 200 OK
# Веб-интерфейс: http://localhost:5173
```

Порты: `5432` — PostgreSQL, `8000` — backend API, `5173` — фронтенд.
API-ключи и токены — только в `.env` (вне репозитория); в образе контейнера ключ передаётся через env (`OPENAI_API_KEY`/`QWEN_API_KEY`), `key_env` в профиле Hermes ссылается на него.

## 3. Команды проверок и результаты (2026-11-21)

| Проверка | Команда | Результат |
|---|---|---|
| Автотесты (хост) | `cd backend && python -m pytest ../tests -q` | **19/19 passed** |
| Автотесты (в контейнере) | `docker run --rm -v <repo>/tests:/app/tests --entrypoint python mai-agent-backend:latest -m pytest tests -q` | **19/19 passed** |
| Версии в образе | `docker run --rm --entrypoint python mai-agent-backend:latest -c "from importlib.metadata import version; print(version('agent-client-protocol'), version('hermes-agent'))"` | acp 0.9.0 + hermes-agent 0.19.0 |
| Адаптер ACP в образе | `docker run --rm --entrypoint python mai-agent-backend:latest -c "import acp_adapter.entry, acp_adapter.server; from acp.schema import ModelInfo; print('OK')"` | PASS |
| Бинарь `hermes-acp` | `docker run --rm --entrypoint sh mai-agent-backend:latest -c "which hermes-acp"` | PASS |
| Compose-стек | `docker compose up -d backend frontend` + `/health` | PASS |
| E2E 9 сценариев | `python scripts/e2e_compose.py` (нужны `httpx`, `PIL`; стек должен быть запущен на localhost) | **9/9 PASS** |
| Скан reasoning-400 | `docker compose logs backend \| grep -i "reasoning"` + логи Hermes в контейнере | **0 ошибок 400** |
| Миграции | `docker compose exec backend alembic upgrade head` (0001→0005); 0005 downgrade/upgrade проверен | PASS |
| Фронтенд | `tsc -b` + `vite build` (хост и Docker-сборка); nginx-роуты проверены в образе | PASS |

Результаты E2E (2026-11-21 20:15, 33 с, реальные вызовы Qwen из контейнера):
1. `1_auth` — регистрация + JWT + `/users/me` — PASS
2. `2_roles` — applicant → staff-API: 403; admin → staff-API: 200 — PASS
3. `3_profile` — PUT/GET профиля — PASS
4. `4_documents` — загрузка изображения + текстового документа, список — PASS
5. `5_text_chat` — ACP-сессия 18.3 с, ответ Qwen «ОК» 4.0 с — PASS
6. `6_image` — анализ изображения 8.7 с: модель корректно описала красный круг и синий квадрат (vision-ассерты) — PASS
7. `7_history` — 4 сообщения, изображение связано с документом (FK), file-endpoint отдаёт идентичные байты — PASS
8. `8_knowledge` — источник → чанки → эмбеддинги bge-m3 (1024d) → pgvector-поиск — PASS
9. `9_staff` — staff видит абитуриентов — PASS

## 4. Ключевые конфигурационные точки (почему именно так)

- **`agent-client-protocol==0.9.0`** (Dockerfile): `ModelInfo` удалён из `acp.schema` начиная с 0.10.x; скан всех wheel PyPI (0.11.0…1.0.0) не нашёл её ни в одной из них. 0.9.0 — самый новый релиз с полным набором импортов адаптера. Хостовая конфигурация не тронута.
- **`fastmcp==2.14.7`**: резолвер иначе поднимает 2.5.2, несовместимую с pydantic 2.13.
- **`hermes-profile` в образе**: `hermes-agent 0.19.0` не читает env-переменные для выбора модели; в 0.19.0 нет встроенного провайдера `openai`, поэтому основной прогон завязан на именованный `custom:mai` (OpenAI-совместимый клиент на MAI-рель). Auxiliary-слоты идут через `custom:mai` с override-плагином: выключенный reasoning проецируется как `medium` (рель 400-ит на `none`).
- **TLS**: реле MAI предъявляет сертификат российского национального CA (Russian Trusted Sub/Root CA), которого нет в Mozilla-бандле `python:slim`. Используется штатный механизм проекта: `certs/mai-api-ca-chain.pem` → `AI_API_CA_BUNDLE` → `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`. Проверка TLS не отключалась, хеши зависимостей (`--require-hashes`) не ослаблялись.
- **Telegram**: polling — только Backend; Hermes Telegram Gateway в compose не используется.

## 5. Известные ограничения

- Hermes в контейнере — `0.19.0` (PyPI), на хосте — v0.23.1 (source). Каждая связка самодостаточна; ACP — wire-протокол (JSON-RPC, `PROTOCOL_VERSION=1`), совместимость подтверждена сквозным E2E.
- У фронтенда нет автотестов (контроль: `tsc -b` + `vite build`).
- Живой Telegram-сценарий: polling-ownership и обработка обновлений покрыты автотестами (5 тестов), реальный polling стартует штатно при наличии токена; проверка «от лица пользователя» без внешнего доступа невозможна (ограничение Bot API).
- На рабочей машине порт 5432 занят нативным postgres — локальная compose-проверка использовала override на 5433 (файл вне репозитория). Для чистого деплоя это не актуально.

## 6. Чек-лист приёмки (следующий этап)

**Интерфейс (http://localhost:5173):**
- [ ] Регистрация / вход (JWT), проверка `/users/me`
- [ ] Роль: applicant не видит staff-API (403)
- [ ] Профиль абитуриента: заполнение, сохранение
- [ ] Документы: загрузка изображения и текста, отображение, лимит 10 МБ
- [ ] Чат: текстовое сообщение → ответ агента
- [ ] Чат: отправка изображения → анализ (красный/синий объекты и т.п.), без зависаний
- [ ] История: изображения отображаются после перезагрузки страницы
- [ ] База знаний: создание источника, векторный поиск
- [ ] Staff workspace: список абитуриентов, комплектность

**Telegram (нужен `TELEGRAM_BOT_TOKEN` в `.env`):**
- [ ] Polling стартует в compose (лог backend)
- [ ] `/start` → привязка, `/pair КОД` → привязка к учётной записи
- [ ] Текстовое сообщение → ответ агента
- [ ] Фото с подписью → анализ изображения, подпись не теряется

## 7. Безопасность

- В репозиторий не попали: `.env` (gitignore), приватные ключи, JWT, токены бота, локальные БД/логи/загрузки.
- `certs/` — только публичные CA-сертификаты (проверено: `BEGIN PRIVATE KEY` отсутствует); в репозиторий взят единственный требуемый compose-файл, остальные игнорируются.
- Контейнерный Hermes-профиль не содержит секретов (ключ — через `key_env: OPENAI_API_KEY`).
- Проверка TLS и хеши зависимостей сохранены в полной строгости.
