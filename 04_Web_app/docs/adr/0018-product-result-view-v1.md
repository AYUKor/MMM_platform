# ADR 0018: Product Result View V1

## Status

Accepted for Backend Phase C on `2026-07-16`.

## Context

`DecisionResult v1` является полным audit contract, а `ResultOverview v1`
публикует browser-oriented scenario metrics и selected allocation. Для полного
product screen frontend все еще пришлось бы самостоятельно:

- выбирать default/result benchmark;
- расшифровывать domain statuses;
- извлекать ranks из loose artifacts;
- агрегировать budget по channel и geo;
- решать, какие missing metrics можно показывать;
- определять, чем best raw отличается от recommendation.

В design spec присутствуют reliability score 1-10, daily media plan, карта и
average-basket delta, но canonical artifacts не содержат утвержденную formula,
daily scenario rows, approved coordinates или average-basket delta RUB/order.

## Decision

1. Сохранить `DecisionResult v1`, `ResultOverview v1`, `/result`, `/overview` и
   artifact download без изменений.
2. Добавить read-time `job_result_view_v1` для четырех result tabs.
3. Добавить paginated `scenario_media_plan_v1` для S01-S06 на grain
   `segment × geo × channel` за весь период.
4. Строить projections только из persisted result/overview и hash-checked
   artifacts после terminal publication barrier.
5. Не хранить дублирующий result-view JSON и не вызывать MMM/optimizer/report.
6. Считать orders per 100k только как deterministic presentation projection:
   `orders quantile / fixed allocated budget × 100000`.
7. Публиковать `optimizer_raw_rank` как `raw_rank` и
   `optimizer_reliable_rank` как `safe_rank`, без пересортировки.
8. Оставить reliability score и component scores `null`. Показать только
   source-backed qualitative components.
9. Оставить `avg_basket_delta_rub`, daily plan, date matrices, map coordinates
   и working-plan XLSX controlled unavailable.
10. Отделить canonical recommendation, best safe и best raw. Ни best raw, ни
    default S01 не становятся recommendation при отсутствии safe outcome.
11. Переводить canonical coverage/support/business/search evidence в отдельный
    browser-safe `warnings[]`; raw optimizer messages и reason codes не
    публиковать, warnings не используют для нового выбора winner.

## Why not extend ResultOverview v1

Изменение существующей strict schema создало бы breaking change для merged
frontend. Additive projections позволяют сохранить текущих consumers и дать
Phase C более узкий browser contract.

## Why not use overview allocation rows alone

Текущий overview содержит только selected recommendation comparison. Для
scenario selector S01-S06 нужны candidate-specific allocation rows и реальные
ranks. Они уже существуют в immutable optimizer artifacts и доступны backend
через hash-checked artifact index.

## Consequences

Положительные:

- frontend не выбирает winner и не рассчитывает ranks/reliability/business
  metrics;
- channel/geo/geo-channel totals имеют один backend source of truth;
- missing отличается от zero;
- raw high-effect candidate виден, но не маскируется под recommendation;
- report links и sheet metadata основаны на реальном XLSX;
- old contracts остаются совместимыми.

Ограничения:

- projection зависит от published allocation/report artifacts;
- daily calendar и map остаются недоступны;
- partial-coverage plan показывает рассчитанную часть, а не выдуманный полный
  план;
- числовая reliability 1-10 потребует отдельной утвержденной versioned policy;
- отдельный working media-plan XLSX потребует нового реального artifact kind.

## Rejected alternatives

- вычислить reliability score из warning counts: rejected, weights не
  утверждены;
- назвать basket turnover bridge изменением среднего чека: rejected,
  несовместимая unit semantics;
- восстановить daily S02-S06 пропорционально source flighting: rejected, это
  новая непроверенная projection logic;
- добавить координаты через внешний geocoder: rejected, отсутствует approved
  versioned reference;
- пересчитать или переоценить Scenario 6: rejected, Phase C меняет только
  product contracts.
