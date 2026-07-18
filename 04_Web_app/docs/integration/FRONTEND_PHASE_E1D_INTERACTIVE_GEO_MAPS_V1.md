# Frontend Phase E.1D: interactive geo budget maps

## Статус и граница

Phase E.1D реализует один общий интерактивный `GeoBudgetMap` для Главной и
проверки новой кампании. Ветка начата от
`origin/main@3ab8de98f9e73fb6d5c4dc8060261165a99d50c3` после merge PR #25.

Frontend не меняет Python backend, schemas/OpenAPI, geo catalog, workspace
aggregation, validation semantics, MMM, forecast, optimizer, recommendation,
auth/admin, report artifacts или deployment. Новых npm dependencies нет.

## Источники данных

| Режим | Endpoint | Что является backend fact |
|---|---|---|
| `workspace` | `GET /api/v1/workspace/geo-budget` | total budget, campaigns, rows, coordinates, shares и coverage |
| `campaign` | `GET /api/v1/validations/{validation_id}/view-v2` | geo points, coordinates, budget/share, channel display names, limitations и coverage |
| version guard | `GET /api/v1/meta/geo-catalog` | catalog version, source/license и catalog availability |

Все запросы продолжают использовать `credentials: "include"`. Raw payload не
передается в renderer. `adaptWorkspaceGeoBudget` и
`adaptValidationGeoBudget` формируют узкую typed projection. Они принимают
только `coordinates_status=canonical`, не геокодируют названия, не исправляют
координаты, не объединяют aliases и не суммируют budget rows. Fail-closed
runtime parsers клиента остаются первым contract guard; adapter дополнительно
отклоняет NaN, отрицательные деньги, invalid shares и WGS84 вне диапазона.

## Общий component API

```ts
type GeoBudgetMapRequestState =
  | "ready"
  | "loading"
  | "network-error"
  | "unsupported-contract";

interface GeoBudgetMapProps {
  model: GeoBudgetMapModel | null;
  requestState?: GeoBudgetMapRequestState;
  onRetry?: () => void;
}
```

`GeoBudgetMapModel` — discriminated union `workspace | campaign`. Общая часть
содержит canonical located points, backend coverage, unlocated geography list,
unlocated budget/share и presentation maximum. Workspace добавляет готовые
workspace totals; campaign добавляет validation ID и requested budget.

## Контур и projection

Локальный `frontend/src/assets/maps/russia-outline-v1.svg` создан offline из
Natural Earth Admin 0 – Countries 1:50m v5.1.1, feature `ADM0_A3=RUS`.
Natural Earth публикует набор в public domain. Исходный архив и итоговый SVG
зафиксированы SHA-256 в `frontend/src/assets/maps/RUSSIA_OUTLINE_SOURCE.md`.
SVG содержит только упрощенную геометрию без политических подписей и не является
юридически авторитетной картой границ.

Asset импортируется через Vite `?raw`; runtime fetch tiles/GeoJSON/boundary не
выполняется. Перед inline render применяется fail-closed local-asset guard,
запрещающий script, foreignObject и URL-bearing href/src.

Оба режима используют одну spherical Albers Equal Area projection:

- standard parallels: `45° N`, `70° N`;
- central meridian: `100° E`;
- latitude of origin: `55° N`;
- fixed viewBox: `0 0 1200 680`;
- fixed affine transform: scale `880.2744673041848`, offsets
  `659.5017197759643 / 522.4001925283919`.

Longitude относительно central meridian заворачивается в `[-π, π)`. Ни один
параметр не вычисляется из текущих points, поэтому один город остается в одной
позиции между workspace, кампаниями, themes и viewport sizes. Полное решение
зафиксировано ADR 0024.

## Визуальная семантика

- radius: `minRadius + sqrt(budget / maxBudget) * (maxRadius - minRadius)`;
- desktop radius `5–22 px`, mobile `4–16 px`;
- brightness использует тот же sqrt-normalized budget и один accent color;
- points сортируются `budget ascending`, затем `geoDisplayName ascending`,
  поэтому крупные bubbles рисуются последними;
- zero budget не создает активную точку;
- desktop workspace labels: top-10 по опубликованному backend budget,
  tie-break по display name;
- desktop campaign labels: все located geographies;
- compact workspace labels: постоянно видимы top-5 из той же backend-budget
  очереди; остальные точки и tooltip остаются интерактивными;
- compact campaign labels: все географии доступны через отдельную
  keyboard-accessible кнопку и полный список под картой, а permanent on-map
  labels скрыты, чтобы не создавать нечитаемый слой;
- desktop/compact positions рассчитывает deterministic collision-aware layout
  в пикселях текущего canvas: он избегает пересечения label-label и
  label-marker, удерживает подписи внутри карты и добавляет leader lines для
  удаленных свободных позиций;
- карта не заменяет полный campaign geography list.

Workspace tooltip показывает город, общий бюджет, число кампаний и backend
share. Campaign tooltip показывает город, budget/share, только
`channel_display_name` и published limitation count/state. Raw channel IDs и
локальный channel dictionary не используются.

## Accessibility и responsive behavior

Каждая точка — native `button` с 44×44 px touch target и полным accessible
name. Tooltip открывается hover, keyboard focus и click/touch. `Escape`
закрывает его и возвращает focus без повторного открытия; close button и outside
pointer поддержаны отдельно. Tooltip ограничен canvas на desktop и становится
нижней panel на mobile. Map group, legend, attribution и coverage остаются
доступны без hover. В compact campaign mode кнопка с `aria-expanded` открывает
полный список всех подписей; native marker buttons остаются доступны всегда.
`prefers-reduced-motion` отключает transitions.

Visible attribution:

- `Координаты городов: GeoNames, CC BY 4.0.`
- `Контур карты: Natural Earth, public domain.`

## Coverage и request states

| State | Поведение |
|---|---|
| `available` | рисуются все canonical located points |
| `partial` | карта рисуется; unlocated count, names, budget и share остаются видимыми |
| `unavailable` | карта не рисуется; workspace показывает backend display text, campaign — нейтральную contract-gap формулировку |
| empty workspace | controlled empty state, без fake points |
| loading | отдельный спокойный loading state |
| network error | красный transport state с retry; остальная Home page сохраняется |
| unsupported contract/version mismatch | fail-closed state, точки и budget map скрыты |

Partial/unavailable не переименовываются в file error и не удаляют unlocated
budget. Frontend не вычисляет complement share и не восстанавливает координаты.

## Control campaign

Test/review fixture явно помечена `Демонстрационные данные` и содержит 45 rows,
15 canonical geographies, три human-readable channels и ровно
`267 818 706 RUB`. Fixture budgets reconciled exactly; campaign map renders 15
points and 15 labels. Synthetic data используется только в unit/E2E/review
screenshots и не выдается за live result.

## Performance

Сравнение production build с точным baseline на тех же locked dependencies:

| Asset group | Baseline raw / gzip | E.1D raw / gzip | Delta raw / gzip |
|---|---:|---:|---:|
| JavaScript | 622,314 / 173,250 B | 683,594 / 198,180 B | +61,280 / +24,930 B |
| CSS | 163,785 / 26,021 B | 173,743 / 27,765 B | +9,958 / +1,744 B |
| HTML | 839 / 512 B | 839 / 515 B | 0 / +3 B |
| Total | 786,938 / 199,783 B | 858,176 / 226,460 B | **+71,238 / +26,677 B** |

Projection и paint order memoized. Tooltip state does not rerender SVG outline
or marker paths. Bundle warning over 500 kB predates this phase and remains
non-blocking; the measured delta introduces no new runtime library.

## Verification

| Gate | Result |
|---|---|
| Generated contract drift | passed: 26 generated files unchanged |
| TypeScript | passed |
| ESLint | passed: 0 warnings |
| Unit/component | passed: 42 files, 483 tests |
| Production build | passed: 156 modules |
| Fixture/full Playwright | passed: 177 tests across all six visual/product specs |
| Chromium automated | passed: 177 fixture + 1 live test |
| Live backend, no interception | passed: real control job and validation, including Excel download |
| Safari manual smoke | passed on live desktop Home/workspace and campaign maps; pointer tooltip and Escape dismissal verified |
| Light/dark/mobile screenshots | passed visual review: 20 PNG |
| Pull Request / final CI / head SHA | Draft PR #26; final CI and head SHA pending |

Browser evidence and screenshot inventory are recorded in
`docs/ui-review/phase-e1d-interactive-geo-maps-v1/REVIEW_NOTES.md`.

## Known limitations

1. The outline is a country-level schematic, not a legal, route or cadastral
   map; there are no region polygons or pan/zoom controls.
2. Label placement is a deterministic greedy collision-aware layout, not a
   full cartographic labeling engine. The 15-point control campaign remains
   the reviewed density boundary. Compact workspace intentionally keeps five
   permanent labels; compact campaign exposes every name through the
   accessible toggle/list instead of overlaying all names on the map.
3. Campaign `map_coverage` has no browser display text; unavailable campaign
   copy is therefore neutral frontend presentation, while all counts/money
   remain backend facts.
4. Zero-budget canonical geographies remain in the detailed list but do not
   create misleading active bubbles.
5. Safari manual smoke covers the live desktop layout. Compact/mobile layout is
   covered by automated Chromium and reviewed responsive screenshots rather
   than Safari device emulation.
