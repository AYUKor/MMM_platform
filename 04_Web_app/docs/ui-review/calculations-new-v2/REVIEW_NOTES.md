# UI review notes: `/calculations/new` V2

## Review setup

Review-скриншоты создаются Playwright при viewport `1440 × 900` попарно в
светлой и темной темах с intercepted synthetic API responses. Они проверяют
композицию, состояния, charts, темы и responsive-safe layout; они не являются
результатами реальной кампании или свидетельством работы MMM-модели.

Synthetic responses существуют только в E2E/review code, имеют
`record_origin = synthetic_fixture` и показываются с явной маркировкой
`Демонстрационные данные`. Live application mode не имеет fallback на эти
fixtures.

PNG-файлы в этом каталоге регенерируются одной E2E-спецификацией. Оба варианта
темы должны обновляться вместе; старый screenshot не используется как
доказательство актуального UI.

## Что подключено к live contracts

- рабочее скачивание backend XLSX через
  `GET /api/v1/templates/campaign-plan.xlsx` без frontend-копии шаблона;
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
- budget-by-channel и budget-by-geo charts только из соответствующих массивов
  `ValidationResult.preview`;
- временная матрица активности только из
  `ValidationResult.preview.channel_flighting`, с доступной раскрываемой
  таблицей точных row-level значений и статусов;
- список проверок только из `ValidationResult.preview.checks`; frontend не
  добавляет собственные проверки и не выводит raw machine codes;
- issue severity, marketer-safe `what`, `why`, `recommended_action`, scope
  и affected cells; `display_text` остается совместимым fallback;
- map использует только optional `preview.geo_points`; при отсутствии массива
  отображается контролируемое состояние недоступности;
- все шесть scenario descriptions без forecast values;
- фактическое число проверяемых вариантов S6, `profile_label` и
  `model_version_label` из `GET /api/v1/calculation-profile` с fail-closed
  runtime validation;
- создание job только со scenario screen и переход по возвращенному `job_id`;
- восстановление upload-result, review и scenarios через query parameters;
- fail-closed привязка загруженных records к ID из текущего URL;
- отмена polling при смене шага или ресурса;
- стабильные idempotency keys на выбранный файл, upload и validation, чтобы
  повтор после потерянного ответа не создавал дублирующие ресурсы или расчет;
- поздний ответ action не меняет маршрут, если пользователь уже ушел на другой
  экран.

## Оставшийся data gap

Schema предусматривает optional `ValidationResult.preview.geo_points`, но
текущий application runtime не публикует координаты. Поэтому карта остается в
состоянии «данные пока недоступны». Frontend не выводит координаты из названий,
не обращается к внешнему geocoder и не считает наличие budget-by-geo
доказательством наличия точек для карты.

Полная карта gaps и временных UI-состояний находится в
`04_Web_app/docs/integration/FRONTEND_BACKEND_GAPS_NEW_CALCULATION_V1.md`.

## Known limitations

- `ValidationResult.preview` и каждый его массив optional для backward
  compatibility. Отсутствующий projection получает собственное состояние
  «Нет данных»; frontend не заполняет его из campaign summary.
- Guidance fields в legacy issue optional. Если полного набора нет, карточка
  использует безопасный `display_text` и скрывает отсутствующие секции, а не
  показывает временные тексты.
- При 503, сетевой ошибке или неподдерживаемом
  `GET /api/v1/calculation-profile` сценарий S6 остается доступен для
  ознакомления, но число вариантов не показывается и не подменяется константой.
- Карта недоступна до появления реального `geo_points`; budget-by-geo chart
  продолжает использовать отдельную backend projection.
- Browser не сохраняет объект выбранного файла при refresh. После успешного
  upload серверное состояние восстанавливается по `uploadId`; до upload файл
  нужно выбрать повторно.
- Скриншоты подтверждают только UI на synthetic intercepted responses. Live
  HTTP integration проверена отдельно ниже; MMM correctness и полный job run
  этими review-артефактами не доказываются.

## Live HTTP acceptance

Статус в этом документе: **passed 2026-07-16 без route interception**.

Критерии прогона:

1. Frontend направлен на реальный backend base URL через
   `VITE_API_BASE_URL`; Playwright routes не подменяют ответы.
2. Скачанный endpoint возвращает настоящий XLSX и backend filename
   `campaign-plan-template.xlsx`.
3. Upload и validation создаются реальными POST-запросами, затем
   восстанавливаются GET-запросами по фактическим IDs.
4. Значения channel/geo/flighting/checks в UI совпадают с
   `GET /api/v1/validations/{validation_id}`.
5. Число вариантов S6 в UI совпадает с
   `GET /api/v1/calculation-profile`.
6. При отсутствующем `geo_points` карта остается в controlled unavailable
   state.

Evidence:

- backend base URL: `http://127.0.0.1:8765`; `/health = ok`, `/ready = ready`;
- input artifact: временный synthetic CSV `PR14 live smoke` вне repo;
- `upload_id = upload_6e9e4bcda3b51b6cb7b1`, parsed, одна кампания;
- `validation_id = validation_9c58b89b5724a4512af7`, `valid`,
  `record_origin = application_runtime`;
- template: `campaign-plan-template.xlsx`, OpenXML spreadsheet MIME, XLSX
  integrity passed;
- real preview: channel/geo/flighting/checks непустые, actionable warning
  guidance непустой, `geo_points` отсутствует;
- calculation profile: backend `2048`, UI `2 048 вариантов`, browser-safe
  profile/model labels совпадают;
- browser: headless local Chrome, `1440 × 900` и `375 × 812`, dark theme;
  download, review, exact-values table и scenarios passed, document overflow
  отсутствует, raw names и fixture badge отсутствуют.

Ручной Safari pass в этом прогоне не выполнялся: macOS-сессия была
заблокирована. Контрактный smoke и основной E2E выполнены в Chrome; Safari
остается отдельным ручным review-пунктом, а не заявленным pass.

## Review checklist

- обе темы сохраняют black/white base и accent `#C7FD72`;
- на странице нет X5 Digital name/logo и технических raw names;
- upload, validation и scenarios — отдельные состояния;
- ссылка на шаблон активна и использует backend endpoint;
- budget charts и flighting показывают только backend preview values;
- проверки формируются только из `preview.checks`;
- issue guidance не заменяется временными текстами;
- число вариантов S6 не захардкожено;
- при отсутствии `geo_points` карта явно сообщает о недоступности данных;
- текст one-campaign guard: «В результате проверки должна быть ровно одна
  кампания»;
- warning не оформлен как blocking error;
- S5 и S6 не показаны победителями до расчета;
- отсутствующие projections не заменены нулями или synthetic production data;
- keyboard focus видим, status не кодируется одним цветом;
- reduced-motion preference не включает декоративное движение;
- drag-and-drop, delayed parsing, GET error recovery, stale URL navigation и
  повтор job creation с тем же idempotency key покрыты E2E.
