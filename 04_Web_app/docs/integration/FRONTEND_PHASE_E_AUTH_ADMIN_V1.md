# Frontend Phase E Auth and Administration V1

## Статус

Frontend Phase E реализована и локально принята.

Baseline: `origin/main@4b61e13d25c7f811250e1efe62fecd089fd494eb`
(merged PR #21).

Реализованные routes:

1. `/login` — вход в local research-pilot contour;
2. `/admin/users` — пользователи и активные сессии;
3. `/admin/roles` — опубликованный каталог ролей и разрешений;
4. `/admin/system` — browser-safe состояние системы;
5. `/admin/audit` — административный журнал.

Все существующие product routes теперь закрыты session bootstrap и отдельной
permission guard. Backend, schemas, OpenAPI, MMM, forecast, optimizer и
deployment в Phase E frontend не менялись.

## API boundary

Frontend использует только утвержденные Phase E endpoints:

| Область | Method и endpoint | Контракт / результат |
|---|---|---|
| Вход | `POST /api/v1/auth/login` | `auth_session_v1@1.0.0` |
| Выход | `POST /api/v1/auth/logout` | anonymous `auth_session_v1@1.0.0` |
| Bootstrap | `GET /api/v1/auth/session` | `auth_session_v1@1.0.0` |
| Пользователи | `GET /api/v1/admin/users` | `admin_user_list_v1@1.0.0` |
| Новый пользователь | `POST /api/v1/admin/users` | `admin_user_detail_v1@1.0.0` |
| Пользователь | `GET|PATCH /api/v1/admin/users/{user_id}` | `admin_user_detail_v1@1.0.0` |
| Статус | `POST .../{user_id}/disable|enable` | `admin_user_detail_v1@1.0.0` |
| Сессии | `POST .../{user_id}/sessions/revoke` | strict local response parser |
| Роли | `GET /api/v1/admin/roles` | `admin_role_catalog_v1@1.0.0` |
| Система | `GET /api/v1/admin/system/status` | `admin_system_status_v1@1.0.0` |
| Журнал | `GET /api/v1/admin/audit` | `admin_audit_log_v1@1.0.0` |

Общий `credentialedFetch` выставляет `credentials: "include"` для каждого
frontend API request, включая существующие Phase A–D clients. Cookie остается
HttpOnly и не читается в JavaScript. Login намеренно не отправляет глобальный
expired-session event на ожидаемый invalid-credentials `401`.

## Session lifecycle

`AuthProvider` хранит session projection только в React runtime:

1. при старте выполняется `GET /auth/session`;
2. до ответа protected tree показывает `Проверяем сессию…`;
3. anonymous session ведет на `/login?return_to=<safe internal path>`;
4. login выполняет `POST /auth/login`, затем повторный `GET /auth/session`;
5. после подтвержденной authenticated session очищается старый query cache;
6. logout вызывает `POST /auth/logout` и всегда очищает runtime session/cache;
7. refresh восстанавливает session только с backend, не из browser storage.

`return_to` принимает только same-origin internal path. Protocol-relative URL,
external origin и возврат на сам `/login` нормализуются к `/`.

Auth state, permission set, session ID и token не записываются в
`localStorage` или `sessionStorage`. Theme и dev-only synthetic review marker
не содержат auth data.

## 401 и 403

- Любой protected API `401` публикует единый unauthorized event. Provider
  выполняет single-flight повторную проверку `/auth/session`, очищает runtime
  session и возвращает пользователя на Login с исходным internal path.
- Несколько одновременно завершившихся requests не запускают несколько
  session rechecks.
- `403` отображает `Недостаточно прав` на исходном URL. Session и профиль
  остаются активными; автоматический logout не выполняется.
- Protected `403` запускает single-flight refresh session projection. Если
  backend изменил роль или permissions, permission-bound cache очищается и UI
  сразу применяет новый доступ; cached admin data при error не рендерится.
- Invalid login `401`, rate limit `429`, unavailable/network и unsupported
  session contract имеют разные controlled states.

## Permission model

Единственный источник прав — `session.user.permissions[]`. `role_id` нужен
только для отображения роли; frontend не выводит permissions из названия роли.

| Route / действие | Проверяемое разрешение |
|---|---|
| Главная | `workspace.read` |
| История / progress | `calculation.read` |
| Новый расчет | `calculation.create` |
| Отмена на progress | `calculation.cancel` |
| Результат | `result.read` |
| Скачивание отчета | `report.download` |
| Модель | `model.read` |
| Справка | `help.read` |
| Users и Roles read | `admin.users.read` |
| System | `admin.system.read` |
| Audit | `admin.audit.read` |
| Имя, enable/disable | `admin.users.write` |
| Создание пользователя | `admin.users.write` + `admin.roles.write` |
| Назначение роли | `admin.users.write` + `admin.roles.write` |
| Revoke sessions | `admin.sessions.write` |

Sidebar, mobile navigation, `/admin` landing и row actions строятся по тому же
permission set. Отсутствующее действие скрывается или становится недоступным,
но не подменяется предположением по роли.

## Admin pages

### Users

- server-side `search`, `role`, `status`, `sort`, `page`, `page_size`;
- query state хранится в URL и восстанавливается после refresh/back/forward;
- desktop semantic table и mobile cards;
- create, rename, role change, enable/disable и revoke с confirmation dialogs;
- password очищается после submit/error и никогда не выводится обратно;
- `null` last login показывает `Нет данных`, известный `0` sessions остается `0`;
- last-admin `409` показывает browser-safe backend explanation без logout;
- при недоступном role catalog UI fail closed: raw `role_id` не показывается,
  create/edit role controls недоступны.

### Roles

Страница рендерит только titles, descriptions и permission descriptions из
`admin_role_catalog_v1`. Raw permission IDs не видны пользователю. Отдельного
role mutation endpoint в Phase E нет, поэтому страница read-only;
`admin.roles.write` применяется к назначению роли пользователю.

### System status

Показаны шесть утвержденных subsystem: application, calculation storage,
queue, active model, reports, users/sessions. Status reconciliation не
вычисляется frontend. Из open `facts` отображается только явный whitelist
понятных labels; неизвестные facts и `source_revision` скрываются.

### Audit

Server-side filters и pagination хранятся в URL:
`actor_user_id`, `event_type`, `occurred_from_utc`, `occurred_to_utc`, `sort`,
`page`, `page_size`. Frontend явно отправляет `page_size=50`, чтобы не зависеть
от различающихся defaults в prose/OpenAPI/runtime.

Показываются localized event/result/target labels и
`browser_safe_summary`. `event_id`, `user_id`, `target_id` и `request_id` не
рендерятся.

## Runtime validation и errors

Typed client использует generated TypeScript interfaces и отдельные strict
runtime parsers. Парсеры fail closed:

- exact `contract_name` и `schema_version`;
- exact object keys, enums, IDs, timestamps и pagination reconciliation;
- unique users, roles, permissions и audit events;
- safe browser text без local paths, secrets и internal infrastructure terms;
- consistent authenticated/anonymous session shapes;
- known subsystem inventory и safe facts;
- echoed Users/Audit filters должны совпадать с запросом;
- malformed success response не рендерится частично.

Loading, empty, unavailable, 401, 403, 404, 409, 422, 429, 5xx/network и
unsupported-contract states контролируются отдельно. Backend `display_text`
используется только после validation browser-safe error envelope.

## Accessibility и visual QA

- landmarks, semantic tables/cards, labels и live regions;
- modal focus trap, Escape close и возврат focus к opener;
- visible focus и keyboard navigation;
- `prefers-reduced-motion` отключает looping skeleton/pulse animations;
- desktop 1440×900 и mobile 375×812 без document overflow;
- content-bearing small text измерен по WCAG: minimum `4.923:1` dark и
  `4.857:1` light;
- semantic green admin status локально затемнен в light theme; глобальная
  Phase A–D palette не менялась.

Review evidence:

`04_Web_app/docs/ui-review/phase-e-auth-admin-v1/`

Каталог содержит 18 обязательных desktop screenshots и два дополнительных
mobile screenshots. Contract-valid synthetic states имеют badge
`Демонстрационные данные`; dev marker недоступен в production build.

## Live backend acceptance

Проверка выполнена без `page.route` и без intercepted fixtures:

- backend `http://127.0.0.1:8765`;
- Vite `http://127.0.0.1:4173` с real API base;
- temporary local auth SQLite и bootstrap administrator вне Git;
- immutable registered package проверен в supported `serving_bundle` mode:
  package `pkg_807d3ddbae57a52a_9aacd3beb350725b`, 55 inventory files,
  source panel `provenance_only_not_copied`;
- backend preflight: `ready`, baseline revision `4b61e13d...`.

Live test подтвердил:

1. login, повторный session bootstrap, protected Home, logout/login;
2. Users list/create/edit/role/revoke/disable/enable;
3. viewer и analyst получают backend `403`, а session остается authenticated;
4. Roles, System и filtered Audit отвечают real contract payloads;
5. last-active-admin disable возвращает controlled `409`;
6. external session revoke приводит active SPA к real protected `401`, Login
   notice и сохраненному `return_to`;
7. повторный вход после `401` работает;
8. auth/session/token keys отсутствуют в local/session storage;
9. mobile Users имеет `scrollWidth - clientWidth = 0`;
10. application page errors и неожиданные console warnings/errors отсутствуют.

Chrome пишет стандартные network console rows для двух намеренно полученных
`401`; live test требует их наличия отдельно и одновременно запрещает любые
другие console issues.

## Verification

| Gate | Результат |
|---|---|
| Generated contract drift | passed; generated tree без diff |
| TypeScript | passed |
| ESLint | passed; 0 warnings |
| Unit | 37 files, 392 tests passed |
| Production build | passed; 150 modules transformed |
| Phase E browser suite | 40 tests passed |
| Full frontend Playwright | 193 passed, 1 live-only skipped |
| Live backend Playwright | 1 passed, no interception |
| WCAG small-text contrast | dark 4.923:1; light 4.857:1 |

Production build сохраняет неблокирующий Vite advisory: основной minified JS
chunk `628.74 kB` (`175.54 kB` gzip) превышает standard 500 kB threshold.

## Known limitations и contract gaps

1. Session revoke success payload не имеет versioned JSON Schema/OpenAPI body;
   frontend использует exact local parser `{user_id, revoked_sessions_n}`.
2. Audit prose/OpenAPI и runtime расходятся в default `page_size`; frontend
   всегда отправляет `50` и проверяет echoed pagination.
3. OpenAPI не перечисляет все фактические 401/403/404/422/503 responses;
   frontend обрабатывает их через общий validated error envelope.
4. Login-specific `503` schema отсутствует; network/5xx отображаются единым
   controlled unavailable state без выдуманного backend reason.
5. User mutation schema объединяет create/update, а HTTP methods имеют разные
   обязательные поля; frontend валидирует POST и PATCH раздельно.
6. Backend требует одновременно `admin.users.write` и `admin.roles.write` для
   role PATCH; UI повторяет эту action-level policy.
7. Actor picker в Audit строится из участников текущей backend page. Deep-linked
   actor ID сохраняется, но полного отдельного actor catalog contract нет.
8. System `facts` — open object; неизвестные ключи намеренно не показываются.
9. Local pilot auth не включает corporate SSO, MFA, password recovery или
   multi-node session store — это backend/deployment limitation, не frontend
   fallback.
10. Automated browser gate использует Chromium; Safari/WebKit parity не входит
    в Phase E acceptance.
11. Main JS chunk сохраняет указанный выше size advisory.

## Out of scope confirmation

Phase E не меняет backend, Python packages, schemas, OpenAPI, worker, model
registry, MMM, forecast, optimizer, Scenario 6 ranking, recommendation policy
или deployment.
