# B2.2 federal campaign UI review

## Evidence boundary

Скриншоты ниже создаются Chromium fixture E2E при `1440 × 900/1000` и не
выдаются за live MMM result. Live no-interception path проверяется отдельно на
development checkout с реальным active package.

| Экран | Light | Dark |
|---|---|---|
| New Calculation: template + dictionary | `new-calculation-downloads-light.png` | `new-calculation-downloads-dark.png` |
| Federal validation | `federal-validation-light.png` | `federal-validation-dark.png` |
| Mixed РФ + local | `federal-mixed-local-light.png` | `federal-mixed-local-dark.png` |
| Unknown federal alias | `federal-unknown-alias-light.png` | `federal-unknown-alias-dark.png` |
| Campaign map after expansion | `federal-map-light.png` | `federal-map-dark.png` |

## Review checklist

- [x] template и dictionary являются соседними download actions;
- [x] federal info не смешан с `Проверка файла` и `Ограничения модели`;
- [x] successful federal validation сохраняет положительный file status;
- [x] difference ниже tolerance показана как zero, без scientific notation;
- [x] два source rows показаны агрегированно;
- [x] multiple directions показываются отдельно, geo counts не суммируются;
- [x] mixed plan имеет один warning и остаётся calculation-ready;
- [x] unknown alias имеет один human blocking message;
- [x] raw channel IDs, paths, hashes, policy/package IDs не показаны;
- [x] map использует backend `geo_points`, keyboard/pointer tooltip остаётся
  доступным;
- [x] 375px и 1024x768 не имеют horizontal document overflow;
- [x] light/dark render не теряет hierarchy и readable contrast.

## Workbook QA

Словарь, скачанный с live development backend, импортирован и отрендерен через
spreadsheet tooling. Подтверждены три листа, readable headers/wrapping, 6 каналов,
220 географий, три aliases и actual-package support counts 211/220/114/117.

## Browser matrix

- Chromium full suite: 189 passed, 4 opt-in live skipped;
- WebKit `Desktop Safari` full suite: 189 passed, 4 opt-in live skipped;
- targeted федеральный Chromium и WebKit flow, light/dark, 375/1024 overflow и
  keyboard/pointer map behavior: passed;
- native Safari: not accepted. `safaridriver /status` отвечает `ready=true`, но
  создание browser session возвращает `session not created`, потому что Safari
  `Developer -> Allow remote automation` выключен. Настройка не изменялась.

## Live acceptance

No-interception test использует временные state/runtime/artifact directories и
read-only active package evidence. Exact code candidate
`bac0672fc3c2f4a26c8984ad416e6300e38f4de8` использовал package
`pkg_807d3ddbae57a52a_9aacd3beb350725b` и прошел:

- `ТС5/Онлайн`, `2026-09-01`: 211 declared -> 175 ready, 36 excluded,
  100,000,000 RUB -> 100,000,000 RUB, difference <= 0.01 RUB, 175 map points,
  zero unlocated; full result/media plan/report job
  `job_a56d2b1cc5ebb03ae51e` succeeded;
- `ТСХ/Онлайн`: 114 declared -> 103 ready, validation passed;
- explicit Якутск: validation blocked before job with the approved human text;
- explicit Москва: validation and full job `job_9529fb96fb4e0c7c181c` succeeded;
- `РФ + Москва`: validation passed with one additive overlap warning;
- `РФ + Якутск`: federal 100,000,000 RUB reconciliation remained complete, while
  the explicit Якутск row blocked job creation.

## Regression evidence

- backend/web: 204 passed, 10 skipped, 839 subtests passed;
- PyMC contract suite: 90 passed, 9 skipped, 4 subtests passed;
- frontend unit: 42 files, 508 tests passed;
- TypeScript, ESLint, generated contract drift and production build: passed;
- build retains the pre-existing non-blocking warning for a chunk above 500 kB.

PR #41 must remain Draft until native Safari smoke passes. Required operator
action: `Safari -> Settings -> Developer -> Allow remote automation`.
