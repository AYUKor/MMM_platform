# B2.2 Federal Campaign UX V1

## Назначение и граница

B2.2 завершает пользовательский путь федеральной кампании без изменения
population-weighted allocation formula, MMM, optimizer, scenario semantics или
geo projection:

```text
словарь -> upload -> validation -> federal info -> canonical geo plan
         -> S1-S6 calculation -> existing result/media plan/report
```

Frontend не определяет eligible geographies, channel/direction support,
population weights, allocated budget или reconciliation. Он строго проверяет и
показывает готовую backend projection.

## Validation contract

`validation_result_v2` аддитивно содержит `federal_allocation` со статусом:

- `none` — федеральных строк нет, блок не показывается;
- `available` — allocation завершён и reconciliation опубликован;
- `error` — федеральное обозначение обнаружено, но allocation не завершён;
  пользователь получает только безопасный русский текст.

Для `available` backend публикует policy/package identity, количество исходных
строк, исходный и распределённый бюджет, абсолютную difference, declared/ready/
excluded geo counts, denominator policy, `lmax`, required period, display-name
каналы, business directions, mixed-plan flag и direction × channel × period
breakdown. Full population vector, denominator rows, expanded rows, hashes, paths
и stack traces в browser contract не входят.

Projection строится не из объекта allocator в памяти. Endpoint повторно читает
immutable `job_inputs.json`, проверяет SHA/size durable
`federal_geo_allocation_audit.json` и только затем формирует browser view.
Expanded provenance CSV и полный audit остаются backend artifacts согласно
`FEDERAL_GEO_ALLOCATION_V1.md`.

При одном однородном universe `geo_count` содержит `ready_geo_count`. При разных
направлениях или периодах верхний count может быть `null`; frontend показывает
breakdown и не складывает разные universe в фиктивное общее число географий.

## Forecast geo availability

`ForecastGeoAvailabilityResolver` является единственной backend-проверкой
временной доступности. Он получает pinned package, direction, channel, даты,
package `l_max` и действующую denominator policy. Exact pure denominator lookup
используется одновременно resolver-ом и `ForecastEngine`; runtime вызов в
forecast сохраняется как defense-in-depth.

Для каждой исходной строки required horizon равен
`campaign_start .. campaign_end + lmax` включительно. Действующая policy:
analog year 2025, та же geography, ближайшее наблюдение не дальше 7 дней,
без extrapolation, cross-geo fill или специальных исключений. Федеральная строка
распределяется только по ready subset; локальная declared-but-not-ready geography
блокирует validation до создания job.

Текущий package regression на однодневную кампанию `2026-09-01`:
`175 / 182 / 103 / 104` ready из declared `211 / 220 / 114 / 117` для
`ТС5 Онлайн / ТС5 Офлайн / ТСХ Онлайн / ТСХ Офлайн`. Это test evidence, а не
hard-coded production count.

## Словарь медиаплана

`GET /api/v1/templates/media-plan-dictionary` требует permission
`calculation.create`, возвращает XLSX attachment с `Cache-Control: no-store` и
UTF-8 filename `Словарь_для_медиаплана.xlsx`.

Workbook создаётся при запросе из одного verified active-package context и
canonical geo catalog:

- `Каналы` — шесть display-name каналов, описание и поддержка federal input;
- `Географии` — 220 canonical geographies, direction support `Да/Нет` и спокойное
  пояснение, что фактическая доступность зависит от дат;
- `Как указать всю Россию` — три точных aliases, правило, пример и mixed-plan
  semantics.

Counts не являются production constants. Для текущего pinned package regression
evidence равно `211 / 220 / 114 / 117` для `ТС5 Онлайн / ТС5 Офлайн /
ТСХ Онлайн / ТСХ Офлайн`.

## Пользовательский интерфейс

На `/calculations/new` кнопки `Скачать шаблон` и `Скачать словарь` образуют один
блок подготовки файла. Existing template endpoint и содержимое шаблона не
менялись.

Успешный federal validation показывает отдельный информационный блок:

- `Обнаружено федеральное размещение`;
- исходный и распределённый бюджеты;
- declared/ready/excluded число географий или breakdown по строкам;
- метод `Пропорционально населению`;
- число исходных строк;
- `Распределено полностью · 0 ₽`, если difference не выше 0.01 RUB.

Federal allocation не превращается ни в ошибку файла, ни в model limitation.
Mixed `РФ + local geo` остаётся разрешённым и получает ровно одно спокойное
additive warning. Неутверждённое `Вся Россия` блокируется человеческой подсказкой
с тремя разрешёнными значениями.

Campaign map использует существующие `geo_points` после backend expansion и
показывает только ready allocated geographies. Для полностью покрытого ready
subset backend возвращает canonical points и zero unlocated budget; отдельной
федеральной карты и новой projection нет.

## Test matrix A-J

| Case | Evidence |
|---|---|
| A. Обычная кампания | existing validation/frontend regression; `federal_allocation.status=none` |
| B. `РФ` | allocator/service integration, UI E2E и opt-in live full flow |
| C. `Россия` | approved-alias allocator regression и real-package service test |
| D. `российская федерация` | case-insensitive allocator regression |
| E. `Вся Россия` | real-package service rejection + browser human error |
| F. `РФ + Москва` | allocator additive reconciliation + exactly one browser warning |
| G. две строки РФ | separate expansion/audit + aggregated browser source row count |
| H. разные directions | backend breakdown reconciliation + browser 211/114 display |
| I. dictionary download | HTTP, OpenXML, sheets, counts and visual workbook QA |
| J. template download | unchanged endpoint regression and live download |

Default live test is opt-in:

```bash
B2_2_LIVE=true \
B2_2_LIVE_EMAIL='<local-acceptance-user>' \
B2_2_LIVE_PASSWORD='<local-acceptance-password>' \
PLAYWRIGHT_REUSE_SERVER=true \
node node_modules/@playwright/test/cli.js test \
  e2e/b2-2-federal-campaign.live.spec.ts --project=chromium --workers=1
```

Он не подменяет routes: скачивает оба XLSX, загружает `geo=РФ`, сверяет
100,000,000 RUB -> 100,000,000 RUB, `211 declared -> 175 ready` mapped
geographies и zero unlocated для `ТС5/Онлайн`, запускает job, открывает
result/media plan и проверяет report download. В том же live acceptance отдельно
проверяется `114 declared -> 103 ready` для `ТСХ/Онлайн`.

## Browser и visual evidence

Fixture E2E покрывает light/dark screenshots, 375px и 1024x768 без horizontal
overflow, keyboard map tooltip и download controls. Chromium является default
automation. Safari-compatible acceptance запускается так:

```bash
PLAYWRIGHT_ENGINE=webkit PLAYWRIGHT_REUSE_SERVER=true \
node node_modules/@playwright/test/cli.js test \
  e2e/new-calculation.visual.spec.ts --project=webkit \
  --grep 'upload screen|federal validation|mixed federal|unknown federal|campaign map'
```

PNG хранятся только в `docs/ui-review/b2-2-federal-campaign-ux/` и не входят в
runtime bundle. Они являются UI fixture evidence, а не результатом реального MMM
расчёта.

## Post-merge Predfin materialization

B2.2 не меняет `02_Predfin`. После merge оператор должен сначала разрешить exact
target commit и убедиться, что Predfin checkout не содержит tracked changes:

```bash
test -z "$(git -C <MMM_WORKSPACE_ROOT>/02_Predfin/MMM_platform status --porcelain --untracked-files=no)"
git -C <MMM_WORKSPACE_ROOT>/02_Predfin/MMM_platform fetch origin main
B2_2_SHA="$(git -C <MMM_WORKSPACE_ROOT>/02_Predfin/MMM_platform rev-parse origin/main)"
git -C <MMM_WORKSPACE_ROOT>/02_Predfin/MMM_platform cat-file -e "${B2_2_SHA}^{commit}"
git -C <MMM_WORKSPACE_ROOT>/02_Predfin/MMM_platform checkout --detach "${B2_2_SHA}"
git -C <MMM_WORKSPACE_ROOT>/02_Predfin/MMM_platform status --short --branch
git -C <MMM_WORKSPACE_ROOT>/02_Predfin/MMM_platform rev-parse HEAD^{tree}
```

Затем применяются gates из `docs/workspace/PROMOTION_TO_PREDFIN.md`: package
closure и extensions проверяются физически и по SHA, backend `--check-only`,
backend/frontend/browser regression, secrets/path scan и новая versioned
acceptance evidence. Эти команды не являются разрешением на Fin или deploy.

## Не изменено

- population-weighted allocation formula и population source;
- MMM/posterior mathematics и model fits;
- forecast, optimizer и S1-S6 semantics;
- geo projection и canonical catalog;
- authentication semantics;
- existing campaign-plan template;
- Predfin, Fin и corporate server.
