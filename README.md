# F1 Pit Wall — інформаційна система моніторингу роботи з БД

Прикладна інформаційна система в тематиці **Formula 1**. Система генерує і
актуалізує дані гонок у PostgreSQL (симуляція або **повтор реальної гонки** з
відкритого API [OpenF1](https://openf1.org)), обмінюється подіями через
RabbitMQ, збирає метрики (Prometheus), логи (Loki) і трейси (Tempo) та
відображає все це в Grafana. Доступ є лише в авторизованих користувачів.

## Архітектура

```
                     ┌───────────────── gateway (nginx, :8080) ─────────────────┐
  користувач ──────▶ │ /auth/*      → auth           (FastAPI + SQLite, JWT)    │
                     │ /grafana/*   → Grafana        ┐                          │
                     │ /api/*       → pitwall-api    ├ auth_request → auth      │
                     │ /prometheus/*, /rabbitmq/*    ┘ (лише роль admin)        │
                     └──────────────────────────────────────────────────────────┘

  OpenF1 API ─┐
              ▼
  race-engine ──INSERT/UPDATE/DELETE──▶ PostgreSQL ◀── postgres-exporter
      │                                    ▲   ▲
      └──publish events──▶ RabbitMQ ──▶ race-control      pitwall-api (SELECT-only)

  /metrics усіх сервісів ───────────────────────▶ Prometheus (TSDB) ─┐
  stdout (JSON-логи з trace_id) ─▶ Alloy ─▶ Loki ────────────────────┼─▶ Grafana
  OpenTelemetry spans ──────────────────────────▶ Tempo ─────────────┘
```

| Сервіс | Роль |
|---|---|
| `race-engine` | Генерує гонку коло за колом (Strategy: симуляція або replay OpenF1), пише в БД, публікує події, віддає телеметрію як метрики |
| `race-control` | Споживає події з RabbitMQ: журнал подій, коментарі «Race Control», статистика, нарахування очок чемпіонату |
| `auth` | Сервер авторизації: користувачі в SQLite (bcrypt), JWT у HttpOnly cookie, ролі `admin / engineer / viewer` |
| `pitwall-api` | REST API для читання даних (окрема read-only роль БД) |
| `gateway` | Єдиний опублікований порт; перевіряє кожен запит через `auth` |

## Відповідність вимогам завдання

| # | Вимога | Реалізація |
|---|---|---|
| 0 | СУБД у Docker | PostgreSQL 16, схема та ролі в `infra/postgres/init` |
| 1 | Генерація/актуалізація даних (Python) | `race-engine`: `INSERT` кола, піт-стопи, телеметрія; `UPDATE` статус гонки; `DELETE` стару телеметрію (retention) |
| 2 | Збір даних Prometheus | метрики сервісів, `postgres-exporter`, RabbitMQ, Loki, Tempo, Grafana; правила алертів `infra/prometheus/alerts.yml` |
| 3 | Time Series Storage | вбудована TSDB Prometheus (retention 7 днів) + exemplars |
| 4 | Grafana | 3 дашборди як код (`infra/grafana/dashboards`), datasources зв'язані між собою |
| 5 | Grafana Loki | JSON-логи з `trace_id`; збір через Grafana Alloy з Docker |
| 6 | Grafana Tempo | OpenTelemetry: один trace проходить race-engine → RabbitMQ → race-control → PostgreSQL; service graph |
| 7 | Авторизація (Python + SQLite) | `services/auth` + nginx `auth_request` + Grafana auth proxy |
| 8 | Docker | `docker-compose.yml`, один параметризований `services/Dockerfile`, non-root контейнери, healthchecks |
| 9 | Брокер повідомлень | RabbitMQ: topic exchange, durable queue, dead-letter queue, trace context у заголовках |

## Запуск

Потрібні Docker Desktop і `make`.

```bash
make up          # створює .env з випадковими паролями, збирає і запускає все
make ps          # стан контейнерів
```

Відкрити **http://localhost:8080**. Логін `admin`, пароль: `grep ADMIN_PASSWORD .env`.

| URL | Що там | Доступ |
|---|---|---|
| `/grafana/` | дашборди F1 Pit Wall, Database & Messaging, Services & Observability | будь-який користувач |
| `/api/docs` | Swagger UI для REST API | будь-який користувач |
| `/prometheus/` | Prometheus UI (targets, alerts) | admin |
| `/rabbitmq/` | RabbitMQ management (логін з `.env`) | admin |
| `/auth/logout` | вихід | — |

### Джерело даних гонки

За замовчуванням `RACE_SOURCE=replay`: двигун завантажує реальні гонки сезону
2024 (Monza → Silverstone → Spa) з OpenF1 і програє їх у прискореному часі
(`SPEED_FACTOR=20`: гонка триває ~4 хв). Відповіді API кешуються у volume,
тож після першого завантаження інтернет не потрібен. Якщо API недоступне,
система автоматично переходить на симуляцію.

```bash
make simulate    # синтетичні гонки (фізика шин, стратегія піт-стопів, safety car, сходи)
make replay      # реальні гонки з OpenF1
```

У replay-режимі час кіл, сектори, піт-стопи, шини та повідомлення Race Control —
реальні. Значень, яких OpenF1 не публікує (знос шин, паливо, швидкість між
контрольними точками), система оцінює тими ж моделями, що й у симуляції.

### Користувачі та ролі

```bash
TOKEN=$(curl -s -X POST localhost:8080/auth/token -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$(grep ^ADMIN_PASSWORD .env | cut -d= -f2)\"}" | jq -r .access_token)

# створити користувача (viewer | engineer | admin)
curl -X POST localhost:8080/auth/users -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"username":"toto","password":"wolff-2024","role":"engineer"}'

curl localhost:8080/api/races/latest/standings -H "Authorization: Bearer $TOKEN"
```

| Роль | Grafana | API | Prometheus / RabbitMQ UI |
|---|---|---|---|
| `viewer` | Viewer | так | ні |
| `engineer` | Editor | так | ні |
| `admin` | Admin | так | так |

## Що показати на захисті

1. **Pit Wall**: live-класифікація з БД, розриви, знос і температура шин, швидкість, піт-стопи, чемпіонат, журнал Race Control з Loki.
2. **Database & Messaging**: операції з рядками/с (insert/update/delete), транзакції, розмір БД, cache hit ratio, кількість рядків у таблицях, глибина черг RabbitMQ, dead letters.
3. **Services & Observability**: стан усіх targets, алерти, service graph з Tempo, latency з exemplars (клік → trace), логи помилок.
4. **Trace наскрізь**: на панелі «Recent pit stop traces» відкрити trace `pit_stop`, побачити ланцюг `race.lap → pit_stop → publish → consume → handle → db INSERT`, а з span перейти в логи цього trace (Loki).
5. **Логи → trace**: у логах `race-control` поле `trace_id` є посиланням на Tempo.
6. **Безпека**: без логіну `/grafana/` перенаправляє на сторінку входу, `/api/*` повертає 401, viewer отримує 403 на `/prometheus/`.

## Структура репозиторію

```
libs/common/            спільна бібліотека f1_common (DRY):
                        settings, JSON-логи, tracing, метрики, БД, RabbitMQ, контракти подій
services/
  Dockerfile            один образ для всіх Python-сервісів (ARG SERVICE)
  auth/                 domain → security → repository → service → api
  race_engine/          domain (моделі, шини, класифікація) → sources (simulation | openf1) → engine
  race_control/         dispatcher + handlers (journal, commentary, stats, championship)
  pitwall_api/          api → service → repository
infra/                  конфіги postgres, prometheus, loki, tempo, alloy, rabbitmq, nginx, grafana
```

### Принципи

- **SRP** — шари HTTP / бізнес-логіка / доступ до даних розділені; кожен handler у `race-control` робить одну річ.
- **OCP** — нове джерело гонок = новий клас `RaceSource`; нова реакція на подію = новий handler у списку, без змін диспетчера.
- **LSP / ISP** — вузькі `Protocol`-інтерфейси (`RaceRepository`, `EventPublisher`, `UserRepository`), будь-яка реалізація (Postgres, in-memory у тестах) взаємозамінна.
- **DIP** — бізнес-логіка залежить від абстракцій; конкретні класи збираються лише в `main.py` (composition root).
- **DRY** — логування, tracing, метрики БД/HTTP/черг, FastAPI-фабрика, Dockerfile — по одному разу для всіх сервісів.
- **Безпека** — bcrypt, JWT у HttpOnly cookie, захист від open redirect і timing-атак, rate limit на логін, least-privilege ролі БД, секрети лише в `.env`.
- **Надійність** — ідемпотентні записи (`ON CONFLICT`), dead-letter queue, автоматичне перепідключення до RabbitMQ, graceful shutdown, healthchecks.

## Розробка

```bash
make dev     # локальний venv з усіма сервісами
make test    # unit-тести (pytest)
make lint    # ruff
```
