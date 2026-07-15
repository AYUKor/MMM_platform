# Frontend Phase 1 contract map

Status: implementation constraint for `Foundation + Result Overview`.

The visual composition is defined by the approved HTML/PNG handoff. Runtime
data is defined only by `decision_result_v1` and the sanitized fixtures. When
the two sources differ, the frontend preserves the composition and renders a
controlled unavailable state instead of calculating a replacement metric.

| UI block | Contract source | Phase 1 behavior |
|---|---|---|
| Campaign header | `campaign_results[].passport` | Render directly. |
| Recommendation | `campaign_results[].recommendation` | Present as an allocation recommendation, never as a launch/cancel decision. |
| Incremental turnover | `recommendation.metrics.incremental_turnover` | Render p10/p50/p90. |
| ROAS | `recommendation.metrics.roas_p50` | Render p50; p10/p90 are `Нет данных`. |
| Orders per 100k | Missing denominator/projection | Render `Нет данных`; do not derive from raw orders. |
| Average basket delta | Missing; `avg_basket_bridge` is not a delta | Render `Нет данных`. |
| Reliability score | Missing | Render `Нет данных`; quality status remains a separate contract-backed label. |
| S5 | Scenario `S05` | Label `Устойчивый benchmark`. |
| S6 unavailable | `available=false`, `quality.explanation`, `scenario6.explanation` | Render the backend explanation and no metrics. |
| Allocation before/after | Uploaded allocation is missing | Render `Нет данных`; do not aggregate or reconstruct. |
| Top geo deltas | Baseline allocation is missing | Render `Нет данных`. |
| Best raw | Only opaque candidate IDs are present | Do not expose IDs or calculate a display block. |
| Campaign selection | `campaign_results[]` | Select the sole campaign; require an explicit campaign ID when there are multiple campaigns. |
| Fixture mode | `result_origin=sanitized_fixture` | Show `Демонстрационные данные`. |

The fixture provider is development-only and fails closed outside development.
No HTTP endpoint, authentication state, system-health state, download action,
or admin permission is fabricated in Phase 1.
