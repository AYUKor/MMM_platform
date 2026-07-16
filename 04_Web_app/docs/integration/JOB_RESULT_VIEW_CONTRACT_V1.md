# Job Result View Contract V1

## Назначение

`GET /api/v1/jobs/{job_id}/result-view` возвращает один browser-safe снимок
для четырех вкладок результата: обзор, сценарии и надежность, медиаплан и
отчет. Это read-only projection уже завершенного расчета. Endpoint не запускает
MMM, forecast, optimizer или отчет заново и не меняет рекомендацию.

Существующие `GET .../result` (`DecisionResult v1`) и `GET .../overview`
(`ResultOverview v1`) сохранены без изменений. Новый контракт additive.

## Источники

Projection согласует:

- terminal `job.json` со статусом `succeeded`;
- опубликованные `result.json` и `overview.json` одного `result_id`;
- ровно одну campaign в product job;
- hash-checked `scenario_results_csv`, `decision_pool_csv`,
  `recommended_allocations_csv` и `marketer_report_xlsx`.

Локальные пути, raw candidate names, внутренние статусы и stack traces в ответ
не попадают. CSV читает только backend через artifact resolver с повторной
проверкой size и SHA-256.

## Recommendation semantics

- `recommended` означает canonical outcome существующей recommendation policy;
- `no_safe_recommendation` означает, что automatic safe reallocation не
  опубликован. `scenario_id` в этом состоянии равен `null`, а `S01` используется
  только как default для просмотра;
- `unavailable` означает, что recommendation нельзя показать;
- `best_safe` и `best_raw` не подменяют canonical recommendation;
- allocation recommendation относится только к распределению бюджета и не
  является решением запускать или отменять кампанию.

Если canonical recommendation сохранена как S01 из-за materiality policy, API
не называет другой вариант победителем.

## Метрики

| Поле | Статус | Семантика |
|---|---|---|
| `incremental_turnover_rub` | available, если есть в overview | Дополнительный оборот против counterfactual без кампании, p10/p50/p90. |
| `roas` | available, если есть в overview | Дополнительный оборот / deterministic allocated budget, p10/p50/p90. Это не прибыль. |
| `incremental_orders` | diagnostic only | Дополнительные заказы p10/p50/p90. Не primary optimizer KPI. |
| `orders_per_100k_rub` | diagnostic only | `orders quantile / deterministic allocated_budget × 100000`. При budget <= 0 поле unavailable. |
| `avg_basket_delta_rub` | unavailable | Текущий canonical result не содержит изменение среднего чека в RUB/order. Значение не реконструируется. |
| `avg_basket_turnover_bridge_rub` | diagnostic only | Часть incremental turnover, связанная с механизмом среднего чека. Это не delta среднего чека. |

Missing никогда не заменяется нулем. Каждая metric содержит `status`,
`usage`, `unit`, nullable p10/p50/p90 и browser-safe `display_text`.

## Reliability

Утвержденной шкалы 1-10 и утвержденных весов нет. Поэтому:

```json
{
  "score": null,
  "status": "unavailable"
}
```

API отдельно показывает шесть evidence components без числовых scores:

1. похожесть на исторические бюджеты;
2. модельный статус;
3. выход за наблюдаемую область;
4. posterior uncertainty;
5. business constraints;
6. полнота рассчитанного бюджета.

Component status принимает `good`, `caution`, `poor`, `unavailable`. Это
объяснение имеющихся сигналов, а не новая formula и не вероятность точности.
`uncertainty_width_share` публикуется как observed value, но не переводится в
score без утвержденных thresholds.

Deterministic presentation mapping v1:

- historical support / extrapolation: inside p95 и zero warnings → `good`;
  p95-p99 или elevated warning → `caution`; above p99, strong или hard warning
  → `poor`; отсутствие оценки → `unavailable`;
- model support: canonical `quality.status` переводится без изменения порядка
  риска (`reliable` → good, elevated uncertainty → caution, manual/blocking →
  poor, not calculated → unavailable);
- business constraints: только canonical business-decision status;
- data completeness: campaign `model_coverage_share`, а не неоднородный
  scenario coverage; 100% → good, partial positive → caution, zero → poor;
- posterior uncertainty: observed interval width показывается, но status и
  score остаются unavailable без approved thresholds.

## Rank semantics

- `raw_rank` читается из `optimizer_raw_rank` опубликованного allocation
  artifact;
- `safe_rank` читается из `optimizer_reliable_rank` того же artifact;
- ranks не рассчитываются и не сортируются заново;
- `safe_rank` означает support/policy-aware порядок существующего optimizer,
  а не reliability score и не обязательную recommendation;
- если rank отсутствует в source artifact, поле равно `null`.

Scenario rows S01-S06 имеют unique ranks where present. `best_raw` выводится
отдельно и только при наличии canonical candidate evidence. Blocking cells
показываются только при реальных non-OK `gate_reason_codes`; иначе их status
`unavailable`, а не пустое доказательство безопасности.

## Overview aggregates

`selected_scenario_id` равен canonical recommendation при status
`recommended`; иначе для просмотра используется `S01`. Source всегда `S01`,
устойчивый benchmark всегда `S05`.

Backend возвращает готовые и reconciled:

- `channel_summary`;
- `geo_summary`;
- `geo_channel_summary`;
- turnover range rows p10/p50/p90 для доступных S01-S06;
- headline metrics выбранного для просмотра сценария.

Frontend не суммирует row-level data для получения source-of-truth totals.

## Browser-safe warnings

`warnings[]` не копирует raw optimizer messages. Projection формирует
устойчивые пользовательские предупреждения только из canonical evidence:

- частичное покрытие загруженного бюджета;
- elevated/strong/hard support counts выбранного сценария;
- отсутствие safe automatic reallocation;
- отсутствие утвержденного launch/cancel threshold;
- завершение Scenario 6 по заданному search limit без заявления global
  optimum.

Каждый warning содержит stable machine `code`, severity, title, простое
объяснение, recommended action и scope. Warning не меняет recommendation.

## Report

`marketer_report_xlsx` доступен только через canonical artifact download path.
Перед публикацией projection повторно проверяет file size, SHA-256 и XLSX
workbook structure. `sheets[]` содержит реальные sheet names; descriptions
равны `null`, если авторитетного описания нет. `generated_at_utc` также `null`,
если artifact не публикует отдельное время генерации.

Отдельный working media-plan XLSX сейчас не формируется, поэтому его status
`unavailable`. CSV не выдается за XLSX.

В текущем worker terminal `succeeded` публикуется только после готовности
marketer XLSX. Поэтому отсутствие или повреждение этого artifact у succeeded
job дает `409 RESULT_VIEW_INCONSISTENT`, а не тихий `report=unavailable`.
`failed/unavailable` сохранены в versioned shape для будущего независимого
report lifecycle; текущая ошибка report завершается через Phase B progress и
error contracts до публикации result-view.

## Controlled unavailable

- daily scenario plan: unavailable;
- channel × date matrix: unavailable;
- approved map coordinates: unavailable;
- reliability score 1-10: unavailable;
- average-basket delta in RUB/order: unavailable;
- working media-plan XLSX: unavailable.

Эти gaps не блокируют turnover/ROAS/scenario comparison и geo × channel plan.

## HTTP errors

| HTTP | Code | Значение |
|---:|---|---|
| 404 | `JOB_NOT_FOUND` | Job не существует. |
| 404 | `RESOURCE_NOT_READY` | Result/overview еще не опубликованы. |
| 409 | `RESULT_VIEW_INCONSISTENT` | IDs, artifacts, ranks, budgets или hashes не согласованы. |
| 503 | `RESULT_VIEW_UNAVAILABLE` | Projection временно не может быть построена. |

В error response нет exception text или filesystem path.

## Основные invariants

- ровно одна campaign;
- scenarios строго S01-S06, без дублей;
- p10 <= p50 <= p90;
- recommendation scenario существует и совпадает с recommendation flag;
- missing recommendation не получает synthetic winner;
- safe/raw ranks unique where present;
- selected/source budgets неотрицательны;
- channel, geo и geo × channel aggregates сходятся с scenario totals;
- selected allocation не добавляет отсутствующие в S01 cells;
- report и allocation artifacts проходят hash check;
- response не содержит workstation paths.
