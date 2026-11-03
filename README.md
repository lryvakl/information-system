# F1 Pit Wall — інформаційна система моніторингу роботи з базою даних

## 1. Опис проєкту

**F1 Pit Wall** — прикладна інформаційна система, яка генерує й актуалізує дані
в реляційній БД, збирає та обробляє метрики роботи системи й СУБД і відображає
їх у Grafana. Доступ до системи мають лише авторизовані користувачі.

Предметна область — **Formula 1**. Система моделює «стіну піт-лейну» гоночної
команди: у реальному часі надходять кола, піт-стопи, обгони, сходи з дистанції,
повідомлення дирекції гонки та телеметрія автомобілів. Ці дані записуються в
PostgreSQL, передаються між сервісами через брокер повідомлень і стають джерелом
метрик, логів і трейсів.

Дані надходять з одного з двох джерел:

- **повтор реальної гонки**. Історичні дані сезону 2024 з відкритого API
  [OpenF1](https://openf1.org): час кіл і секторів, піт-стопи, шини, повідомлення
  Race Control. Гонка відтворюється коло за колом у прискореному часі;
- **симуляція**. Синтетичні гонки з моделлю зносу шин, витрати палива,
  стратегією піт-стопів, виїздами safety car і сходами з дистанції.

## 2. Архітектура

```
                     ┌──────────────── gateway (nginx, порт 8080) ────────────────┐
  користувач ──────▶ │ /auth/*      → auth           (FastAPI + SQLite, JWT)      │
                     │ /grafana/*   → Grafana        ┐                            │
                     │ /api/*       → pitwall-api    ├─ перевірка через auth      │
                     │ /prometheus/*, /rabbitmq/*    ┘  (лише роль admin)         │
                     └────────────────────────────────────────────────────────────┘

  OpenF1 API ─┐
              ▼
  race-engine ──INSERT / UPDATE / DELETE──▶ PostgreSQL ◀── postgres-exporter
      │                                       ▲    ▲
      └── події ──▶ RabbitMQ ──▶ race-control ┘    └── pitwall-api (лише SELECT)

  метрики всіх сервісів (/metrics) ─────────────▶ Prometheus (TSDB) ─┐
  логи контейнерів (JSON + trace_id) ─▶ Alloy ─▶ Loki ───────────────┼─▶ Grafana
  трейси (OpenTelemetry) ───────────────────────▶ Tempo ─────────────┘
```

### 2.1. Компоненти

| Компонент | Технологія | Призначення |
|---|---|---|
| `race-engine` | Python | Генерує й актуалізує дані гонки в БД, публікує події в RabbitMQ, віддає телеметрію як метрики |
| `race-control` | Python | Споживає події з RabbitMQ: веде журнал подій, формує повідомлення Race Control, рахує статистику, нараховує очки чемпіонату |
| `pitwall-api` | Python, FastAPI | REST API для читання даних гонок (працює з окремою read-only роллю БД) |
| `auth` | Python, FastAPI, SQLite | Сервер авторизації: облік користувачів, видача та перевірка JWT, ролі |
| `gateway` | nginx | Єдина точка входу в систему; перед кожним захищеним запитом звертається до `auth` |
| `postgres` | PostgreSQL 16 | Основна база даних системи |
| `rabbitmq` | RabbitMQ 3.13 | Брокер повідомлень між сервісами |
| `postgres-exporter` | Prometheus exporter | Метрики роботи СУБД (транзакції, операції з рядками, з'єднання, розмір, кеш) |
| `prometheus` | Prometheus 2.54 | Збір метрик, зберігання у вбудованій TSDB, правила алертів |
| `loki` + `alloy` | Grafana Loki 3.2, Grafana Alloy | Збір і зберігання логів усіх контейнерів |
| `tempo` | Grafana Tempo 2.6 | Зберігання розподілених трейсів, побудова service graph |
| `grafana` | Grafana 11.3 | Візуалізація метрик, логів, трейсів і даних з БД |

### 2.2. Потік даних

1. `race-engine` отримує чергове коло гонки (з OpenF1 або із симулятора).
2. Розраховує позиції, розриви, обгони та найшвидше коло.
3. Записує в PostgreSQL кола, піт-стопи і телеметрію автомобілів (щосекунди).
4. Публікує події (`lap.completed`, `pit.stop`, `overtake`, `race.control` тощо) в обмінник RabbitMQ.
5. `race-control` отримує події з черги й записує їх у журнал `race_events`. Після фінішу гонки нараховує очки чемпіонату.
6. Prometheus щоп'ять секунд збирає метрики з усіх сервісів, СУБД і брокера.
7. Grafana будує дашборди за даними з Prometheus, Loki, Tempo і безпосередньо з PostgreSQL.

### 2.3. Актуалізація даних у БД

| Операція | Коли виконується |
|---|---|
| `INSERT` | нова гонка та її учасники, кожне коло, піт-стоп, зріз телеметрії (щосекунди), подія в журналі, результати чемпіонату |
| `UPDATE` | зміна статусу гонки (`RUNNING` → `FINISHED` / `ABORTED`), визначення переможця |
| `DELETE` | періодичне видалення телеметрії, старшої за 30 хвилин (retention) |
| `SELECT` | REST API, панелі Grafana з джерелом PostgreSQL |

Незавершені гонки, що залишилися після аварійної зупинки, під час
перезапуску автоматично отримують статус `ABORTED`.

## 3. Модель даних

| Таблиця / представлення | Зміст |
|---|---|
| `races` | гонки: назва, траса, сезон, кількість кіл, джерело даних, статус, переможець |
| `race_entries` | учасники гонки: пілот, номер, команда, колір команди, стартова позиція |
| `laps` | кола: час кола і секторів, позиція, розрив до лідера, шини, знос, максимальна швидкість |
| `pit_stops` | піт-стопи: коло, час у піт-лейні, час зупинки, нові шини |
| `telemetry` | телеметрія: швидкість, оберти, передача, газ, температура шин, паливо, заряд ERS |
| `race_events` | журнал подій, отриманих з RabbitMQ (JSONB) |
| `championship_results` | очки пілотів за кожну гонку |
| `race_standings(race_id)` | функція: поточна класифікація будь-якої гонки |
| `v_live_standings` | представлення: класифікація поточної гонки |
| `v_championship` | представлення: залік чемпіонату (очки, перемоги, подіуми) |

Схема створюється скриптами `infra/postgres/init/` під час першого запуску
контейнера PostgreSQL. Для доступу до БД використовуються окремі ролі з
мінімально необхідними правами:

| Роль | Права | Хто використовує |
|---|---|---|
| власник БД | читання й запис | `race-engine`, `race-control` |
| `pitwall_api` | лише читання | `pitwall-api` |
| `grafana_reader` | лише читання | Grafana |
| `postgres_exporter` | `pg_monitor` | `postgres-exporter` |

## 4. Моніторинг

### 4.1. Метрики (Prometheus)

Prometheus зберігає метрики у вбудованій Time Series Storage (термін зберігання —
7 днів). Джерела метрик:

- **СУБД**: транзакції, операції вставки / оновлення / видалення / читання
  рядків, кількість з'єднань, розмір БД, cache hit ratio, кількість рядків у
  таблицях;
- **робота застосунку з БД**: кількість і тривалість кожної операції за
  таблицею та типом запиту;
- **брокер**: кількість опублікованих, доставлених і підтверджених повідомлень,
  глибина черг, dead-letter queue;
- **сервіси**: кількість і тривалість HTTP-запитів, спроби входу, перевірки
  токенів, час обробки подій;
- **предметна область**: позиції, розриви, час кіл, знос і температура шин,
  швидкість, паливо, обгони, піт-стопи.

Правила алертів (`infra/prometheus/alerts.yml`):

| Алерт | Умова |
|---|---|
| `ServiceDown` | сервіс недоступний понад 30 с |
| `PostgresDown` | СУБД недоступна |
| `QueueBacklog` | у черзі понад 500 необроблених повідомлень |
| `DeadLetters` | з'явилися повідомлення, які не вдалося обробити |
| `LoginBruteForce` | понад 10 невдалих спроб входу за 5 хвилин |
| `HighHttpErrorRate` | понад 5 % відповідей з помилкою сервера |
| `TyreWearCritical`, `SafetyCarDeployed`, `SlowPitStop` | події предметної області |

### 4.2. Логи (Loki)

Усі сервіси пишуть структуровані JSON-логи з ідентифікатором трейсу
(`trace_id`). Grafana Alloy збирає логи всіх контейнерів і передає їх у Loki. З
рядка логу в Grafana можна перейти до відповідного трейсу в Tempo.

### 4.3. Трейси (Tempo)

Сервіси інструментовано через OpenTelemetry. Контекст трейсу передається в
заголовках повідомлень RabbitMQ, тому одна операція відстежується наскрізь:

```
race.lap → pit_stop → publish (RabbitMQ) → consume → handle → db INSERT (PostgreSQL)
```

На основі трейсів Tempo будує граф взаємодії сервісів (service graph). Метрики
затримок містять exemplars — посилання на конкретні трейси.

### 4.4. Дашборди Grafana

Дашборди й джерела даних налаштовуються автоматично під час запуску
(`infra/grafana/`).

| Дашборд | Вміст |
|---|---|
| **F1 Pit Wall** | поточна гонка, класифікація з БД, розриви, час кіл, знос і температура шин, швидкість, піт-стопи, чемпіонат, стрічка повідомлень Race Control з Loki |
| **F1 Database & Messaging** | стан і продуктивність PostgreSQL, операції застосунку з БД, статистика таблиць, пропускна здатність і черги RabbitMQ |
| **F1 Services & Observability** | доступність сервісів, активні алерти, service graph, HTTP-запити та затримки, спроби входу, трейси піт-стопів, логи помилок, журнал доступу gateway |

## 5. Авторизація та безпека

- Користувачі зберігаються в SQLite сервера авторизації, паролі — у вигляді
  bcrypt-хешів.
- Після входу сервер видає JWT, який браузер зберігає в HttpOnly cookie, а
  API-клієнти передають у заголовку `Authorization: Bearer`.
- Gateway перевіряє кожен запит до Grafana, API та адміністративних інструментів
  через сервер авторизації (`auth_request`). Неавторизованого користувача
  перенаправлено на сторінку входу, API повертає `401`.
- Grafana не має власної форми входу: користувач і його роль передаються з
  gateway (режим auth proxy).
- Захист: обмеження частоти спроб входу, захист від open redirect і timing-атак,
  ролі БД з мінімальними правами. Секрети зберігаються лише у файлі `.env`, який
  не потрапляє в репозиторій.

| Роль | Grafana | REST API | Prometheus, RabbitMQ UI |
|---|---|---|---|
| `viewer` | перегляд | так | ні |
| `engineer` | редагування | так | ні |
| `admin` | адміністратор | так | так |

## 6. Відповідність вимогам завдання

| № | Вимога | Реалізація |
|---|---|---|
| 0 | Запуск СУБД у Docker-контейнері | PostgreSQL 16 у Docker; схема, функції, представлення та ролі — `infra/postgres/init/` |
| 1 | Генерація та актуалізація даних у БД засобами Python | `race-engine` і `race-control`: `INSERT`, `UPDATE`, `DELETE` (розділ 2.3) |
| 2 | Збір даних Prometheus | метрики сервісів, СУБД (`postgres-exporter`), RabbitMQ, компонентів моніторингу; правила алертів |
| 3 | Зберігання в Time Series Storage | вбудована TSDB Prometheus, термін зберігання 7 днів |
| 4 | Відображення в Grafana | 3 дашборди; джерела Prometheus, Loki, Tempo, PostgreSQL з переходами між ними |
| 5 | Дослідження логів Grafana Loki | структуровані JSON-логи всіх сервісів, збір через Grafana Alloy |
| 6 | Дослідження трейсів Grafana Tempo | OpenTelemetry, наскрізні трейси через RabbitMQ, service graph |
| 7 | Сервер авторизації (Python + SQLite) | `services/auth` (FastAPI, SQLite, bcrypt, JWT) + перевірка на gateway |
| 8 | Контейнеризація Docker | Docker Compose, 14 контейнерів, healthchecks, сервіси працюють не від root |
| 9 | Обмін повідомленнями між сервісами | RabbitMQ: topic exchange, durable-черга, dead-letter queue |

## 7. Запуск

**Вимоги:** Docker Desktop (рекомендовано виділити ≥ 6 ГБ пам'яті), `make`, `openssl`.

```bash
make up
```

Команда створює файл `.env` з випадковими паролями, збирає образи й запускає
всі контейнери. Після запуску система доступна за адресою
**http://localhost:8080**.

Обліковий запис адміністратора: логін `admin`, пароль — значення
`ADMIN_PASSWORD` у файлі `.env`.

| Адреса | Призначення | Доступ |
|---|---|---|
| `/grafana/` | дашборди | усі авторизовані користувачі |
| `/api/docs` | документація REST API (Swagger UI) | усі авторизовані користувачі |
| `/prometheus/` | інтерфейс Prometheus (targets, алерти) | `admin` |
| `/rabbitmq/` | інтерфейс керування RabbitMQ | `admin` |
| `/auth/logout` | вихід із системи | — |

### 7.1. Керування

| Команда | Дія |
|---|---|
| `make up` | зібрати й запустити систему |
| `make up-debug` | те саме + публікація портів усіх внутрішніх сервісів на `127.0.0.1` (розділ 7.4) |
| `make ports` | співставлення портів хост ↔ контейнер для запущених контейнерів |
| `make down` | зупинити систему (дані зберігаються) |
| `make clean` | зупинити систему й видалити всі дані |
| `make ps` | стан контейнерів |
| `make logs` | логи сервісів застосунку |
| `make replay` | джерело даних — повтор реальних гонок (за замовчуванням) |
| `make simulate` | джерело даних — симуляція |

### 7.2. Налаштування джерела даних

Параметри задаються у файлі `.env`:

| Параметр | За замовчуванням | Опис |
|---|---|---|
| `RACE_SOURCE` | `replay` | `replay` — реальні гонки з OpenF1, `simulation` — симуляція |
| `REPLAY_RACES` | `2024:Monza,2024:Silverstone,2024:Spa-Francorchamps` | гонки для повтору (рік і траса) |
| `SPEED_FACTOR` | `20` | прискорення часу (гонка триває ≈ 4 хв) |

Відповіді OpenF1 кешуються, тому після першого завантаження доступ до інтернету
не потрібен. Якщо API недоступне, система автоматично перемикається на
симуляцію. OpenF1 не публікує знос шин, залишок палива і швидкість між
контрольними точками. Ці значення система оцінює тими ж моделями, що й під час
симуляції.

### 7.3. Керування користувачами

Нових користувачів створює адміністратор через API:

```bash
TOKEN=$(curl -s -X POST localhost:8080/auth/token -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<ADMIN_PASSWORD>"}' | jq -r .access_token)

curl -X POST localhost:8080/auth/users -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"username":"engineer1","password":"<пароль>","role":"engineer"}'
```

### 7.4. Співставлення портів (хост ↔ контейнер)

Усі контейнери працюють в одній внутрішній мережі Docker `backend` і звертаються
один до одного за іменем сервісу (`postgres:5432`, `rabbitmq:5672` тощо). На хост
за замовчуванням опубліковано **лише один порт — gateway**: усі запити проходять
перевірку авторизації, і жоден внутрішній сервіс не доступний напряму.

Для діагностики є режим `make up-debug` (файл `docker-compose.debug.yml`), який
додатково публікує порти внутрішніх сервісів. Вони прив'язані до `127.0.0.1`,
тобто доступні лише з цього комп'ютера, а не з мережі.

Формат запису в `docker-compose`: `"ХОСТ:ПОРТ_ХОСТА:ПОРТ_КОНТЕЙНЕРА"`.

| Контейнер | Порт у контейнері | Порт на хості (`make up`) | Порт на хості (`make up-debug`) | Що там |
|---|---|---|---|---|
| `gateway` | 80 | **8080** (`GATEWAY_PORT`) | **8080** | єдина точка входу: `/auth`, `/grafana`, `/api`, `/prometheus`, `/rabbitmq` |
| `auth` | 8000 | — | 127.0.0.1:8001 | сервер авторизації, Swagger `/auth/docs`, `/metrics` |
| `pitwall-api` | 8000 | — | — ¹ | REST API, Swagger `/api/docs` |
| `grafana` | 3000 | — | — ¹ | дашборди |
| `race-engine` | 9100 | — | 127.0.0.1:9100 | `/metrics` (телеметрія) |
| `race-control` | 9101 | — | 127.0.0.1:9101 | `/metrics` |
| `postgres` | 5432 | — | 127.0.0.1:5432 | PostgreSQL |
| `postgres-exporter` | 9187 | — | 127.0.0.1:9187 | `/metrics` СУБД |
| `rabbitmq` | 5672 | — | 127.0.0.1:5672 | AMQP |
| `rabbitmq` | 15672 | — | 127.0.0.1:15672 | Management UI (`/rabbitmq/`) |
| `rabbitmq` | 15692 | — | 127.0.0.1:15692 | `/metrics` брокера |
| `prometheus` | 9090 | — | 127.0.0.1:9090 | UI та API (`/prometheus/`) |
| `loki` | 3100 | — | 127.0.0.1:3100 | HTTP API (LogQL) |
| `tempo` | 3200 | — | 127.0.0.1:3200 | HTTP API (TraceQL) |
| `tempo` | 4317 / 4318 | — | 127.0.0.1:4317 / 4318 | прийом трейсів OTLP gRPC / HTTP |
| `alloy` | 12345 | — | 127.0.0.1:12345 | UI конвеєра збору логів |

¹ Grafana і `pitwall-api` довіряють заголовкам з ідентичністю користувача, які
виставляє gateway (`X-WEBAUTH-USER`, `X-User`). Пряма публікація дозволила б
видати себе за будь-кого, тому вони доступні тільки через `http://localhost:8080`.

Фактичне співставлення запущених контейнерів:

```bash
make ports                    # таблиця «сервіс → порти»
docker compose port gateway 80   # → 0.0.0.0:8080
```

Змінити зовнішній порт gateway: `GATEWAY_PORT=9000` у `.env`, потім `make up`.

### 7.5. Гайд: як скористатися кожним сервісом

Перед початком: `make up` (або `make up-debug`), дочекатися, поки `make ps`
покаже всі контейнери у стані `healthy`/`running` (≈ 1–2 хв), і взяти пароль
адміністратора: `grep ADMIN_PASSWORD .env`.

#### 1. Вхід у систему (auth)

1. Відкрити **http://localhost:8080** → перенаправлення на `/auth/login`.
2. Увійти як `admin` / `<ADMIN_PASSWORD>`. Браузер отримує JWT у cookie, далі всі
   сторінки відкриваються без повторного входу.
3. Вихід — **http://localhost:8080/auth/logout**.
4. Swagger сервера авторизації — **http://localhost:8080/auth/docs**.

Токен для консольних клієнтів (використовується в прикладах нижче):

```bash
TOKEN=$(curl -s -X POST localhost:8080/auth/token -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$(grep ^ADMIN_PASSWORD .env | cut -d= -f2)\"}" \
  | jq -r .access_token)

curl -s localhost:8080/auth/me    -H "Authorization: Bearer $TOKEN"   # хто я
curl -s localhost:8080/auth/users -H "Authorization: Bearer $TOKEN"   # користувачі (admin)
```

#### 2. Grafana — дашборди

**http://localhost:8080/grafana/** (будь-який авторизований користувач).

- *Dashboards → F1 Pit Wall* — поточна гонка: класифікація, розриви, кола, шини,
  піт-стопи, чемпіонат, стрічка Race Control.
- *F1 Database & Messaging* — PostgreSQL (транзакції, рядки, з'єднання, кеш) і
  RabbitMQ (швидкість публікації/споживання, черги).
- *F1 Services & Observability* — доступність сервісів, алерти, service graph,
  HTTP-затримки, спроби входу, логи помилок.
- Перехід метрика → трейс → лог: клік на точку-exemplar на графіку затримок
  відкриває трейс у Tempo, а з трейсу кнопка *Logs for this span* — логи в Loki.

#### 3. Loki — логи

*Grafana → Explore → джерело **Loki***. Приклади LogQL:

```logql
{service="race-control"}                              # усі логи сервісу
{service=~"race-.*", level="ERROR"}                   # лише помилки
{service="gateway"} | json | status >= 400            # невдалі HTTP-запити
{service="auth"} |= "login"                           # спроби входу
{service="race-engine"} | json | trace_id != ""       # логи з прив'язкою до трейсу
```

Мітки: `service` (ім'я сервісу з compose), `level`. У рядку з `trace_id` є
посилання на відповідний трейс у Tempo.

#### 4. Tempo — трейси

*Grafana → Explore → джерело **Tempo***:

- вкладка *Search*: Service Name = `race-engine`, Span Name = `race.lap` → список
  трейсів кожного кола;
- *TraceQL*: `{ resource.service.name = "race-control" && duration > 50ms }`;
- *Service Graph* — карта викликів між сервісами (race-engine → RabbitMQ →
  race-control → PostgreSQL).

Наскрізний трейс показує подію від публікації в RabbitMQ до запису в БД.

#### 5. Prometheus — метрики та алерти (роль `admin`)

**http://localhost:8080/prometheus/** (у режимі debug також http://localhost:9090/prometheus/).

- *Status → Targets* — усі 10 джерел метрик мають бути `UP`.
- *Alerts* — правила: `TyreWearCritical`, `SafetyCarDeployed`, `SlowPitStop`,
  `ServiceDown`, `PostgresDown`, `QueueBacklog`, `DeadLetters`,
  `LoginBruteForce`, `HighHttpErrorRate`.
- Приклади запитів у *Graph*:

```promql
f1_race_current_lap                              # поточне коло
topk(5, f1_tyre_wear_percent)                    # найбільш зношені шини
rate(f1_pit_stops_total[5m])                     # частота піт-стопів
rate(pg_stat_database_xact_commit{datname="f1"}[1m])  # транзакції СУБД
rate(app_mq_messages_consumed_total[1m])         # спожиті повідомлення
sum by (result) (rate(auth_login_attempts_total[5m]))  # спроби входу
up                                               # доступність усіх сервісів
```

#### 6. REST API (pitwall-api)

Swagger UI: **http://localhost:8080/api/docs** (після входу в браузері можна
виконувати запити кнопкою *Try it out*). З консолі:

```bash
H="Authorization: Bearer $TOKEN"
curl -s localhost:8080/api/me                             -H "$H"
curl -s localhost:8080/api/races                          -H "$H"   # список гонок
curl -s localhost:8080/api/races/latest                   -H "$H"   # поточна гонка
curl -s localhost:8080/api/races/latest/standings         -H "$H"   # класифікація
curl -s localhost:8080/api/races/latest/pit-stops         -H "$H"
curl -s localhost:8080/api/races/latest/drivers/VER/laps  -H "$H"   # кола пілота
curl -s localhost:8080/api/races/latest/events            -H "$H"   # журнал подій
curl -s localhost:8080/api/championship                   -H "$H"
```

Без токена API повертає `401`.

#### 7. RabbitMQ — брокер повідомлень (роль `admin`)

**http://localhost:8080/rabbitmq/** → вхід `RABBITMQ_USER` / `RABBITMQ_PASSWORD` з `.env`.

- *Exchanges* → `race.events` (topic): сюди `race-engine` публікує події;
  `race.events.dlx` — dead-letter.
- *Queues* → `race-control`: черга споживача, графік швидкості повідомлень;
  `race-control.dead` — dead-letter черга для повідомлень, які не вдалося обробити.

#### 8. PostgreSQL — база даних

Через контейнер (працює завжди):

```bash
docker compose exec postgres psql -U f1 -d f1
```

У режимі `make up-debug` — будь-яким клієнтом (DBeaver, DataGrip, `psql`) на
`localhost:5432`, БД `f1`, користувач `POSTGRES_USER`, пароль `POSTGRES_PASSWORD` з `.env`.

```sql
\dt                                   -- таблиці
SELECT * FROM v_live_standings;       -- поточна класифікація
SELECT * FROM v_championship;         -- чемпіонат
SELECT count(*) FROM laps;            -- кількість записаних кіл (росте під час гонки)
```

Також у Grafana: *Explore → джерело **PostgreSQL***.

#### 9. Сирі метрики та Alloy (лише `make up-debug`)

```bash
curl -s localhost:9100/metrics | grep ^f1_      # телеметрія race-engine
curl -s localhost:9101/metrics                  # race-control
curl -s localhost:9187/metrics | grep ^pg_      # postgres-exporter
curl -s localhost:15692/metrics | head          # RabbitMQ
curl -s 'localhost:3100/loki/api/v1/labels'     # мітки Loki
curl -s localhost:3200/ready                    # Tempo
```

Alloy UI — **http://localhost:12345**: граф конвеєра збору логів контейнерів.

## 8. Структура репозиторію

```
libs/common/          спільна бібліотека: конфігурація, логування, трейсинг, метрики,
                      доступ до БД, робота з RabbitMQ, контракти подій
services/
  Dockerfile          спільний образ для всіх Python-сервісів
  auth/               сервер авторизації
  race_engine/        генератор даних: модель предметної області, джерела даних, оркестрація
  race_control/       обробник подій з RabbitMQ
  pitwall_api/        REST API
infra/                конфігурація PostgreSQL, Prometheus, Loki, Tempo, Alloy,
                      RabbitMQ, nginx, Grafana (джерела даних і дашборди)
docker-compose.yml    опис усіх контейнерів системи
docker-compose.debug.yml  публікація портів внутрішніх сервісів на 127.0.0.1 (make up-debug)
Makefile              команди запуску, тестування й перевірки коду
```

## 9. Якість коду

- **Архітектура сервісів.** Кожен сервіс поділено на шари: HTTP / обробка подій,
  бізнес-логіка, доступ до даних (Repository). Залежності між шарами
  спрямовані через інтерфейси (`Protocol`), а конкретні реалізації збираються в
  одному місці — `main.py` кожного сервісу.
- **Принципи SOLID.** Джерела даних гонки взаємозамінні (патерн Strategy).
  Обробники подій додаються без зміни диспетчера. У тестах реальні сховища
  замінюються реалізаціями в пам'яті.
- **DRY.** Логування, трейсинг, метрики, робота з БД і брокером, Dockerfile
  реалізовані один раз і використовуються всіма сервісами.
- **Надійність.** Ідемпотентний запис подій, dead-letter queue, автоматичне
  перепідключення до брокера, коректне завершення роботи сервісів, healthchecks
  контейнерів.
- **Тестування.** 48 модульних тестів (pytest) і статичний аналіз (ruff).

```bash
make dev     # створити локальне віртуальне середовище
make test    # модульні тести
make lint    # статичний аналіз коду
```
