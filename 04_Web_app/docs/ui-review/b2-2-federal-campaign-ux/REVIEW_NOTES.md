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

- Chromium desktop + responsive automation: passed;
- WebKit `Desktop Safari` automation: passed for download controls, federal
  validation, mixed plan, unknown alias, map, scenarios and 375/1024 overflow;
- native Safari manual smoke: pending; Safari 26.2 установлен, но штатный
  `safaridriver` требует вручную включить Developer -> Allow remote automation.

## Live acceptance

No-interception test использует временные state/runtime/artifact directories и
read-only active package evidence. На clean commit `49b5dac4ada52545167c83675c28afe61fd61be4`
успешно завершен job `job_722829320d6cfd6beef8`: `ТСХ/Онлайн`, 100,000,000 RUB,
114/114 mapped geographies, zero unlocated, result/media plan/report download.

PR нельзя переводить в Ready: `ТС5/Онлайн` federal plan раскрывает 211 geo, но
Якутск имеет только один denominator row (`2026-01-01`), тогда как forecast
carryover horizon требует следующую дату до `end_date + l_max`. Fail-closed
ошибка воспроизведена на exact committed candidate. B2.2 не меняет model data,
support universe или denominator fallback.
