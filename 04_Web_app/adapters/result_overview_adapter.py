"""Build the browser-facing ResultOverview v1 from verified DecisionResult evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from adapters.optimizer_result_adapter import (  # noqa: E402
    _artifact_path,
    _bool,
    _find_one,
    _float,
    _opaque_id,
    _optional_float,
    _read_csv,
    _read_json,
    build_decision_result,
    write_json_atomic,
)


CONTRACT_NAME = "result_overview_v1"
SCHEMA_VERSION = "1.0.0"
OVERVIEW_ADAPTER_VERSION = "1.0.0"
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)")


class ResultOverviewAdapterError(RuntimeError):
    """Raised when verified result evidence cannot produce a safe overview."""


def _quantile_metric(unit: str, p10: float, p50: float, p90: float) -> dict[str, Any]:
    values = (float(p10), float(p50), float(p90))
    if not all(math.isfinite(value) for value in values):
        raise ResultOverviewAdapterError(f"Non-finite {unit} quantile")
    if not values[0] <= values[1] <= values[2]:
        raise ResultOverviewAdapterError(f"Invalid {unit} quantile order")
    return {"unit": unit, "p10": values[0], "p50": values[1], "p90": values[2]}


def _roas_metric(turnover: dict[str, Any] | None, budget_rub: float) -> dict[str, Any] | None:
    if turnover is None or budget_rub <= 0:
        return None
    return _quantile_metric(
        "ratio",
        float(turnover["p10"]) / budget_rub,
        float(turnover["p50"]) / budget_rub,
        float(turnover["p90"]) / budget_rub,
    )


def _overview_metrics(metrics: dict[str, Any], budget_rub: float) -> dict[str, Any]:
    turnover = copy.deepcopy(metrics.get("incremental_turnover"))
    roas = _roas_metric(turnover, budget_rub)
    source_p50 = metrics.get("roas_p50")
    if roas is not None and source_p50 is not None:
        tolerance = max(1e-9, abs(float(source_p50)) * 1e-8)
        if abs(float(roas["p50"]) - float(source_p50)) > tolerance:
            raise ResultOverviewAdapterError(
                "ROAS p50 does not reconcile with turnover p50 and allocated budget"
            )
    return {
        "incremental_turnover": turnover,
        "turnover_roas": roas,
        "incremental_orders": copy.deepcopy(metrics.get("incremental_orders")),
        "incremental_orders_usage": "diagnostic_only",
        "avg_basket_turnover_bridge": copy.deepcopy(metrics.get("avg_basket_bridge")),
    }


def _scenario_overview(scenario: dict[str, Any]) -> dict[str, Any]:
    allocated_budget = float(scenario["allocated_budget_rub"])
    return {
        "scenario_id": scenario["scenario_id"],
        "name": scenario["name"],
        "description": scenario["description"],
        "available": bool(scenario["available"]),
        "budget": {
            "requested_budget_rub": float(scenario["requested_budget_rub"]),
            "allocated_budget_rub": allocated_budget,
            "unallocated_budget_rub": float(scenario["unallocated_budget_rub"]),
        },
        "metrics": _overview_metrics(scenario["metrics"], allocated_budget),
        "calculation_status": copy.deepcopy(scenario["calculation_status"]),
        "cell_support_status": copy.deepcopy(scenario["cell_support_status"]),
        "optimizer_status": copy.deepcopy(scenario["optimizer_status"]),
        "support": copy.deepcopy(scenario["support"]),
        "quality": copy.deepcopy(scenario["quality"]),
        "paired_comparison": copy.deepcopy(scenario.get("paired_comparison")),
    }


def _candidate_total(
    finalist_rows: list[dict[str, Any]], campaign_name: str, candidate_name: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    rows = [
        row
        for row in finalist_rows
        if str(row.get("source_campaign_name") or "") == campaign_name
        and str(row.get("candidate_name") or "") == candidate_name
        and str(row.get("segment") or "") == "__ALL__"
        and str(row.get("channel") or "") == "__TOTAL__"
        and str(row.get("target") or "") == "turnover_per_user"
    ]
    if not rows:
        return None, None, "search_only"
    if len(rows) != 1:
        raise ResultOverviewAdapterError(
            f"Expected one turnover finalist total for campaign candidate, found {len(rows)}"
        )
    row = rows[0]
    turnover = _quantile_metric(
        "RUB",
        _float(row, "total_effect_p10"),
        _float(row, "total_effect_p50"),
        _float(row, "total_effect_p90"),
    )
    spend = _float(row, "spend_rub")
    roas = _roas_metric(turnover, spend)
    return turnover, roas, "final_posterior"


def _candidate_summary(
    candidate_id: str | None,
    campaign_name: str,
    candidate_rows: list[dict[str, Any]],
    finalist_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if candidate_id is None:
        return None
    matches = [
        row
        for row in candidate_rows
        if _opaque_id("candidate", str(row.get("candidate_name") or "")) == candidate_id
    ]
    if len(matches) != 1:
        raise ResultOverviewAdapterError(
            f"Cannot resolve opaque Scenario 6 candidate {candidate_id!r}"
        )
    row = matches[0]
    candidate_name = str(row.get("candidate_name") or "")
    turnover, roas, evaluation_level = _candidate_total(
        finalist_rows, campaign_name, candidate_name
    )
    support_safe = _bool(row, "support_safe")
    hard_support_safe = _bool(row, "hard_support_safe")
    policy_safe = _bool(row, "policy_safe")
    reasons: list[str] = []
    precheck_reason = str(row.get("precheck_reason") or "").strip()
    if precheck_reason and precheck_reason != "OK":
        reasons.append(precheck_reason)
    violation_codes = str(row.get("policy_violation_codes") or "").strip()
    if violation_codes and violation_codes != "OK":
        reasons.extend(code for code in violation_codes.split("|") if code)
    if not support_safe:
        reasons.append("SUPPORT_NOT_SAFE")
    if not hard_support_safe:
        reasons.append("HARD_SUPPORT_NOT_SAFE")
    if not policy_safe:
        reasons.append("POLICY_NOT_SAFE")
    reasons = list(dict.fromkeys(reasons))
    eligible = (
        str(row.get("precheck_status") or "") == "scored"
        and support_safe
        and hard_support_safe
        and policy_safe
    )
    explanation = (
        "Кандидат прошел support и policy gates."
        if eligible
        else "Кандидат показан для аудита, но не может быть выбран автоматически."
    )
    return {
        "candidate_id": candidate_id,
        "evaluation_level": evaluation_level,
        "eligible_for_automatic_recommendation": eligible,
        "incremental_turnover": turnover,
        "turnover_roas": roas,
        "support": {
            "elevated_warnings": int(round(_float(row, "elevated_support_warnings_n"))),
            "strong_warnings": int(round(_float(row, "strong_support_warnings_n"))),
            "hard_warnings": int(round(_float(row, "hard_support_warnings_n"))),
            "policy_violations": int(round(_float(row, "policy_violations_n"))),
        },
        "rejection_reasons": reasons,
        "explanation": explanation,
    }


def _allocation_comparison(
    campaign_name: str,
    selected_candidate_id: str,
    scenario_rows: list[dict[str, Any]],
    allocation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_rows = [row for row in scenario_rows if str(row.get("scenario_no") or "") == "S01"]
    if len(source_rows) != 1:
        raise ResultOverviewAdapterError(f"Campaign {campaign_name!r} must contain one S01")
    source_candidate = str(source_rows[0].get("candidate_name") or "")

    original = {
        (str(row.get("segment") or ""), str(row.get("geo") or ""), str(row.get("channel") or "")): row
        for row in allocation_rows
        if str(row.get("source_campaign_name") or "") == campaign_name
        and str(row.get("candidate_name") or "") == source_candidate
    }
    recommended = {
        (str(row.get("segment") or ""), str(row.get("geo") or ""), str(row.get("channel") or "")): row
        for row in allocation_rows
        if str(row.get("source_campaign_name") or "") == campaign_name
        and _opaque_id("candidate", str(row.get("candidate_name") or "")) == selected_candidate_id
    }
    if not original or not recommended:
        raise ResultOverviewAdapterError(
            f"Campaign {campaign_name!r} lacks original or selected allocation evidence"
        )

    result: list[dict[str, Any]] = []
    for segment, geo, channel in sorted(set(original) | set(recommended)):
        old_row = original.get((segment, geo, channel), {})
        new_row = recommended.get((segment, geo, channel), {})
        old_budget = _float(old_row, "budget_rub")
        new_budget = _float(new_row, "budget_rub")
        delta = new_budget - old_budget
        if abs(delta) < 0.01:
            delta = 0.0
        action = "keep" if delta == 0 else ("increase" if delta > 0 else "decrease")
        policy_row = new_row or old_row
        gate_codes = [
            code
            for code in str(policy_row.get("gate_reason_codes") or "").split("|")
            if code and code != "OK"
        ]
        result.append(
            {
                "segment": segment,
                "geo": geo,
                "channel": channel,
                "uploaded_budget_rub": old_budget,
                "recommended_budget_rub": new_budget,
                "delta_budget_rub": delta,
                "uploaded_budget_share": _float(old_row, "budget_share"),
                "recommended_budget_share": _float(new_row, "budget_share"),
                "action": action,
                "optimizer_policy": str(policy_row.get("optimizer_policy") or ""),
                "allowed_use": str(policy_row.get("allowed_use") or ""),
                "gate_reason_codes": gate_codes,
            }
        )
    return result


def _campaign_overview(
    campaign: dict[str, Any],
    scenario_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    finalist_rows: list[dict[str, Any]],
    allocation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    campaign_name = str(campaign["passport"]["campaign_name"])
    scenarios = [_scenario_overview(scenario) for scenario in campaign["scenarios"]]
    selected = next(
        scenario
        for scenario in scenarios
        if scenario["scenario_id"] == campaign["recommendation"]["scenario_id"]
    )
    uploaded = next(scenario for scenario in scenarios if scenario["scenario_id"] == "S01")
    allocation = _allocation_comparison(
        campaign_name,
        campaign["recommendation"]["candidate_id"],
        scenario_rows,
        allocation_rows,
    )
    moved_budget = 0.5 * sum(abs(float(line["delta_budget_rub"])) for line in allocation)
    selected_turnover = selected["metrics"]["incremental_turnover"]
    uploaded_turnover = uploaded["metrics"]["incremental_turnover"]
    delta_p50 = None
    delta_share = None
    if selected_turnover is not None and uploaded_turnover is not None:
        delta_p50 = float(selected_turnover["p50"]) - float(uploaded_turnover["p50"])
        if float(uploaded_turnover["p50"]) != 0:
            delta_share = delta_p50 / abs(float(uploaded_turnover["p50"]))

    best_raw = _candidate_summary(
        campaign["scenario6"]["best_raw_candidate_id"],
        campaign_name,
        candidate_rows,
        finalist_rows,
    )
    best_safe = _candidate_summary(
        campaign["scenario6"]["best_safe_candidate_id"],
        campaign_name,
        candidate_rows,
        finalist_rows,
    )
    recommendation = campaign["recommendation"]
    return {
        "campaign_id": campaign["campaign_id"],
        "passport": copy.deepcopy(campaign["passport"]),
        "budget": copy.deepcopy(campaign["budget"]),
        "statuses": copy.deepcopy(campaign["statuses"]),
        "quality": copy.deepcopy(campaign["quality"]),
        "scenarios": scenarios,
        "recommendation": {
            "scenario_id": recommendation["scenario_id"],
            "scenario_name": recommendation["scenario_name"],
            "recommendation_type": copy.deepcopy(recommendation["recommendation_type"]),
            "reason": recommendation["reason"],
            "plan_status": copy.deepcopy(recommendation["plan_status"]),
            "optimizer_available": bool(recommendation["optimizer_available"]),
            "metrics": copy.deepcopy(selected["metrics"]),
            "versus_uploaded_plan": {
                "delta_incremental_turnover_p50_rub": delta_p50,
                "delta_incremental_turnover_p50_share": delta_share,
                "moved_budget_rub": moved_budget,
            },
        },
        "scenario6": {
            "audit": copy.deepcopy(campaign["scenario6"]),
            "best_raw": best_raw,
            "best_safe": best_safe,
            "raw_differs_from_safe": (
                best_raw is not None
                and best_safe is not None
                and best_raw["candidate_id"] != best_safe["candidate_id"]
            ),
        },
        "allocation_comparison": allocation,
        "warnings": copy.deepcopy(campaign["warnings"]),
    }


def _reject_paths(value: Any, field_name: str = "root") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _reject_paths(nested, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field_name}[{index}]")
    elif (
        isinstance(value, str)
        and _ABSOLUTE_PATH_RE.match(value)
        and not (field_name.endswith(".download_path") and value.startswith("/api/v1/"))
    ):
        raise ResultOverviewAdapterError(f"Absolute path is forbidden at {field_name}")


def validate_result_overview(payload: dict[str, Any]) -> None:
    if payload.get("contract_name") != CONTRACT_NAME or payload.get("schema_version") != SCHEMA_VERSION:
        raise ResultOverviewAdapterError("Unsupported ResultOverview contract")
    campaigns = payload.get("campaigns") or []
    if not campaigns:
        raise ResultOverviewAdapterError("ResultOverview must contain campaigns")
    for campaign in campaigns:
        scenario_ids = [scenario.get("scenario_id") for scenario in campaign.get("scenarios") or []]
        if scenario_ids != ["S01", "S02", "S03", "S04", "S05", "S06"]:
            raise ResultOverviewAdapterError("Campaign scenarios must be ordered S01-S06")
        lines = campaign.get("allocation_comparison") or []
        if not lines:
            raise ResultOverviewAdapterError("Allocation comparison must not be empty")
        for line in lines:
            expected = float(line["recommended_budget_rub"]) - float(line["uploaded_budget_rub"])
            if abs(expected - float(line["delta_budget_rub"])) > 0.01:
                raise ResultOverviewAdapterError("Allocation delta does not reconcile")
    for artifact in payload.get("artifacts") or []:
        if artifact.get("download_path") != f"/api/v1/artifacts/{artifact.get('artifact_id')}/download":
            raise ResultOverviewAdapterError("Artifact download path is not canonical")
    _reject_paths(payload)


def build_result_overview(
    optimizer_output_dir: Path | str,
    *,
    storage_prefix: str = "optimizer-runs",
    job_id: str | None = None,
    workflow_config_sha256: str | None = None,
) -> dict[str, Any]:
    output_dir = Path(optimizer_output_dir).expanduser().resolve()
    decision = build_decision_result(
        output_dir,
        storage_prefix=storage_prefix,
        job_id=job_id,
        workflow_config_sha256=workflow_config_sha256,
    ).to_dict()
    run_card = _read_json(_find_one(output_dir, "*_optimizer_run_card.json"))
    report_card = _read_json(output_dir / "marketer_report_card.json")
    scenario_rows = _read_csv(_artifact_path(output_dir, report_card.get("scenario_results_csv")))
    candidate_rows = _read_csv(
        _artifact_path(output_dir, (run_card.get("outputs") or {}).get("candidate_scores_csv"))
    )
    finalist_rows = _read_csv(
        _artifact_path(output_dir, (run_card.get("outputs") or {}).get("finalist_summary_csv"))
    )
    allocation_rows = _read_csv(
        _artifact_path(output_dir, (run_card.get("outputs") or {}).get("recommended_allocations_csv"))
    )

    campaigns: list[dict[str, Any]] = []
    for campaign in decision["campaign_results"]:
        campaign_name = str(campaign["passport"]["campaign_name"])
        campaigns.append(
            _campaign_overview(
                campaign,
                [row for row in scenario_rows if str(row.get("campaign_name") or "") == campaign_name],
                [row for row in candidate_rows if str(row.get("campaign_name") or "") == campaign_name],
                [row for row in finalist_rows if str(row.get("source_campaign_name") or "") == campaign_name],
                [row for row in allocation_rows if str(row.get("source_campaign_name") or "") == campaign_name],
            )
        )

    artifacts = []
    for artifact in decision["artifacts"]:
        item = copy.deepcopy(artifact)
        item["download_path"] = f"/api/v1/artifacts/{artifact['artifact_id']}/download"
        artifacts.append(item)
    payload = {
        "contract_name": CONTRACT_NAME,
        "schema_version": SCHEMA_VERSION,
        "overview_adapter_version": OVERVIEW_ADAPTER_VERSION,
        "overview_id": _opaque_id("overview", decision["result_id"]),
        "source_result_id": decision["result_id"],
        "result_origin": decision["result_origin"],
        "created_at_utc": decision["created_at_utc"],
        "campaigns": campaigns,
        "artifacts": artifacts,
        "warnings": copy.deepcopy(decision["warnings"]),
    }
    validate_result_overview(payload)
    return payload


def sanitized_overview_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(payload)
    sanitized["result_origin"] = "sanitized_fixture"
    sanitized["overview_id"] = _opaque_id("overview", "sanitized-result-overview-v1")
    sanitized["source_result_id"] = _opaque_id("result", "sanitized-result-overview-source-v1")
    label_maps: dict[str, dict[str, str]] = {"segment": {}, "geo": {}, "channel": {}}

    def label(kind: str, source: str) -> str:
        if source not in label_maps[kind]:
            label_maps[kind][source] = f"{kind.upper()}_{len(label_maps[kind]) + 1:02d}"
        return label_maps[kind][source]

    def scale(node: Any) -> None:
        if isinstance(node, dict):
            unit = node.get("unit")
            factor = {
                "RUB": 0.083,
                "turnover_bridge_from_avg_basket_rub": 0.083,
                "orders": 0.419,
                "ratio": 0.083 / 0.137,
            }.get(unit)
            if factor is not None:
                for key in ("p10", "p50", "p90"):
                    if isinstance(node.get(key), (int, float)):
                        node[key] = round(float(node[key]) * factor, 6)
            for key, value in list(node.items()):
                if key.endswith("budget_rub") or key == "moved_budget_rub":
                    if isinstance(value, (int, float)):
                        node[key] = round(float(value) * 0.137, 2)
                elif key == "delta_incremental_turnover_p50_rub" and isinstance(value, (int, float)):
                    node[key] = round(float(value) * 0.083, 2)
                else:
                    scale(value)
        elif isinstance(node, list):
            for item in node:
                scale(item)

    scale(sanitized)
    for index, campaign in enumerate(sanitized["campaigns"], start=1):
        campaign["campaign_id"] = _opaque_id("campaign", f"sanitized-overview-campaign-{index}")
        passport = campaign["passport"]
        passport["campaign_name"] = f"Demo campaign {index}"
        passport["source_campaign_name"] = f"Demo source campaign {index}"
        for field in ("segments",):
            passport[field] = [label("segment", value) for value in passport[field]]
        for field in ("source_channels", "modeled_channels", "unmodeled_channels"):
            passport[field] = [label("channel", value) for value in passport[field]]
        passport["geographies"] = [label("geo", value) for value in passport["geographies"]]
        passport["creatives"] = [f"CREATIVE_{i:02d}" for i, _ in enumerate(passport["creatives"], 1)]
        lines = campaign["allocation_comparison"]
        if len(lines) > 30:
            ranked = sorted(lines, key=lambda line: abs(float(line["delta_budget_rub"])), reverse=True)
            kept = ranked[:24]
            omitted = ranked[24:]
            aggregates: list[dict[str, Any]] = []
            for action in ("increase", "decrease", "keep"):
                group = [line for line in omitted if line["action"] == action]
                if not group:
                    continue
                aggregates.append(
                    {
                        "segment": f"SEGMENT_OTHER_{action.upper()}",
                        "geo": f"GEO_OTHER_{action.upper()}",
                        "channel": f"CHANNEL_OTHER_{action.upper()}",
                        "uploaded_budget_rub": round(
                            sum(float(line["uploaded_budget_rub"]) for line in group), 2
                        ),
                        "recommended_budget_rub": round(
                            sum(float(line["recommended_budget_rub"]) for line in group), 2
                        ),
                        "delta_budget_rub": round(
                            sum(float(line["delta_budget_rub"]) for line in group), 2
                        ),
                        "uploaded_budget_share": sum(
                            float(line["uploaded_budget_share"]) for line in group
                        ),
                        "recommended_budget_share": sum(
                            float(line["recommended_budget_share"]) for line in group
                        ),
                        "action": action,
                        "optimizer_policy": "sanitized_aggregate",
                        "allowed_use": "mixed",
                        "gate_reason_codes": ["SANITIZED_AGGREGATE"],
                    }
                )
            campaign["allocation_comparison"] = kept + aggregates
        for line in campaign["allocation_comparison"]:
            line["segment"] = label("segment", line["segment"])
            line["geo"] = label("geo", line["geo"])
            line["channel"] = label("channel", line["channel"])
            line["delta_budget_rub"] = round(
                float(line["recommended_budget_rub"]) - float(line["uploaded_budget_rub"]),
                2,
            )
            line["action"] = (
                "keep"
                if line["delta_budget_rub"] == 0
                else ("increase" if line["delta_budget_rub"] > 0 else "decrease")
            )
        campaign["recommendation"]["versus_uploaded_plan"]["moved_budget_rub"] = round(
            0.5
            * sum(
                abs(float(line["delta_budget_rub"]))
                for line in campaign["allocation_comparison"]
            ),
            2,
        )
        for key in ("best_raw", "best_safe"):
            candidate = campaign["scenario6"].get(key)
            if candidate:
                candidate["candidate_id"] = _opaque_id("candidate", f"sanitized-{key}-{index}")
        audit = campaign["scenario6"]["audit"]
        for key in ("best_raw_candidate_id", "best_safe_candidate_id"):
            if audit.get(key):
                mapped = campaign["scenario6"]["best_raw" if key.startswith("best_raw") else "best_safe"]
                audit[key] = mapped["candidate_id"] if mapped else None
        for warning in campaign["warnings"]:
            warning["affected_cells"] = []
    for index, artifact in enumerate(sanitized["artifacts"], start=1):
        artifact["artifact_id"] = _opaque_id("artifact", f"sanitized-overview-artifact-{index}")
        artifact["sha256"] = hashlib.sha256(f"sanitized-overview-{index}".encode()).hexdigest()
        artifact["storage_key"] = f"fixtures/result-overview-v1/artifact-{index:02d}"
        artifact["download_path"] = f"/api/v1/artifacts/{artifact['artifact_id']}/download"
        artifact["size_bytes"] = 0
    validate_result_overview(sanitized)
    return sanitized


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--optimizer-output-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sanitized-fixture-output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = build_result_overview(args.optimizer_output_dir)
    write_json_atomic(args.output, payload)
    if args.sanitized_fixture_output is not None:
        write_json_atomic(args.sanitized_fixture_output, sanitized_overview_payload(payload))
    print(json.dumps({"status": "ok", "overview_id": payload["overview_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
