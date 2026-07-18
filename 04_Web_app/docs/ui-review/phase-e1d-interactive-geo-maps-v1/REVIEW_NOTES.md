# Phase E.1D Interactive Geo Maps — Review Notes

## Статус evidence

Review status: **20 fixture screenshots reviewed; local regression, Chromium,
live backend acceptance and Safari desktop smoke passed. PR CI is PENDING**.

Baseline:
`origin/main@3ab8de98f9e73fb6d5c4dc8060261165a99d50c3`
(merged PR #25).

Branch:
`codex/frontend-phase-e1d-interactive-geo-maps-v1`.

Pull Request: **#26** (Draft until final CI is green).

Implementation commit: `3e2efc2`; final evidence head is tracked by PR #26.

Файлы ниже созданы fixture E2E и не являются доказательством live backend
result. Они проверяют review states на synthetic contract fixtures. Live
acceptance проводится отдельно без route interception.

## Review boundary

Один `GeoBudgetMap` используется в двух режимах:

- `workspace` получает готовые totals, canonical points, budget shares и
  coverage только из `GET /api/v1/workspace/geo-budget`;
- `campaign` получает points, budgets, channel display names, limitations и
  coverage только из `GET /api/v1/validations/{validation_id}/view-v2`.

Frontend не агрегирует workspace history, не геокодирует названия, не
подставляет aliases и не восстанавливает отсутствующие coordinates. Local
Natural Earth outline и фиксированная Albers Equal Area projection не требуют
runtime map API.

## Screenshot inventory

Review directory:
`04_Web_app/docs/ui-review/phase-e1d-interactive-geo-maps-v1/`

| # | State | Light | Dark | Capture status |
|---:|---|---|---|---|
| 1 | Workspace desktop, backend-budget top-10 | `home-workspace-map-top-10-light.png` | `home-workspace-map-top-10-dark.png` | captured |
| 2 | Workspace mouse/keyboard tooltip | `home-workspace-map-tooltip-light.png` | `home-workspace-map-tooltip-dark.png` | captured |
| 3 | Workspace partial coverage | `home-workspace-map-partial-light.png` | `home-workspace-map-partial-dark.png` | captured |
| 4 | Workspace unavailable coverage | `home-workspace-map-unavailable-light.png` | `home-workspace-map-unavailable-dark.png` | captured |
| 5 | Workspace compact/mobile, persistent top-5 | `home-workspace-map-mobile-light.png` | `home-workspace-map-mobile-dark.png` | captured |
| 6 | Campaign desktop, 15 canonical points and labels | `campaign-map-light.png` | `campaign-map-dark.png` | captured |
| 7 | Campaign tooltip with display-name channels | `campaign-map-tooltip-light.png` | `campaign-map-tooltip-dark.png` | captured |
| 8 | Campaign partial coverage | `campaign-map-partial-light.png` | `campaign-map-partial-dark.png` | captured |
| 9 | Campaign unavailable coverage | `campaign-map-unavailable-light.png` | `campaign-map-unavailable-dark.png` | captured |
| 10 | Campaign compact/mobile, accessible all-label toggle/list | `campaign-map-mobile-light.png` | `campaign-map-mobile-dark.png` | captured |

Всего: **20 PNG**. Все файлы прошли visual review на overlap, clipping, tooltip
bounds, contrast и legibility. Synthetic fixture badge остается видимым; эти
PNG не выдаются за live backend evidence.

## Expected visual behavior

- Desktop workspace постоянно подписывает top-10 городов, выбранных по
  опубликованному backend budget; все остальные located cities остаются
  интерактивными точками.
- Desktop campaign подписывает все located geographies.
- Collision-aware layout располагает labels в rendered-canvas pixels,
  избегает уже занятых labels и bubbles, удерживает текст внутри canvas и
  использует leader lines для удаленных позиций.
- Compact workspace постоянно показывает top-5 из workspace top-10.
- Compact campaign не накладывает 15 постоянных labels на узкую карту. Все
  названия доступны через кнопку с `aria-expanded` и полный список; marker
  buttons и tooltip остаются доступны keyboard, mouse и touch.
- Размер и яркость bubbles зависят от budget через sqrt scaling. Крупные точки
  рисуются поверх мелких; coordinates и projection не масштабируются по
  min/max текущего набора.
- Partial/unavailable states сохраняют unlocated count, money и share; карта не
  скрывает потерянный budget за декоративным empty state.

## Product review checklist

- [x] Fixture inventory содержит light/dark evidence для обоих режимов,
      tooltip, partial, unavailable и compact/mobile states.
- [x] Workspace и campaign используют общий component и fixed projection.
- [x] Desktop workspace label policy — top-10; campaign — all located.
- [x] Compact workspace label policy — top-5; campaign — accessible all-label
      toggle/list.
- [x] Visible attribution содержит GeoNames CC BY 4.0 и Natural Earth public
      domain.
- [x] Final visual inspection всех 20 PNG.
- [x] Chromium automated acceptance: 177 fixture + 1 live test.
- [x] Live backend acceptance без interception.
- [x] Safari manual smoke: live desktop Home/workspace and campaign maps,
      pointer tooltip and Escape dismissal.
- [ ] Pull Request CI и final head SHA: `PENDING_E1D_FINAL`.

## Automated quality gates

| Gate | Result | Evidence |
|---|---|---|
| Generated contract drift | passed | 26 generated files unchanged |
| TypeScript | passed | `tsc -b --pretty false` |
| ESLint | passed | zero warnings |
| Unit/component tests | passed | 42 files, 483 tests |
| Production build | passed | 156 modules transformed |
| Fixture/full Playwright | passed | 177/177 across all six visual/product specs |
| Chromium automated | passed | 177 fixture tests plus one live acceptance |
| Live E.1D acceptance | passed | real backend; no route interception |
| Safari manual smoke | passed | live desktop Home/workspace and campaign maps; pointer tooltip and Escape dismissal |
| GitHub Pull Request CI | `PENDING_E1D_FINAL` | Draft PR #26; final head not yet frozen in this note |

## Live backend acceptance

Status: **passed**.

Live Chromium ran against the isolated local runtime without route interception.
It used job `job_a8d96e52fc792197be1f` and validation
`validation_edcd6ec607d845ae34b2`. The backend returned one workspace campaign,
15 canonical workspace points and total budget 267,818,706 RUB. The control
validation retained 45 rows, 15/15 canonical geographies, three
human-readable channels, 267,818,706 RUB and zero unlocated budget. The same
acceptance also downloaded and byte-checked the real ready Excel artifact.

## Safari manual smoke

Status: **passed for the live desktop layout**.

Safari accepted the real local login/session and rendered the Home workspace
map from the live backend. It exposed 15 native marker buttons with exact city,
budget, share and campaign accessible names, showed the backend total
267.8 million RUB, 15 geographies, the top-10 label policy and both visible
attribution lines without a crash or raw channel names.

The same session opened the live control validation review: 45 rows, 15/15
canonical geographies, three human-readable channels, 267.8 million RUB and 15
campaign markers/labels. Pointer activation opened the Санкт-Петербург tooltip
with budget, share, channels and limitation count; Escape dismissed it. No
Safari-specific rendering or interaction failure was observed.

Compact/mobile, keyboard traversal, partial/unavailable states, clipping,
overlap and horizontal-overflow boundaries remain covered by Chromium
automation and the reviewed responsive screenshot matrix. Safari manual smoke
supplements but does not replace those deterministic gates.

## Known limitations

1. The local outline is a country-level schematic, not a legal, route or
   cadastral map; region polygons, pan and zoom are absent.
2. Label placement is deterministic and collision-aware but remains a greedy
   presentation algorithm, not a full cartographic labeling engine. The
   15-point control campaign is the reviewed density boundary.
3. Compact campaign mode intentionally moves all permanent names to an
   accessible toggle/list; the points themselves remain on the map.
4. Zero-budget canonical geographies remain in the detailed list but do not
   create misleading active bubbles.
5. Campaign `map_coverage` has no backend display text, so the unavailable
   sentence is neutral frontend copy while all counts and money remain backend
   facts.
6. Safari manual smoke covers live desktop behavior; compact/mobile is not a
   Safari device-emulation claim.
