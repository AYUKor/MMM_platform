"""Contract and projection tests for Phase E.1A business semantics."""

from __future__ import annotations

import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_APP_DIR = PROJECT_ROOT / "04_Web_app"
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"
for entry in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from contracts.business_semantics_v2 import (  # noqa: E402
    BusinessSemanticsContractError,
    load_geo_catalog_v1_schema,
    load_job_result_view_v2_schema,
    load_model_overview_v2_schema,
    load_model_passport_v2_schema,
    load_scenario_media_plan_v2_schema,
    load_validation_result_v2_schema,
    load_workspace_geo_budget_v1_schema,
    validate_job_result_view_v2,
    validate_validation_result_v2,
)
from mmm_core.serving_semantics import (  # noqa: E402
    channel_display_name,
)
from services.business_semantics_v2 import (  # noqa: E402
    build_geo_catalog,
    build_model_overview_v2,
    build_model_passport_v2,
    build_scenario_media_plan_v2,
    build_validation_result_v2,
    build_workspace_geo_budget_v1,
)


FIXTURE_DIR = WEB_APP_DIR / "tests" / "fixtures"
CHANNELS = ["Digital_Performance", "OOH_Total", "Радио"]
GEOS = [f"ГЕО {index:02d}" for index in range(1, 16)]
REQUESTED_BUDGET = 267_818_706.0


def _schema_valid(schema: dict, payload: dict) -> None:
    Draft202012Validator(schema).validate(payload)


def _validation_payload() -> dict:
    equal = REQUESTED_BUDGET / len(GEOS)
    budget_rows = [
        {"geo": geo, "total_budget_rub": equal, "max_daily_budget_rub": equal / 30}
        for geo in GEOS
    ]
    budget_rows[-1]["total_budget_rub"] += REQUESTED_BUDGET - sum(
        row["total_budget_rub"] for row in budget_rows
    )
    return {
        "validation_id": "validation_e1a00000001",
        "status": {"code": "valid", "display_text": "План можно рассчитать"},
        "job_creation_allowed": True,
        "campaigns": [
            {
                "campaign_id": "campaign_e1a000000001",
                "campaign_name": "Региональная кампания",
                "geographies": GEOS,
                "channels": CHANNELS,
            }
        ],
        "totals": {
            "source_rows_n": 45,
            "uploaded_budget_rub": REQUESTED_BUDGET,
            "model_input_budget_rub": REQUESTED_BUDGET,
        },
        "blocking_errors": [],
        "warnings": [
            {
                "code": "MODEL_CAUTION_CELLS",
                "severity": "warning",
                "scope": "model",
                "what": "Для OOH_Total есть ограничение качества оценки.",
                "why": "Историческая активность ограничена.",
                "recommended_action": "Проверьте отмеченные географии.",
                "affected_cells": [
                    {
                        "target": "turnover_per_user",
                        "channel": "OOH_Total",
                        "geo": GEOS[0],
                    },
                    {
                        "target": "turnover_per_user",
                        "channel": "OOH_Total",
                        "geo": GEOS[1],
                    },
                ],
            },
            {
                "code": "MODEL_CAUTION_CELLS",
                "severity": "warning",
                "scope": "model",
                "affected_cells": [
                    {
                        "target": "turnover_per_user",
                        "channel": "OOH_Total",
                        "geo": GEOS[1],
                    }
                ],
            },
            {
                "code": "MODEL_DIAGNOSTIC_CELLS",
                "severity": "warning",
                "scope": "model",
                "affected_cells": [
                    {
                        "target": "orders_per_user",
                        "channel": "Digital_Performance",
                        "geo": GEOS[0],
                    }
                ],
            },
            {
                "code": "MODEL_GENERAL_NOTICE",
                "severity": "warning",
                "scope": "model",
                "what": "Общее ограничение модели.",
                "affected_cells": [],
            },
        ],
        "preview": {
            "budget_by_geo": budget_rows,
            "checks": [
                {"code": "FILE_STRUCTURE", "status": "passed", "display_text": "Структура файла распознана."},
                {"code": "CAMPAIGN_COUNT", "status": "passed", "display_text": "Найдена одна кампания."},
                {"code": "BUDGET_RECONCILIATION", "status": "passed", "display_text": "Бюджет сходится."},
                {"code": "DATES", "status": "passed", "display_text": "Даты заполнены корректно."},
            ],
        },
    }


def _metric(p10: float, p50: float, p90: float, *, unit: str) -> dict:
    return {
        "status": "available",
        "unit": unit,
        "p10": p10,
        "p50": p50,
        "p90": p90,
        "display_text": "Показатель рассчитан.",
    }


def _scenario(
    scenario_id: str,
    *,
    requested: float = 100.0,
    allocated: float = 100.0,
    effect: tuple[float, float, float] = (80.0, 100.0, 120.0),
    variant: str | None = None,
) -> dict:
    unallocated = requested - allocated
    available = allocated > 0
    turnover = _metric(*effect, unit="RUB") if available else {
        "status": "unavailable",
        "unit": "RUB",
        "p10": None,
        "p50": None,
        "p90": None,
        "display_text": "Показатель недоступен.",
    }

    def roas(denominator: float) -> dict:
        if not available or denominator <= 0:
            return {
                "status": "unavailable",
                "unit": "ratio",
                "p10": None,
                "p50": None,
                "p90": None,
                "display_text": "Показатель недоступен.",
            }
        return _metric(*(value / denominator for value in effect), unit="ratio")

    is_s1 = scenario_id == "S01"
    is_s5_partial = scenario_id == "S05" and variant == "safe_partial"
    is_s6 = scenario_id == "S06"
    decision_status = (
        "keep_uploaded_plan"
        if is_s1
        else "no_safe_recommendation"
        if is_s5_partial
        else "recommended_reallocation"
        if is_s6
        else "manual_review_required"
    )
    return {
        "scenario_id": scenario_id,
        "name": f"Сценарий {scenario_id}",
        "description": "Вариант распределения бюджета.",
        "scenario_kind": (
            "uploaded_plan"
            if is_s1
            else "conservative_plan"
            if scenario_id == "S05"
            else "optimized_plan"
            if is_s6
            else "benchmark_plan"
        ),
        "scenario_variant": variant or f"variant_{scenario_id.lower()}",
        "status": "completed",
        "is_recommended": is_s6,
        "decision_status": decision_status,
        "review_status": (
            "not_required" if decision_status == "recommended_reallocation" else "manual_review_required"
        ),
        "budget": {
            "requested_budget_rub": requested,
            "allocated_budget_rub": allocated,
            "unallocated_budget_rub": unallocated,
            "allocation_share": allocated / requested if requested > 0 else None,
        },
        "incremental_turnover": turnover,
        "roas": {
            "allocated_budget": roas(allocated),
            "requested_budget": roas(requested),
            "primary_denominator_kind": "allocated_budget" if is_s5_partial else "requested_budget",
            "primary_denominator_budget_rub": allocated if is_s5_partial else requested,
        },
        "risk_budget": {
            "within_support_budget_rub": allocated,
            "within_support_share": 1.0 if allocated > 0 else None,
            "controlled_extrapolation_budget_rub": 0.0,
            "controlled_extrapolation_share": 0.0 if allocated > 0 else None,
            "high_risk_budget_rub": 0.0,
            "high_risk_share": 0.0 if allocated > 0 else None,
            "within_support_cells_n": 1 if allocated > 0 else 0,
            "controlled_extrapolation_cells_n": 0,
            "high_risk_cells_n": 0,
        },
        "reliability": {
            "status": "within_support",
            "display_text": "Бюджет находится в поддержанном диапазоне.",
            "evidence_codes": ["WITHIN_SUPPORT"],
            "safe_rank": None,
            "raw_rank": None,
        },
        "limiting_constraints": ["Недостаточная допустимая емкость."] if is_s5_partial else [],
    }


def _result_payload() -> dict:
    scenarios = [
        _scenario("S01"),
        _scenario("S02"),
        _scenario("S03"),
        _scenario("S04"),
        _scenario("S05", variant="full_conservative"),
        _scenario("S06", variant="full_effect_maximizing"),
    ]
    return {
        "contract_name": "job_result_view_v2",
        "schema_version": "2.0.0",
        "record_origin": "sanitized_fixture",
        "job_id": "job_e1a000000001",
        "result_id": "result_e1a000000001",
        "source_overview_id": "overview_e1a000001",
        "updated_at_utc": "2026-07-17T12:00:00+00:00",
        "campaign": {
            "campaign_id": "campaign_e1a000000001",
            "campaign_name": "Региональная кампания",
            "segments": ["ТС5/Онлайн"],
            "start_date": "2026-08-01",
            "end_date": "2026-08-30",
            "requested_budget_rub": 100.0,
            "channels": [
                {"channel_id": channel, "channel_display_name": channel_display_name(channel)}
                for channel in CHANNELS
            ],
            "geographies_n": len(GEOS),
            "geographies": [
                {"geo_id": f"geo_{index:016x}", "geo_display_name": geo}
                for index, geo in enumerate(GEOS, start=1)
            ],
        },
        "recommendation": {
            "decision_status": "recommended_reallocation",
            "review_status": "not_required",
            "scenario_id": "S06",
            "title": "Рекомендуемое перераспределение бюджета",
            "display_text": "Выбран полный план в пределах утвержденных ограничений.",
            "decision_scope_text": "Рекомендация относится к распределению бюджета, а не к запуску кампании.",
        },
        "scenarios": scenarios,
        "media_plan": {
            "endpoint": "/api/v1/jobs/job_e1a000000001/media-plan-v2",
            "selected_scenario_id": "S06",
        },
        "map": {
            "status": "unavailable",
            "display_text": "Утвержденные координаты пока недоступны; карта не строится.",
            "coordinate_catalog_version": "geo_catalog_v1_unlocated_2026_07",
            "geo_points": [
                {
                    "geo_id": f"geo_{index:016x}",
                    "geo_display_name": geo,
                    "latitude": None,
                    "longitude": None,
                    "coordinates_status": "unavailable",
                    "region_id": None,
                    "region_display_name": None,
                }
                for index, geo in enumerate(GEOS, start=1)
            ],
        },
        "limitations": [
            {"code": "incremental_effect_only", "display_text": "Показан дополнительный оборот."}
        ],
    }


class BusinessSemanticsV2Test(unittest.TestCase):
    def test_channel_catalog_is_versioned_and_fail_closed(self) -> None:
        self.assertEqual(channel_display_name("Digital_Performance"), "Цифровая реклама")
        self.assertEqual(channel_display_name("OOH_Total"), "Наружная реклама")
        self.assertEqual(channel_display_name("Радио"), "Радио")
        self.assertEqual(channel_display_name("Indoor"), "Indoor")
        with self.assertRaisesRegex(ValueError, "absent from channel_catalog_v1"):
            channel_display_name("Неизвестный канал")

    def test_media_plan_v2_publishes_channel_and_geo_identities(self) -> None:
        budget_fields = {
            "source_budget_rub": 100.0,
            "selected_budget_rub": 100.0,
            "delta_rub": 0.0,
            "delta_pct": 0.0,
            "quality_status": "within_support",
            "quality_display_text": "Бюджет находится в поддержанном диапазоне.",
        }
        geo_channel = {"geo": GEOS[0], "channel": "Digital_Performance", **budget_fields}
        payload_v1 = {
            "contract_name": "scenario_media_plan_v1",
            "schema_version": "1.0.0",
            "record_origin": "sanitized_fixture",
            "job_id": "job_e1a000000001",
            "result_id": "result_e1a000000001",
            "campaign_id": "campaign_e1a000000001",
            "scenario": {
                "scenario_id": "S01",
                "title": "Как загружено",
                "status": "completed",
                "is_selected": True,
                "safe_rank": 1,
                "raw_rank": 1,
                "quality_status": "within_support",
                "quality_display_text": "План рассчитан.",
            },
            "source_artifact": {
                "artifact_id": "artifact_e1a000000001",
                "kind": "recommended_allocations_csv",
                "sha256": "a" * 64,
            },
            "grain": "geo_channel_total",
            "filters": {"channel": None, "geo": None, "date": None},
            "pagination": {"page": 1, "page_size": 100, "total_rows": 1, "total_pages": 1},
            "totals": {
                "requested_budget_rub": 100.0,
                "source_budget_rub": 100.0,
                "selected_budget_rub": 100.0,
                "unallocated_budget_rub": 0.0,
                "delta_rub": 0.0,
                "reconciliation_status": "reconciled",
            },
            "filtered_totals": {
                "source_budget_rub": 100.0,
                "selected_budget_rub": 100.0,
                "delta_rub": 0.0,
            },
            "rows": [
                {
                    "scenario_id": "S01",
                    "campaign_id": "campaign_e1a000000001",
                    "segment": "ТС5/Онлайн",
                    "geo": GEOS[0],
                    "channel": "Digital_Performance",
                    "date": None,
                    **budget_fields,
                    "source_budget_share": 1.0,
                    "selected_budget_share": 1.0,
                }
            ],
            "aggregates": {
                "by_channel": [{"channel": "Digital_Performance", **budget_fields}],
                "by_geo": [{"geo": GEOS[0], **budget_fields}],
                "by_geo_channel": [geo_channel],
                "by_date": {"status": "unavailable", "display_text": "Недоступно.", "rows": None},
                "channel_date_matrix": {"status": "unavailable", "display_text": "Недоступно.", "rows": None},
                "geo_channel_matrix": {"status": "ready", "display_text": "Готово.", "rows": [geo_channel]},
            },
            "map": {
                "status": "unavailable",
                "display_text": "Карта недоступна.",
                "geo_points": None,
                "coordinate_catalog_version": None,
            },
            "working_media_plan": {
                "status": "unavailable",
                "display_text": "Файл недоступен.",
                "artifact": None,
            },
            "limitations": [{"code": "total_grain", "display_text": "Итоги за период."}],
            "updated_at_utc": "2026-07-17T12:00:00+00:00",
        }

        payload = build_scenario_media_plan_v2(payload_v1)
        _schema_valid(load_scenario_media_plan_v2_schema(), payload)
        row = payload["rows"][0]
        self.assertEqual(row["channel_id"], "Digital_Performance")
        self.assertEqual(row["channel_display_name"], "Цифровая реклама")
        self.assertEqual(row["geo_display_name"], GEOS[0])
        self.assertNotIn("channel", row)
        self.assertNotIn("geo", row)

    def test_validation_keeps_15_geos_and_separates_turnover_limitations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalized = Path(tmp) / "normalized.csv"
            with normalized.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["geo", "channel"])
                writer.writeheader()
                for geo in GEOS:
                    for channel in CHANNELS:
                        writer.writerow({"geo": geo, "channel": channel})
            payload = build_validation_result_v2(
                _validation_payload(), normalized_plan_path=normalized
            )

        _schema_valid(load_validation_result_v2_schema(), payload)
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["file_validation"]["status"], "passed")
        self.assertEqual(payload["file_validation"]["rows_n"], 45)
        self.assertEqual(payload["file_validation"]["geographies_n"], 15)
        self.assertEqual(payload["file_validation"]["channels_n"], 3)
        self.assertEqual(payload["file_validation"]["warnings_n"], 0)
        self.assertEqual(len(payload["model_limitations"]), 1)
        limitation = payload["model_limitations"][0]
        self.assertEqual(limitation["target"], "turnover")
        self.assertEqual(limitation["channel_display_name"], "Наружная реклама")
        self.assertEqual(limitation["affected_geos_n"], 2)
        self.assertNotIn("OOH_Total", limitation["what"])
        self.assertEqual(len(payload["geo_points"]), 15)
        self.assertAlmostEqual(
            sum(row["budget_rub"] for row in payload["geo_points"]),
            REQUESTED_BUDGET,
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("orders_per_user", serialized)
        self.assertNotIn("avg_basket", serialized)

        invalid_coordinate = copy.deepcopy(payload)
        invalid_coordinate["geo_points"][0].update(
            {"latitude": 999.0, "longitude": 37.62, "coordinates_status": "canonical"}
        )
        with self.assertRaises(BusinessSemanticsContractError):
            validate_validation_result_v2(invalid_coordinate)
        with self.assertRaises(Exception):
            _schema_valid(load_validation_result_v2_schema(), invalid_coordinate)

    def test_geo_catalog_never_guesses_coordinates(self) -> None:
        unavailable = build_geo_catalog(GEOS)
        _schema_valid(load_geo_catalog_v1_schema(), unavailable)
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertTrue(all(row["latitude"] is None for row in unavailable["entries"]))

        partial = build_geo_catalog(
            GEOS,
            canonical_coordinates={GEOS[0]: {"latitude": 55.75, "longitude": 37.62}},
        )
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["entries"][0]["coordinates_status"], "canonical")
        with self.assertRaisesRegex(ValueError, "unknown geographies"):
            build_geo_catalog(GEOS, canonical_coordinates={"ДРУГОЕ ГЕО": {"latitude": 1, "longitude": 2}})

    def test_workspace_geo_budget_reconciles_without_map_coordinates(self) -> None:
        payload = build_workspace_geo_budget_v1([_validation_payload()])
        _schema_valid(load_workspace_geo_budget_v1_schema(), payload)
        self.assertEqual(payload["geographies_n"], 15)
        self.assertAlmostEqual(payload["total_budget_rub"], REQUESTED_BUDGET)
        self.assertEqual(payload["status"], "unavailable")

    def test_model_contracts_publish_one_target_and_four_active_models(self) -> None:
        passport_v1 = json.loads(
            (FIXTURE_DIR / "model_passport_v1_synthetic.json").read_text(encoding="utf-8")
        )
        passport_v1["coverage"]["targets"].append(
            {"target": "orders_per_user", "allowed_use_counts": {"diagnostic": 1}, "objective_roles": ["side_metric_only"]}
        )
        passport_v1["coverage"]["channel_policies"].append(
            {
                "segment": "ТС5/Онлайн",
                "channel": "Indoor",
                "target": "orders_per_user",
                "allowed_use": "diagnostic",
                "forecast_action": "diagnostic",
                "optimizer_action": "fixed_at_plan",
                "display_text": "Заказы используются только как диагностика.",
            }
        )
        passport = build_model_passport_v2(passport_v1)
        _schema_valid(load_model_passport_v2_schema(), passport)
        self.assertEqual(passport["serving"]["serving_targets_n"], 1)
        self.assertEqual(passport["serving"]["active_serving_models_n"], 4)
        self.assertEqual(passport["serving"]["research_models_in_package_n"], 12)
        self.assertTrue(all(row["target"] == "turnover" for row in passport["channel_policies"]))

        verified_incomplete = copy.deepcopy(passport_v1)
        verified_incomplete["record_origin"] = "verified_model_package"
        with self.assertRaisesRegex(ValueError, "12-to-4"):
            build_model_passport_v2(verified_incomplete)

        verified_complete = copy.deepcopy(verified_incomplete)
        verified_complete["coverage"]["segments"] = [f"segment_{index}" for index in range(4)]
        verified_complete["coverage"]["targets"] = [
            {"target": target}
            for target in ("turnover_per_user", "orders_per_user", "avg_basket")
        ]
        measured = build_model_passport_v2(verified_complete)
        self.assertEqual(measured["serving"]["active_serving_models_n"], 4)
        self.assertEqual(measured["serving"]["research_models_in_package_n"], 12)

        overview = build_model_overview_v2(
            {
                "limitations": [
                    {"code": "orders_diagnostic_only", "display_text": "Заказы остаются диагностикой."},
                    {"code": "allocation_only", "display_text": "Система рекомендует только распределение бюджета."},
                ]
            },
            passport,
        )
        _schema_valid(load_model_overview_v2_schema(), overview)
        serialized = json.dumps({"passport": passport, "overview": overview}, ensure_ascii=False)
        self.assertNotIn("orders_per_user", serialized)
        self.assertNotIn("avg_basket", serialized)
        self.assertNotIn("orders_diagnostic_only", serialized)

    def test_result_contract_enforces_s1_s5_s6_and_roas_denominators(self) -> None:
        payload = _result_payload()
        partial = _scenario(
            "S05",
            requested=REQUESTED_BUDGET,
            allocated=102_600_000.0,
            effect=(150_000_000.0, 160_800_000.0, 175_000_000.0),
            variant="safe_partial",
        )
        payload["scenarios"][4] = partial
        validate_job_result_view_v2(payload)
        _schema_valid(load_job_result_view_v2_schema(), payload)
        self.assertAlmostEqual(partial["budget"]["allocation_share"], 102_600_000 / REQUESTED_BUDGET)
        self.assertAlmostEqual(partial["roas"]["allocated_budget"]["p50"], 160_800_000 / 102_600_000)
        self.assertAlmostEqual(partial["roas"]["requested_budget"]["p50"], 160_800_000 / REQUESTED_BUDGET)
        self.assertFalse(payload["scenarios"][0]["is_recommended"])
        self.assertEqual(payload["scenarios"][0]["decision_status"], "keep_uploaded_plan")
        self.assertEqual(len(payload["campaign"]["geographies"]), 15)

        wrong_review = copy.deepcopy(payload)
        wrong_review["scenarios"][4]["review_status"] = "not_required"
        with self.assertRaisesRegex(BusinessSemanticsContractError, "safe_partial"):
            validate_job_result_view_v2(wrong_review)

        absolute_path = copy.deepcopy(payload)
        absolute_path["limitations"][0]["display_text"] = "/home/service/model/package.json"
        with self.assertRaisesRegex(BusinessSemanticsContractError, "Local path"):
            validate_job_result_view_v2(absolute_path)

        invalid_s6 = copy.deepcopy(payload)
        invalid_s6["scenarios"][5] = _scenario(
            "S06",
            requested=100.0,
            allocated=90.0,
            variant="full_effect_maximizing",
        )
        with self.assertRaisesRegex(BusinessSemanticsContractError, "Completed S6"):
            validate_job_result_view_v2(invalid_s6)

        diagnostic = copy.deepcopy(payload)
        diagnostic["scenarios"][0]["incremental_orders"] = {"p50": 1}
        with self.assertRaisesRegex(BusinessSemanticsContractError, "Diagnostic target field"):
            validate_job_result_view_v2(diagnostic)

        truncated = copy.deepcopy(payload)
        truncated["campaign"]["geographies"][0]["geo_display_name"] = "УФА ... ещё 3"
        with self.assertRaisesRegex(BusinessSemanticsContractError, "Presentation-truncated"):
            validate_job_result_view_v2(truncated)

        forbidden_wording = copy.deepcopy(payload)
        forbidden_wording["limitations"][0]["display_text"] = (
            "Часть дополнительного оборота связана со средним чеком."
        )
        with self.assertRaisesRegex(BusinessSemanticsContractError, "Forbidden diagnostic wording"):
            validate_job_result_view_v2(forbidden_wording)

        unsafe_recommendation = copy.deepcopy(payload)
        unsafe_s6 = unsafe_recommendation["scenarios"][5]
        unsafe_s6["risk_budget"].update(
            {
                "within_support_budget_rub": 0.0,
                "within_support_share": 0.0,
                "high_risk_budget_rub": 100.0,
                "high_risk_share": 1.0,
            }
        )
        with self.assertRaisesRegex(BusinessSemanticsContractError, "Recommended S6"):
            validate_job_result_view_v2(unsafe_recommendation)

        missing_flag = copy.deepcopy(payload)
        missing_flag["scenarios"][5]["is_recommended"] = False
        with self.assertRaisesRegex(BusinessSemanticsContractError, "complete policy-safe"):
            validate_job_result_view_v2(missing_flag)


if __name__ == "__main__":
    unittest.main()
