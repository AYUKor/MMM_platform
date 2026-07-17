# Frontend Phase D Navigation V1

## Статус

Phase D реализована и локально принята.

Baseline: `origin/main@ed5bddfa5948d86ff5f76220e093a9cfa8cadc2d`
(merged PR #19).

Реализованные product routes:

1. `/` — Главная;
2. `/calculations` — История расчетов;
3. `/model` — Модель;
4. `/help` — Справка.

## API boundary

Каждая страница использует ровно одну read-only projection:

| Страница | Endpoint | Контракт |
|---|---|---|
| Главная | `GET /api/v1/workspace/home` | `workspace_home_v1@1.0.0` |
| История расчетов | `GET /api/v1/calculations/history` | `calculation_history_v1@1.0.0` |
| Модель | `GET /api/v1/model/overview` | `model_overview_v1@1.0.0` |
| Справка | `GET /api/v1/help/catalog` | `help_catalog_v1@1.0.0` |

Legacy `GET /api/v1/jobs`, `GET /api/v1/models/active`, lifecycle storage,
model registry, Markdown и local filesystem не являются источниками этих
страниц. Старый Model Passport browser regression мигрирован на
`model/overview` и отдельно запрещает legacy request.

## Runtime validation

Typed client fail closed:

- проверяет exact `contract_name` и `schema_version`;
- отклоняет лишние и отсутствующие ключи;
- проверяет IDs, calendar dates, timestamps и безопасные internal routes;
- проверяет reconciliation home counters и history summary/pagination;
- проверяет active/recent status rules и result/report flags;
- принимает одну available active model либо explicit unavailable;
- не принимает неизвестные model quality/reliability fields;
- проверяет уникальность model versions, help sections, articles и relations;
- отклоняет HTML, scripts/event handlers, unsafe URLs и local paths;
- не показывает частично распарсенный payload.

HTTP/state mapping:

| HTTP/state | UI |
|---|---|
| Loading | composition-matched skeleton |
| 404 | `Раздел не найден` |
| 409 | `Опубликованные сведения временно не согласованы` |
| 422 | backend `display_text` возле History filters; последний snapshot сохранен |
| 503 | `Сведения временно недоступны` |
| Malformed/unsupported contract | `Формат сведений не поддерживается` |

## Главная

Главная больше не дублирует History. Она показывает workspace summary,
активные и последние расчеты, состояние модели, warnings и быстрые действия.
Все данные приходят из `workspace_home_v1`; jobs не агрегируются в браузере.

- backend zero показывается как `0`;
- missing facts показываются как `Нет данных` или explicit unavailable;
- `current_stage=null` не превращается в искусственный этап;
- доступность результата и отчета показана отдельными contract-backed полями;
- navigation использует опубликованные paths;
- `can_cancel` не расширяет Phase D API: отмена остается на progress page.

## История расчетов

URL хранит пользовательское состояние:

- `status`;
- `search`;
- `created_from`;
- `created_to`;
- `sort`;
- `page`;
- `page_size`.

Back, forward и refresh восстанавливают query. Frontend запрашивает только
возвращаемую backend страницу и проверяет echoed filters/pagination. Browser-side
загрузка всей истории, filtering, sorting или pagination не используются.

Desktop отображает semantic table, mobile — cards. `null` в budget, period,
segments, counts, warnings и completion time не превращается в ноль.
Placeholder поиска явно отражает backend scope: `Поиск по названию кампании`.
Старая формулировка про сегмент и номер расчета запрещена unit и browser
regression checks.

При 422 последний успешно показанный snapshot остается видимым, а backend
`display_text` показывается рядом с фильтрами. Draft search/dates сохраняются,
если пользователь меняет sort до нажатия `Применить`; этот live-QA regression
зафиксирован отдельным Playwright test. Recovery отдельно проверен после
нескольких успешных query, чтобы UI не выбирал произвольный snapshot из cache.

`report_available` является только признаком. Отдельного `report_path` в
contract нет, поэтому frontend не создает несуществующий route.

## Модель

`model_overview_v1` — единственный источник active model, framework, training
period, supported scope, capabilities, data requirements, methodology,
limitations, versions и published artifacts.

- internal `model_id` не используется как product title;
- quality score, versions и artifacts не дополняются frontend constants;
- unavailable active model сохраняет model facts как `null`;
- пустая `versions[]` показывает honest empty state;
- research/preprod и allocation-only limitations выводятся из contract;
- рекомендация не интерпретируется как решение запускать кампанию.

## Справка

Frontend рендерит только structured `paragraph`, `steps` и `note` из
`help_catalog_v1`; raw HTML и Markdown не используются. Поиск выполняется
локально только по `title`, `summary` и `keywords` уже загруженного catalog и
не создает новый endpoint.

Deep link:

```text
/help?section=scenarios&article=scenarios_s1_s6
```

Unknown section/article нормализуется к существующей article. Related routes
ограничены approved internal routes; unsafe schemes и local paths отклоняются
parser.

## UI и navigation

Design language продолжает Phase A-C: bold typography, restrained green
accent, light/dark themes, compact status pills и явные empty/error states.
Desktop sidebar содержит Главную, Новый расчет, Историю, Модель и Справку;
mobile использует пять product destinations в нижней navigation.

Home и History намеренно имеют разную hierarchy:

- Home отвечает на `что происходит и куда идти дальше`;
- History отвечает на `как найти конкретный запуск`.

## QA evidence

Review screenshots:

`04_Web_app/docs/ui-review/phase-d-navigation-v1/`

В каталоге 16 reviewed PNG `1440×900`: восемь состояний в light/dark themes.
Synthetic states содержат badge `Демонстрационные данные`.

Локальные gates:

| Gate | Результат |
|---|---|
| Generated contract drift | passed, diff отсутствует |
| TypeScript | passed |
| ESLint | passed, 0 warnings |
| Unit | 319/319 passed |
| Production build | passed |
| Phase D Playwright | 43/43 passed |
| Full frontend Playwright | 153/153 passed |
| Small-text WCAG contrast | passed; light 5.783:1, dark 7.273:1 |
| Backend Phase D contract/HTTP | 11 passed, 1 optional schema check skipped |

Build advisory: основной minified JS chunk `568.44 kB` превышает стандартный
Vite warning threshold, но production build завершается успешно.

## Live backend acceptance

Проверка проведена без interception и без fixture provider:

- backend `127.0.0.1:8765` — штатный `api/http_smoke.py`;
- Vite `127.0.0.1:4173` с `VITE_API_BASE_URL` на real backend;
- все четыре projections вернули 200;
- History получил status/search/date/sort/page/page_size через real HTTP;
- desktop, mobile 375×812 и landscape 812×375 не имеют page overflow;
- browser console warning/error отсутствуют.

Local state был пуст: live run честно подтвердил empty Home/History,
unavailable active model и published Help. Active/recent, available model и
multi-page History дополнительно проверены contract-valid synthetic E2E и не
выдаются за live result.

## Known limitations и contract gaps

1. History не публикует `report_path`; отдельной download link нет.
2. Home `can_cancel` не добавляет новый Phase D endpoint.
3. Model artifacts могут быть пустыми; frontend не создает download actions.
4. Единый reliability score, daily plans, approved map и отдельный working
   media-plan XLSX не входят в эти projections.
5. Local backend state не содержал active/recent и multi-page history.
6. Browser automation использует Chromium; Safari/WebKit parity не является
   gate этой версии.
7. Playwright пока не запускается GitHub Actions и остается локальным evidence.
8. Production JS chunk имеет неблокирующий size advisory, указанный выше.

## Out of scope confirmation

Phase D не меняет backend, schemas, OpenAPI, worker, upload/validation,
progress/result pages, MMM, forecast, optimizer, Scenario 6 ranking или
recommendation policy.
