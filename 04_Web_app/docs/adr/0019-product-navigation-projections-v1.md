# ADR 0019: Product Navigation Projections V1

## Status

Accepted for Backend Phase D on `2026-07-17`.

## Context

После Phase A-C браузер умеет создавать расчет, показывать progress и читать
result contracts. Для Главной, Истории, Модели и Справки оставался опасный
архитектурный разрыв: frontend мог начать читать file-backed lifecycle state,
model registry или Markdown и самостоятельно агрегировать business facts.

Такой подход создал бы несколько источников правды, привязал UI к локальной
структуре хранения и позволил бы незаметно подменять missing нулями или
правдоподобными заглушками.

## Decision

1. Добавить четыре additive read-only contracts и endpoints:
   `workspace_home_v1`, `calculation_history_v1`, `model_overview_v1`,
   `help_catalog_v1`.
2. Собирать все четыре проекции в одном тематическом service module без
   копирования MMM/forecast/optimizer logic.
3. Историю строить из persisted job + validation + published result state;
   фильтровать, искать, сортировать и пагинировать на сервере.
4. Home строить поверх тех же calculation facts, `job_progress_view_v1` и
   `model_overview_v1`, чтобы счетчики сходились.
5. Model page строить из active ModelPassport и реальных registrations.
   Отсутствующая модель представляется explicit unavailable без fake quality.
6. Help хранить в versioned structured JSON. Markdown и HTML не являются
   runtime content source.
7. Missing business facts возвращать как `null`; result/report availability
   определять только по published state.
8. Публиковать фиксированные browser-safe ошибки 409/422/503 без raw exception,
   local path и internal keys.
9. Сохранить старые `/jobs`, `/models/active`, progress, result и media-plan
   endpoints без breaking changes.
10. Не менять frontend implementation в Backend Phase D; добавить только
    generated TypeScript contracts для следующего frontend milestone.

## Consequences

Положительные:

- frontend получает один source of truth для navigation pages;
- lifecycle storage, registry и content files можно заменить без изменения UI;
- missing, unavailable и zero разделены;
- model history содержит только реальные registrations;
- help content versioned, testable и защищен от HTML injection;
- старые consumers остаются совместимыми.

Ограничения:

- file-backed history остается single-node research-pilot adapter;
- home не содержит fake activity charts, ETA или quality score;
- model artifacts array пуст, пока нет утвержденных browser routes;
- help catalog требует code review для изменения текста;
- dedicated Phase D frontend integration выполняется отдельным PR.

## Rejected alternatives

- читать state/registry/Markdown из React: rejected, это нарушает boundary и
  привязывает UI к локальному хранению;
- вычислять model quality score: rejected, formula и thresholds не утверждены;
- генерировать историю версий из directory names: rejected, source не
  authoritative;
- считать missing warnings/budget/channel counts нулями: rejected;
- расширить существующий strict Product API schema: rejected, отдельные
  additive contracts снижают риск breaking change.
