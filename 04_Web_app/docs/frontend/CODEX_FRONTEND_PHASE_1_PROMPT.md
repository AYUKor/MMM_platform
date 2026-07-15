# Задание Codex — Frontend Phase 1: Foundation + Result Overview

## Режим

IMPLEMENTATION — FRONTEND PHASE 1 ONLY

## Цель

Создать фундамент frontend и реализовать первую утвержденную страницу — результат расчета, вкладка «Обзор» — по дизайн-документу и HTML-макету.

Это не задание на весь frontend сразу.

## Обязательные материалы

Перед изменениями прочитай:

- `04_Web_app/docs/design/MMM_WEBAPP_DESIGN_SPEC_V1.md`
- `04_Web_app/docs/design/reference/mmm_result_overview_mockup.html`
- `04_Web_app/docs/design/reference/mmm_result_overview_dark.png`
- `04_Web_app/docs/design/reference/mmm_result_overview_light.png`
- `04_Web_app/docs/frontend/MMM_FRONTEND_IMPLEMENTATION_SPEC_V1.md`
- текущие backend contracts / JSON Schemas / OpenAPI проекта
- текущую структуру `04_Web_app`

## Важная граница

HTML-файл является визуальным референсом, а не production-кодом и не источником реальных значений.

Не копируй demo-числа как production data.

Не изменяй backend, MMM, forecast, optimizer, model package и JSON contracts.

## Перед началом

1. Определи, существует ли frontend.
2. Если существует — используй текущий stack.
3. Если отсутствует — создай React + TypeScript + Vite frontend.
4. Покажи краткий план файлов, которые будешь менять.
5. Работай в отдельной ветке, не в `main`.

## Scope Phase 1

Реализовать:

1. Application shell:
   - sidebar;
   - topbar;
   - desktop layout;
   - collapsed sidebar around 1100 px;
   - theme switch light/dark/system;
   - theme persistence;
   - reduced motion support.

2. Design tokens:
   - цвета;
   - typography;
   - spacing;
   - cards;
   - borders;
   - shifted shadow;
   - contour background.

3. Routing skeleton:
   - `/login` placeholder;
   - `/` placeholder;
   - `/calculations` placeholder;
   - `/calculations/:id/result` implemented;
   - `/model` placeholder;
   - `/help` placeholder;
   - admin routes as permission-aware placeholders.

4. Shared UI components:
   - Card;
   - Button;
   - Tabs;
   - StatusBadge;
   - MetricCard;
   - RangeMetric;
   - PageHeader;
   - ThemeSwitcher;
   - EmptyState;
   - ErrorState;
   - LoadingSkeleton.

5. Result page, tab «Обзор»:
   - campaign header;
   - tabs;
   - green recommendation card;
   - stable comparison card;
   - 4 KPI cards;
   - recommendation reasons;
   - search statistics;
   - budget before/after by channel;
   - top geo deltas;
   - caveats;
   - best raw block shown only conditionally.

6. Data provider:
   - use actual existing DecisionResult contract if ready;
   - otherwise create a typed sanitized fixture adapter only for development;
   - show visible `Демонстрационные данные` badge in fixture mode;
   - do not place real values or company data into committed fixture;
   - keep API and fixture providers behind one interface.

7. States:
   - loading;
   - success;
   - partial data;
   - error;
   - permission denied;
   - result unavailable.

## Business display rules

- RTO: p10/p50/p90.
- ROAS: p10/p50/p90.
- Orders: per 100,000 users, p10/p50/p90, with diagnostic/caution note.
- Average basket: delta, p10/p50/p90.
- Winner vs S5 unless winner is S5; then S5 vs S1.
- If winner is S1, compare S1 vs S5.
- Best raw appears only when different from best safe and blocked by warnings.
- Do not expose candidate IDs, attempt IDs, R-hat, ESS, beta/scaling internals.

## Visual requirements

- Match the approved HTML mockup closely.
- Acid green `#C7FD72` in both themes.
- Main recommendation has green background, black text, black border, shifted shadow.
- Dark and light screenshots must both look intentional.
- Animated contour lines must be slow and low contrast.
- No X5 Digital logo or company name.
- Inter font with fallback.
- Charts/background must not become unreadable in light theme.

## Not in Phase 1

Do not implement yet:

- full upload flow;
- validation flow;
- scenario explanation page;
- calculation progress page;
- media-plan tab;
- report tab;
- dashboard data;
- model passport;
- help content;
- admin functionality;
- auth backend integration;
- Docker changes unless required to run the existing frontend;
- backend changes.

Placeholders may be created for routes, but they must be clearly marked as not implemented.

## Tests

At minimum:

- theme switching;
- system theme behavior;
- reduced motion;
- result page render;
- p10/p50/p90 formatting;
- orders per 100k formatting;
- comparison rule winner/S5/S1;
- conditional best raw;
- no internal candidate ID in visible scenario name;
- fixture-mode badge;
- loading/error/permission states.

## Visual evidence

Generate screenshots at 1440 × 900:

- result overview dark;
- result overview light.

Compare them with the approved PNG references and report major differences.

## Definition of Done

Phase 1 is done when:

- application shell works;
- themes work;
- approved result overview is implemented;
- data is typed;
- demo data is isolated behind fixture provider;
- no real business data is committed;
- tests pass;
- backend/MMM code is untouched;
- screenshots are produced;
- branch is pushed and PR created, but not merged.

## Final response

Return:

- branch;
- PR URL;
- changed files;
- stack used;
- data source used;
- what is fixture vs API;
- routes;
- tests;
- screenshots paths;
- known gaps;
- confirmation that backend/MMM were not changed.
