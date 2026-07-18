# Phase E.1F Historical Home Map — Review Notes

## Evidence boundary

Baseline: `origin/main@370ea98024c7931dfd92c8ec4e289c6b0116e3da`.

Branch: `codex/frontend-phase-e1f-historical-home-map-v1`.

Pull Request metadata and final head are recorded in GitHub after publication.

The six PNG files below use a clearly marked synthetic E2E contract fixture.
They verify presentation states only and are not evidence of real model totals.
Live acceptance runs separately against the local backend without route
interception.

## Screenshot inventory

Directory:
`04_Web_app/docs/ui-review/phase-e1f-historical-home-map-v1/`

| # | State | File | Status |
|---:|---|---|---|
| 1 | Desktop available, light | `home-historical-light.png` | reviewed |
| 2 | Desktop available, dark | `home-historical-dark.png` | reviewed |
| 3 | Historical tooltip, light | `home-historical-tooltip-light.png` | reviewed |
| 4 | Historical tooltip, dark | `home-historical-tooltip-dark.png` | reviewed |
| 5 | Controlled artifact unavailable, light | `home-historical-unavailable-light.png` | reviewed |
| 6 | Compact top-5, light | `home-historical-mobile.png` | reviewed |

Exactly six Phase E.1F screenshots are generated. Campaign screenshots are not
re-captured because campaign mode is intentionally unchanged.

## Review checklist

- [x] Historical title, backend period, total and 220 geographies are visible.
- [x] Desktop permanently labels top-10 by published historical budget.
- [x] Compact permanently displays top-5 from the same ordering.
- [x] Tooltip contains historical budget, share, active days and period.
- [x] Tooltip and Home summary contain no campaign count.
- [x] Partial and unavailable states retain honest backend semantics.
- [x] Light/dark/mobile have no clipping, overlap or horizontal overflow.
- [x] Synthetic-data badge remains visible in every fixture screenshot.
- [x] Campaign map regression passes without new screenshots.
- [x] Live local acceptance passes without interception or workspace fallback.
- [ ] GitHub CI must be green before the PR is marked Ready for review.

Local evidence: generated drift, TypeScript, ESLint, 68 targeted tests, the
full 497-test frontend regression and production build passed. Chromium passed
18 targeted Home fixture cases plus the unchanged campaign-map regression. The
real-package Home acceptance passed without route interception and with a clean
console.

## Known limitation

The hosted transfer bundle does not yet include the package-bound historical
artifact extension. Hosted controlled unavailable is expected; no workspace
fallback is allowed. Local real-package acceptance remains the authoritative
available-state evidence.
