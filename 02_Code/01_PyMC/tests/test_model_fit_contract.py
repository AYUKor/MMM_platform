"""Contract tests for the script-backed Q1 MMM fit runtime."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

PYMC_CODE_DIR = Path(__file__).resolve().parents[1]
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core import fit  # noqa: E402
from mmm_core import model as model_runtime  # noqa: E402


class GuardedFitContractTests(unittest.TestCase):
    def test_contraction_categories_keep_expansion_separate(self) -> None:
        cases = [
            (1.0, 2.0, -1.0, "posterior_expanded"),
            (1.0, 0.9, 0.1, "low_contraction"),
            (1.0, 0.7, 0.3, "medium_contraction"),
            (1.0, 0.2, 0.8, "high_contraction"),
        ]
        for prior_var, posterior_var, expected_value, expected_verdict in cases:
            value, verdict = fit.classify_prior_posterior_contraction(prior_var, posterior_var)
            self.assertAlmostEqual(float(value), expected_value)
            self.assertEqual(verdict, expected_verdict)

    def test_contraction_unavailable_for_invalid_prior_variance(self) -> None:
        for prior_var in [0.0, float("nan"), float("inf")]:
            value, verdict = fit.classify_prior_posterior_contraction(prior_var, 1.0)
            self.assertIsNone(value)
            self.assertEqual(verdict, "unavailable")

    def test_expected_fit_set_is_complete(self) -> None:
        self.assertEqual(len(fit.EXPECTED_FIT_KEYS), 12)
        self.assertEqual(len(set(fit.EXPECTED_FIT_KEYS)), 12)
        self.assertEqual(
            fit.normalize_only_fits(["ТСХ/Оффлайн::avg_basket"]),
            {"ТСХ/Оффлайн::avg_basket"},
        )
        with self.assertRaisesRegex(ValueError, "Unknown --only-fit"):
            fit.normalize_only_fits(["missing::fit"])

    def test_fixed_lambda_configuration_is_fit_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "fit.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "mode: pilot",
                        f"panel_path: {root / 'panel.parquet'}",
                        f"run_dir: {root / 'run'}",
                        "fixed_lambda_channels_by_fit:",
                        "  ТС5_Оффлайн__turnover_per_user:",
                        "    - Нац_ТВ",
                    ]
                ),
                encoding="utf-8",
            )
            spec = fit.load_guarded_fit_spec(config_path)
            self.assertEqual(
                spec.fixed_lambda_channels_by_fit,
                {"ТС5/Оффлайн::turnover_per_user": ("Нац_ТВ",)},
            )

            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "ТС5_Оффлайн__turnover_per_user",
                    "missing__fit",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Unknown fixed-lambda fit_key"):
                fit.load_guarded_fit_spec(config_path)

    def test_geo_lag_tensor_resets_at_geo_boundary(self) -> None:
        values = np.array([[1.0], [2.0], [100.0], [200.0]])
        geo_idx = np.array([0, 0, 1, 1])
        lagged = fit.make_geo_lagged_tensor(values, geo_idx, 1)
        np.testing.assert_array_equal(lagged[0, :, 0], [1.0, 2.0, 100.0, 200.0])
        np.testing.assert_array_equal(lagged[1, :, 0], [0.0, 1.0, 0.0, 100.0])

    def test_run_identity_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel_path = root / "panel.parquet"
            config_path = root / "fit.yaml"
            run_dir = root / "run"
            pd.DataFrame({"x": [1]}).to_parquet(panel_path, index=False)
            config_path.write_text("mode: fast\n", encoding="utf-8")
            spec = fit.GuardedFitSpec(
                config_path=config_path,
                panel_path=panel_path,
                run_dir=run_dir,
                mode="fast",
                train_start="2025-01-01",
                train_end="2025-01-31",
                holdout_start="2025-02-01",
                holdout_end="2025-03-01",
                profile=dict(fit.MODE_PROFILES["fast"]),
                require_numpyro=True,
                random_seed=42,
                thin_sample_threshold=50,
                vif_threshold=7.0,
            )
            first = fit._ensure_run_identity(spec, resume=False, prepare_only=True)
            second = fit._ensure_run_identity(spec, resume=True, prepare_only=False)
            self.assertEqual(first, second)
            config_path.write_text("mode: medium\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Immutable run identity differs"):
                fit._ensure_run_identity(spec, resume=True, prepare_only=False)

    def test_existing_contract_detects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fit_contract.json"
            payload = {"fit_key": "S::T", "fit_contract_sha256": "abc"}
            fit._write_or_validate_contract(path, payload)
            fit._write_or_validate_contract(path, payload)
            path.write_text(json.dumps({**payload, "fit_contract_sha256": "tampered"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                fit._write_or_validate_contract(path, payload)

    def test_csv_metadata_roundtrip_ignores_only_machine_precision_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scalers.csv"
            expected = pd.DataFrame(
                {
                    "fit_key": ["segment::target"],
                    "mean": [0.12345678901234567],
                    "std": [9876543.210987654],
                }
            )
            expected.to_csv(path, index=False)
            fit._validate_csv_roundtrip(path, expected, "scalers")

            tampered = expected.copy()
            tampered.loc[0, "mean"] += 1e-4
            with self.assertRaisesRegex(ValueError, "scalers changed"):
                fit._validate_csv_roundtrip(path, tampered, "scalers")

    def test_orchestrator_cached_fit_validation_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            fit_key = "ТС5/Онлайн::turnover_per_user"
            safe = "ТС5_Онлайн__turnover_per_user"
            posterior = run_dir / f"posterior_{safe}.nc"
            posterior.write_bytes(b"posterior")
            state = {
                "status": "complete",
                "fit_key": fit_key,
                "posterior_sha256": model_runtime.sha256_file(posterior),
            }
            (run_dir / f"fit_state_{safe}.json").write_text(
                json.dumps(state, ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertTrue(model_runtime._cached_fit_is_valid(run_dir, fit_key))
            posterior.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                model_runtime._cached_fit_is_valid(run_dir, fit_key)

    def test_extracted_data_math_matches_notebook_fixture(self) -> None:
        notebook_path = PYMC_CODE_DIR / "notebooks/02_mmm_pipeline_specific_TC5_offline_fixed_tier_scaling_2026Q1.ipynb"
        if not notebook_path.exists():
            self.skipTest("Reference notebook fixture is not included in the source checkout")
        notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        source = "".join(notebook["cells"][21]["source"])
        namespace = {
            "np": np,
            "pd": pd,
            "MEDIA_SCALING_MODE": "tier_p95_shrunk",
            "MEDIA_GEO_SCALE_MIN_NZ": 8,
            "MEDIA_GEO_SCALE_FULL_NZ": 30,
            "MEDIA_GEO_SCALE_RATIO_FLOOR": 0.25,
            "MEDIA_GEO_SCALE_RATIO_CEIL": 4.0,
            "MEDIA_TIER_COUNT": 3,
            "MEDIA_TIER_SCALE_MIN_NZ": 20,
            "MEDIA_TIER_SCALE_FULL_NZ": 120,
            "MEDIA_TIER_SCALE_RATIO_FLOOR": 0.5,
            "MEDIA_TIER_SCALE_RATIO_CEIL": 2.0,
            "MARKET_SIZE_TIER_COL": "market_size_tier",
            "MARKET_SIZE_TIER_FALLBACK": "population_k_qcut",
            "MEDIA_RESPONSE_MODE": "tight",
            "CENTER_MEDIA_RESPONSE": False,
            "BETA_STRUCTURE_BY_TARGET": dict(fit.BETA_STRUCTURE_BY_TARGET),
            "ALLOWED_BETA_STRUCTURES": set(fit.ALLOWED_BETA_STRUCTURES),
            "BASELINE_STRUCTURE": "geo",
            "ERROR_STRUCTURE": "global",
            "TC5_OFFLINE_SPECIFIC_POLICY_ENABLED": False,
        }
        exec(compile(source, str(notebook_path), "exec"), namespace)

        dates = pd.date_range("2025-01-01", periods=40, freq="D")
        rows = []
        for geo_index, geo in enumerate(["G1", "G2"]):
            for day_index, date in enumerate(dates):
                spend = float(100 + day_index * 5 + geo_index * 10)
                rows.append(
                    {
                        "date": date,
                        "geo_label": geo,
                        "network": "ТСХ",
                        "channel": "Онлайн",
                        "population_k": 100.0 + geo_index * 20,
                        "market_size_tier": "small" if geo_index == 0 else "large",
                        "anomaly_period_jul2025": 0,
                        "turnover_per_user": 1500.0 + day_index + geo_index * 20,
                        "orders_per_user": 1.1 + day_index / 1000,
                        "avg_basket": 1400.0 + day_index,
                        "spend_Радио": spend,
                        "ruonia_change": day_index / 100.0,
                    }
                )
        frame = pd.DataFrame(rows)
        priors = {
            "ТСХ/Онлайн": {
                "turnover_per_user": {
                    "spend_Радио": {
                        "decay": 0.5,
                        "beta_FE": 0.01,
                        "beta_SE": 0.001,
                    }
                }
            }
        }

        old_grouping = fit.MEDIA_GROUPING_ENABLED
        old_panel = fit.panel
        old_spend = fit.SPEND_ACTIVE_BASE
        old_tc5 = fit.TC5_OFFLINE_SPECIFIC_POLICY_ENABLED
        try:
            fit.MEDIA_GROUPING_ENABLED = False
            fit.panel = frame
            fit.SPEND_ACTIVE_BASE = ["spend_Радио"]
            fit.TC5_OFFLINE_SPECIFIC_POLICY_ENABLED = False
            _, coords_script, data_script = fit.build_single_target_data(
                frame,
                "ТСХ",
                "Онлайн",
                "turnover_per_user",
                ["spend_Радио"],
                ["ruonia_change"],
                priors,
                14,
            )
            _, coords_notebook, data_notebook = namespace["build_single_target_data"](
                frame,
                "ТСХ",
                "Онлайн",
                "turnover_per_user",
                ["spend_Радио"],
                ["ruonia_change"],
                priors,
                14,
            )
        finally:
            fit.MEDIA_GROUPING_ENABLED = old_grouping
            fit.panel = old_panel
            fit.SPEND_ACTIVE_BASE = old_spend
            fit.TC5_OFFLINE_SPECIFIC_POLICY_ENABLED = old_tc5

        self.assertEqual(set(coords_script), set(coords_notebook))
        for name in coords_script:
            np.testing.assert_array_equal(np.asarray(coords_script[name]), np.asarray(coords_notebook[name]))
        for name in ["Y", "X_spend", "X_lagged", "X_ctrl", "ctrl_mean", "ctrl_std", "x_scale"]:
            np.testing.assert_allclose(data_script[name], data_notebook[name], rtol=0, atol=0)
        self.assertEqual(data_script["beta_structure"], data_notebook["beta_structure"])


if __name__ == "__main__":
    unittest.main()
