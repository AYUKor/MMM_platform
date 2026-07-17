# Phase E Auth and Administration V1 — Review Notes

## Статус evidence

Baseline: `origin/main@4b61e13d25c7f811250e1efe62fecd089fd494eb`
(merged PR #21).

Frontend Phase E реализована и проверена. Review screenshots получены из
contract-valid TypeScript fixtures с dev-only marker
`mmm-review-data="synthetic"`; интерфейс показывает badge
`Демонстрационные данные`. Live acceptance выполнялась отдельно с настоящим
local backend, реальными cookie и без route interception.

## Screenshot inventory

Desktop-кадры имеют размер `1440x900`, mobile — `375x812`.
Для всех кадров дождались fonts, отключили animations и проверили отсутствие
document overflow.

| Файл | Состояние | Theme | Статус |
|---|---|---|---|
| `01-login-dark.png` | Login, anonymous session | dark | reviewed |
| `01-login-light.png` | Login, anonymous session | light | reviewed |
| `02-login-error-dark.png` | Invalid credentials, password cleared | dark | reviewed |
| `02-login-error-light.png` | Invalid credentials, password cleared | light | reviewed |
| `03-session-profile-dark.png` | Authenticated profile menu и logout | dark | reviewed |
| `03-session-profile-light.png` | Authenticated profile menu и logout | light | reviewed |
| `04-users-dark.png` | Users table, filters и actions | dark | reviewed |
| `04-users-light.png` | Users table, filters и actions | light | reviewed |
| `05-user-create-dark.png` | Create user dialog | dark | reviewed |
| `05-user-create-light.png` | Create user dialog | light | reviewed |
| `06-roles-dark.png` | Published roles catalog | dark | reviewed |
| `06-roles-light.png` | Published roles catalog | light | reviewed |
| `07-system-dark.png` | Browser-safe system status | dark | reviewed |
| `07-system-light.png` | Browser-safe system status | light | reviewed |
| `08-audit-dark.png` | Audit log, URL filters и pagination | dark | reviewed |
| `08-audit-light.png` | Audit log, URL filters и pagination | light | reviewed |
| `09-forbidden-dark.png` | Permission-level 403 without logout | dark | reviewed |
| `09-forbidden-light.png` | Permission-level 403 without logout | light | reviewed |
| `10-users-mobile-dark.png` | Responsive user cards | dark | reviewed |
| `10-users-mobile-light.png` | Responsive user cards | light | reviewed |

## Functional browser matrix

| Область | Acceptance | Результат |
|---|---|---|
| Credentials | Каждый Phase A-E API request отправляет `credentials: "include"` | passed |
| Browser storage | Auth/session/token не записываются в local/session storage | passed |
| Cookie boundary | Cookie и session token не читаются JavaScript-кодом | passed |
| Bootstrap | loading, authenticated, anonymous, unavailable, unsupported contract | passed |
| Login | valid, invalid, rate-limited, unavailable, safe `return_to` | passed |
| Logout | server call и fail-closed local runtime cleanup | passed |
| Protected routes | Anonymous redirect; authenticated route recovery | passed |
| 401 | single-flight session recheck, Login notice и сохраненный return path | passed |
| 403 | controlled denied state без сброса authenticated session | passed |
| Permissions | Только `session.user.permissions[]`; нет role-name inference | passed |
| Action permissions | users, roles и sessions writes проверяются раздельно | passed |
| Users URL | server search/filter/sort/page/page_size сохраняются в URL | passed |
| User actions | create, edit, role change, disable, enable, revoke sessions | passed |
| Roles | backend titles/descriptions only; raw role IDs не показываются | passed |
| System | known browser-safe facts only; unknown keys скрыты | passed |
| Audit URL | actor/event/date/sort/page/page_size сохраняются в URL | passed |
| States | loading, ready, empty, invalid, conflict, unavailable, forbidden | passed |
| Accessibility | landmarks, labels, dialog focus, keyboard, contrast | passed |
| Responsive | desktop и `375x812` без document overflow | passed |
| Raw copy | internal IDs и raw permission names не видны пользователю | passed |

## Verification results

Команды выполнялись из `04_Web_app/frontend` bundled Node runtime:

| Gate | Результат |
|---|---|
| Generated contract drift | passed; generated tree без diff |
| TypeScript | passed |
| ESLint | passed; 0 warnings |
| Unit tests | 37 files, 392 tests passed |
| Production build | passed; 150 modules transformed |
| Phase E Playwright | 40 tests passed |
| Full frontend Playwright | 193 passed, 1 live-only skipped |
| Live backend Playwright | 1 passed; no interception |
| WCAG small-text contrast | dark 4.923:1; light 4.857:1 |

Production build сохраняет неблокирующий Vite advisory: основной minified JS
chunk `628.74 kB` (`175.54 kB` gzip) превышает standard 500 kB threshold.

## Live backend acceptance

Live run выполнен с настоящими backend и frontend процессами:

- backend: `http://127.0.0.1:8765`;
- frontend: `http://127.0.0.1:4173`;
- backend revision: `4b61e13d25c7f811250e1efe62fecd089fd494eb`;
- route interception отсутствовал;
- local auth включен только во временном acceptance runtime.

Проверены реальные сценарии:

1. anonymous protected route возвращает на Login с безопасным `return_to`;
2. login, session bootstrap, refresh, logout и повторный login работают через
   HttpOnly cookie;
3. пользователь создан, переименован, переведен из viewer в analyst,
   отключен, включен, его сессии отозваны;
4. viewer и analyst получают backend `403`, но session остается authenticated;
5. Roles, System Status и filtered Audit отвечают real contract payloads;
6. попытка отключить последнего active admin возвращает controlled `409`;
7. отзыв текущей admin session приводит к real protected `401`, Login notice и
   восстановлению исходного route после нового входа;
8. browser storage не содержит auth/session/token keys;
9. mobile Users имеет `scrollWidth - clientWidth = 0`;
10. неожиданные application console warnings/errors отсутствуют.

Chrome создает стандартные network console rows для намеренно полученных
`401`. Live test отдельно допускает только эти rows и запрещает остальные
console issues.

## Manual visual review

- [x] Login визуально отделен от authenticated application shell.
- [x] Profile menu явно показывает текущего пользователя и действие выхода.
- [x] Admin navigation появляется только при соответствующих read permissions.
- [x] Table и mobile card представления сохраняют одинаковую семантику.
- [x] Destructive actions требуют confirmation dialog.
- [x] Long localized text переносится без overlap и clipping.
- [x] Light/dark status colors не полагаются только на цвет.
- [x] Мелкий содержательный текст имеет measured contrast не ниже 4.5:1.
- [x] Focus видим; controls имеют accessible names.
- [x] Error и forbidden states не показывают внутренние детали.
- [x] Все 20 PNG просмотрены вручную.

## Known limitations и contract gaps

1. Session revoke success body не имеет versioned JSON Schema; frontend
   использует exact local parser `{user_id, revoked_sessions_n}`.
2. Audit OpenAPI default `page_size` расходится с runtime; frontend явно
   отправляет `50` и валидирует echoed pagination.
3. OpenAPI не перечисляет все фактические error statuses; общий error envelope
   обрабатывает 401/403/404/409/422/429/503 fail-closed.
4. Login-specific 503 schema отсутствует; network/5xx получают controlled
   unavailable state без выдуманного backend reason.
5. Backend требует `admin.users.write` и `admin.roles.write` одновременно для
   role PATCH; UI повторяет эту action-level policy.
6. Audit actor picker ограничен участниками текущей backend page: отдельного
   actor catalog endpoint нет.
7. System `facts` — open object; frontend показывает только известный whitelist.
8. Corporate SSO, MFA, password recovery и multi-node session store не входят
   в local pilot backend contract.
9. Автоматический browser gate использует Chromium; Safari/WebKit parity не
   входит в Phase E acceptance.
10. Playwright пока остается локальным review evidence и не запускается текущим
    GitHub Actions workflow.
