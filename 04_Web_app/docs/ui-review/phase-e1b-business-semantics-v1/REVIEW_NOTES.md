# Phase E.1B Business Semantics — Review Notes

## Статус evidence

Review status: **automated, live backend, visual evidence and Safari manual
smoke passed**.

Baseline:
`origin/main@f5944c5b25296a2cd58e27b4c8469c572fe93e20`
(merged PR #23).

Branch:
`codex/frontend-phase-e1b-business-semantics-v1`.

Synthetic screenshots и fixture E2E не используются как доказательство live
backend result. Live acceptance проведена отдельно, без route interception.

## Review boundary

Product migration использует семь business projections и один изолированный
artifact transport:

- `GET /api/v1/jobs/{job_id}/result-view-v2`;
- `GET /api/v1/jobs/{job_id}/media-plan-v2`;
- `GET /api/v1/validations/{validation_id}/view-v2`;
- `GET /api/v1/models/active-v2`;
- `GET /api/v1/model/overview-v2`;
- `GET /api/v1/meta/geo-catalog`;
- `GET /api/v1/workspace/geo-budget`.
- `GET /api/v1/jobs/{job_id}/result-view` — только validated `report` subtree.

V1 business fallback, client-side ROAS/recommendation/allocation computation,
raw channel IDs и guessed map coordinates запрещены. Artifact-only parser не
возвращает campaign, KPI, budgets, ROAS, scenarios, recommendation или
reliability из v1. Existing upload/job lifecycle и workspace home projection
не становятся источником v2 business semantics.

## Screenshot inventory

Review directory:
`04_Web_app/docs/ui-review/phase-e1b-business-semantics-v1/`

| State | Light | Dark | Review |
|---|---|---|---|
| Validation passed | `validation-passed-light.png` | `validation-passed-dark.png` | passed |
| Grouped model limitations | `validation-limitations-light.png` | `validation-limitations-dark.png` | passed |
| S1 reference/manual review | `result-s1-light.png` | `result-s1-dark.png` | passed |
| S5 safe partial, ROAS, budget and risk | `result-s5-safe-partial-light.png` | `result-s5-safe-partial-dark.png` | passed |
| S5 full conservative | `result-s5-full-conservative-light.png` | `result-s5-full-conservative-dark.png` | passed |
| S6 infeasible | `result-s6-infeasible-light.png` | `result-s6-infeasible-dark.png` | passed |
| S6 feasible | `result-s6-feasible-light.png` | `result-s6-feasible-dark.png` | passed |
| Unsupported v2 contract | `result-unsupported-light.png` | `result-unsupported-dark.png` | passed |
| S5 media plan | `result-media-s5-light.png` | `result-media-s5-dark.png` | passed |
| Ready Excel report | `result-report-ready-light.png` | `result-report-ready-dark.png` | passed |
| Turnover-only model | `model-light.png` | `model-dark.png` | passed |
| Home geo-budget unavailable map | `home-geo-budget-light.png` | `home-geo-budget-dark.png` | passed |
| Mobile S5, 390×844 | `result-mobile-s5-light.png` | `result-mobile-s5-dark.png` | passed |

Всего: 26 PNG. Отдельный overflow screenshot не создавался: отсутствие
horizontal overflow проверено Playwright на 375×812, 812×375 и 1440×900.
Каждый synthetic screenshot содержит badge `Демонстрационные данные`.

## Product review checklist

- [x] В UI нет дополнительных заказов, заказов на 100 000 рублей, среднего
      чека, его механизма или псевдодекомпозиции оборота.
- [x] S1 подписан `Исходный план` / `Точка отсчета` и требует ручной проверки.
- [x] Один публичный S5 различает `full_conservative` и `safe_partial` без
      S5.1/S5.2.
- [x] Partial S5 показывает allocated/requested ROAS как две разные contract
      metrics и точные allocated/unallocated RUB.
- [x] S6 infeasible не показывает KPI, crash, retry loop или пустой ready plan.
- [x] Decision и review status визуально и семантически разделены.
- [x] Risk composition показывает RUB и share трех contract categories.
- [x] Validation разделена на `Проверка файла` и `Ограничения модели`.
- [x] Limitations сгруппированы; полный geo list раскрывается без стены chips.
- [x] Все 15 structured geographies доступны в media-plan filters.
- [x] Product labels используют channel display names, raw IDs не видны.
- [x] Model views показывают один target, 4 serving models и 12 research fits.
- [x] Home не рассчитывает geo totals из jobs/history.
- [x] Карта находится в honest unavailable state.
- [x] Report status, sheets и final/working download используют только узкую
      artifact projection; v2 остается источником всех business semantics.
- [x] Без `report.download` ссылки не рендерятся; unsafe path fail closed.
- [x] Status не кодируется только цветом; focus и accordions доступны с
      клавиатуры.
- [x] Desktop/mobile documents не имеют horizontal overflow.

## Automated quality gates

| Gate | Результат | Evidence |
|---|---|---|
| Generated contract drift | passed | generated files unchanged |
| TypeScript | passed | `tsc -b --pretty false` |
| ESLint | passed | `eslint . --max-warnings=0` |
| Unit tests | passed | 40 files, 463 tests |
| Production build | passed | 152 modules; non-blocking bundle-size warning |
| Fixture Playwright | passed | 157 tests; 1 unrelated opt-in live suite skipped |
| Full frontend regression | passed | Phase A–E and E.1B fixture suites |
| Chromium automated | passed | installed Chrome Chromium channel |
| Live E.1B acceptance | passed | 1 test, no route interception; real XLSX download verified |
| Screenshot dimensions/overflow | passed | 26 PNG; 375×812, 812×375, 1440×900 checks |
| Contrast light/dark | passed | result 5.981/8.002; validation 5.981/8.002 |
| Safari manual smoke | passed | live backend, Safari 1024×768 |

## Live backend acceptance

Status: **passed without route interception**.

Control job `job_a8d96e52fc792197be1f` и validation
`validation_edcd6ec607d845ae34b2` подтвердили:

- 45 строк, 15 географий и 3 канала;
- requested budget 267 818 706 RUB;
- file validation passed и grouped turnover limitations;
- S5 `safe_partial`: allocated 173 912 510.62947646 RUB, unallocated
  93 906 195.37052354 RUB, high-risk 0;
- allocated-budget ROAS P50 1.9817393657528313 и requested-budget ROAS P50
  1.2868752659545044;
- S6 `infeasible` без KPI и media-plan request;
- S1 `keep_uploaded_plan + manual_review_required`;
- S5 media-plan: 45 строк, 15 географий, 3 канала, `is_selected=false`;
- final Excel report: `ready`, 16 416 bytes, 3 sheets; browser download и
  повторный authenticated GET подтвердили XLSX MIME, attachment header,
  metadata size и ZIP signature `PK`;
- working media-plan XLSX: честный `unavailable`, без CSV-подмены;
- model: 1 serving target, 4 serving models, 12 research fits;
- Home geo-budget и честный unavailable state карты;
- отсутствие raw channel IDs и diagnostic target cards;
- clean browser console, отсутствие auth leakage и document overflow.

## Safari manual smoke

Status: **passed on the live local backend**.

В Safari при окне 1024×768 вручную подтверждены:

- login и session bootstrap с переходом на Главную;
- Home с live geo-budget, 15 географиями и unavailable-state карты;
- Result Overview и turnover-only KPI;
- сценарии S1, partial S5 и infeasible S6 без fake KPI;
- media-plan с 3 display-name каналами и 15 structured geographies;
- Validation с отдельными блоками `Проверка файла` и `Ограничения модели`;
- Model с 1 serving target, 4 serving-моделями и 12 research fits;
- отсутствие overlap, raw channel IDs и legacy orders/average-basket metrics.

Safari smoke дополняет, но не заменяет Chromium automation, fixture regression
и отдельный live acceptance без route interception.

## Known limitations и contract gaps

1. `job_result_view_v2` не содержит report artifact metadata/download path;
   report transport изолирован в narrow v1 artifact projection без semantic
   fallback. Текущий backend не публикует отдельный working media-plan XLSX.
2. Contract публикует `allocation_share`, но не отдельную
   `unallocated_share`; frontend не вычисляет `1 - allocation_share`.
3. Approved coordinates отсутствуют; Phase E.1B не реализует карту.
4. Daily media-plan rows и channel/date calendar недоступны.
5. S6 infeasible намеренно не имеет effect/ROAS/media plan.
6. Research package остается preprod/restricted; recommendation касается
   распределения бюджета, не запуска кампании.

Backend, optimizer, contracts, OpenAPI, auth/admin и deployment находятся вне
review boundary этой frontend-фазы.
