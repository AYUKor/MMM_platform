# Локальный backend X5 MMM

Этот режим нужен для совместной разработки frontend и backend до переноса в
корпоративную инфраструктуру. Браузер обращается к `localhost`, а расчет идет
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

## Предварительная проверка

Из корня проекта:

```bash
python -B 04_Web_app/backend_runtime.py \
  --config 04_Web_app/config/local_backend_v1.json \
  --check-only
```

Проверка подтверждает Python runtime, policy-файлы, Git commit, registry
channel, package ID, fingerprint и неизменность package inventory. Текущий
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

## Что пока не является production

Локальный runtime не заменяет PostgreSQL, durable queue, object storage,
SSO/RBAC, TLS, antivirus/DLP, quotas, monitoring, backup и disaster recovery.
Эти реализации должны заменить локальные adapters, сохранив lifecycle,
DecisionResult и ResultOverview contracts. До появления sealed OOT модель
остается `preprod_restricted`, а система не должна выдавать формальный
launch/cancel verdict.
