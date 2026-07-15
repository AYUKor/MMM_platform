# Backend X5 MMM: local development и research pilot

Локальный режим нужен для совместной разработки frontend и backend. Браузер обращается к `localhost`, а расчет идет
в отдельном Python subprocess через существующий `budget_optimizer.py`.
Adstock, saturation, posterior forecast и Scenario 6 в HTTP-слое не
дублируются.

## Что уже проходит через один API

1. Маркетолог загружает канонический CSV/XLSX с будущей кампанией.
2. Backend сохраняет исходный файл и SHA-256, затем в фоне нормализует строки.
3. Отдельный запрос запускает validation против закрепленного model package.
4. Успешная validation создает неизменяемый `DecisionJob v1`.
5. Worker запускает Scenarios 1-5, Scenario 6 и marketer report.
6. Frontend опрашивает статус/progress, получает `ResultOverview v1` для
   компактных экранов или полный `DecisionResult v1` для Phase 1 Result Overview.
7. Excel скачивается по opaque artifact ID с повторной проверкой SHA-256.
8. Product API публикует readiness, паспорт активной модели, JSON Schemas,
   OpenAPI, каталог ошибок и paginated job history.

## Предварительная проверка

Из корня проекта:

```bash
python -B 04_Web_app/backend_runtime.py \
  --config 04_Web_app/config/local_backend_v1.json \
  --check-only
```

Проверка подтверждает Python runtime, policy-файлы, Git commit, registry
channel, package ID, fingerprint, неизменность package inventory и собирает
`ModelPassport v1`. Текущий
конфиг намеренно закрепляет `preprod` package
`pkg_807d3ddbae57a52a_9aacd3beb350725b`. Это не production activation.

## Запуск

```bash
python -B 04_Web_app/backend_runtime.py \
  --config 04_Web_app/config/local_backend_v1.json
```

По умолчанию API доступен на `http://127.0.0.1:8765`, а frontend dev server
может обращаться к нему с `http://localhost:4173` или
`http://127.0.0.1:4173`. Порт `5173` также оставлен в локальном allowlist для
совместимости с альтернативным Vite-конфигом.

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/ready
curl http://127.0.0.1:8765/api/v1/models/active
```

Во втором терминале:

```bash
cd 04_Web_app/frontend
cp .env.example .env.local
npm ci
npm run dev
```

Основной локальный путь маркетолога начинается с
`http://127.0.0.1:4173/calculations/new`. История доступна на
`http://127.0.0.1:4173/calculations`, а завершенный расчет открывается по
`http://127.0.0.1:4173/calculations/{job_id}/result`.

Runtime-данные находятся в игнорируемой Git папке `04_Web_app/var/local/`:

- `state/`: browser-safe lifecycle JSON и idempotency indices;
- `runtime/`: worker attempts, защищенные логи и optimizer outputs;
- `artifacts/`: загруженные файлы и подготовленные immutable inputs;
- `backend.lock`: защита от двух backend-процессов на одном state.

## HTTP-последовательность для frontend

| Шаг | Метод и route | Результат |
|---|---|---|
| Загрузка | `POST /api/v1/uploads` | `CampaignUpload v1` |
| Статус загрузки | `GET /api/v1/uploads/{upload_id}` | `received`, `parsed` или `rejected` |
| Проверка | `POST /api/v1/uploads/{upload_id}/validations` | `ValidationResult v1` |
| Статус проверки | `GET /api/v1/validations/{validation_id}` | `running`, `valid` или `invalid` |
| Расчет | `POST /api/v1/validations/{validation_id}/jobs` | `DecisionJob v1` |
| История | `GET /api/v1/jobs` | jobs с campaign preview из validation |
| Статус | `GET /api/v1/jobs/{job_id}` | lifecycle job status |
| Прогресс | `GET /api/v1/jobs/{job_id}/progress` | browser-safe progress events |
| Экран результата | `GET /api/v1/jobs/{job_id}/overview` | `ResultOverview v1` |
| Полный результат | `GET /api/v1/jobs/{job_id}/result` | `DecisionResult v1` |
| Excel | `GET /api/v1/artifacts/{artifact_id}/download` | hash-checked файл |

История поддерживает `limit`, `offset` и optional `status`, например:

```bash
curl 'http://127.0.0.1:8765/api/v1/jobs?limit=50&offset=0&status=succeeded'
```

Product metadata:

| Route | Назначение |
|---|---|
| `GET /ready` | Готовы ли package, campaign service и локальные stores |
| `GET /api/v1/models/active` | Период, coverage, gate statuses и policy модели |
| `GET /api/v1/meta/errors` | Стабильные error codes и действия пользователя |
| `GET /api/v1/openapi.json` | OpenAPI 3.1 для frontend/integration |
| `GET /api/v1/contracts/{name}.json` | Опубликованные JSON Schemas |

Каждый `POST` требует уникальный заголовок `Idempotency-Key` длиной не менее
16 символов. Повтор того же запроса с тем же ключом возвращает тот же ресурс;
другое содержимое с уже использованным ключом получает `409`.

## Поведение после перезапуска

- `queued` jobs автоматически возвращаются в локальную очередь;
- незавершенный parsing и validation запускаются повторно;
- `running` и `cancel_requested` jobs закрываются как retryable failure
  `LOCAL_BACKEND_RESTARTED`, потому что новый процесс не может доказать
  состояние старого subprocess;
- frontend должен предложить повторный запуск из завершенной validation;
- два backend-процесса не могут использовать один state root одновременно.

## Retention

Сначала посмотреть dry-run, не удаляя файлы:

```bash
python -B 04_Web_app/backend_runtime.py \
  --config 04_Web_app/config/local_backend_v1.json \
  --retention-report
```

Применить тот же алгоритм к terminal-ресурсам старше `retention.days`:

```bash
python -B 04_Web_app/backend_runtime.py \
  --config 04_Web_app/config/local_backend_v1.json \
  --apply-retention
```

Cleanup удаляет только полностью завершенную старую цепочку ресурсов и пишет
audit event. Активные jobs и их родительские validation/upload сохраняются.

## Research-pilot профиль

`04_Web_app/config/research_backend_v1.example.json` является шаблоном одного
внешнего VM/server. Python backend и там слушает только `127.0.0.1`; HTTPS и
простую авторизацию обеспечивает reverse proxy. Перед запуском задаются
реальный HTTPS origin и CORS allowlist. Tracked config не содержит пароль или
token.

Допустимые non-secret overrides:

- `MMM_BACKEND_PUBLIC_BASE_URL`;
- `MMM_BACKEND_ALLOWED_ORIGINS` как comma-separated origins;
- `MMM_BACKEND_PORT`;
- `MMM_BACKEND_RETENTION_DAYS`.

Готовая упаковка для одного Linux-сервера описана в
`04_Web_app/deployment/README_RESEARCH_PILOT.md`. Скрипт
`04_Web_app/deployment/research_pilot.py` отдельно переносит зарегистрированный
model inventory без training panel, генерирует Nginx/systemd-конфигурацию и
обслуживает health, disk, retention и backup/restore. Model archive и секреты
не попадают в GitHub.

## Граница research pilot

File-backed runtime подходит для одного research server и одного worker, но не заменяет PostgreSQL, durable queue, object storage,
SSO/RBAC, TLS, antivirus/DLP, quotas, monitoring, backup и disaster recovery.
Эти реализации понадобятся для company-contour/multi-user production, сохранив lifecycle,
DecisionResult, ResultOverview и Product API contracts. До появления sealed
OOT модель остается `preprod_restricted`; это не блокирует исследовательские
прогнозы и allocation, но система не выдает формальный launch/cancel verdict.
