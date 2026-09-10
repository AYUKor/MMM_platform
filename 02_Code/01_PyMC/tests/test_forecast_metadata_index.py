"""Metadata indexing must preserve lookup semantics and avoid repeated full scans."""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mmm_core.forecast_engine import ForecastEngine

class MetadataIndexTest(unittest.TestCase):
    def engine(self):
        engine = ForecastEngine.__new__(ForecastEngine)
        engine._metadata_indices = {}
        engine._source_plan = None
        engine._source_plan_index = {}
        engine.warm_start = pd.DataFrame([
            ('F','G','C','2026-01-01',1,3.),
            ('F','X','C','2026-01-01',0,999.),
            ('F','G','C','2026-01-01',2,2.),
            ('F','G','C','2026-01-01',0,4.),
        ], columns=['fit_key','geo_label','channel','as_of_date','lag','scaled_spend'], index=[7,7,1,3])
        engine.media_scales = pd.DataFrame([
            ('F','G','C','small',2.), ('F','G','C','small',4.),
            ('F','X','C','large',10.), ('F','Y','C','large',14.),
        ], columns=['fit_key','geo_label','channel','market_size_tier','x_scale'])
        return engine

    def test_warm_tail_padding_boundaries_and_source_immutability(self):
        e = self.engine(); original=e.warm_start.copy(deep=True)
        np.testing.assert_array_equal(e._warm_start_for('F','G','C',date(2026,1,2),3), [2.,3.,4.])
        np.testing.assert_array_equal(e._warm_start_for('F','G','C',date(2026,1,3),3), [3.,4.,0.])
        for start in [date(2026,1,1),date(2026,1,5)]:
            self.assertIsNone(e._warm_start_for('F','G','C',start,3))
        self.assertIsNone(e._warm_start_for('F','missing','C',date(2026,1,2),3))
        pd.testing.assert_frame_equal(e.warm_start,original)

    def test_scale_exact_tier_fit_and_missing_fallbacks(self):
        e=self.engine()
        self.assertEqual(e._x_scale('F','G','C','large'),3.)
        self.assertEqual(e._x_scale('F','missing','C','large'),12.)
        self.assertEqual(e._x_scale('F','missing','C','absent'),7.)
        self.assertEqual(e._x_scale('unknown','G','C'),1.)

    def test_index_is_built_once_and_preserves_duplicate_row_order(self):
        e=self.engine()
        with patch.object(e.warm_start,'groupby',wraps=e.warm_start.groupby) as groupby:
            for _ in range(5):
                e._warm_start_for('F','G','C',date(2026,1,2),3)
                e._warm_start_for('F','missing','C',date(2026,1,2),3)
            self.assertEqual(groupby.call_count,1)
        rows=e._metadata_rows('warm_start',('fit_key','geo_label','channel'),('F','G','C'))
        self.assertEqual(rows.index.tolist(),[7,1,3])
        self.assertEqual(rows['scaled_spend'].tolist(),[3.,2.,4.])

    def test_missing_keys_and_categorical_columns_keep_equality_semantics(self):
        e=self.engine()
        e.warm_start['geo_label']=pd.Categorical(e.warm_start['geo_label'],categories=['G','X','unused'])
        for geo in ['G','X','unused','absent']:
            expected=e.warm_start[(e.warm_start['fit_key']=='F') & (e.warm_start['geo_label']==geo) & (e.warm_start['channel']=='C')]
            actual=e._metadata_rows('warm_start',('fit_key','geo_label','channel'),('F',geo,'C'))
            pd.testing.assert_frame_equal(actual,expected)

    def test_source_plan_index_rebuilds_for_next_plan_and_preserves_order(self):
        engine = self.engine()
        columns = ['campaign_name', 'segment', 'geo', 'channel', 'budget_rub']
        first = pd.DataFrame([
            ('A', 'S', 'G', 'C', 20.), ('A', 'S', 'X', 'C', 99.),
            ('A', 'S', 'G', 'C', 10.), ('B', 'S', 'G', 'C', 77.),
        ], columns=columns, index=[4, 4, 2, 8])
        cell = first.iloc[0]
        with patch.object(first, 'groupby', wraps=first.groupby) as groupby:
            for _ in range(3):
                actual = engine._source_cell_rows(first, cell)
                pd.testing.assert_frame_equal(actual, first.iloc[[0, 2]])
            self.assertEqual(groupby.call_count, 1)
        second = first.iloc[[2, 1, 0]].copy()
        pd.testing.assert_frame_equal(engine._source_cell_rows(second, cell), second.iloc[[0, 2]])
        missing = cell.copy()
        missing['geo'] = 'missing'
        pd.testing.assert_frame_equal(engine._source_cell_rows(second, missing), second.iloc[:0])

if __name__=='__main__': unittest.main()
