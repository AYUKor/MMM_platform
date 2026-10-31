# mmm_core

Общий слой переиспользуемой MMM-логики.

Что здесь должно жить:

- accepted PyMC MMM specification and wrappers;
- единые функции чтения/записи и config validation;
- shared reporting builders;
- scenario planning primitives, которые нужны и forecast, и optimizer.

Что здесь не должно жить:

- разовые notebook experiments;
- сырые path-хардкоды конкретного запуска;
- orchestration конкретного batch/run.

Если функция нужна только одному workflow и занимает пару строк, сначала держим ее внутри workflow. Выносим в `mmm_core` только когда появляется реальное переиспользование или код становится сложно читать.

## Model Package Contract

`model_package.py` builds the bridge between the fitted PyMC model and downstream
planning layers. Forecast and budget optimizer code should read the generated
`model_manifest.json`, `capability_matrix.csv`, `risk_registry.csv`, and
`posterior_index.json` instead of hard-coding model assumptions.

The builder supports partial runs: if only `run_config.json` exists, the package
is marked `config_only_or_partial`; once posterior/diagnostic artifacts appear,
rerunning the builder upgrades the package to `posterior_ready`.

## Fit → package stage boundary

A guarded fit ends at `fit_complete`: posteriors, `fit_execution_card.json` and the post-fit evidence
(`diagnostics_summary.csv`, `adequacy.json`, `roas_all_fits.csv`, `channel_reliability.csv`,
`target_effects_all_fits.csv`, `prior_posterior_contraction.csv`). The model package (`model_manifest.json`,
`capability_matrix.csv`, ...), the exported design metadata (`fit_design_metadata.json`, ...) and
`model_fit_card.json` belong to the separate package/export stage, so fit diagnostics can be reviewed before
any package exists.

| Command | Result |
|---|---|
| `02_pymc_model.py --mode fit ...` | Default `--package skip`: stops at `fit_complete`; the printed card has `package_created: false` and `next_stage`. |
| `02_pymc_model.py --mode fit --package auto ...` | Single shot as before the boundary: package, design metadata and `model_fit_card.json` right after `fit_complete`. |
| `02_pymc_model.py --mode fit --orchestrate ...` | Same policy for every isolated fit job (`--package` is passed explicitly). Completion needs a `fit_complete` `fit_execution_card.json` of this run identity (`skip`) or `model_fit_card.json` (`auto`); `fit_orchestrator_status.json` records `package_policy` and `package_created`. |
| `02_pymc_model.py --mode package --run-dir <run>` | Package/export stage of a completed fit; never samples. Refuses an incomplete fit, a missing or tampered posterior, missing post-fit evidence and an existing package; `--no-write` only checks these preconditions. Writes the same `model_fit_card.json` as `--package auto` (`package_policy: stage`). |
| `02_pymc_model.py --mode replay --run-dir <run>` | Rebuilds an existing package and re-exports its design metadata (new `generated_at_utc`). It needs a package, so it cannot create the first one. On a guarded-fit package the exported `fit_design_metadata.json` is part of the package fingerprint, so replay changes the fingerprint and every verdict written before it stops matching (`STALE_OR_UNBOUND_*`). Do not run it after validation. |
| `mmm_core/model_package.py --run-dir <run> --write` | Manifest rebuild: recompiles `model_manifest.json`, the capability matrix and the gate files from the files as they are. Exports nothing, so the fingerprint stays and verdicts written for it are picked up. This is the step after validation. |

Order for a new run: prepare → fit → review fit diagnostics → package → validation (`03_model_validation.py`) →
manifest rebuild (`mmm_core/model_package.py --run-dir <run> --write`) to refresh the package gates and blockers →
registry and promotion, which stay separate gates.
Validation verdicts bind to the package fingerprint, so `03_model_validation.py` refuses to write a verdict (OOT
with `--write-verdict`, response replay) until `model_manifest.json` exists, and points at `--mode package`;
thresholds and gates are unchanged.
The package stage is technical: it does not accept, OOT-validate or promote a model.
Before this boundary `--mode fit` always built the package after the last fit; pass `--package auto` for that.

A refit on a longer window of an already OOT-validated specification can inherit that OOT instead of repeating it:
`03_model_validation.py --mode inherit-oot --run-dir <refit> --source-run-dir <validated run> --decision <owner
decision> [--write-verdict]`. The conditions (owner decision, same specification, same twelve fits, runtime
acceptance or pinned exceptions, passed replay) are checked by code; see "OOT inheritance for a refit" in
`04_Web_app/docs/workspace/MODEL_LIFECYCLE.md`.

## V4k time effect and assumption channels

`config["time_effect"]` switches the V4k variant of the fit on (`mode: "analytic_level"`); the default is `off`, and
then the fit, its contract and the posterior are the same as before V4k. Allowed keys (anything else is an error):
`mode`, `eta_sd_prior` (0.02), `level_sd0` (1.0), `drop_time_only_controls` (true), `no_rounding_priors` (true),
`roas_priors`, `pool_tier_channels`, `assumption_channels`, `alpha_prior`, `tc5_offline_policy_enabled`.

An **assumption channel** is a channel whose exposure has no usable city split in the data (national TV, digital
money spread by population). In the fit its lagged scaled exposure is replaced, row by row, by the unweighted mean
of the same lag over all fit rows of the same date, and its coefficient follows the ROAS prior (the data cannot
tell it from the time effect). The frozen `fit_transform_<fit>.json` records what was applied
(`time_effect.mode`, `time_effect.assumption_channels` as spend-column names); `fit_design_metadata.json` carries
the list per fit as `assumption_channels`.

**The serving side must use the exposure the fit used.** Forecast engine, optimizer, historical replay and the
past-campaign catalog treat an assumption channel as a *national index*: one exposure series per date, the mean
over the fit geographies of the adstocked per-resident exposure (a plan geography adds its exposure, the others
only carry over). In the forecast and the optimizer these are the fit geographies that have a usable denominator on
every horizon date (the *universe* of the index; the replay uses the rows present on each date, as the fit does).
The effect is `y_scale * sum_t M_t * [tanh(lambda * (A0_t + dA_t) / 2) - tanh(lambda * A0_t / 2)]`
with `M_t` the coefficient-weighted number of users (orders for `avg_basket`) over the same geographies, and it is
booked on the plan rows in proportion to their spend, so every row of one campaign x channel has the same ROAS.
All other channels keep city-level exposure. The classification comes from `ForecastEngine.assumption_channels_for`
(metadata first, then the frozen transform, so packages exported before the field existed work too). Result rows say
which basis was used (`exposure_basis`: `city_level` or `national_mean_index`) and how many fit geographies were left out
of the index because they had no usable denominator (`national_index_geos_without_denominator_n`). The optimizer evaluates the cells of a national channel
with a proportional-share kernel (exact at the plan's own proportions, concave away from them), so shifting money
between cities inside a national channel is not rewarded; finalists are re-scored exactly by the forecast.

**Parity gate.** `validation.run_serving_roas_parity` replays the training window through the serving geo loop on the
exact 200 posterior draws behind `roas_rub_all_fits.csv` (`RandomState(42).choice(n_total, 200, replace=False)`,
chain-major) and compares the ROAS per turnover channel (p5, median, p95) with that table, relative tolerance 1%.
It also checks that the channels the serving side averages are exactly those the fit averaged. The result is
`historical_replay_validation.json["serving_roas_parity"]` and a failure fails the replay verdict, so the manifest
gets the production blocker `MISSING_OR_FAILED_HISTORICAL_REPLAY`. Run it with the replay:

```bash
python 02_Code/01_PyMC/03_model_validation.py --mode response-replay --run-dir <run> --panel <panel.parquet> [--write-verdict]
```

A change of the model (new data, new exposure or response logic) needs the matching change of forecast engine and
optimizer *before* the final package is built; see "Смена модели" in `AGENTS.md`. The code files in the package
fingerprint are frozen after the package exists, so a failed parity check means: fix the code, build a new package,
repeat validation.

**What the gate ties, and what it does not.** The gate ties the replay of the training window (training rule, same rows,
same draws) to the published ROAS table. It does not promise that the forecast of a *new plan* reproduces the table:

- The table is the average over the whole training window; a shorter window or another budget level sits elsewhere on
  the saturation curve.
- A forecast takes the users of the analog year (default: the year before the plan) for every plan day. Where users grew
  from one year to the next, every channel of the fit comes out lower by the same factor; this is the denominator policy
  and not a property of national channels. (Halloween package, 2026 windows against analog 2025: users grew by 3% to 36%
  depending on the fit.)
- For an assumption channel the training mean runs over the fit rows present on each date; the forecast index runs over
  the universe described above, which is constant over the horizon. They coincide when the cities with a denominator are
  the cities that have rows on those dates, which is the case for a window inside 2025 with the 2025 denominators
  (forecast against replay 0.9995 to 1.0007 on the Halloween package; in the Halloween panel 38, 41, 12 and 14 fit
  cities exist only from 2026-01-01 and are outside the universe of such a plan, as they are outside the training mean
  of those dates). They differ a little where a city appears or has gaps inside the window. A **historical**
  recalculation of a past campaign (the past-campaign catalog) follows the replay rule
  (`build_historical_forecast_replay_rows`: mean over the rows present on each date), not the forecast convention.
- A fit city with no usable denominator is outside the universe: it receives no exposure, carries no users and is not
  in the divisor. The denominator of a forecast day is the one of the analog year (nearest available day of the same
  geography within 7 days), and a city is left out when it is missing on any date of the horizon (plan end plus the
  carryover days). In the Halloween panel the cities that appear only in 2026 have no 2025 rows, so for a plan whose
  horizon reaches past 2026-07-07 they are out on every date: 39, 41, 12 and 13 cities in TS5 online, TS5 offline, TSX
  online and TSX offline (2.99%, 3.30%, 1.34% and 1.30% of the June 2026 users; one more TSX offline city has no rows at
  all). Two things follow. First, such a plan puts no money and no effect in those cities, and its national-channel ROAS
  comes out lower than the same plan with them included. Measured on a federal row of 20 mln national TV and 5 mln
  digital over 14 days (600 draws; the second run with the analog-year gap raised to 400 days so that they get money):
  TS5 online 1.7% (TV) and 3.9% (digital), TS5 offline 0.6% and 0.8%, TSX online digital 6.3%, TSX offline 0.0% (TV) and
  8.1% (digital). The loss does not follow their share of users (1.3% to 3.3%) but their weight in the simple mean of the
  index (see the next two bullets). Second, the divisor has to be the universe, not all fit cities: a federal row, which
  the portal spreads over the cities it can compute (182 of 223 in TS5 offline), keeps its per-resident exposure only if
  the mean runs over those same cities; dividing by all 223 understated national TV and digital by 17.5% in the test of a
  July plan. The count of cities left out is `national_index_geos_without_denominator_n` in the engine rows; the CLI
  output files do not carry it. Giving the new cities a denominator is a denominator-policy decision that also touches
  other packages.
- A federal row does not reproduce the table, and by how much depends on the fit. The index is the *simple* mean over the
  universe of `e_g = spend_g / population_g / x_scale_g` (`x_scale_g` is a constant of the city's tier in the frozen
  transform). Money spread by population gives every city the same spend per resident, so `e_g` differs between cities
  wherever `x_scale_g` does, and the simple mean differs from the user-weighted mean that a city-by-city calculation (the
  earlier serving rule) implies. For a federal row of 20 mln national TV and 5 mln digital on 2026-07-01..14 (Halloween
  package, 600 draws, p50) the forecast against the package table is 0.91 (TS5 online TV), 0.99 (TS5 online digital),
  0.93 and 1.12 (TS5 offline TV and digital), 2.02 (TSX online digital), 1.11 and 1.59 (TSX offline TV and digital);
  against the earlier city-by-city rule 0.98, 1.05, 1.01, 1.01, 1.45, 1.00 and 1.04. Where the money is split so that
  `e_g` is equal in every city, the two rules agree to 0.23%. The fit saw the real historical split of the money between
  cities, and the table averages it; another split gives another ROAS under this rule. The gate is not affected: it
  replays the training window with the real split, and that is the only place where table and forecast must agree.
  Same money and dates with only the city split changed (Mac check, 600 draws): digital in TSX offline falls from 1.59 to
  0.96 of the table when the money follows the historical split of the channel instead of the population (TSX online 2.02
  to 0.73, TS5 online 0.99 to 0.86, TS5 offline 1.12 to 0.98), while national TV does not move (0.9998 to 1.0003),
  because its history is spent by population. On the real plan of the clean window (2026-02-01..06-23), re-splitting the
  daily national totals by population instead of the real city spend raises digital by a factor of 3.7 in TSX online, 1.7
  in TSX offline, 1.06 in TS5 online and 1.02 in TS5 offline. In TSX the three largest cities hold 58% to 80% of the
  historical digital money against about 21% of the population. So a federal row shows a digital ROAS in TSX that is 1.7
  to 3.7 times what the same money shows with the historical split of the fit; the optimizer is not affected. The remedy
  is a model decision (a user- or population-weighted index at the next fit), not a serving change.
- Money booked in one city, or in a few, is not read like a federal row. The index is the unweighted mean of the
  per-resident exposure, so a ruble in a small city lifts the index more than a ruble in Moscow, and the effect then
  applies to the users of every city of the universe. The ROAS of such a plan row depends on the size of the city. In
  the forecast (TSX offline, 5 mln digital over 14 days, p50): Moscow 1.4, Saint Petersburg 3.3, Tula 30 (ROAS times
  population in thousands: 18.6, 18.6 and 13.9 thousand; the plans in Saint Petersburg and Tula lie outside the observed
  spend range, so these two figures are indicative). The past-campaign catalog (replay rule) finds the same pattern for
  real single-city campaigns (Moscow 1.2 to 1.5, Saint Petersburg 3.3, Tula 36). National TV, 20 mln in Moscow only,
  gives 0.13 against 1.2 in the table (TSX offline). This follows from how the fit saw these channels, not from a defect
  of the serving code. Book national TV and digital as a federal row (spread by population). The optimizer is not
  affected (proportional-share kernel). A population-weighted mean in serving would stop agreeing with the fit, so it is
  a decision for the model owner and, to stay consistent, a refit.

Checked on the real Halloween package (`pkg_8c7458c130658027_ab12e4a11a1af1e8`), same real-spend plan and same 300 draws
(replay against `forecast_daily_rows`):

| window | analog year of the denominators | city-level channels | national channels |
|---|---|---|---|
| 2026-02-01..2026-06-23 | 2026 | 0.993 to 1.000 (median 1.000) | 0.986 to 1.000 (median 0.998) |
| 2025-01-01..2025-12-31 | 2025 | 1.000 to 1.003 | 0.9995 to 1.0007 |
| 2026-04-01..2026-06-23 | 2026 | 0.76 to 1.00 (median 0.990) | 0.931 to 1.000 (median 0.985) |

A plan that starts inside the training window runs without a warm start (the carryover of earlier spend is supplied only
for plans that start 1 to `l_max` days after the end of training), so a comparison on a historical window with large
spend just before it comes out lower (the last row: 0.76 for one regional TV row, 0.931 for national TV in TSX offline);
plans after the end of training are not affected. City-level channels are not touched by the national-index code (their
forecast and replay are identical before and after the change).

## Forecast Engine Audit

`forecast_engine_audit.py` checks whether a completed model run folder is ready for the posterior forecast/optimizer engine. It does not run PyMC and does not calculate campaign effects. It validates:

- model-package files;
- capability/risk artifacts;
- posterior response variables (`beta`, `alpha`, `lam`);
- baseline variables (`gamma`, `tau_g`, `sigma`);
- missing strict-replay metadata that must be exported before forecast math.

Example:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B 02_Code/01_PyMC/mmm_core/forecast_engine_audit.py \
  --run-dir 03_Outputs/01_PyMC_outputs/<run_folder>/<production_folder>
```

Do not copy a package ID or readiness status from an old handoff into runtime
code. Resolve the current package through the live registry and verify its
registration and inventory. The evidence-backed status and remaining blockers
are maintained in `04_Web_app/CURRENT_TRUTH.md`; production activation remains
fail-closed until its required gates pass.

## Historical Geo Budget Artifact

`historical_geo_budget.py` builds a deterministic package-bound aggregate for
the Home historical-spend map. It resolves the source panel only through model
registry registration metadata, verifies size and SHA-256, projects date, geo
and the six columns declared in
`configs/historical_geo_budget_spend_columns_v1.json`, and writes:

- `historical_geo_budget_v1.parquet`;
- `historical_geo_budget_v1.metadata.json`;
- `package_artifacts_manifest_v1.json`.

The extension lives under
`03_Outputs/01_PyMC_outputs/00_Model_registry/package_artifacts/<package_id>/`
so an already registered immutable package is not mutated. The web service
verifies this identity chain and reads the small metadata aggregate; it never
opens the training panel during a Home request. Null, infinite and negative
spend values fail closed, and aggregate OOH cannot be combined with its raw
components.
