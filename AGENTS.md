# AGENTS.md — MMM Platform

## Назначение

Этот репозиторий содержит released application code MMM Platform: backend, frontend,
контракты, тесты, model-serving adapters, deployment templates и документацию.
Рабочий корень репозитория: `05_MMM_localapp/`.

Главный принцип: сначала установить текущую истину по физическим артефактам и
живому коду, затем предлагать изменение. Нельзя превращать предположение, старый
handoff или имя каталога в подтверждённый факт.

## Что прочитать перед нетривиальной работой

1. Этот `AGENTS.md`.
2. `04_Web_app/PROJECT_BRIEF.md` — стабильная цель продукта.
3. `04_Web_app/CURRENT_TRUTH.md` — последняя зафиксированная текущая истина.
4. `04_Web_app/PROJECT_HANDOFF.md` — карта системы и передача контекста.
5. Релевантные accepted ADR, schemas, policies, manifests, runbooks и тесты.
6. Для истории решений — project brain вне этого Git-репозитория:
   `../01_Main_Brain_MMM/wiki/`.

Если документы расходятся с кодом или проверяемым артефактом, не продолжать как
будто противоречия нет: зафиксировать конфликт, выбрать более сильное evidence или
пометить результат `UNKNOWN`.

## Иерархия фактических источников

Для утверждений о текущем состоянии использовать такой порядок:

1. live code, API/schema contracts, активные configs/policies, manifests и
   физически проверенные artifacts;
2. текущий Git state и история merged changes;
3. deployment evidence и актуальные runbooks;
4. `CURRENT_TRUTH.md`;
5. `PROJECT_HANDOFF.md` и принятые ADR;
6. narrative handoff;
7. старые phase docs, архивные summaries и исторические brain notes.

`AGENTS.md` задаёт правила работы, а `PROJECT_BRIEF.md` — стабильную цель; они не
заменяют проверку текущей реализации. Accepted ADR задаёт одобренную семантику,
но её фактическое внедрение должно подтверждаться кодом и тестами.

## Граница расчётов и изменений

- Не запускать DWH SQL без прямого разрешения.
- Не пересчитывать модели, панели, posteriors, forecasts, optimizer outputs или
  reports без прямого разрешения.
- Не менять model semantics, posterior/training logic, optimizer logic,
  recommendation policy или business KPI contract, если это не входит в явно
  согласованный scope.
- Raw data считать immutable. Новые результаты создавать versioned рядом с
  исходными; не перезаписывать единственный экземпляр.
- Перед любым расчётом фиксировать population, grain, period, denominator,
  estimand, counterfactual, maturity/as-of semantics и epistemic status.
- Разделять causal estimate от operational proxy. Нормализация или перевод в
  маржу не исправляет неверный counterfactual.

## Local workspace safety

Аудит локального workspace по умолчанию строго read-only.

- Не перемещать, не переименовывать и не удалять файлы или каталоги.
- Не считать каталог устаревшим только по имени, дате или расположению.
- До предложения миграции проверить code imports, configs, manifests, hashes,
  symlinks, notebooks, runbooks и внешние зависимости.
- Сохранять raw sources и невоспроизводимые artifacts.
- Destructive cleanup — отдельная задача с явным подтверждением пользователя.
- Миграция допустима только по схеме `copy first -> verify -> switch references ->
  delete last`, причём последний шаг требует отдельного разрешения.
- Данные и model artifacts могут находиться в родительском workspace вне Git;
  отсутствие файла внутри clone не означает его отсутствие или ненужность.

Планируемая структура `03_ML_MMM/{00_Data,01_Test,02_Predfin,03_Fin}` пока не
создана. До отдельной milestone нельзя раскладывать файлы по этой схеме.

## Git и GitHub

- `origin/main` — source of truth для released application code.
- Одна задача — одна ветка `codex/<task>` — один PR.
- Все исправления review по задаче остаются в том же PR.
- Codex может создать commit и Draft PR только в согласованном scope.
- Codex никогда не merge'ит PR самостоятельно.
- Запрещены destructive Git actions без явного разрешения: `reset --hard`,
  force-push, удаление веток, переписывание history, удаление чужих изменений.
- Не трогать unrelated dirty/untracked files. В отчёте отделять их от изменений
  текущей задачи.

## Server и deployment

- Сервер не изменять без отдельного явного разрешения.
- Не выполнять SSH, restart, deploy, config edit, certificate operation или
  cleanup в рамках локального аудита.
- Документированный server status не выдавать за live-verified status.
- Не публиковать IP, jump-host details, ключи, credentials, cookies, tokens,
  private certificates или иные secrets.
- Model serving bundle переносится отдельно от application Git и должен
  проверяться по manifest/hash; source panel на сервер не переносится.

## Реализация и проверка

- Предпочитать локальные воспроизводимые pipelines, функции с type hints и
  docstrings, deterministic seeds, logging и явные sanity/shape checks.
- Notebook — читаемый интерфейс; повторяемую логику выносить в `src/`, когда это
  улучшает воспроизводимость.
- Проверять изменения пропорционально риску: targeted tests, затем связанный
  regression surface. Не скрывать known failing tests.
- Для UI сверять фактический router, API calls, permissions и состояния, а не
  только макеты или phase docs.
- Для model-serving сверять pointer -> package manifest -> policy -> adapter ->
  public contract.

## Документация и handoff

После meaningful progress обновлять только разрешённые пользователем документы.
Фиксировать:

- что проверено и по какому evidence;
- что является observed fact, documented status, assumption или `UNKNOWN`;
- какие файлы изменены;
- tests/checks и их результат;
- unresolved risks и следующий milestone.

Если scope допускает только documentation, любые обнаруженные code/model/server
проблемы заносятся как ограничения или будущие задачи, но не исправляются.
