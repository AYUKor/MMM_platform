# Phase D Navigation V1 — Review Notes

## Статус evidence

Baseline: `origin/main@ed5bddfa5948d86ff5f76220e093a9cfa8cadc2d`
(merged PR #19).

Frontend Phase D реализована и проверена. Все review screenshots получены из
TypeScript fixtures с `record_origin="synthetic_fixture"`. Badge
`Демонстрационные данные` присутствует в fixture-backed UI; в двух Home кадрах
header с badge остается выше выбранной scroll position.
Live acceptance выполнялась отдельно с настоящим local backend, без route
interception и без fixture provider.

## Screenshot inventory

Все 16 кадров имеют размер `1440×900`, `fullPage=false`, готовые fonts,
disabled animations и проверку document overflow.

| Файл | Состояние | Theme | Статус |
|---|---|---|---|
| `01-home-active-dark.png` | Home: active calculation и model summary | dark | reviewed |
| `01-home-active-light.png` | Home: active calculation и model summary | light | reviewed |
| `02-home-empty-dark.png` | Home: известные нули и empty lists | dark | reviewed |
| `02-home-empty-light.png` | Home: известные нули и empty lists | light | reviewed |
| `03-history-dark.png` | History: много строк, desktop table | dark | reviewed |
| `03-history-light.png` | History: много строк, desktop table | light | reviewed |
| `04-history-filtered-dark.png` | History: server filters/search | dark | reviewed |
| `04-history-filtered-light.png` | History: server filters/search | light | reviewed |
| `05-model-dark.png` | Model overview: available | dark | reviewed |
| `05-model-light.png` | Model overview: available | light | reviewed |
| `06-model-unavailable-dark.png` | Model overview: unavailable | dark | reviewed |
| `06-model-unavailable-light.png` | Model overview: unavailable | light | reviewed |
| `07-help-dark.png` | Help: deep-linked article | dark | reviewed |
| `07-help-light.png` | Help: deep-linked article | light | reviewed |
| `08-error-states-dark.png` | Controlled 503 state | dark | reviewed |
| `08-error-states-light.png` | Controlled 503 state | light | reviewed |

Для Home кадр сфокусирован на блоке `Активные расчеты`, чтобы active и empty
состояния различались не только ниже первого viewport. В ходе ручного просмотра
уменьшен scale заголовка компактной model card: длинное русское название больше
не разрывается посреди слова.

## Functional browser matrix

| Область | Acceptance | Результат |
|---|---|---|
| Endpoint boundary | Только четыре утвержденных Phase D GET | passed |
| Legacy guard | Нет вызовов jobs list и `/api/v1/models/active` | passed |
| Home | ready, empty, known zero, missing facts, warnings | passed |
| History URL | back/forward/refresh восстанавливают query state | passed |
| History server behavior | status/search/date/sort/page/page_size уходят в endpoint | passed |
| History search copy | Placeholder ограничен поиском по названию кампании | passed |
| History draft | смена sort не стирает введенные search/date до Apply | passed |
| History states | general/filter/search empty, 422 last-visible snapshot recovery | passed |
| Null vs zero | missing → `Нет данных`; известный `0` остается нулем | passed |
| Model | available, unavailable, 503, unsupported contract | passed |
| Help | sections, article, local search, relations, deep link | passed |
| Accessibility | landmarks, labels, keyboard, focus, semantic table/cards, small-text contrast | passed |
| Responsive | 375×812 и 812×375 без document overflow | passed |
| Stress content | long copy, 100 history rows, internal table scroll | passed |
| Reduced motion | active infinite animations отсутствуют | passed |
| Raw copy | internal contract/query field names не видны пользователю | passed |
| Console | browser warning/error отсутствуют | passed |

## Verification results

Команды выполнялись из `04_Web_app/frontend` bundled Node runtime:

| Gate | Результат |
|---|---|
| Generated contract drift | passed; generated types без diff |
| TypeScript | passed |
| ESLint | passed, 0 warnings |
| Unit tests | 27 files, 319 tests passed |
| Production build | passed; 129 modules transformed |
| Phase D Playwright | 43 tests passed |
| Full frontend Playwright regression | 153 tests passed |
| Browser WCAG contrast | minimum 5.783:1 light; 7.273:1 dark |
| Backend Phase D contract/HTTP tests | 12 run, 11 passed, 1 optional schema test skipped |

Production build сохраняет неблокирующий Vite advisory: основной JS chunk
`568.44 kB` (`160.50 kB` gzip) превышает стандартный warning threshold 500 kB.

## Live backend acceptance

Live run выполнен через штатный `04_Web_app/api/http_smoke.py`:

- backend: `http://127.0.0.1:8765`;
- frontend: `http://127.0.0.1:4173`;
- `VITE_API_BASE_URL=http://127.0.0.1:8765`;
- `VITE_RESULT_PROVIDER=http`;
- interception отсутствовал.

Реальные ответы:

| Request | Результат |
|---|---|
| `GET /api/v1/workspace/home` | 200, empty local workspace |
| `GET /api/v1/calculations/history` | 200, empty local history |
| `GET /api/v1/model/overview` | 200, explicit unavailable active model |
| `GET /api/v1/help/catalog` | 200, published structured catalog |

History дополнительно получила реальный запрос с `status=failed`,
`search=тест`, `created_from=2026-07-01`, `created_to=2026-07-17`,
`sort=campaign_asc`, `page=1`, `page_size=10`; backend вернул 200 и echoed
query state прошел runtime validation.

В live browser проверены desktop, 375×812 и 812×375: у всех четырех routes
`scrollWidth === clientWidth`; console warning/error отсутствуют. При очень
быстрой автоматизированной смене routes dev browser отменял уже ненужные
повторные GET; dependency-light smoke server мог записать `BrokenPipe` после
client abort. Завершенные запросы оставались 200, UI error state не возникал.

Пустой local state не доказывает active/recent или multi-page history на live
данных. Эти состояния проверены отдельно contract-valid synthetic E2E и явно
помечены как демонстрационные.

## Manual visual review

- [x] Home и History имеют разные задачи и page identity.
- [x] Active navigation однозначна на всех четырех routes.
- [x] Light/dark contrast и status semantics читаемы; мелкий содержательный
      текст измерен в браузере, включая hover, и превышает 4.5:1.
- [x] Long localized copy переносится без overlap/clipping.
- [x] Desktop history table остается в своей scroll region.
- [x] Mobile использует cards и нижнюю product navigation.
- [x] Skeleton повторяет композицию страницы.
- [x] Focus видим, controls имеют accessible names.
- [x] Synthetic badge присутствует на fixture-backed ready кадрах.
- [x] Отсутствующие значения не выглядят как нули.
- [x] Unavailable/error states не показывают внутренние детали.
- [x] Все 16 PNG просмотрены вручную.

## Known limitations

1. History contract не публикует отдельный `report_path`; frontend показывает
   availability и не создает ссылку.
2. Home не вызывает cancel endpoint; отмена остается в существующем progress
   flow.
3. Model artifacts могут быть пустыми; frontend не создает download actions.
4. Единый reliability score, daily scenario plans, approved map и отдельный
   working media-plan XLSX не публикуются этим contract.
5. Live local state был пуст: active/recent и multi-page history подтверждены
   synthetic contract tests, но не live dataset.
6. Автоматический browser project — Chromium; Safari/WebKit не является gate
   Phase D.
7. Playwright пока не входит в GitHub Actions workflow и остается локальным
   review evidence.
