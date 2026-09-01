# Federal Geo Allocation V1

## Статус и граница

`FEDERAL_GEO_ALLOCATION_V1` — backend policy для преобразования федеральных строк медиаплана до границы forecast. Компонент живет в `mmm_core.federal_geo_allocator`; математическая часть MMM и optimizer не знают о федеральных обозначениях.

Рабочая последовательность:

```text
upload -> parsing -> existing daily split -> normalization
       -> FederalGeoAllocator -> aggregation -> existing forecast
```

Forecast получает только дневные строки с canonical model geography. Любое федеральное обозначение на этой границе блокирует расчет кодом `FEDERAL_ROW_REACHED_FORECAST_BOUNDARY`.

## Федеральные обозначения

Смысловых aliases ровно три: `РФ`, `Россия`, `Российская Федерация`.

Перед сравнением разрешены только удаление пробелов по краям и case folding. Внутренние пробелы, дефисы, fuzzy matching, транслитерация и дополнительные синонимы не нормализуются. Поэтому ` россия ` распознается, а `Вся Россия`, `Russia` и `Российская  Федерация` — нет.

Эта норма является утвержденным B2.1-уточнением и заменяет только case-sensitive часть исходного B2.0 alias contract.

## Pinned package context

Registry pointer, registration и package inventory проверяются существующим registry resolver один раз на validation run. В allocation context фиксируются:

- `package_id`;
- SHA exact pointer byte snapshot;
- `registration_content_sha256`;
- зарегистрированные SHA `target_denominator_metadata.csv`, `historical_support_bounds.csv` и `capability_matrix.csv`;
- SHA population и canonical geo catalog;
- checksums direction-level eligible geo sets.

Изменение внешнего pointer после resolution не меняет уже созданный context. Allocation не выполняет file I/O внутри цикла по строкам.

## Eligible geographies и capability

Для направления eligible set равен distinct `geo_label` из package `target_denominator_metadata.csv`. Он обязан точно совпасть с union географий `historical_support_bounds.csv` для `target=turnover_per_user` и `scope=geo`.

`direction × channel` отдельно проверяется по `capability_matrix.csv`. Counts и списки географий не hard-coded. Поддерживаемые policy channels: `Digital_Performance`, `OOH_Total`, `Indoor`, `Радио`, `Нац_ТВ`, `Рег_ТВ`; конкретная пара может быть запрещена active package.

## Population и формула

Иммутабельный application snapshot `04_Web_app/data/federal_geo_allocation/geo_reference_v2.csv` является byte-for-byte копией canonical source с SHA-256 `dcda497e151969506f9d65e6e8d294852a21aa92f066667efecb61ac41636043`. Путь и ожидаемый SHA задаются backend config; runtime не обращается к соседним Test/Predfin/Fin contour.

Для каждой федеральной дневной source row:

```text
weight_geo = population_k_geo / sum(population_k over eligible direction geos)
allocated_spend_rub_geo = source_spend_rub * weight_geo
```

Промежуточного округления до копеек и принудительного residual assignment нет. Missing, non-finite или nonpositive population блокирует весь upload; mean fallback, исключение geo и автоматическое перераспределение запрещены.

## Grain, mixed plans и provenance

Каждая federal daily source row расширяется независимо. Только после успешной проверки всех строк выполняется aggregation до `campaign × date × business_direction × channel × geo_id`. Несколько строк РФ не pre-aggregate: эталон `60 млн + 40 млн` дает `422` provenance rows и `211` aggregated rows.

Смешанный plan `РФ + explicit local geo` additive: локальная сумма добавляется поверх федеральной доли. На logical group `date × direction × channel` возвращается одно предупреждение `FEDERAL_AND_LOCAL_GEO_OVERLAP`, без warning на каждую geo.

Отдельные immutable artifacts содержат expanded provenance и audit payload с source-row reconciliation, package/policy/source hashes, федеральными и локальными totals, difference, warnings и errors. Полный raw workbook в audit не копируется.

## Conservation и fail-closed

Допуск на source-row и whole-plan уровнях: `abs(allocated - source) <= 0.01 RUB`. Нарушение дает `BUDGET_CONSERVATION_FAILED`; частичные expanded outputs не возвращаются.

Публичные blocking codes и русские тексты соответствуют B2.0 error contract. Внутренние paths, hashes и traceback остаются только в protected log/audit и не попадают в пользовательский текст.

## Не входит в B2.1

UI, dictionary download, validation-page design, model/forecast mathematics, optimizer, retraining, population methodology, parent-child population overlap, Predfin/Fin promotion и deployment не изменяются.
