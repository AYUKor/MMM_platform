# Budget optimizer

This folder contains the budget optimization / reallocation workflow.

## Current executable workflow

The optimizer now runs end-to-end on top of the same posterior forecast engine used by campaign forecast:

1. read explicit future campaign brief from `00_Data/00_Future_Campaigns/01_Inbox/`;
2. normalize rows and build daily flighting;
3. validate requested rows against the selected model package;
4. generate baseline and scenario 6 candidate allocations;
5. score candidates through fitted MMM posterior response logic;
6. re-score top finalists and write allocation/report outputs.

Full run:

```bash
cd /Users/aleksan.korenkov/Work/01_ML_projects/03_ML_MMM
PYTHONDONTWRITEBYTECODE=1 /Users/aleksan.korenkov/miniconda3/bin/python -B   02_Code/02_Budget_optimizer/budget_optimizer.py   --config 02_Code/02_Budget_optimizer/budget_optimizer_template.yaml
```

Useful partial runs:

```bash
# Check selected fitted model package only.
PYTHONDONTWRITEBYTECODE=1 /Users/aleksan.korenkov/miniconda3/bin/python -B   02_Code/02_Budget_optimizer/budget_optimizer.py   --config 02_Code/02_Budget_optimizer/budget_optimizer_template.yaml   --check-model-package-only

# Parse, flight and validate the campaign brief only.
PYTHONDONTWRITEBYTECODE=1 /Users/aleksan.korenkov/miniconda3/bin/python -B   02_Code/02_Budget_optimizer/budget_optimizer.py   --config 02_Code/02_Budget_optimizer/budget_optimizer_template.yaml   --prepare-campaign-only

# Export strict replay/forecast metadata from the model package only.
PYTHONDONTWRITEBYTECODE=1 /Users/aleksan.korenkov/miniconda3/bin/python -B   02_Code/02_Budget_optimizer/budget_optimizer.py   --config 02_Code/02_Budget_optimizer/budget_optimizer_template.yaml   --export-model-metadata-only
```

## Objective policy

Default policy is `balanced`:

- `objective_allowed` rows can enter the optimizer objective;
- `objective_allowed_with_penalty` rows can enter the objective but must be reported as caution;
- `side_metric_only` / diagnostic rows are kept in outputs but excluded from objective scoring.

The objective score is currently `turnover_per_user` p50 total incremental turnover. Other targets remain side metrics and must not be summed into a single business effect.

## Scenario 6 search

Scenario 6 is the actual reallocation search layer. It generates candidate budget mixes across the existing campaign `geo x channel` cells and scores each candidate with the same posterior MMM forecast engine.

Current implementation uses `adaptive_marginal_posterior` search plus five transparent benchmark candidates:

- Scenario 1: uploaded plan;
- Scenario 2: equal split across source `geo x channel` cells;
- Scenario 3: keep channel totals and equalize geos;
- Scenario 4: keep geo totals and equalize channels;
- Scenario 5: closest-to-source proportional allocation inside p95 support;
- Scenario 6: adaptive support-aware candidates inside gate and robust-support constraints.

This is not a static ROAS multiplier. The engine compiles the exact serving
equation for every campaign `geo x channel` cell (denominator, scaling,
warm-start, adstock, tanh saturation, posterior beta and target units) into a
reusable response kernel. Candidate generation is separate from effect
estimation, but both search and finalist scoring use the fitted MMM posterior
response.

The current surgical-search defaults are:

- `2,048` donor/receiver checks instead of the old 16 random candidates;
- `128` shared posterior draws during search and `600` draws for finalists;
- marginal greedy starts under both p99 and robust-upper support bounds;
- paired coordinate refinement at `5M`, `1M`, `250k` and `50k RUB` transfer steps;
- a `100k RUB` allocation quantum for the greedy initializer, which is search
  resolution and not output rounding;
- no line-item rounding before scoring or in the recommended allocation;
- an auditable search trace, unique-plan count, effective dimension,
  convergence flag and search-budget-exhausted flag.

The optimizer does not promise that every campaign has a better feasible plan.
If the uploaded allocation is already locally optimal under model gates and
support bounds, the correct result is no proven improvement, not an invented
one. When the attempt budget is exhausted before the 50k step is certified, the
report explicitly avoids claiming global or local optimality.

Every Scenario 6 run records:

- attempts generated and rejected;
- best raw and best safe candidates;
- paired posterior `delta p10 / p50 / p90` against Scenario 1;
- `P(delta > 0)` and non-inferiority probability;
- moved budget and search resolution;
- elevated, strong, hard support and model-policy violations.

## Recommendation materiality

Recommendation policy is versioned separately in `optimizer_decision_policy_v2.yaml`.

Current defaults:

- absolute p50 gain at least `1,000,000 RUB`;
- relative p50 gain at least `1%`;
- moved budget at least `max(500,000 RUB, 0.5% of model budget)`;
- `P(delta > 0) >= 80%`;
- p10 degradation no worse than `1%`;
- no line-item rounding before posterior scoring or in the exported plan;
- full model coverage at least `99%`, usable partial coverage at least `95%`.

The report separates the reliability champion, best-safe Scenario 6 and final recommendation. A reliability improvement may override economic materiality when the source plan is materially less trustworthy, but the report must explain the expected-effect trade-off.

## Marketer report

`marketer_report.py` reads completed optimizer artifacts only. It never reruns forecast.

The workbook contains:

- `00_Итог_и_как_читать` with the campaign result and recommendation;
- one business-readable sheet per campaign with its passport, all six scenarios and the full `geo x channel` allocation matrix;
- `99_Качество` with scenario-level model coverage, uncertainty and support caveats.

Raw candidate identifiers, sampler diagnostics and long validation-code dumps are not exposed in this stakeholder workbook.

## Current limitations before production allocator usage

- Production activation remains blocked until a valid sealed OOT period is available.
- Finance/Marketing still need to approve a ROAS or contribution-margin hurdle for campaign go/no-go.
- Current local runtimes on the four agency files are about 38-247 seconds;
  geo-rich runs still belong in asynchronous server jobs and need progress
  events plus a configurable search-time service level.
- The backend-only technical XLSX can truncate a very long cell-level violation-code string at Excel's 32,767-character limit; the CSV remains canonical and complete. Normalize these codes into a separate table before API rollout.
- Real operating constraints are still needed per campaign: inventory, min/max shares, mandatory channels, geo exclusions and contractual spend commitments.
- Saturation curves remain model-based interventional assumptions, not experimentally proven causal response functions.
