"""Campaign reasons: the split of a campaign effect and the rule file. Synthetic arrays only, no real model files."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

PYMC_CODE_DIR = Path(__file__).resolve().parents[1]
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core import campaign_catalog as cc  # noqa: E402
from mmm_core import campaign_reasons as cre  # noqa: E402
from mmm_core import weekly_joint as wj  # noqa: E402

S, C = len(wj.SEGMENTS), len(wj.CHANNELS)


def synthetic(seed: int = 7, tail: int = 0):
    """Three ad units of one segment, 30 weeks, two campaigns that share unit 1 in weeks 10-14."""
    rng = np.random.default_rng(seed)
    A, W, L = 3, 30, 4
    dn = [np.zeros((2, W + tail, C)), np.zeros((2, W + tail, C))]
    dn[0][:, 8:15, 4] = rng.uniform(0.5, 2.0, (2, 7))            # campaign 0: digital, units 0 and 1
    dn[1][:, 10:20, 3] = rng.uniform(0.2, 1.0, (2, 10))          # campaign 1: outdoor, units 1 and 2
    dn[1][0, 10:14, 4] = 0.8                                     # and some digital in unit 1
    base = rng.uniform(0.0, 0.3, (A, W + tail, C))
    sn = base.copy()
    sn[[0, 1]] += dn[0]
    sn[[1, 2]] += dn[1]
    arr = dict(spend_norm=sn[:, :W, :], seg_a=np.ones(A, int), tier_a=np.zeros(A, int), local_c=np.ones(C),
               geo_ratio_a=np.ones(A), tau_a=np.full(A, 50.0), m_ref_a=np.ones((A, C)), mask_a=np.ones((A, C)),
               roas_scale='equal')
    draw = dict(alpha=np.full(C, 0.5), lam=np.full(C, 0.8), logR_orders=np.full(C, -1.0), sig_seg=0.1,
                z_seg=np.zeros((S, C)), sig_tier=0.1, z_tier=np.zeros((3, C)), sig_unit=0.1,
                z_unit=rng.normal(0, 1, (A, C)), R_check=np.full((S, C), 0.2))
    a_i = np.repeat(np.arange(A), W + tail)
    w_i = np.tile(np.arange(W + tail), A)
    rows = lambda us: np.concatenate([np.where(a_i == u)[0] for u in us])
    items = []
    for k, us in enumerate(([0, 1], [1, 2])):
        r = rows(us)
        loc = {u: i for i, u in enumerate(us)}
        items.append(dict(units=np.array(us), dn=dn[k], rows=r, loc_rows=np.array([loc[x] for x in a_i[r]]),
                          zone=r, zone_buyers=1.0, zone_orders=1.0))
    n_rows = len(a_i)
    camp = SimpleNamespace(n=2, items=items, T=rng.uniform(1e5, 2e5, n_rows), O=np.full(n_rows, 100.0),
                           B=np.full(n_rows, 80.0), a_i=a_i, w_i=w_i, s_i=np.ones(n_rows, int),
                           n_fit=A * W if tail else n_rows, n_tail=tail, sn_tail=sn[:, W:, :], L=L, pad=False)
    return camp, arr, draw


class DecomposeTests(unittest.TestCase):
    def test_adstock_split_matches_the_catalog_function(self) -> None:
        camp, arr, draw = synthetic()
        for pad in (False, True):
            x = cre.adstock_np(arr['spend_norm'], draw['alpha'], camp.L, pad)
            s = cc.adstock_sat_np(arr['spend_norm'], draw['alpha'], draw['lam'], camp.L, pad)
            np.testing.assert_allclose(1 - np.exp(-x / draw['lam']), s, rtol=0, atol=1e-12)

    def test_kept_effect_is_the_catalog_effect_and_the_order_holds(self) -> None:
        for tail in (0, 3):
            camp, arr, draw = synthetic(tail=tail)
            ref = cc.Campaigns.effects(camp, arr, draw)
            got = cre.decompose(camp, arr, draw)
            np.testing.assert_allclose(got['loo'], ref['turn'], rtol=1e-12)
            self.assertTrue(np.all(got['loo'] <= got['alone'] * (1 + 1e-12)))
            self.assertTrue(np.all(got['alone'] <= got['lin'] * (1 + 1e-12)))
            self.assertTrue(np.all(got['lin'] > 0))
            # the shared unit costs campaign 1 some effect: its kept effect is below its alone effect
            self.assertLess(got['loo'][1], got['alone'][1])
            if tail:
                self.assertGreaterEqual(got['loo_tail'].min(), 0.0)
            else:
                self.assertEqual(got['loo_tail'].tolist(), [0.0, 0.0])
            for k in range(2):
                np.testing.assert_allclose(got['units'][k].sum(1), [got['lin'][k], got['alone'][k], got['loo'][k]])

    def test_factors_add_up(self) -> None:
        lin = np.array([10.0, 12.0, 8.0])
        alone = np.array([6.0, 7.0, 5.0])
        loo = np.array([4.0, 5.0, 3.0])
        f = cre.factors(budget=2.0, seen=1.9, lin=lin, alone=alone, loo=loo, loo_tail=np.zeros(3), expected_lin=4.0)
        self.assertAlmostEqual(f['kept_share'] + f['own_loss_share'] + f['overlap_loss_share'], 1.0, places=12)
        self.assertAlmostEqual(f['unseen_share'], 0.05)
        self.assertAlmostEqual(f['first_ruble_roas'], 10.0 / 1.9)
        self.assertAlmostEqual(f['geo_factor'], (10.0 / 1.9) / (4.0 / 1.9))


    def test_split_percents_add_up_to_one_hundred(self) -> None:
        self.assertEqual(cre.split_percents(0.335, 0.335, 0.33), (34, 33, 33))
        self.assertEqual(cre.split_percents(0.201, 0.625819, 0.173181), (20, 63, 17))
        self.assertEqual(cre.split_percents(0.125, 0.125, 0.75), (13, 12, 75))
        rng = np.random.default_rng(3)
        for parts in rng.dirichlet([1.0, 1.0, 1.0], 500):
            self.assertEqual(sum(cre.split_percents(*parts)), 100)


class RuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = cre.load_rules()

    def factors(self, **over):
        f = dict(kept_share=0.4, own_loss_share=0.45, overlap_loss_share=0.15, saturation_loss_share=0.6,
                 tail_share=0.0, unseen_share=0.0, first_ruble_roas=3.0, typical_first_ruble_roas=3.0, geo_factor=1.0,
                 geo_weight=0.0, potential_turnover_rub=1e6)
        f.update(over)
        return f

    def facts(self, **over):
        f = dict(n_geo=3, top_geo='КАЗАНЬ', top_geo_share=0.4, density_regional_rub=100.0,
                 density_national_rub=float('nan'), weeks_n=6, burn_2w_share=0.4, others_rub=0.0,
                 neighbor_number=None, neighbor_rub=0.0)
        f.update(over)
        return f

    def catalog(self, rows):
        """rows: (main channel, nationwide, factors overrides, own cities[, facts overrides])."""
        entries = {}
        for i, row in enumerate(rows, 1):
            channel, nationwide, over, cities = row[:4]
            facts = self.facts(**(row[4] if len(row) > 4 else {}))
            if nationwide:
                facts.update(n_geo=0, top_geo='', top_geo_share=float('nan'), density_regional_rub=float('nan'),
                             density_national_rub=facts['density_national_rub']
                             if facts['density_national_rub'] == facts['density_national_rub'] else 100.0)
            entries[str(i)] = dict(number=i, modeled=True, factors=self.factors(**over), facts=facts,
                                   main_channel=channel, main_nationwide=nationwide, own_loss_cities=cities,
                                   overlap_loss_cities=[])
        return entries

    def neutral(self, channel, nationwide=False, n=5):
        return [(channel, nationwide, dict(kept_share=0.5, own_loss_share=0.2, overlap_loss_share=0.3,
                                           saturation_loss_share=0.5), []) for _ in range(n)]

    def label(self, rows, tail_weeks=7, names=None):
        entries = self.catalog(rows)
        norms = cre.label_catalog(entries, self.rules, tail_weeks=tail_weeks, names=names)
        return entries, norms

    def test_default_rule_file_is_valid_and_versioned(self) -> None:
        self.assertEqual(self.rules['contract_name'], 'campaign_reason_rules')
        self.assertTrue(self.rules['version'].startswith('campaign_reasons_v3'))
        self.assertEqual(self.rules['max_reasons'], 3)
        self.assertEqual(self.rules['norms'], {'group_by': 'main_channel', 'statistic': 'median', 'min_group': 5})
        self.assertEqual(set(self.rules['channel_phrases']),
                         {'Цифровая реклама', 'Наружная реклама', 'Indoor', 'Радио', 'Национальное ТВ', 'Региональное ТВ'})
        self.assertNotIn('fallback', self.rules)  # no general sentence: nothing specific, no words
        self.assertEqual(set(self.rules['notes']), {'own_note', 'overlap_note'})

    def test_times_and_plural_words(self) -> None:
        self.assertEqual([cre._times(x) for x in (19.3, 3.04, 2.46, 12.0, 22.4, 1.26, 21.0, 2.0)],
                         ['19 раз', '3 раза', '2,5 раза', '12 раз', '22 раза', '1,3 раза', '21 раз', '2 раза'])
        self.assertEqual([cre._plural(v, 'неделю', 'недели', 'недель') for v in (1, 2, 5, 11, 21, 7)],
                         ['неделю', 'недели', 'недель', 'недель', 'неделю', 'недель'])

    def test_typical_campaign_gets_no_words(self) -> None:
        entries, _ = self.label(self.neutral('Региональное ТВ', n=6))
        for entry in entries.values():
            self.assertEqual(entry['reasons'], [])

    def test_own_saturation_with_the_campaign_fact(self) -> None:
        rows = self.neutral('Региональное ТВ') + [('Региональное ТВ', False, dict(
            kept_share=0.2, own_loss_share=0.55, overlap_loss_share=0.25, saturation_loss_share=0.8), ['Москва'],
            dict(n_geo=1, top_geo='ЕКАТЕРИНБУРГ', top_geo_share=1.0, density_regional_rub=420.0))]
        entries, norms = self.label(rows)
        self.assertEqual(norms, [dict(main_channel='Региональное ТВ', campaigns_n=6, own_norm=1,
                                      norm_group='у кампаний на региональном ТВ', norm_kept_share=0.5,
                                      norm_own_loss_share=0.2, norm_overlap_loss_share=0.3, norm_density_rub=100.0)])
        # one short phrase, one fact (the first that holds): the shares are on the bar
        self.assertEqual(entries['6']['reasons'], [dict(
            code='own_saturation', weight=entries['6']['reasons'][0]['weight'],
            display_text='Достигнут предел насыщения: весь бюджет в одном месте (Екатеринбург).')])

    def test_own_saturation_without_facts_is_said_plainly(self) -> None:
        rows = self.neutral('Наружная реклама') + [('Наружная реклама', False, dict(
            kept_share=0.2, own_loss_share=0.5, overlap_loss_share=0.3, saturation_loss_share=0.8),
            ['Краснодарский край (кроме Городов)'])]
        entries, _ = self.label(rows)
        self.assertEqual(entries['6']['own_loss_cities'], ['Краснодарский край (кроме городов)'])
        self.assertEqual(entries['6']['reasons'][0]['display_text'], 'Достигнут предел насыщения.')

    def test_dense_money_before_a_large_place_and_fast_spend(self) -> None:
        rows = self.neutral('Радио') + [('Радио', False, dict(
            kept_share=0.2, own_loss_share=0.5, overlap_loss_share=0.3, saturation_loss_share=0.8), [],
            dict(n_geo=4, top_geo='МОСКВА', top_geo_share=0.54, weeks_n=4, burn_2w_share=0.67))]
        entries, _ = self.label(rows)
        self.assertEqual(entries['6']['reasons'][0]['display_text'],
                         'Достигнут предел насыщения: 54% бюджета в одном месте (Москва).')
        rows[-1][4].update(density_regional_rub=420.0)
        entries, _ = self.label(rows)
        self.assertEqual(entries['6']['reasons'][0]['display_text'],
                         'Достигнут предел насыщения: денег на город в неделю в 4,2 раза больше обычного.')
        rows[-1][4].update(density_regional_rub=100.0, top_geo_share=0.3)
        entries, _ = self.label(rows)
        self.assertEqual(entries['6']['reasons'][0]['display_text'],
                         'Достигнут предел насыщения: 67% бюджета за две недели.')

    def test_nationwide_campaign_compares_money_per_week(self) -> None:
        rows = self.neutral('Национальное ТВ', True) + [('Национальное ТВ', True, dict(
            kept_share=0.2, own_loss_share=0.5, overlap_loss_share=0.3, saturation_loss_share=0.8), ['Москва'],
            dict(density_national_rub=500.0))]
        entries, _ = self.label(rows)
        first = entries['6']['reasons'][0]
        self.assertEqual(first['code'], 'own_saturation')
        self.assertEqual(first['display_text'], 'Достигнут предел насыщения: денег в неделю в 5 раз больше обычного.')

    def test_overlap_only_above_the_channel_norm_with_the_neighbour(self) -> None:
        # most Indoor campaigns lose 80% to other ads: for Indoor that is the norm, not a reason
        typical = self.neutral('Indoor', n=2) + [('Indoor', False, dict(
            kept_share=0.08, own_loss_share=0.12, overlap_loss_share=0.8, saturation_loss_share=0.92), [])] * 4
        entries, _ = self.label(typical)
        self.assertNotIn('overlap', [r['code'] for e in entries.values() for r in e['reasons']])
        high = self.neutral('Радио') + [('Радио', False, dict(
            kept_share=0.25, own_loss_share=0.2, overlap_loss_share=0.55, saturation_loss_share=0.75), [],
            dict(neighbor_number=2, neighbor_rub=12_345_678.0))]
        entries, _ = self.label(high, names={'2': 'Промо 2025'})
        reason = entries['6']['reasons'][0]
        self.assertEqual(reason['code'], 'overlap')
        self.assertEqual(reason['display_text'],
                         'Спрос уже насыщен другой рекламой: больше всего «Промо 2025» (12,3 млн ₽).')
        entries, _ = self.label(high)  # no name for the neighbour: no neighbour in the text
        self.assertEqual(entries['6']['reasons'][0]['display_text'], 'Спрос уже насыщен другой рекламой.')

    def test_money_spread_thin_and_tiny_shares(self) -> None:
        rows = self.neutral('Наружная реклама') + [('Наружная реклама', False, dict(
            kept_share=0.65, own_loss_share=0.05, overlap_loss_share=0.3, saturation_loss_share=0.35), [],
            dict(density_regional_rub=10.0))]
        entries, _ = self.label(rows)
        self.assertEqual([r['display_text'] for r in entries['6']['reasons']],
                         ['Потерь меньше обычного: насыщения и другой рекламы меньше, чем у похожих кампаний.',
                          'Насыщение ниже обычного: денег на город в неделю в 10 раз меньше.'])
        digital = self.neutral('Цифровая реклама') + [('Цифровая реклама', False, dict(
            kept_share=0.6, own_loss_share=0.05, overlap_loss_share=0.35, saturation_loss_share=0.4), [],
            dict(density_regional_rub=10.0))]
        entries, _ = self.label(digital)
        self.assertEqual(entries['6']['reasons'], [])  # digital money per city says little: no comparison
        thin = self.neutral('Национальное ТВ', True) + [('Национальное ТВ', True, dict(
            kept_share=0.647, own_loss_share=0.003, overlap_loss_share=0.35, saturation_loss_share=0.353), [],
            dict(density_national_rub=10.0))]
        entries, _ = self.label(thin)
        self.assertEqual([r['display_text'] for r in entries['6']['reasons']],
                         ['Насыщение ниже обычного: денег в неделю в 10 раз меньше.'])
        self.assertEqual(cre.text_values(dict(entries['6']['factors']))['own_loss_pct'], 'меньше 1%')

    def test_low_loss_only_when_nothing_else_pulls_the_number_down(self) -> None:
        good = ('Цифровая реклама', False, dict(kept_share=0.8, own_loss_share=0.05, overlap_loss_share=0.15,
                                                saturation_loss_share=0.2), [])
        entries, _ = self.label(self.neutral('Цифровая реклама') + [good])
        self.assertEqual([r['code'] for r in entries['6']['reasons']], ['low_loss'])
        for over, code in ((dict(geo_factor=0.5, geo_weight=float(abs(np.log(0.5)))), 'weak_geo'),
                           (dict(unseen_share=0.3), 'money_outside_model')):
            entries, _ = self.label(self.neutral('Цифровая реклама') + [(*good[:2], {**good[2], **over}, [])])
            self.assertEqual([r['code'] for r in entries['6']['reasons']], [code])
        # most of the effect lost even if less than usual for the channel: not «меньше обычного»
        indoor = self.neutral('Indoor') + [('Indoor', False, dict(
            kept_share=0.45, own_loss_share=0.1, overlap_loss_share=0.45, saturation_loss_share=0.55), [])]
        entries, _ = self.label(indoor)
        self.assertNotIn('low_loss', [r['code'] for r in entries['6']['reasons']])

    def test_small_channel_is_compared_with_the_whole_catalog(self) -> None:
        rows = self.neutral('Цифровая реклама') + [('Радио', False, dict(
            kept_share=0.05, own_loss_share=0.65, overlap_loss_share=0.3, saturation_loss_share=0.95), [],
            dict(density_regional_rub=1000.0))]
        entries, norms = self.label(rows)
        radio = next(row for row in norms if row['main_channel'] == 'Радио')
        self.assertEqual((radio['own_norm'], radio['norm_group']), (0, 'у всех кампаний каталога'))
        # own loss 65% against the catalog's 20%; money density is compared only inside the same channel
        self.assertEqual(entries['6']['reasons'][0]['display_text'], 'Достигнут предел насыщения.')

    def test_saturation_first_then_special_cases_at_most_three(self) -> None:
        rows = self.neutral('Наружная реклама') + [('Наружная реклама', False, dict(
            kept_share=0.1, own_loss_share=0.4, overlap_loss_share=0.5, saturation_loss_share=0.9, unseen_share=0.4,
            tail_share=0.2, geo_factor=2.0, geo_weight=float(np.log(2.0))), ['Казань'])]
        entries, _ = self.label(rows)
        got = [r['code'] for r in entries['6']['reasons']]
        # rank 1 (saturation) by weight: overlap +0.20, own +0.20 (order breaks the tie); then the heaviest special case
        self.assertEqual(got, ['own_saturation', 'overlap', 'strong_geo'])

    def test_weak_cities_and_the_forecast_tail(self) -> None:
        rows = self.neutral('Цифровая реклама') + [('Цифровая реклама', False, dict(
            kept_share=0.5, own_loss_share=0.2, overlap_loss_share=0.3, saturation_loss_share=0.5, geo_factor=0.5,
            geo_weight=float(abs(np.log(0.5))), tail_share=0.3), [])]
        entries, _ = self.label(rows, tail_weeks=5)
        got = {r['code']: r['display_text'] for r in entries['6']['reasons']}
        self.assertEqual(got['weak_geo'],
                         'Низкая отдача: в городах и неделях кампании рубль рекламы даёт в 2 раза меньше среднего.')
        self.assertEqual(got['tail_forecast'], 'Эффект выходит за конец данных: 30% досчитано прогнозом.')

    def test_at_most_three_reasons_and_saturation_before_special_cases(self) -> None:
        rng = np.random.default_rng(11)
        rows = []
        for channel in ('Цифровая реклама', 'Наружная реклама', 'Национальное ТВ'):
            for parts in rng.dirichlet([2.0, 1.0, 2.0], 40):
                rows.append((channel, channel == 'Национальное ТВ', dict(
                    kept_share=parts[0], own_loss_share=parts[1], overlap_loss_share=parts[2],
                    saturation_loss_share=parts[1] + parts[2], geo_factor=float(rng.uniform(0.5, 2.0)),
                    unseen_share=float(rng.uniform(0, 0.1))), [], dict(density_regional_rub=float(rng.uniform(5, 500)),
                                                                       density_national_rub=float(rng.uniform(5, 500)))))
        entries, _ = self.label(rows)
        ranks = {rule['code']: rule['rank'] for rule in self.rules['rules']}
        for e in entries.values():
            got = [ranks[r['code']] for r in e['reasons']]
            self.assertLessEqual(len(got), 3)
            self.assertEqual(got, sorted(got))

    def test_ledger_facts(self) -> None:
        import pandas as pd
        rows = []

        def add(cat, date, ct, geo, b, ch='Оффлайн', action='keep'):
            rows.append(dict(cat=cat, date=pd.Timestamp(date), network='ТС5', channel=ch, channel_type=ct,
                             action=action, geo_label=geo, budget=b))
        for d, b in [('2025-03-03', 40), ('2025-03-10', 40), ('2025-03-17', 10), ('2025-03-24', 10)]:
            add(0, d, 'OOH', 'ЕКАТЕРИНБУРГ', b)
        add(1, '2025-03-11', 'OOH', 'ЕКАТЕРИНБУРГ', 30)
        add(1, '2025-03-11', 'OOH', 'МОСКВА', 70)
        add(2, '2025-03-12', 'Нац ТВ', 'РОССИЯ', 500)
        add(2, '2025-04-12', 'Нац ТВ', 'РОССИЯ', 500)
        add(3, '2025-03-04', 'OOH', 'ЕКАТЕРИНБУРГ', 99, ch='Доставка')  # another direction: not a neighbour
        add(3, '2025-03-05', 'OOH', 'ЕКАТЕРИНБУРГ', 0, ch='Оффлайн')  # no money: not a neighbour
        add(4, '2025-03-05', 'Радио', 'ЕКАТЕРИНБУРГ', 500)  # another model channel: not a neighbour
        for i in range(25):  # an agency row «РФ» spread by the template over 25 places, a little own money in Kazan
            add(5, '2025-03-05', 'Радио', f'ГОРОД {i:02d}', 4, action=cre.TEMPLATE_ACTION)
            add(6, '2025-03-05', 'Радио', f'ГОРОД {i:02d}', 1, action=cre.TEMPLATE_ACTION)
        add(5, '2025-03-05', 'Радио', 'КАЗАНЬ', 50)
        add(6, '2025-03-05', 'Радио', 'ТУЛА', 100)  # mostly for Tula: places count only Tula, share of the budget
        add(6, '2025-03-12', 'Радио', 'ТУЛА', 100)
        facts = cre.ledger_facts(pd.DataFrame(rows), 7)
        self.assertEqual(facts[0], dict(n_geo=1, top_geo='ЕКАТЕРИНБУРГ', top_geo_share=1.0, density_regional_rub=25.0,
                                        density_national_rub=facts[0]['density_national_rub'], template_share=0.0,
                                        weeks_n=4, burn_2w_share=0.8, others_rub=30.0, neighbor_cat=1, neighbor_rub=30.0))
        self.assertEqual((facts[4]['neighbor_cat'], facts[4]['others_rub']), (-1, 0.0))  # OOH of №0 is another channel
        self.assertEqual((facts[5]['n_geo'], facts[5]['template_share'], facts[5]['top_geo']), (0, 2 / 3, ''))
        self.assertEqual((facts[6]['n_geo'], facts[6]['top_geo'], facts[6]['top_geo_share'],
                          facts[6]['density_regional_rub'], facts[6]['template_share']),
                         (1, 'ТУЛА', 200 / 225, 100.0, 25 / 225))
        self.assertNotEqual(facts[5]['top_geo_share'], facts[5]['top_geo_share'])  # left empty: the template
        self.assertNotEqual(facts[5]['density_regional_rub'], facts[5]['density_regional_rub'])
        self.assertEqual((facts[1]['n_geo'], facts[1]['top_geo'], facts[1]['top_geo_share'], facts[1]['neighbor_rub']),
                         (2, 'МОСКВА', 0.7, 40.0))
        self.assertEqual((facts[2]['n_geo'], facts[2]['density_national_rub'], facts[2]['weeks_n'],
                          facts[2]['burn_2w_share'], facts[2]['neighbor_cat']), (0, 500.0, 5, 0.5, -1))
        self.assertEqual(facts[3]['neighbor_cat'], -1)
        by_number = cre.facts_by_number(facts, {0: 10, 1: 11, 2: 12, 3: 13, 4: 14, 5: 15, 6: 16})
        self.assertEqual((by_number['10']['neighbor_number'], by_number['12']['neighbor_number']), (11, None))
        self.assertNotIn('neighbor_cat', by_number['10'])

    def test_rule_file_contract_is_enforced(self) -> None:
        good = json.loads(cre.DEFAULT_RULES.read_text(encoding='utf-8'))
        breaks = [
            lambda r: r['rules'][0]['conditions'][0].update(op='=='),
            lambda r: r['rules'][0].pop('rank'),
            lambda r: r['rules'][0].update(text='Съело {unknown_value}.'),
            lambda r: r['rules'][0].update(weight=1.0),
            lambda r: r['rules'][1].update(code=r['rules'][0]['code']),
            lambda r: r.update(norms={'group_by': 'segment', 'statistic': 'median', 'min_group': 5}),
            lambda r: r.update(fallback={'code': r['rules'][0]['code'], 'text': 'x'}),
            lambda r: r['notes']['own_note'].update(max_items=0),
            lambda r: r['notes']['own_note'].update(style='list'),
            lambda r: r['notes']['own_note']['items'][0].update(text='{own_note}'),
            lambda r: r['notes']['own_note']['items'][0]['conditions'].append({'field': 'n_geo', 'op': '='}),
            lambda r: r['notes'].update(top_geo={'max_items': 1, 'items': [{'conditions': [], 'text': 'x'}]}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for i, brk in enumerate(breaks):
                bad = json.loads(json.dumps(good))
                brk(bad)
                path = Path(tmp) / f'rules_{i}.json'
                path.write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')
                with self.assertRaises(cre.CampaignReasonsError, msg=str(i)):
                    cre.load_rules(path)


class RelabelTests(unittest.TestCase):
    """14_weekly_joint_campaign_reasons.py --relabel-from: new labels on the numbers of an earlier green run."""

    def test_relabel_reuses_the_numbers_and_refuses_another_catalog(self) -> None:
        import subprocess
        from mmm_core.campaign_catalog_synthetic import write_synthetic_catalog_dir, write_synthetic_reasons_dir
        script = PYMC_CODE_DIR / '14_weekly_joint_campaign_reasons.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = write_synthetic_catalog_dir(root / 'catalog')
            first = write_synthetic_reasons_dir(root / 'first', catalog)
            run = lambda *extra: subprocess.run([sys.executable, '-I', str(script), '--catalog-dir', str(catalog),
                                                 *extra], capture_output=True, text=True)
            done = run('--relabel-from', str(first), '--out', str(root / 'second'))
            self.assertEqual(done.returncode, 0, done.stderr)
            a = json.loads((first / 'catalog_reasons.json').read_text(encoding='utf-8'))
            b = json.loads((root / 'second' / 'catalog_reasons.json').read_text(encoding='utf-8'))
            self.assertEqual(b['meta']['rules_version'], cre.load_rules()['version'])
            self.assertEqual(b['meta']['catalog_results_sha256'], a['meta']['catalog_results_sha256'])
            for number, entry in a['campaigns'].items():
                self.assertEqual(b['campaigns'][number]['reasons'], entry['reasons'])
                if entry['factors']:
                    self.assertEqual(b['campaigns'][number]['factors']['kept_share'], entry['factors']['kept_share'])
            for name in ('catalog_reasons.csv', 'checks.json', 'reason_norms.csv', 'typical_first_ruble.csv'):
                self.assertTrue((root / 'second' / name).is_file(), name)
            other = write_synthetic_catalog_dir(root / 'other', campaigns_n=13)
            refused = subprocess.run([sys.executable, '-I', str(script), '--catalog-dir', str(other), '--relabel-from',
                                      str(first), '--out', str(root / 'third')], capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('another catalog run', refused.stderr)
            missing = run('--out', str(root / 'fourth'))
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('--panel', missing.stderr)
            raw = json.loads((first / 'catalog_reasons.json').read_text(encoding='utf-8'))
            for entry in raw['campaigns'].values():
                entry.pop('facts')
            old_run = root / 'old_run'
            shutil.copytree(first, old_run)
            (old_run / 'catalog_reasons.json').write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
            no_facts = run('--relabel-from', str(old_run), '--out', str(root / 'fifth'))
            self.assertNotEqual(no_facts.returncode, 0)
            self.assertIn('pass --ledger', no_facts.stderr)


if __name__ == '__main__':
    unittest.main()
