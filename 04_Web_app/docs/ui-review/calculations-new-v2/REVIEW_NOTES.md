# UI review notes: `/calculations/new` V2

## Review setup

Все восемь review-скриншотов создаются Playwright при viewport `1440 × 900` с
intercepted synthetic API responses. Они проверяют композицию, состояния,
темы и responsive-safe layout; они не являются результатами реальной кампании
или свидетельством работы MMM-модели.

Synthetic responses существуют только в E2E/review code, имеют
`record_origin = synthetic_fixture` и показываются с явной маркировкой
`Демонстрационные данные`. Live application mode не имеет fallback на эти
fixtures.

Synthetic review fixtures используются в следующих файлах:

- `01-upload-empty-dark.png`;
- `01-upload-empty-light.png`;
- `02-upload-selected-dark.png`;
- `02-upload-selected-light.png`;
- `03-validation-warning-dark.png`;
- `03-validation-warning-light.png`;
- `04-scenarios-dark.png`;
- `04-scenarios-light.png`.

## Что подключено к live contracts

- выбор одного `.xlsx` или `.csv` файла и его отправка через upload endpoint;
- polling upload до `parsed` / `rejected`;
- имя и размер исходного файла, source rows и detected campaign count;
- frontend blocking state при `detected_campaigns_n !== 1` без вызова validation;
- запуск validation только по действию `Продолжить к проверке`;
- polling и восстановление validation по `validationId`;
- верхнеуровневые ready / warning / blocked states на основе
  `status`, `job_creation_allowed`, `warnings` и `blocking_errors`;
- повторная проверка `validation.campaigns.length === 1`;
- campaign summary из `CampaignPreview` и исходное имя файла через связанный
  upload record;
- issue severity, marketer-safe `display_text`, scope и affected cells;
- все шесть scenario descriptions без forecast values;
- создание job только со scenario screen и переход по возвращенному `job_id`;
- восстановление upload-result, review и scenarios через query parameters;
- fail-closed привязка загруженных records к ID из текущего URL;
- отмена polling при смене шага или ресурса;
- стабильные idempotency keys на выбранный файл, upload и validation, чтобы
  повтор после потерянного ответа не создавал дублирующие ресурсы или расчет;
- поздний ответ action не меняет маршрут, если пользователь уже ушел на другой
  экран.

## Backend fields still missing

1. Реальный template artifact/action для `Скачать шаблон медиаплана`.
2. Budget aggregates by channel.
3. Budget aggregates by geography.
4. Browser-safe daily flighting projection; текущий ArtifactIdentity не
   содержит series для календаря.
5. Approved coordinates / geo catalog для карты кампании.
6. Structured outcomes для отдельных validation checks.
7. Раздельные marketer-safe warning fields `what`, `why` и
   `recommended_action`.
8. Scenario 6 configured attempt count до создания job. Поле из
   `DecisionJob.sampling` появляется слишком поздно для pre-job экрана.

Полная карта gaps и временных UI-состояний находится в
`04_Web_app/docs/integration/FRONTEND_BACKEND_GAPS_NEW_CALCULATION_V1.md`.

## Known limitations

- Кнопка скачивания шаблона disabled до появления реального artifact/action;
  fake URL не используется.
- Budget-by-channel, budget-by-geo, flighting calendar и campaign map
  показывают polished unavailable states. Frontend не агрегирует бюджеты и не
  придумывает координаты.
- Validation contract не позволяет честно поставить статус `Пройдено` каждой
  проверке. Отсутствующие check outcomes показываются как `Нет данных`.
- Issue card может точно показать, что обнаружено и где, но отдельные причины
  и рекомендуемые действия доступны только после расширения contract. Raw
  warning codes в marketer-facing UI не показываются.
- Фактическое число Scenario 6 attempts до запуска неизвестно и поэтому не
  отображается; значение `150` не используется как константа.
- Browser не сохраняет объект выбранного файла при refresh. После успешного
  upload серверное состояние восстанавливается по `uploadId`; до upload файл
  нужно выбрать повторно.
- Автоматизированный browser gate выполнен в установленном Chrome. Отдельный
  WebKit/Safari binary в текущем QA-окружении отсутствует; mobile overflow
  дополнительно проверяется на длинных непрерывных contract strings.
- Ограничение `.xlsx` / `.csv` и one-campaign guard реализованы во frontend,
  но не заменяют server-side enforcement.
- Скриншоты подтверждают только UI на synthetic intercepted responses. Live
  HTTP integration, backend enforcement и MMM correctness ими не доказываются.

## Review checklist

- обе темы сохраняют black/white base и accent `#C7FD72`;
- на странице нет X5 Digital name/logo и технических raw names;
- upload, validation и scenarios — отдельные состояния;
- warning не оформлен как blocking error;
- S5 и S6 не показаны победителями до расчета;
- отсутствующие projections не заменены нулями или synthetic production data;
- keyboard focus видим, status не кодируется одним цветом;
- reduced-motion preference не включает декоративное движение;
- drag-and-drop, delayed parsing, GET error recovery, stale URL navigation и
  повтор job creation с тем же idempotency key покрыты E2E.
