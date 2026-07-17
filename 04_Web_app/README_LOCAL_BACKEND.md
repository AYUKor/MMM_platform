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
9. Local pilot auth защищает продуктовые маршруты server-side сессиями и
   permissions для ролей viewer, analyst и admin.
10. Admin API управляет локальными пользователями, отзывом сессий, безопасным
    состоянием системы и append-only audit log.

## Первый локальный запуск auth

Реальных паролей и session secret в Git нет. Python environment должен
содержать `argon2-cffi==25.1.0`; Phase E намеренно не меняет отдельный server
deployment package. Затем задайте секрет через untracked environment и один
раз создайте администратора:

```bash
export MMM_AUTH_SESSION_SECRET='<random-secret-at-least-32-characters>'
export MMM_AUTH_BOOTSTRAP_ADMIN_EMAIL='admin@example.org'
export MMM_AUTH_BOOTSTRAP_ADMIN_PASSWORD='<temporary-strong-password>'

python -B 04_Web_app/backend_runtime.py \
  --config 04_Web_app/config/local_backend_v1.json \
  --bootstrap-admin
```

После bootstrap удалите временные email/password variables. Session secret
нужен каждому последующему запуску backend. Полный порядок и безопасное
обновление существующего администратора описаны в
`04_Web_app/docs/runbooks/BOOTSTRAP_ADMIN_V1.md`.

## Предварительная проверка

Из корня проекта:

```bash
export MMM_AUTH_SESSION_SECRET='<the-same-stable-local-secret>'
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
export MMM_AUTH_SESSION_SECRET='<the-same-stable-local-secret>'
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
```

`health` и `ready` остаются безопасными anonymous checks. Model, calculations,
results и admin routes требуют входа. Браузер получает cookie автоматически;
для ручного smoke-теста сначала вызовите login с разрешенным `Origin` и cookie
jar, затем используйте тот же jar для защищенных GET.

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
- `auth/auth.sqlite3`: users, session digests, login attempts и audit events;
- `backend.lock`: защита от двух backend-процессов на одном state.

## HTTP-последовательность для frontend

| Шаг | Метод и route | Результат |
|---|---|---|
| Вход | `POST /api/v1/auth/login` | `AuthSession v1` и HttpOnly cookie |
| Текущая сессия | `GET /api/v1/auth/session` | authenticated/anonymous состояние и permissions |
| Загрузка | `POST /api/v1/uploads` | `CampaignUpload v1` |
| Статус загрузки | `GET /api/v1/uploads/{upload_id}` | `received`, `parsed` или `rejected` |
| Проверка | `POST /api/v1/uploads/{upload_id}/validations` | `ValidationResult v1` |
| Статус проверки | `GET /api/v1/validations/{validation_id}` | `running`, `valid` или `invalid` |
| Расчет | `POST /api/v1/validations/{validation_id}/jobs` | `DecisionJob v1` |
| История | `GET /api/v1/jobs` | jobs с campaign preview из validation |
| Статус | `GET /api/v1/jobs/{job_id}` | lifecycle job status |
| Прогресс | `GET /api/v1/jobs/{job_id}/progress` | browser-safe progress events |
| Экран процесса | `GET /api/v1/jobs/{job_id}/progress-view` | `JobProgressView v1` |
| Экран результата | `GET /api/v1/jobs/{job_id}/overview` | `ResultOverview v1` |
| Product result | `GET /api/v1/jobs/{job_id}/result-view` | `JobResultView v1` для четырех вкладок |
| Медиаплан сценария | `GET /api/v1/jobs/{job_id}/media-plan?scenario_id=S06` | paginated `ScenarioMediaPlan v1` |
| Полный результат | `GET /api/v1/jobs/{job_id}/result` | `DecisionResult v1` |
| Excel | `GET /api/v1/artifacts/{artifact_id}/download` | hash-checked файл |
| Выход | `POST /api/v1/auth/logout` | revoke server-side session и clear cookie |

Технический job-list поддерживает `limit`, `offset` и optional `status`.
Запрос выполняется только внутри authenticated browser session.

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
| `GET /api/v1/admin/users` | Локальные пользователи, filters и pagination |
| `GET /api/v1/admin/roles` | Versioned roles и готовые permissions |
| `GET /api/v1/admin/system/status` | Реальные безопасные subsystem checks |
| `GET /api/v1/admin/audit` | Append-only административный audit |

Создание upload, validation и calculation требует уникальный заголовок
`Idempotency-Key` длиной не менее 16 символов. Login/logout/admin mutations не
используют этот ключ: их consistency обеспечивают session, permission и
SQLite transaction rules.

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
дополнительный perimeter control обеспечивает reverse proxy, а приложение
проверяет собственную local pilot session. Перед запуском задаются
реальный HTTPS origin и CORS allowlist. Tracked config не содержит пароль или
token.

Допустимые non-secret overrides:

- `MMM_BACKEND_PUBLIC_BASE_URL`;
- `MMM_BACKEND_ALLOWED_ORIGINS` как comma-separated origins;
- `MMM_BACKEND_PORT`;
- `MMM_BACKEND_RETENTION_DAYS`.
- `MMM_AUTH_MODE=local`;
- `MMM_AUTH_COOKIE_SECURE=true`;

`MMM_AUTH_SESSION_SECRET` является secret override и намеренно не входит в
effective config hash или runtime card.

Готовая упаковка для одного Linux-сервера описана в
`04_Web_app/deployment/README_RESEARCH_PILOT.md`. Скрипт
`04_Web_app/deployment/research_pilot.py` отдельно переносит зарегистрированный
model inventory без training panel, генерирует Nginx/systemd-конфигурацию и
обслуживает health, disk, retention и backup/restore. Model archive и секреты
не попадают в GitHub.

## Граница research pilot

File-backed runtime и SQLite auth подходят для одного research server и одного
worker, но не заменяют PostgreSQL, durable queue, object storage, corporate
SSO/MFA, TLS, antivirus/DLP, quotas, monitoring, backup и disaster recovery.
Эти реализации понадобятся для company-contour/multi-user production, сохранив lifecycle,
DecisionResult, ResultOverview и Product API contracts. До появления sealed
OOT модель остается `preprod_restricted`; это не блокирует исследовательские
прогнозы и allocation, но система не выдает формальный launch/cancel verdict.
