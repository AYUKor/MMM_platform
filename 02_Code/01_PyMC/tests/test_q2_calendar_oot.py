"""Регрессии Q2.2: synthetic fixtures, без sampling и изменения панелей."""
from __future__ import annotations

import sys
import tempfile
import unittest
import json
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mmm_core import fit
from mmm_core.media_history import calendar_lags, load_media_history, scaled_history_lags
from mmm_core.validation import OOTSplit, build_oot_feature_snapshot, evaluate_predictive_oot, run_predictive_oot, _score_fit_snapshot
from mmm_core.validation import build_model_side_historical_replay_rows, _canonical_hash
from mmm_core.forecast_engine import build_historical_forecast_replay_rows


class CalendarTests(unittest.TestCase):
    def test_dates_not_row_positions_and_no_future_or_geo_leakage(self):
        dates = pd.to_datetime(['2026-04-30', '2026-05-02', '2026-05-02'])
        values = np.array([[10.], [100.], [900.]])
        result = calendar_lags(values, np.array([0, 0, 1]), dates, 14)
        self.assertEqual(result[1, 1, 0], 0.)
        self.assertEqual(result[2, 1, 0], 10.)
        self.assertEqual(result[2, 2, 0], 0.)
        self.assertEqual(result[1:, 0, :].sum(), 0.)

    def test_contiguous_dates_preserve_accepted_tensor(self):
        x = np.arange(12.).reshape(6, 2)
        g = np.array([0, 0, 0, 1, 1, 1])
        dates = pd.to_datetime(['2026-01-01', '2026-01-02', '2026-01-03'] * 2)
        np.testing.assert_array_equal(fit.make_geo_lagged_tensor(x, g, 14), calendar_lags(x, g, dates, 14))

    def test_missing_target_does_not_remove_april_history_and_horizon(self):
        rows = pd.DataFrame({'date': pd.to_datetime(['2026-05-01', '2026-05-15']), 'geo_label': 'YNAO',
                             'network': 'ТС5', 'channel': 'Оффлайн', 'population_k': 100., 'spend_OOH_Total': 0.})
        history = pd.DataFrame({'date': pd.to_datetime(['2026-04-30']), 'geo_label': 'YNAO',
                                'network': 'ТС5', 'channel': 'Оффлайн', 'spend_OOH_Total': 1000.})
        result = scaled_history_lags(rows, history, ['spend_OOH_Total'], ['YNAO'], np.array([[2.]]), 14)
        self.assertEqual(result[1, 0, 0], 5.)
        self.assertEqual(result[:, 1, :].sum(), 0.)
        weights = .5 ** np.arange(15)
        weights /= weights.sum()
        self.assertAlmostEqual(float((result[:, 0, 0] * weights).sum()), 5 * weights[1])

    def test_empirical_prior_adstock_keeps_filtered_spend_and_elapsed_time(self):
        history = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=3), 'geo_label': 'G', 'spend_R': [8., 4., 0.]})
        observed = history.iloc[[0, 2]].copy()
        result = fit.adstock_panel_inplace(observed, 'spend_R', .5, history)
        np.testing.assert_allclose(result.spend_R_ads, [8., 4.])

    def test_duplicate_calendar_keys_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            calendar_lags(np.ones((2, 1)), np.array([0, 0]), ['2026-01-01'] * 2, 14)

    def test_no_placements_in_known_complete_ledger_is_zero_exposure(self):
        rows = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=3), 'geo_label': 'G', 'spend_R': 0.})
        history = rows.iloc[:0].copy()
        result = fit.adstock_panel_inplace(rows, 'spend_R', .5, history)
        np.testing.assert_array_equal(result.spend_R_ads, np.zeros(3))

    def test_ledger_keeps_distinct_placements_and_grouped_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'ledger.parquet'
            pd.DataFrame({'date': pd.to_datetime(['2026-04-30'] * 3), 'geo_label': 'G', 'network': 'N',
                          'channel': 'C', 'channel_type': ['OOH', 'OOH', 'OOH'], 'budget': [10., 20., 30.]}).to_parquet(source)
            history = load_media_history(source, '2026-04-01', '2026-05-31', {'N/C': {'spend_OOH_Total': ['spend_OOH']}})
            self.assertEqual(history.spend_OOH.iloc[0], 60.)
            self.assertEqual(history.spend_OOH_Total.iloc[0], 60.)

    def test_mroas_perturbs_missing_target_history_too(self):
        data = {'l_max': 14, 'lag_mode': 'calendar_days_v1', 'X_spend': np.array([[2.], [0.]]),
                'X_lagged': np.ones((15, 2, 1)), 'geo_idx': np.array([0, 0])}
        base, _ = fit._x_ads_sat_np(data, np.array([.5]), np.array([1.]))
        perturbed, _ = fit._x_ads_sat_np(data, np.array([.5]), np.array([1.]), X=data['X_spend'] * 1.01)
        np.testing.assert_allclose(perturbed, base * 1.01)

    def test_oot_scorer_uses_calendar_history_with_frozen_scaling(self):
        snapshot = pd.DataFrame({'date': pd.to_datetime(['2026-06-01', '2026-06-03']),
                                 'geo_label': 'G', 'network': 'N', 'channel': 'C',
                                 'population_k': 100., 'market_size_tier': 'small', 'spend_OOH_Total': 0.})
        history = snapshot.iloc[[0]].copy()
        history['date'] = pd.Timestamp('2026-05-31')
        history['spend_OOH_Total'] = 100.
        transform = {'fit_key': 'N/C::turnover_per_user', 'geos': ['G'], 'spend_active': ['spend_OOH_Total'],
                     'controls': [], 'x_scale_geo': [[1.]], 'geo_tier_idx': [0], 'l_max': 14,
                     'lag_mode': 'calendar_days_v1', 'y_scaling': 'p95abs', 'y_scale': 1.}
        posterior = {'arrays': {'alpha': (np.array([[.5]]), []), 'lam': (np.array([[1.]]), []),
                                'beta': (np.array([[1.]]), ['channel']), 'tau_g': (np.array([[0.]]), []),
                                'gamma': (None, []), 'sigma': (np.array([0.]), []), 'sigma_tier': (None, [])}}
        _, draws = _score_fit_snapshot(snapshot, transform, posterior, OOTSplit('2026-05-31', '2026-06-01', '2026-06-30'), seed=42, media_history=history)
        z = sum(.5**i for i in range(15))
        np.testing.assert_allclose(draws[:, 0], np.tanh(np.array([.5, .5**3]) / z / 2))

    def test_independent_replay_kernels_agree_with_missing_target_day(self):
        import arviz as az
        import xarray as xr
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = 'N/C::turnover_per_user'
            safe = fit._safe_fit_key(key)
            panel = pd.DataFrame({'date': pd.to_datetime(['2026-05-01', '2026-05-03']), 'geo_label': 'G',
                                  'network': 'N', 'channel': 'C', 'population_k': 100., 'market_size_tier': 'small',
                                  'spend_OOH_Total': 0., 'unique_users': 100, 'orders_cnt': 80})
            source = root / 'history.parquet'
            pd.DataFrame({'date': pd.to_datetime(['2026-04-30', '2026-05-02']), 'geo_label': 'G', 'network': 'N',
                          'channel': 'C', 'channel_type': 'OOH', 'budget': [100., 200.]}).to_parquet(source)
            config = {'lag_mode': 'calendar_days_v1', 'train_start': '2026-05-01', 'train_end': '2026-05-03',
                      'media_history': {'path': str(source), 'sha256': fit.sha256_file(source)},
                      'media_grouping_config': {'N/C': {'spend_OOH_Total': ['spend_OOH']}}}
            (root / 'run_config.json').write_text(json.dumps(config))
            transform = {'fit_key': key, 'channels': ['OOH_Total'], 'spend_active': ['spend_OOH_Total'],
                         'geos': ['G'], 'geo_tier_idx': [0], 'x_scale_geo': [[1.]], 'l_max': 14,
                         'lag_mode': 'calendar_days_v1', 'y_scale': 1.}
            transform['transform_sha256'] = _canonical_hash(transform)
            (root / f'fit_transform_{safe}.json').write_text(json.dumps(transform))
            ds = xr.Dataset({name: (['chain', 'draw', 'channel'], np.array([[[value]]]))
                             for name, value in [('alpha', .5), ('lam', 1.), ('beta', 2.)]},
                            coords={'chain': [0], 'draw': [0], 'channel': ['OOH_Total']})
            posterior_file = f'posterior_{safe}.nc'
            az.InferenceData(posterior=ds).to_netcdf(root / posterior_file)
            index = panel[['date', 'geo_label', 'network', 'channel']].assign(fit_key=key, row_position=[0, 1])
            engine = SimpleNamespace(run_dir=root, metadata={'fits': {key: {'posterior_file': posterior_file}}},
                                     _x_scale=lambda *args: 1.)
            reference = build_model_side_historical_replay_rows(root, panel, index, [key], [(0, 0)])
            serving = build_historical_forecast_replay_rows(engine, panel, index, [(0, 0)])
            self.assertGreater(reference.effect_value.iloc[0], 0.)
            np.testing.assert_allclose(reference.effect_value, serving.effect_value, rtol=1e-12)


class ObservedOOTTests(unittest.TestCase):
    @staticmethod
    def fixture():
        frame = pd.DataFrame({'date': pd.date_range('2026-05-18', '2026-06-30'), 'geo_label': 'KNOWN',
                              'network': 'ТС5', 'channel': 'Оффлайн', 'population_k': 100.,
                              'market_size_tier': 'small', 'spend_OOH_Total': 1.,
                              'turnover_per_user': 999., 'turnover_per_user_observed': 10.,
                              'turnover_per_user_observed_valid': True,
                              'avg_basket': 888., 'avg_basket_observed': 20., 'avg_basket_observed_valid': True})
        transform = {'fit_key': 'ТС5/Оффлайн::turnover_per_user', 'geos': ['KNOWN'], 'spend_active': ['spend_OOH_Total'], 'controls': []}
        return frame, transform, OOTSplit('2026-05-31', '2026-06-01', '2026-06-30')

    def test_observed_values_and_individual_target_masks(self):
        frame, transform, split = self.fixture()
        frame.loc[frame.date.eq('2026-06-29'), ['turnover_per_user_observed', 'turnover_per_user_observed_valid']] = [np.nan, False]
        snapshot, outcomes = build_oot_feature_snapshot(frame, transform, split)
        self.assertEqual(len(snapshot), 44)
        self.assertEqual(outcomes.observed_valid.sum(), 29)
        self.assertTrue(outcomes.loc[outcomes.observed_valid, 'turnover_per_user'].eq(10.).all())
        self.assertFalse(any('observed' in c for c in snapshot))
        transform['fit_key'] = 'ТС5/Оффлайн::avg_basket'
        _, basket = build_oot_feature_snapshot(frame, transform, split)
        self.assertEqual(basket.observed_valid.sum(), 30)

    def test_unknown_babushkin_is_reported_not_fabricated_or_development_seen(self):
        frame, transform, split = self.fixture()
        new = frame[frame.date.ge('2026-06-29')].assign(geo_label='БАБУШКИН')
        snapshot, outcomes = build_oot_feature_snapshot(pd.concat([frame, new]), transform, split)
        coverage = snapshot.attrs['geo_coverage']
        self.assertEqual(coverage['unknown_geo_rows'], 2)
        self.assertEqual(coverage['scored_rows_all'], 32)
        self.assertEqual(coverage['scored_rows_known'], 30)
        self.assertEqual(len(coverage['excluded_observations']), 2)
        self.assertEqual(set(outcomes.geo_label), {'KNOWN'})
        self.assertFalse(split.development_seen)

    def test_missing_observed_provenance_is_not_silently_repaired(self):
        frame, transform, split = self.fixture()
        with self.assertRaisesRegex(ValueError, 'Observed OOT provenance'):
            build_oot_feature_snapshot(frame.drop(columns='turnover_per_user_observed'), transform, split)

    def test_metrics_align_draws_by_prediction_key_and_exclude_invalid(self):
        dates = pd.date_range('2026-06-01', periods=3)
        predictions = pd.DataFrame({'date': dates, 'geo_label': 'G', 'mean': [10., 999., 30.],
                                    'p05': [9., 998., 29.], 'p95': [11., 1000., 31.]})
        outcomes = pd.DataFrame({'date': dates[::-1], 'geo_label': 'G', 'target': [30., np.nan, 10.], 'observed_valid': [True, False, True]})
        training = pd.DataFrame({'date': pd.date_range('2026-05-01', periods=3), 'geo_label': 'G', 'target': [1., 2., 3.]})
        metrics = evaluate_predictive_oot(predictions, np.repeat(np.array([[10.], [999.], [30.]]), 5, axis=1), outcomes, training, target='target')
        self.assertEqual(metrics['rows'], 2)
        self.assertEqual(metrics['prediction_rows'], 3)
        self.assertEqual(metrics['excluded_invalid_observed_rows'], 1)
        self.assertEqual(metrics['mae'], 0.)
        self.assertEqual(metrics['crps'], 0.)

    def test_partial_geo_quality_cannot_silently_activate_whole_model(self):
        # Synthetic deterministic predictions isolate the orchestration/gate contract.
        def transform(_run, fit_key):
            return {'fit_key': fit_key, 'geos': ['KNOWN'], 'spend_active': ['spend_OOH_Total'], 'controls': []}

        def score(snapshot, transform, posterior, split, **kwargs):
            rows = snapshot.loc[snapshot.date.ge(split.oot_start), ['date', 'geo_label']].reset_index(drop=True)
            y = rows.date.dt.day.to_numpy(float) + 100.
            rows['mean'], rows['p05'], rows['p95'] = y, y - 1, y + 1
            rows.loc[:2, 'p05'] += 10
            rows.loc[:2, 'p95'] += 10
            return rows, np.repeat(y[:, None], 3, axis=1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame, _, split = self.fixture()
            frames = []
            for segment in fit.EXPECTED_SEGMENTS:
                net, ch = segment.split('/')
                sub = frame.assign(network=net, channel=ch)
                for target in fit.EXPECTED_TARGETS:
                    sub[target] = sub.date.dt.day + 100.
                    sub[target + '_observed'] = sub[target]
                    sub[target + '_observed_valid'] = True
                frames.append(sub)
            panel = pd.concat(frames, ignore_index=True)
            invalid = panel.network.eq('ТС5') & panel.channel.eq('Онлайн') & panel.date.eq('2026-06-05')
            panel.loc[invalid, 'turnover_per_user_observed_valid'] = False
            new = panel[panel.network.eq('ТС5') & panel.channel.eq('Оффлайн') & panel.date.ge('2026-06-29')].assign(geo_label='БАБУШКИН')
            panel = pd.concat([panel, new], ignore_index=True)
            panel.to_parquet(root / 'panel.parquet')
            (root / 'run_config.json').write_text(json.dumps({'expected_fit_keys': fit.EXPECTED_FIT_KEYS, 'train_start': '2026-05-18', 'train_end': '2026-05-31', 'panel_path': str(root / 'panel.parquet')}))
            (root / 'coverage.json').write_text('{}')
            # Written verdicts bind to a built package, so the fixture needs a package fingerprint.
            (root / 'model_manifest.json').write_text(json.dumps({'package_input_fingerprint': 'f' * 64}))
            with patch('mmm_core.validation.required_oot_inputs', return_value=[]), patch('mmm_core.validation.evaluate_oot_input_coverage', return_value={'status': 'passed'}), patch('mmm_core.validation._load_transform', side_effect=transform), patch('mmm_core.validation._posterior_samples', return_value={}), patch('mmm_core.validation._score_fit_snapshot', side_effect=score):
                verdict = run_predictive_oot(root, root / 'panel.parquet', root / 'coverage.json', split, write=True)
            self.assertEqual(verdict['fits_n'], 12)
            self.assertTrue(verdict['turnover_required_pass'])
            self.assertFalse(verdict['activation_eligible'])
            self.assertEqual(verdict['status'], 'partial_coverage_not_activation_evidence')
            self.assertEqual(len(verdict['excluded_observations']), 7)
            self.assertTrue((root / 'validation/oot/excluded_observations.csv').exists())
            self.assertEqual(json.loads((root / 'oot_validation.json').read_text())['status'], verdict['status'])


if __name__ == '__main__':
    unittest.main()
