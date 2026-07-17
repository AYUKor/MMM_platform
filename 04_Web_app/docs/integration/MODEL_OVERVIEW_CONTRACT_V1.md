# Model Overview Contract V1

E.1A note: this remains the backward-compatible Phase D contract. New model
screens should use `GET /api/v1/model/overview-v2` and
`GET /api/v1/models/active-v2`. Those projections expose only turnover, one
serving target and four active serving fits; they omit diagnostic orders and
average-basket capabilities. No frontend may merge v1 and v2 into a synthetic
hybrid model status.

## Назначение

`GET /api/v1/model/overview` объясняет активную модель для продуктовой страницы
«Модель»: назначение, период обучения, покрытие, возможности, требования к
кампании, методологию, ограничения и реально зарегистрированные версии.

Endpoint не активирует модель и не читает model files в браузере.

## Источники

- active `ModelPassport v1`, уже построенный из verified serving package;
- registrations из model registry для истории версий;
- активный channel pointer только для `published_at_utc` и проверки, что
  активная версия совпадает с passport;
- versioned browser copy в projection service.

`run_dir`, inventory, hashes, local paths, internal registry keys и raw package
messages наружу не публикуются.

## Active model

При доступном passport `active_model` содержит package ID как stable model ID,
display name, model run version, publication time, framework, training period
и supported scope. Scope берется из passport и включает реальные segments,
channels, targets, geographies count, capability-cell count и allowed-use
counts.

Если passport отсутствует, endpoint отвечает `200` с explicit
`active_model.status=unavailable`; все model facts равны `null`. Это честное
состояние страницы, а не synthetic fallback.

## Capabilities

Контракт явно перечисляет пять продуктовых возможностей:

1. incremental-effect forecast;
2. S1-S6;
3. budget allocation;
4. recommendation с reliability guardrails;
5. marketer report.

Safe recommendation имеет status `conditional`: она зависит от support и
policy evidence конкретной кампании. Это не launch/cancel decision.

## Versions

`versions[]` содержит только реальные registry registrations. Активная версия
должна присутствовать ровно один раз. Если registry inventory не включен в
source-only runtime, активный passport может дать одну реальную fallback-запись
с `source=active_model_passport`; история не выдумывается.

## Methodology и limitations

Methodology кратко объясняет carryover, saturation, posterior uncertainty,
counterfactual forecast, scenario search и reliability guardrails.

Limitations явно фиксируют:

- отсутствие утвержденного reliability score;
- отсутствие daily scenario plans;
- отсутствие approved map;
- отсутствие working media-plan XLSX;
- allocation-only decision boundary;
- diagnostic-only orders;
- sealed OOT limitation, пока validation не passed.

Отсутствующее поле не заменяется score, rank или вероятностью.

## Errors

- `409 PRODUCT_NAVIGATION_INCONSISTENT`: passport и active registry pointer не
  совпали либо version relation нарушена;
- `422 PRODUCT_NAVIGATION_QUERY_INVALID`: переданы query parameters;
- `503 PRODUCT_NAVIGATION_UNAVAILABLE`: structured sources временно не читаются.

Существующий `GET /api/v1/models/active` остается canonical ModelPassport API и
не меняется. Новый endpoint является более узкой browser projection для полной
страницы модели.
