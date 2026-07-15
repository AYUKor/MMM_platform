# MMM Forecast & Optimizer — Техническое задание на frontend V1

**Статус:** утверждено для реализации  
**Версия:** 1.0  
**Дата:** 15 июля 2026  
**Назначение:** единый источник требований для Codex при сборке пользовательского интерфейса внутреннего MMM-приложения  
**Связанный дизайн-документ:** `MMM_WEBAPP_DESIGN_SPEC_V1.md`  
**Визуальный референс:** `mmm_result_overview_mockup.html`, `mmm_result_overview_dark.png`, `mmm_result_overview_light.png`

---

## 1. Что нужно сделать

Собрать полноценный frontend внутреннего веб-приложения **MMM Forecast & Optimizer**.

Приложение предназначено для маркетологов, аналитиков и администраторов. Пользователь должен иметь возможность:

1. войти в систему;
2. загрузить медиаплан **одной** будущей рекламной кампании;
3. проверить, как система распознала кампанию;
4. ознакомиться с шестью сценариями расчета;
5. запустить серверный расчет;
6. следить за подробным прогрессом;
7. получить рекомендацию, прогноз и медиаплан;
8. сравнить сценарии и их надежность;
9. скачать полный Excel-отчет и рабочий медиаплан;
10. открыть историю своих расчетов;
11. ознакомиться с текущим состоянием модели;
12. использовать справку;
13. при наличии административной роли — работать с состоянием системы, очередью, версиями модели, ошибками и пользователями.

Frontend не выполняет MMM-математику. Он отображает данные, которые получает от backend.

---

## 2. Обязательные входные материалы

Перед реализацией Codex обязан прочитать:

1. `04_Web_app/docs/design/MMM_WEBAPP_DESIGN_SPEC_V1.md` — полный утвержденный UX/UI-документ;
2. `04_Web_app/docs/design/reference/mmm_result_overview_mockup.html` — утвержденный интерактивный визуальный референс вкладки результата «Обзор»;
3. `04_Web_app/docs/design/reference/mmm_result_overview_dark.png` — темная тема;
4. `04_Web_app/docs/design/reference/mmm_result_overview_light.png` — светлая тема;
5. существующие backend contracts / JSON Schemas / OpenAPI, которые уже созданы в проекте;
6. актуальные документы webapp, если они не противоречат этому ТЗ.

### Приоритет источников

При расхождении источников использовать следующий приоритет:

1. это ТЗ — состав frontend и правила реализации;
2. `MMM_WEBAPP_DESIGN_SPEC_V1.md` — продуктовая логика, страницы, тексты и UX;
3. HTML/PNG-макеты — визуальная композиция, цвет, плотность и стиль;
4. backend contracts — фактические названия полей и допустимые значения;
5. старые прототипы и исторические документы — только как справка, не как источник правды.

Если backend contract не содержит поля, которое требуется дизайну, Codex не должен выдумывать значение. Нужно:

- зафиксировать gap;
- использовать `null` / состояние «Нет данных», если это разрешено контрактом;
- сообщить, какое поле требуется от backend;
- не менять backend без отдельного задания.

---

## 3. Главные границы реализации

### 3.1. Frontend обязан

- отображать данные backend;
- валидировать пользовательские поля на уровне формы;
- показывать loading, empty, error и permission states;
- хранить локальные UI-настройки, например тему;
- обеспечивать навигацию;
- обеспечивать ролевую видимость разделов;
- поддерживать русский интерфейс;
- корректно отображать p10 / p50 / p90;
- показывать понятные business labels отдельно от machine codes;
- работать с одной кампанией в одном расчете.

### 3.2. Frontend не имеет права

- считать adstock;
- считать saturation;
- применять scaling;
- читать posterior и NetCDF;
- рассчитывать incremental effect;
- рассчитывать ROAS самостоятельно;
- генерировать optimizer candidates;
- выбирать best safe / best raw самостоятельно;
- пересчитывать reliability score;
- менять recommendation logic;
- использовать статический ROAS multiplier;
- превращать raw candidate ID в пользовательское название;
- придумывать результаты при отсутствии backend data;
- показывать реальные demo-числа из HTML как production data.

### 3.3. Данные в HTML-макете

Все цифры в `mmm_result_overview_mockup.html` являются **визуальным примером**.

Они используются только для:

- размеров карточек;
- типографики;
- порядка блоков;
- визуальной иерархии;
- проверки темной и светлой темы.

Они не должны быть захардкожены в production frontend.

---

## 4. Рекомендуемый frontend stack

Если frontend уже создан, использовать существующий stack и не мигрировать его без отдельного решения.

Если frontend отсутствует, использовать:

- React;
- TypeScript;
- Vite;
- React Router;
- TanStack Query для server state;
- React Hook Form для форм;
- Zod только если он уже согласован или естественно применяется для frontend validation;
- Apache ECharts или существующую chart library проекта;
- CSS Variables для design tokens и тем;
- обычные CSS Modules / scoped CSS / существующий styling approach проекта.

Не добавлять тяжелый UI-framework только ради скорости, если он мешает повторить утвержденный визуальный стиль.

Допустимо использовать low-level accessibility primitives, если они уже есть в проекте.

---

## 5. Предлагаемая структура frontend

Структура может быть адаптирована к существующему проекту, но зоны ответственности должны сохраняться:

```text
frontend/
  src/
    app/
      App.tsx
      router.tsx
      providers.tsx
    pages/
      auth/
      dashboard/
      calculations/
      model/
      help/
      admin/
    features/
      auth/
      campaign-upload/
      campaign-validation/
      scenario-explanation/
      calculation-progress/
      calculation-result/
      report-download/
      model-passport/
      job-queue/
    entities/
      user/
      campaign/
      calculation/
      scenario/
      model-version/
      warning/
    widgets/
      app-shell/
      sidebar/
      topbar/
      result-overview/
      scenario-comparison/
      media-plan/
    shared/
      api/
      ui/
      charts/
      map/
      theme/
      formatters/
      constants/
      types/
      assets/
```

Не требуется механически создавать именно такую файловую структуру, если существующий frontend использует другую понятную организацию. Важна модульность и отсутствие всей логики в одном `App.tsx`.

---

## 6. Маршруты приложения

Минимальные маршруты:

```text
/login
/
/calculations
/calculations/new/upload
/calculations/new/validation
/calculations/new/scenarios
/calculations/:calculationId/progress
/calculations/:calculationId/result
/model
/help
/admin/system
/admin/jobs
/admin/models
/admin/errors
/admin/users
```

Вкладки результата могут задаваться query parameter или вложенными routes:

```text
/calculations/:id/result?tab=overview
/calculations/:id/result?tab=scenarios
/calculations/:id/result?tab=media-plan
/calculations/:id/result?tab=report
```

При обновлении страницы выбранная вкладка должна сохраняться.

После логина пользователь возвращается на исходный защищенный URL, если он пришел по прямой ссылке.

---

## 7. Роли и видимость

### Маркетолог

Видит:

- Главная;
- Новый расчет;
- Мои расчеты;
- Модель;
- Справка;
- свои результаты и отчеты.

### Аналитик

Дополнительно видит:

- доступные расчеты проекта;
- расширенные сведения модели;
- очередь в режиме просмотра;
- ошибки расчетов и отчетов;
- работу с кандидатными версиями модели в разрешенном объеме.

### Администратор

Дополнительно видит:

- Состояние системы;
- Очередь расчетов;
- Версии модели;
- Ошибки;
- Пользователи;
- административные действия, разрешенные backend.

Frontend скрывает недоступные пункты меню, но безопасность должна обеспечиваться backend. Скрытие кнопки не заменяет серверную проверку прав.

---

# Часть I. Design system

## 8. Цветовые токены

### Темная тема

```css
--bg: #050505;
--surface: #111111;
--surface-secondary: #191919;
--text-primary: #F7F7F7;
--text-secondary: #A8A8A8;
--border: #303030;
--accent: #C7FD72;
--warning: #F5B85A;
--danger: #FF6262;
--info: #80B9FF;
--warm-neutral: #F9DEB8;
```

### Светлая тема

```css
--bg: #F7F7F4;
--surface: #FFFFFF;
--surface-secondary: #E9E9E6;
--text-primary: #090909;
--text-secondary: #656565;
--border: #161616;
--accent: #C7FD72;
--warning: #CC7A10;
--danger: #D83E3E;
--info: #4E8DDA;
--warm-neutral: #F9DEB8;
```

Кислотно-зеленый сохраняется в обеих темах.

Не использовать кислотно-зеленый для мелкого текста на белом фоне.

## 9. Типографика

Основной шрифт: `Inter` с корректным fallback.

```text
Главный экран входа: 52–64 px
Заголовок страницы: 36–44 px
Заголовок блока: 24–28 px
Заголовок карточки: 18–20 px
Основной текст: 15–16 px
Подписи: 13–14 px
Крупный KPI: 32–44 px
```

Не использовать uppercase повсеместно. Он допустим только в коротких labels и hero-акцентах.

## 10. Геометрия и поверхности

```text
Основное скругление: 16 px
Малое скругление: 10–12 px
Внутренние отступы карточек: 20–24 px
Основная граница: 1 px
Акцентная граница: 1–2 px
```

Главная рекомендация:

- фон `#C7FD72`;
- черный текст;
- черная граница;
- смещенная тень;
- одинаковый вид в светлой и темной теме.

Обычные аналитические карточки:

- нейтральная поверхность;
- тонкая граница;
- минимальная тень;
- без избыточного зеленого.

## 11. Темы

Режимы:

- Светлая;
- Темная;
- Системная.

Выбор сохраняется локально и после авторизации — в профиле, если backend поддерживает настройку.

Приложение обязано учитывать `prefers-color-scheme` и `prefers-reduced-motion`.

## 12. Анимированный фон

Использовать медленные абстрактные контурные линии:

- цикл 35–60 секунд;
- низкий контраст;
- без резких вспышек;
- сильнее на login и hero;
- почти незаметно на таблицах и аналитических страницах;
- полностью статично при `prefers-reduced-motion: reduce`.

Под графиками и таблицами фон должен быть однотонным.

## 13. Layout

Базовый desktop viewport: `1440 × 900`.

Sidebar:

- ширина около 228–240 px;
- при ширине менее 1100 px сворачивается до иконок;
- основное мобильное приложение в V1 не требуется;
- интерфейс не должен ломаться на 1024–1280 px.

Контент:

- максимальная ширина около 1320 px;
- свободные отступы;
- sticky topbar;
- таблицы имеют горизонтальный scroll при необходимости.

---

# Часть II. Общие компоненты

## 14. Обязательные shared components

Создать переиспользуемые компоненты:

- `AppShell`;
- `Sidebar`;
- `Topbar`;
- `ThemeSwitcher`;
- `PageHeader`;
- `Tabs`;
- `Card`;
- `StatusBadge`;
- `QualityBadge`;
- `WarningCard`;
- `MetricCard`;
- `RangeMetric` для p10/p50/p90;
- `ProgressStepper`;
- `EmptyState`;
- `ErrorState`;
- `LoadingSkeleton`;
- `ConfirmDialog`;
- `Toast` / уведомления;
- `RoleGuard` / route guard;
- `DataTable` с фильтрами и пагинацией;
- `ArtifactDownloadButton`;
- `HelpTooltip`.

Компоненты не должны содержать бизнес-результаты как константы.

## 15. Форматирование чисел

Единые formatters:

- рубли;
- тысячи / миллионы / миллиарды;
- проценты;
- p10 / p50 / p90;
- даты и время;
- продолжительность;
- количество заказов на 100 000 пользователей.

Требования:

- русская локаль;
- не терять знак `+` для uplift;
- не показывать лишнюю точность;
- `N/A` / «Нет данных» вместо ложного нуля;
- диапазон ROAS показывается так же, как диапазон RTO.

---

# Часть III. Data layer

## 16. Источник данных

Frontend использует backend API и утвержденные JSON contracts.

Если endpoint еще не готов, разрешен development-only fixture provider.

Требования:

1. один интерфейс data access;
2. API provider и fixture provider должны иметь одинаковый тип результата;
3. fixture mode включается только через development configuration;
4. на экране видна метка `Демонстрационные данные`, если используется fixture;
5. production build не должен незаметно работать на fixture;
6. реальные значения не хардкодятся в компонентах.

## 17. Typed API client

Использовать типы из существующего OpenAPI / JSON Schema, если они уже есть.

Не создавать вторую несовместимую модель данных.

Для каждого endpoint предусмотреть:

- loading;
- success;
- empty;
- validation error;
- permission denied;
- network error;
- server error;
- stale data / previous model version, где применимо.

## 18. Логические операции backend

Frontend должен поддерживать следующие операции, используя фактические endpoint names проекта:

### Auth

- login;
- logout;
- current user;
- refresh session, если предусмотрено.

### Campaign and calculation

- upload one campaign file;
- parse/preview campaign;
- validate campaign;
- create calculation;
- get job status;
- get job events/progress;
- request cancellation, если backend поддерживает;
- get result;
- list calculations;
- repeat calculation;
- archive calculation.

### Artifacts

- download full report;
- download recommended media plan;
- retry report generation;
- get artifact status.

### Model

- get active model summary;
- get capability matrix;
- get budget support ranges;
- get model versions;
- get model version details.

### Admin

- get system status;
- get queue/jobs/workers;
- update job priority, если разрешено;
- get errors;
- get users;
- update roles/status, если разрешено.

Не придумывать endpoint URLs. Взять их из текущего backend/OpenAPI.

---

# Часть IV. Страницы

## 19. Login

Требования:

- split layout 55/45;
- слева название, описание и три возможности продукта;
- справа карточка входа;
- текущий MVP: login/password;
- позже: корпоративная кнопка входа;
- нет самостоятельной регистрации;
- theme switch доступен до входа;
- системный статус снизу;
- фон с наиболее заметными контурными линиями;
- понятные ошибки без технических деталей;
- после login вернуть пользователя на исходный URL.

## 20. Главная

Блоки:

1. hero + `Новый расчет`;
2. краткий паспорт текущей модели;
3. мини-карта исторического покрытия;
4. активные расчеты;
5. простой статус системы;
6. последние расчеты;
7. `Что требует внимания`.

Не показывать technical diagnostics.

## 21. Новый расчет — upload

Правила:

- один файл;
- одна кампания;
- XLSX/CSV;
- drag-and-drop;
- скачать шаблон;
- daily/interval template;
- после чтения показать кампанию, период, бюджет, сегмент, каналы и гео;
- не показывать model forecast на этом этапе;
- несколько campaign names — blocking error;
- отсутствующее имя кампании можно ввести вручную.

## 22. Новый расчет — validation

Показывать:

- общий статус: ready / warnings / blocked;
- campaign summary;
- budget by channel;
- budget by geo;
- geo map;
- per-channel timeline;
- validation summary;
- warning cards;
- уровни: campaign, channel, geo, geo × channel, target;
- понятные действия;
- предупреждения не блокируют расчет, если backend считает их non-blocking;
- критические ошибки блокируют переход.

Не показывать RTO/ROAS.

## 23. Новый расчет — scenarios

Показывать все 6 сценариев:

1. S1 — Как загружено;
2. S2 — Равномерно по всем связкам;
3. S3 — Гео выровнены внутри каналов;
4. S4 — Каналы выровнены внутри гео;
5. S5 — Самый устойчивый план;
6. S6 — Адаптивный поиск.

Пользователь не выбирает subset. Все сценарии запускаются.

Обязательно объяснить различие S5 и S6.

До запуска не показывать прогнозные числа.

## 24. Новый расчет — progress

Показывать девять стадий:

1. файл подготовлен;
2. кампания проверена;
3. S1 рассчитан;
4. S2–S4 рассчитаны;
5. S5 построен;
6. S6 выполняется;
7. сценарии сравниваются;
8. рекомендация формируется;
9. отчет готовится.

Показывать реальные счетчики вариантов, если backend их отдает.

Не показывать текущего временного победителя.

Блок `MMM за минуту`:

- facts catalog;
- смена каждые 12–15 секунд;
- максимум 2 предложения;
- источник по клику;
- можно свернуть;
- не повторять в одном запуске;
- при отсутствии каталога компонент показывает нейтральный placeholder, а не выдумывает факты.

## 25. Result — Overview

Визуально повторить утвержденный HTML mockup.

Обязательные блоки:

1. campaign header;
2. result tabs;
3. большая зеленая карточка рекомендации;
4. карточка S5 / S1 для сравнения по утвержденному правилу;
5. KPI cards:
   - incremental turnover p10/p50/p90;
   - ROAS p10/p50/p90;
   - incremental orders per 100k p10/p50/p90;
   - avg basket change p10/p50/p90;
6. `Почему выбран этот план`;
7. optimizer search stats;
8. budget by channel before/after;
9. top geo deltas;
10. caveats;
11. conditional best raw disclosure.

Правило сравнения:

- winner != S5 → winner vs S5;
- winner == S5 → S5 vs S1;
- winner == S1 → S1 vs S5.

Best raw показывается только если отличается от best safe и заблокирован.

## 26. Result — Scenarios and reliability

Требования:

- metric switcher: turnover / ROAS / orders per 100k / avg basket change;
- horizontal p10–p90 interval plot;
- p50 marker;
- zero line, если значения могут быть отрицательными;
- recommended scenario highlighted;
- S5 marked as stable baseline;
- reliability score 1–10 отдельно от рублевой оси;
- table of six scenarios;
- drawer/details per scenario;
- S6 details: candidates checked, safe, warnings, failed;
- best safe and best raw separated;
- unavailable scenarios show `N/A`, not zero.

Frontend не рассчитывает reliability score, а только отображает backend fields and components.

## 27. Result — Media plan

По умолчанию рекомендованный scenario vs S1.

Блоки:

- scenario selector;
- total budget;
- redistributed amount;
- changed cells;
- new cells = 0;
- budget by channel before/after;
- geo map with budget/delta mode;
- top geo deltas;
- geo × channel heatmap;
- flighting timeline;
- detailed allocation table;
- fixed total row;
- download media plan.

Новые channel/geo/cell не должны появляться, если backend не возвращает их как исходные.

## 28. Result — Report

Блоки:

- report status;
- preview summary;
- full report download;
- media plan download;
- report metadata;
- retry generation if report-only failure;
- previous model version notice.

Файлы:

- полный маркетинговый Excel;
- рабочий медиаплан Excel.

## 29. My calculations

Требования:

- tabs: all / in progress / completed / attention / drafts / archive;
- search;
- filters;
- data table;
- progress in active rows;
- recommendation action, not just scenario ID;
- quality label;
- model version;
- report status;
- open/download/repeat/archive;
- repeat creates a new run;
- old result remains immutable;
- marketer sees own, analyst/admin see permitted scope.

## 30. Model

Блоки:

- active model status;
- training/diagnostic/data/update dates separately;
- capability matrix: segment × channel × target;
- primary/caution/diagnostic/unsupported;
- budget support ranges primarily daily geo × channel;
- model coverage dot map;
- historical budget by channels/geos;
- active days/geos;
- timeline;
- model limitations;
- version history;
- technical mode only for analyst/admin.

## 31. Help

Разделы:

- quick start;
- upload;
- reading results;
- six scenarios;
- reliability and warnings;
- current model;
- FAQ.

Search by title/keywords.

No AI chat in V1.

Contextual links from metrics and warnings.

## 32. Admin pages

### System

- overall status;
- frontend/backend/db/queue/worker/storage/model;
- CPU/RAM/disk/worker slots;
- active jobs;
- maintenance mode if backend supports;
- no raw secrets.

### Jobs

- workers;
- active/waiting/completed/error/stopped;
- real progress;
- priority update with reason if authorized;
- safe cancel request;
- retry;
- report-only retry;
- no hard kill in V1.

### Model versions

- active model;
- versions table;
- package readiness;
- compare versions;
- control campaigns;
- activate/rollback if backend allows;
- no model training in browser.

### Errors

- warnings/errors/critical;
- grouping repeated incidents;
- user impact;
- affected jobs;
- safe technical details;
- retry actions;
- no secrets.

### Users

- marketer/analyst/admin;
- list/search/filter;
- create local user only if current auth supports;
- roles/status;
- block/disable;
- no physical delete in V1;
- protect last active admin;
- audit history.

---

# Часть V. Карта и графики

## 33. Карта России

Использовать абстрактную dot map.

Условия:

- координаты должны приходить из backend/config/approved geo catalog;
- не придумывать координаты;
- если координаты отсутствуют, показывать fallback table/chart и сообщить gap;
- историческая яркость зависит от сглаженного/нормализованного бюджета;
- campaign geo — green;
- warning ring — amber;
- blocking ring — red;
- tooltip: geo, budget, channels, period, support status.

## 34. Графики

Единые правила:

- uploaded/current = neutral gray;
- recommended = acid green;
- S5 = green outline;
- warning = amber;
- blocking/error = red;
- p50 = main marker;
- p10–p90 = interval;
- no misleading dual axes;
- units visible;
- no 3D;
- accessible tooltips;
- charts render correctly in both themes.

---

# Часть VI. UI states

## 35. Обязательные состояния

Для каждой страницы/виджета предусмотреть:

- initial;
- loading;
- skeleton;
- success;
- empty;
- partial data;
- warning;
- blocking error;
- permission denied;
- network unavailable;
- stale result/model version;
- retry;
- cancelled;
- timed out, где применимо.

Не использовать пустой экран или бесконечный spinner без объяснения.

## 36. Ошибки

Пользователь видит:

- что произошло;
- что доступно;
- что сделать;
- можно ли повторить.

Не показывать stack trace и raw response body обычному пользователю.

Admin technical details должны быть раскрываемым блоком.

---

# Часть VII. Доступность и качество

## 37. Accessibility

Обязательно:

- keyboard navigation;
- visible focus;
- semantic HTML;
- form labels;
- ARIA where needed;
- error text, not only color;
- contrast;
- reduced motion;
- charts have table/text alternatives;
- icon buttons have accessible names.

## 38. Performance

- route-level code splitting;
- lazy load heavy charts/maps;
- no blocking bundle from all admin pages;
- virtualize large tables if required;
- do not reload the full page for progress updates;
- reuse cached model summary;
- polling/SSE/websocket according to existing backend contract;
- stop polling when result reaches final state.

## 39. Security expectations

- no secrets in frontend code;
- no `.env` values committed except safe public config examples;
- no trust in client-side role checks alone;
- sanitize rendered error text;
- do not expose local paths;
- do not embed real model artifacts;
- do not store uploaded files in browser storage;
- use backend artifact URLs/actions.

---

# Часть VIII. Tests

## 40. Unit/component tests

Минимум проверить:

- theme switch;
- role navigation;
- formatter p10/p50/p90;
- orders per 100k display;
- scenario labels;
- S5/S1 comparison rule;
- best raw conditional visibility;
- warning and blocking states;
- single campaign upload rule;
- route guards;
- report download states;
- no internal candidate ID as visible scenario title.

## 41. Integration tests

Проверить flows:

1. login → dashboard;
2. upload → preview;
3. multiple campaigns → blocked;
4. validation warnings → continue with warnings;
5. blocking validation → cannot continue;
6. scenarios → start calculation;
7. progress → completed result;
8. result tabs;
9. report download;
10. repeat calculation;
11. permission-based admin pages.

## 42. Visual regression

Снять reference screenshots минимум для:

- result overview dark;
- result overview light;
- login dark/light;
- dashboard dark/light;
- upload;
- validation warning;
- progress;
- scenarios comparison;
- media plan.

Сравнить result overview с утвержденными PNG.

Допустимы адаптации из-за реальных компонентов, но визуальная иерархия и палитра должны сохраняться.

---

# Часть IX. Implementation order

## 43. Этап 1 — Foundation

Сделать:

- frontend app shell;
- routing;
- theme system;
- design tokens;
- sidebar/topbar;
- role-based navigation skeleton;
- shared components;
- sanitized fixture provider;
- result overview page по утвержденному mockup.

Не подключать все страницы к реальному API одновременно.

## 44. Этап 2 — Core marketer flow

Сделать:

- upload;
- validation;
- scenarios;
- progress;
- full result tabs;
- calculations list;
- report download states.

## 45. Этап 3 — Model/help/dashboard

Сделать:

- dashboard;
- model passport;
- help;
- contextual help;
- map/chart refinements.

## 46. Этап 4 — Admin

Сделать:

- system;
- jobs;
- model versions;
- errors;
- users.

## 47. Этап 5 — API wiring and hardening

Сделать:

- replace fixtures with API provider;
- full error mapping;
- auth/roles;
- progress transport;
- downloads;
- accessibility pass;
- performance pass;
- visual regression.

---

# Часть X. Definition of Done

## 48. Общие acceptance criteria

Frontend V1 считается готовым, если:

1. утвержденная структура меню реализована;
2. роли видят только разрешенные разделы;
3. работает light/dark/system theme;
4. result overview визуально соответствует mockup;
5. одна загрузка = одна кампания;
6. validation screen показывает warnings и blocking errors;
7. все 6 сценариев объяснены до запуска;
8. progress показывает реальные стадии;
9. результат отображает p10/p50/p90 для RTO и ROAS;
10. orders отображаются на 100 000 пользователей;
11. avg basket отображается как изменение;
12. recommendation сравнивается с S5 или S1 по утвержденному правилу;
13. best raw не показан как автоматическая рекомендация;
14. scenarios page показывает надежность отдельно от денежной оси;
15. media plan показывает before/after по channel/geo/cell;
16. full report и media plan скачиваются отдельно;
17. old result сохраняет model version;
18. dashboard/model/help реализованы по дизайну;
19. admin pages role-protected;
20. отсутствует frontend MMM math;
21. отсутствуют hardcoded production metrics;
22. нет raw technical fields в marketer flow;
23. основные flows покрыты тестами;
24. интерфейс доступен с клавиатуры;
25. анимация отключается при reduced motion;
26. production build не использует fixtures незаметно.

---

# Часть XI. Запрещенные упрощения

Codex не должен:

- заменять утвержденный стиль стандартным admin template;
- использовать синий Material-style интерфейс вместо черно-зеленой системы;
- делать все карточки кислотно-зелеными;
- убирать light theme;
- убирать абстрактные contour lines;
- заменять страницы одним dashboard;
- объединять upload/validation/scenarios в одну перегруженную форму;
- выводить JSON на экран;
- показывать candidate IDs;
- использовать технические warning codes вместо русских объяснений;
- писать «успешно», если backend вернул partial result;
- показывать provisional best candidate во время расчета;
- считать reliability или ROAS на клиенте;
- добавлять новые channels/geos в media plan;
- создавать fake production endpoints;
- менять backend contracts без отдельного согласования.

---

# Часть XII. Результат работы Codex

Codex должен вернуть:

1. список созданных/измененных файлов;
2. маршруты;
3. список компонентов;
4. список подключенных backend contracts;
5. что работает на API, а что временно на fixture;
6. screenshots dark/light;
7. команды запуска;
8. результаты тестов;
9. известные gaps;
10. подтверждение, что MMM/backend logic не изменялась.

Работу выполнять по этапам. Не реализовывать все страницы одним огромным commit.
