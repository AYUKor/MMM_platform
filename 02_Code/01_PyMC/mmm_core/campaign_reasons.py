"""Why a past campaign got its number: an exact split of its catalog effect, and typical reasons in words.

For one posterior draw and one campaign k (same model rows, same adstock and saturation as the catalog,
mmm_core.campaign_catalog.Campaigns.effects):

- first-ruble effect  E_lin   = sum_rows T * sum_c beta_c * adstock(x_k)_c / lam_c   (the response with no saturation);
- alone effect        E_alone = sum_rows T * (1 - exp(-sum_c beta_c * sat(x_k)_c))    (only this campaign's money);
- catalog effect      E_loo   = sum_rows T * (1 - exp(-sum_c beta_c * (sat(x_all) - sat(x_all - x_k))_c)).

Saturation is concave, so E_loo <= E_alone <= E_lin in every draw (checked). The potential E_lin splits into
kept (E_loo), lost to the campaign's own saturation (E_lin - E_alone) and lost because other ads ran in the same
weeks and units (E_alone - E_loo). ROAS = first-ruble ROAS x kept share x share of money the model sees.

Nothing here changes the catalog numbers: E_loo is the catalog turnover effect (checked against the catalog run).
The reasons in words come from a versioned rule file (configs/campaign_catalog/reason_rules_v*.json), so every
future catalog build labels its campaigns the same way.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from mmm_core import campaign_catalog as cc
from mmm_core import campaign_routing as cr
from mmm_core.catalog_text import geo_display, split_percents
from mmm_core import weekly_joint as wj

RULES_DIR = Path(__file__).resolve().parents[1] / 'configs' / 'campaign_catalog'
DEFAULT_RULES = RULES_DIR / 'reason_rules_v3.json'
_OPS = {'>=': lambda a, b: a >= b, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b, '<': lambda a, b: a < b}


class CampaignReasonsError(ValueError):
    """The rule file or the inputs break the contract."""


def adstock_np(spend_norm: np.ndarray, alpha: np.ndarray, L: int, pad_steady: bool = False) -> np.ndarray:
    """The adstock part of campaign_catalog.adstock_sat_np: 1 - exp(-adstock_np / lam) equals it (checked in tests)."""
    A, W, C = spend_norm.shape
    w = alpha[None, :] ** np.arange(L)[:, None]
    w = w / w.sum(0, keepdims=True)
    head = (np.broadcast_to(spend_norm[:, :L, :].mean(1, keepdims=True), (A, L - 1, C)) if pad_steady
            else np.zeros((A, L - 1, C)))
    pad = np.concatenate([head, spend_norm], axis=1)
    x = np.zeros((A, W, C))
    for l in range(L):
        x += w[l][None, None, :] * pad[:, L - 1 - l: L - 1 - l + W, :]
    return x


def decompose(camp: cc.Campaigns, arr: dict, draw: dict, k_list: Sequence[int] | None = None) -> dict:
    """One draw: E_lin, E_alone, E_loo, the tail part of E_loo per campaign; the same three by segment x channel
    (each channel on its own) and per unit of the campaign (for the cities that lost most)."""
    S, C = len(wj.SEGMENTS), len(wj.CHANNELS)
    alpha, lam = np.asarray(draw['alpha']), np.asarray(draw['lam'])
    beta = cc.beta_draw(arr, draw)
    sn = arr['spend_norm']
    if camp.n_tail:
        sn = np.concatenate([sn, camp.sn_tail], axis=1)
    sat = cc.adstock_sat_np(sn, alpha, lam, camp.L, camp.pad)
    n = camp.n
    out = dict(lin=np.zeros(n), alone=np.zeros(n), loo=np.zeros(n), loo_tail=np.zeros(n),
               lin_sc=np.zeros((n, S, C)), alone_sc=np.zeros((n, S, C)), loo_sc=np.zeros((n, S, C)), units={})
    for k in (range(n) if k_list is None else k_list):
        it = camp.items[k]
        if it is None:
            continue
        u = it['units']
        sat_wo = cc.adstock_sat_np(np.maximum(sn[u] - it['dn'], 0.0), alpha, lam, camp.L, camp.pad)
        x_k = adstock_np(it['dn'], alpha, camp.L, camp.pad)
        r = it['rows']
        loc, wk = it['loc_rows'], camp.w_i[r]
        b = beta[0][camp.a_i[r]] + beta[1][camp.a_i[r]]                                   # [n_r, C]
        d_loo = b * (sat[u] - sat_wo)[loc, wk]
        d_alone = b * (1.0 - np.exp(-x_k / lam[None, None, :]))[loc, wk]
        d_lin = b * (x_k / lam[None, None, :])[loc, wk]
        T = camp.T[r]
        e_loo = T * (1.0 - np.exp(-d_loo.sum(1)))
        e_alone = T * (1.0 - np.exp(-d_alone.sum(1)))
        e_lin = T * d_lin.sum(1)
        out['loo'][k], out['alone'][k], out['lin'][k] = e_loo.sum(), e_alone.sum(), e_lin.sum()
        out['loo_tail'][k] = e_loo[r >= camp.n_fit].sum()
        s_r = camp.s_i[r]
        np.add.at(out['loo_sc'][k], s_r, T[:, None] * (1.0 - np.exp(-d_loo)))
        np.add.at(out['alone_sc'][k], s_r, T[:, None] * (1.0 - np.exp(-d_alone)))
        np.add.at(out['lin_sc'][k], s_r, T[:, None] * d_lin)
        per_unit = np.zeros((3, len(u)))
        np.add.at(per_unit[0], loc, e_lin)
        np.add.at(per_unit[1], loc, e_alone)
        np.add.at(per_unit[2], loc, e_loo)
        out['units'][k] = per_unit
    return out


# ---------------------------------------------------------------- rules

NORM_FIELDS = (('norm_kept_share', 'kept_share'), ('norm_own_loss_share', 'own_loss_share'),
               ('norm_overlap_loss_share', 'overlap_loss_share'))
TEXT_KEYS = ('kept_pct', 'own_loss_pct', 'overlap_loss_pct', 'norm_kept_pct', 'norm_own_pct', 'norm_overlap_pct',
             'norm_group', 'unseen_pct', 'tail_pct', 'tail_weeks', 'tail_weeks_text', 'geo_ratio', 'geo_x',
             'own_cities', 'overlap_cities', 'own_cities_note', 'overlap_cities_note', 'main_channel', 'first_ruble',
             'typical_first_ruble', 'top_geo', 'top_geo_pct', 'dense_x', 'thin_x', 'burn_pct', 'weeks_n',
             'neighbor_name', 'neighbor_mln')


def _check_text(text: Any, where: str, extra: Sequence[str] = ()) -> None:
    if not isinstance(text, str) or not text.strip():
        raise CampaignReasonsError(f'{where}: empty text')
    try:
        text.format(**{key: 'x' for key in (*TEXT_KEYS, *extra)})
    except (KeyError, IndexError, ValueError) as exc:
        raise CampaignReasonsError(f'{where}: unknown placeholder in the text ({exc})') from exc


def _check_conditions(conditions: Any, where: str, *, allow_empty: bool = False) -> None:
    if not isinstance(conditions, list) or (not conditions and not allow_empty):
        raise CampaignReasonsError(f'{where}: conditions must be a non-empty list')
    for cond in conditions:
        if not isinstance(cond, Mapping) or set(cond) != {'field', 'op', 'threshold'}:
            raise CampaignReasonsError(f'{where}: a condition needs field, op, threshold')
        if cond['op'] not in _OPS:
            raise CampaignReasonsError(f'{where}: unknown op {cond["op"]}')
        if not isinstance(cond['threshold'], (int, float)) or isinstance(cond['threshold'], bool):
            raise CampaignReasonsError(f'{where}: threshold must be a number')


NOTE_STYLES = ('sentences', 'clause')


def _check_notes(notes: Any) -> list[str]:
    """Notes are short facts appended to a rule text through a placeholder of the same name ({own_note}): as
    sentences (style 'sentences', the default) or as one clause after a colon (style 'clause')."""
    if notes is None:
        return []
    if not isinstance(notes, Mapping):
        raise CampaignReasonsError('reason rules: notes must map note names to their items')
    for name, spec in notes.items():
        if not str(name).replace('_', '').isalnum() or name != str(name).lower() or name in TEXT_KEYS:
            raise CampaignReasonsError(f'reason note {name}: name must be lower_snake_case and not a text key')
        if not isinstance(spec, Mapping) or not isinstance(spec.get('max_items'), int) or spec['max_items'] < 1:
            raise CampaignReasonsError(f'reason note {name}: max_items must be a positive integer')
        if not isinstance(spec.get('items'), list) or not spec['items']:
            raise CampaignReasonsError(f'reason note {name}: items must be a non-empty list')
        if spec.get('style', 'sentences') not in NOTE_STYLES:
            raise CampaignReasonsError(f'reason note {name}: style must be one of {", ".join(NOTE_STYLES)}')
        for part in ('items', 'otherwise'):
            for item in spec.get(part) or []:
                if not isinstance(item, Mapping) or set(item) != {'conditions', 'text'}:
                    raise CampaignReasonsError(f'reason note {name}: an item needs conditions and text')
                _check_conditions(item['conditions'], f'reason note {name}')
                _check_text(item['text'], f'reason note {name}')
    return list(notes)


def load_rules(path: str | Path = DEFAULT_RULES) -> dict:
    """Read and check the rule file: every rule is a rank, a list of conditions (all must hold), a weight and a text."""
    rules = json.loads(Path(path).read_text(encoding='utf-8'))
    if rules.get('contract_name') != 'campaign_reason_rules' or not str(rules.get('version', '')).strip():
        raise CampaignReasonsError('reason rules: wrong contract_name or empty version')
    if not isinstance(rules.get('max_reasons'), int) or rules['max_reasons'] < 1:
        raise CampaignReasonsError('reason rules: max_reasons must be a positive integer')
    norms = rules.get('norms')
    if (not isinstance(norms, Mapping) or norms.get('group_by') != 'main_channel' or norms.get('statistic') != 'median'
            or not isinstance(norms.get('min_group'), int) or norms['min_group'] < 1):
        raise CampaignReasonsError('reason rules: norms must be the median by main_channel with a positive min_group')
    phrases = rules.get('channel_phrases')
    if not isinstance(phrases, Mapping) or not all(isinstance(v, str) and v.strip() for v in phrases.values()):
        raise CampaignReasonsError('reason rules: channel_phrases must map channel names to texts')
    note_names = _check_notes(rules.get('notes'))
    codes = set()
    if not rules.get('rules'):
        raise CampaignReasonsError('reason rules: no rules')
    for rule in rules['rules']:
        for key in ('code', 'rank', 'conditions', 'text'):
            if key not in rule:
                raise CampaignReasonsError(f'reason rule without {key}: {rule}')
        if not str(rule['code']).replace('_', '').isalnum() or rule['code'] != str(rule['code']).lower():
            raise CampaignReasonsError(f'reason rule {rule["code"]}: code must be lower_snake_case')
        if not isinstance(rule['rank'], int) or isinstance(rule['rank'], bool) or rule['rank'] < 1:
            raise CampaignReasonsError(f'reason rule {rule["code"]}: rank must be a positive integer')
        if ('weight_field' in rule) == ('weight' in rule):
            raise CampaignReasonsError(f'reason rule {rule["code"]}: give either weight_field or weight')
        if 'weight' in rule and not isinstance(rule['weight'], (int, float)):
            raise CampaignReasonsError(f'reason rule {rule["code"]}: weight must be a number')
        _check_conditions(rule['conditions'], f'reason rule {rule["code"]}')
        _check_text(rule['text'], f'reason rule {rule["code"]}', note_names)
        if rule['code'] in codes:
            raise CampaignReasonsError(f'reason rule {rule["code"]} twice')
        codes.add(rule['code'])
    fb = rules.get('fallback')
    if fb is not None:  # optional: a sentence for the free place (v3 has none: no facts, no words)
        if not isinstance(fb, Mapping) or not fb.get('code') or fb['code'] in codes:
            raise CampaignReasonsError('reason rules: fallback needs its own code and a text')
        _check_text(fb.get('text'), 'reason rules fallback', note_names)
    return rules


def _pct(x: float) -> str:
    return f'{int(round(100.0 * x))}%'


def _num(x: float, digits: int = 2) -> str:
    return f'{x:.{digits}f}'.replace('.', ',')


def _cities_note(names: Sequence[str]) -> str:
    return f' Больше всего потерь: {", ".join(names)}.' if names else ''


def _times(x: float) -> str:
    """'19 раз', '3 раза', '2,5 раза': a ratio with the Russian word for 'times'."""
    if not _finite(x) or x <= 0:
        return ''
    text = str(int(round(x))) if x >= 10 else _num(round(x, 1), 1).removesuffix(',0')
    if ',' in text:
        return f'{text} раза'
    v = int(text)
    return f'{text} раза' if v % 10 in (2, 3, 4) and v % 100 not in (12, 13, 14) else f'{text} раз'


def _plural(v: int, one: str, few: str, many: str) -> str:
    if v % 10 == 1 and v % 100 != 11:
        return one
    return few if v % 10 in (2, 3, 4) and v % 100 not in (12, 13, 14) else many


def _mln(rub: float) -> str:
    v = float(rub) / 1e6
    if v >= 100:
        return f'{v:,.0f}'.replace(',', '\u00a0')
    return _num(v, 1) if v >= 0.1 else _num(v, 2)


def _share_text(percent: int, share: float) -> str:
    """'6%', or 'меньше 1%' when a non-zero share rounds to 0%."""
    return 'меньше 1%' if percent == 0 and _finite(share) and share > 0 else f'{percent}%'


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def text_values(f: Mapping[str, Any]) -> dict[str, str]:
    """The placeholders of the rule texts, from the campaign factors (norms filled by label_catalog)."""
    g = float(f['geo_factor']) if _finite(f.get('geo_factor')) and f['geo_factor'] > 0 else 1.0
    kept, own, over = split_percents(f['kept_share'], f['own_loss_share'], f['overlap_loss_share'])
    norm = lambda key: _pct(f[key]) if _finite(f.get(key)) else ''  # noqa: E731
    money = lambda key: _num(float(f[key])) if _finite(f.get(key)) else ''  # noqa: E731
    dens = float(f['density_ratio']) if _finite(f.get('density_ratio')) and f['density_ratio'] > 0 else float('nan')
    tail_weeks = int(f.get('tail_weeks') or 0)
    return dict(
        kept_pct=f'{kept}%', own_loss_pct=_share_text(own, f['own_loss_share']),
        overlap_loss_pct=_share_text(over, f['overlap_loss_share']),
        norm_kept_pct=norm('norm_kept_share'), norm_own_pct=norm('norm_own_loss_share'),
        norm_overlap_pct=norm('norm_overlap_loss_share'), norm_group=str(f.get('norm_group') or ''),
        unseen_pct=_pct(f['unseen_share']), tail_pct=_pct(f['tail_share']), tail_weeks=str(tail_weeks),
        tail_weeks_text=f'{tail_weeks} {_plural(tail_weeks, "неделю", "недели", "недель")}',
        geo_ratio=_num(max(g, 1.0 / g), 1), geo_x=_times(max(g, 1.0 / g)),
        own_cities=', '.join(f.get('own_loss_cities', [])), overlap_cities=', '.join(f.get('overlap_loss_cities', [])),
        own_cities_note=_cities_note(f.get('own_loss_cities', [])),
        overlap_cities_note=_cities_note(f.get('overlap_loss_cities', [])),
        main_channel=str(f.get('main_channel', '')),
        first_ruble=money('first_ruble_roas'), typical_first_ruble=money('typical_first_ruble_roas'),
        top_geo=str(f.get('top_geo') or ''), top_geo_pct=norm('top_geo_share'),
        dense_x=_times(dens), thin_x=_times(1.0 / dens) if _finite(dens) else '',
        burn_pct=norm('burn_2w_share'), weeks_n=str(int(f.get('weeks_n') or 0)),
        neighbor_name=str(f.get('neighbor_name') or ''),
        neighbor_mln=_mln(f['neighbor_rub']) if _finite(f.get('neighbor_rub')) else '')


def _holds(f: Mapping[str, Any], cond: Mapping[str, Any]) -> bool:
    value = f.get(cond['field'])
    return _finite(value) and _OPS[cond['op']](float(value), float(cond['threshold']))


def _notes(f: Mapping[str, Any], rules: Mapping[str, Any], values: Mapping[str, str]) -> dict[str, str]:
    """Each note: its items whose conditions hold (at most max_items, in file order), else its 'otherwise'
    items; written as sentences that follow the rule text, or as one clause after a colon (style 'clause')."""
    out = {}
    for name, spec in (rules.get('notes') or {}).items():
        texts = []
        for part in ('items', 'otherwise'):
            texts = [item['text'].format(**values) for item in spec.get(part) or []
                     if all(_holds(f, cond) for cond in item['conditions'])][:int(spec['max_items'])]
            if texts:
                break
        if spec.get('style', 'sentences') == 'clause':
            out[name] = ': ' + ', '.join(texts) if texts else ''
        else:
            out[name] = ''.join(f' {_cap(t)}.' for t in texts)
    return out


def reasons_for(f: Mapping[str, Any], rules: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rules whose conditions all hold, by rank, the heaviest first within a rank, at most max_reasons;
    the fallback (if the file has one) fills a free place. No rule holds: no reasons, the card shows the bar only."""
    values = text_values(f)
    values = {**values, **_notes(f, rules, values)}
    hits = []
    for order, rule in enumerate(rules['rules']):
        if all(_holds(f, cond) for cond in rule['conditions']):
            weight = float(f.get(rule['weight_field']) or 0.0) if 'weight_field' in rule else float(rule['weight'])
            hits.append((int(rule['rank']), -weight, order, rule))
    hits.sort(key=lambda h: h[:3])
    out = [dict(code=rule['code'], display_text=rule['text'].format(**values), weight=-w)
           for _, w, _, rule in hits[:int(rules['max_reasons'])]]
    if rules.get('fallback') and len(out) < int(rules['max_reasons']) and _finite(f.get('first_ruble_roas')) \
            and _finite(f.get('typical_first_ruble_roas')):
        fb = rules['fallback']
        out.append(dict(code=fb['code'], display_text=fb['text'].format(**values), weight=0.0))
    return out


def main_channel_of(card: Mapping[str, Any]) -> tuple[str, bool]:
    """Name of the channel with the largest budget on a catalog card, and whether it is bought nationwide."""
    channels = card.get('channels') or []
    if not channels:
        return '', False
    top = max(channels, key=lambda c: float(c['budget']))
    return str(top['name']), bool(top.get('federal'))


TEMPLATE_ACTION = 'pro_rata_to_eligible_geos'  # ledger rows of an agency row «РФ» / «ДРУГИЕ РЕГИОНЫ» spread by a template
TEMPLATE_MAX_SHARE = 0.5  # above this share of template money the bought places say too little about the campaign
FACT_FIELDS = ('n_geo', 'top_geo', 'top_geo_share', 'density_regional_rub', 'density_national_rub', 'template_share',
               'weeks_n', 'burn_2w_share', 'others_rub', 'neighbor_number', 'neighbor_rub')


def label_catalog(entries: Mapping[str, dict], rules: Mapping[str, Any], *, tail_weeks: int,
                  names: Mapping[str, str] | None = None) -> list[dict]:
    """Label every modeled campaign of one catalog build.

    entries: number -> dict(factors | None, facts | None, own_loss_cities, overlap_loss_cities, main_channel,
    main_nationwide). The norm of a campaign is the median over the campaigns of the same build with the same main
    channel (all campaigns when that channel has fewer than norms.min_group); the money density is compared only
    within the main channel (no comparison when it has fewer than min_group). Fills factors with the norms and the
    differences from them, and entries with reasons; returns the norm table. names: number -> catalog name (for
    the campaign that ran next to this one)."""
    min_group = int(rules['norms']['min_group'])
    names = names or {}
    groups: dict[str, list[dict]] = {}
    dens: dict[str, list[float]] = {}
    for entry in entries.values():
        if entry.get('factors'):
            main = str(entry.get('main_channel') or '')
            groups.setdefault(main, []).append(entry['factors'])
            d = _density(entry)
            if _finite(d) and d > 0:
                dens.setdefault(main, []).append(d)
    every = [f for fs in groups.values() for f in fs]
    norms, group_text, table = {}, {}, []
    for name in sorted(groups):
        own_group = len(groups[name]) >= min_group
        base = groups[name] if own_group else every
        norms[name] = {key: float(statistics.median(float(f[src]) for f in base)) for key, src in NORM_FIELDS}
        norms[name]['norm_density_rub'] = float(statistics.median(dens[name])) \
            if len(dens.get(name, [])) >= min_group else float('nan')
        phrase = rules['channel_phrases'].get(name)
        group_text[name] = (f'у кампаний {phrase}' if phrase else 'у кампаний с тем же основным каналом') \
            if own_group else 'у всех кампаний каталога'
        table.append(dict(main_channel=name, campaigns_n=len(groups[name]), own_norm=int(own_group),
                          norm_group=group_text[name], **norms[name]))
    for entry in entries.values():
        f = entry.get('factors')
        if not f:
            entry['reasons'] = []
            continue
        main = str(entry.get('main_channel') or '')
        f.update(norms[main])
        f['kept_vs_norm'] = f['kept_share'] - f['norm_kept_share']
        f['kept_below_norm'] = -f['kept_vs_norm']
        f['own_vs_norm'] = f['own_loss_share'] - f['norm_own_loss_share']
        f['own_below_norm'] = -f['own_vs_norm']
        f['overlap_vs_norm'] = f['overlap_loss_share'] - f['norm_overlap_loss_share']
        f['main_nationwide'] = 1.0 if entry.get('main_nationwide') else 0.0
        f['main_digital'] = 1.0 if main == 'Цифровая реклама' else 0.0
        d = _density(entry)
        f['density_ratio'] = d / f['norm_density_rub'] if _finite(d) and d > 0 and _finite(f['norm_density_rub']) \
            and f['norm_density_rub'] > 0 else float('nan')
        entry['own_loss_cities'] = [geo_display(x) for x in entry.get('own_loss_cities') or []]
        entry['overlap_loss_cities'] = [geo_display(x) for x in entry.get('overlap_loss_cities') or []]
        facts = dict(entry.get('facts') or {})
        neighbor = facts.get('neighbor_number')
        label = dict(f, **{k: v for k, v in facts.items() if k in FACT_FIELDS and k != 'top_geo'},
                     top_geo=cc.pretty_geo(facts['top_geo']) if facts.get('top_geo') else '',
                     neighbor_name=names.get(str(neighbor), '') if neighbor is not None else '',
                     own_loss_cities=entry['own_loss_cities'], overlap_loss_cities=entry['overlap_loss_cities'],
                     own_cities_n=len(entry['own_loss_cities']), overlap_cities_n=len(entry['overlap_loss_cities']),
                     main_channel=main, tail_weeks=tail_weeks, norm_group=group_text[main])
        if not label['neighbor_name']:
            label['neighbor_rub'] = 0.0
        entry['reasons'] = reasons_for(label, rules)
    return table


def _density(entry: Mapping[str, Any]) -> float:
    """Money per place and week for a campaign bought by city, per week for one bought nationwide."""
    facts = entry.get('facts') or {}
    key = 'density_national_rub' if entry.get('main_nationwide') else 'density_regional_rub'
    value = facts.get(key)
    return float(value) if _finite(value) else float('nan')


def load_campaign_ledger(ledger: str | Path, names: str | Path | None = None,
                         names_sparse: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The ledger with each row's campaign index (column cat) and the directory (cat -> catalog number id),
    exactly as 09_weekly_joint_campaign_catalog.py builds them."""
    led = cr.read_ledger(str(ledger))
    led['name_key'] = led.campaign_id_for_audit.map(cc.norm_name)
    led, waves = cc.assign_waves(led)
    directory, _ = cc.build_directory(led, waves)
    if names:
        directory, _ = cc.keep_numbers(directory, cc.read_names_xlsx(str(names)), sparse=bool(names_sparse))
    else:
        directory['id'], directory['id_match'] = np.arange(1, len(directory) + 1), 'new'
    directory['cat'] = np.arange(len(directory))
    led = led.merge(directory[['name_key', 'wave', 'cat']], on=['name_key', 'wave'], how='left')
    if led.cat.isna().any():
        raise CampaignReasonsError('ledger rows without a campaign')
    led['cat'] = led.cat.astype(np.int64)
    return led, directory


def ledger_facts(led: pd.DataFrame, n: int) -> list[dict[str, Any]]:
    """Facts about how each campaign spent its money, from the ledger (led.cat = campaign index 0..n-1).

    Regional money: channels bought by city (not campaign_catalog.FEDERAL); national money: FEDERAL channels.
    - template_share: share of the regional money that the ledger spreads over places by a template (action
      TEMPLATE_ACTION: the agency row said «РФ» or «ДРУГИЕ РЕГИОНЫ», not a place);
    - n_geo, top_geo, density_regional_rub: from the regional money bought for named places only (no template):
      number of places, the largest place, money per (place, week) with spend; top_geo_share: the largest place's
      money as a share of the whole campaign budget (national and template money count as not in that place);
      all left empty (0, '', NaN) when the template holds more than TEMPLATE_MAX_SHARE of the regional money;
    - density_national_rub: national money per week with national spend;
    - weeks_n: weeks from the first to the last week with spend; burn_2w_share: the largest share of the budget
      spent in two weeks in a row;
    - others_rub, neighbor_cat, neighbor_rub: money of the other campaigns in the same (direction, model channel,
      place, week) cells as this campaign, and the campaign with the most of it. Only the same model channel:
      saturation works inside a channel, a campaign in another channel does not change this one's effect.
    Weeks start on Monday. Facts describe the money only; the model decides what they cost."""
    cols = ['cat', 'date', 'network', 'channel', 'channel_type', 'action', 'geo_label', 'budget']
    x = led.loc[led.budget > 0, cols].copy()
    x['cat'] = x.cat.astype(np.int64)
    x['federal'] = x.channel_type.map(cc.XL_GROUP).isin(cc.FEDERAL)
    x['model_channel'] = x.channel_type.map(cr.MODEL_CHANNEL).fillna(x.channel_type).astype(str)
    x['template'] = x.action.astype(str).eq(TEMPLATE_ACTION) & ~x.federal
    day = x.date.dt.normalize()
    x['week'] = day - pd.to_timedelta(day.dt.weekday, unit='D')
    x['seg'] = x.network.astype(str) + '/' + x.channel.astype(str)
    nan = float('nan')
    out = [dict(n_geo=0, top_geo='', top_geo_share=nan, density_regional_rub=nan, density_national_rub=nan,
                template_share=0.0, weeks_n=0, burn_2w_share=nan, others_rub=0.0, neighbor_cat=-1, neighbor_rub=0.0)
           for _ in range(n)]
    for k, g in x.groupby('cat'):
        total = float(g.budget.sum())
        wk = g.groupby('week').budget.sum()
        span = pd.date_range(wk.index.min(), wk.index.max(), freq='7D')
        full = wk.reindex(span, fill_value=0.0).to_numpy()
        two = full[:-1] + full[1:] if len(full) >= 2 else full
        f = out[int(k)]
        f.update(weeks_n=int(len(full)), burn_2w_share=float(two.max() / total))
        reg = g[~g.federal]
        if len(reg):
            template = float(reg.budget[reg.template].sum() / reg.budget.sum())
            f['template_share'] = template
            named = reg[~reg.template]
            if template <= TEMPLATE_MAX_SHARE and len(named):
                by_geo = named.groupby('geo_label').budget.sum().sort_values(ascending=False, kind='stable')
                f.update(n_geo=int(len(by_geo)), top_geo=str(by_geo.index[0]),
                         top_geo_share=float(by_geo.iloc[0] / total),
                         density_regional_rub=float(named.budget.sum() / named.groupby(['geo_label', 'week']).ngroups))
        nat = g[g.federal]
        if len(nat):
            f['density_national_rub'] = float(nat.budget.sum() / nat.week.nunique())
    cells = x.groupby(['seg', 'model_channel', 'geo_label', 'week', 'cat'], as_index=False).budget.sum()
    cells['cell'] = cells.groupby(['seg', 'model_channel', 'geo_label', 'week']).ngroup()
    pairs = cells[['cell', 'cat']].rename(columns={'cat': 'me'}).merge(cells[['cell', 'cat', 'budget']], on='cell')
    pairs = pairs[pairs.me != pairs.cat]
    per = pairs.groupby(['me', 'cat'], as_index=False).budget.sum().sort_values(
        ['me', 'budget', 'cat'], ascending=[True, False, True], kind='stable')
    for me, g in per.groupby('me', sort=False):
        out[int(me)].update(others_rub=float(g.budget.sum()), neighbor_cat=int(g.cat.iloc[0]),
                            neighbor_rub=float(g.budget.iloc[0]))
    return out


def facts_by_number(facts: Sequence[Mapping[str, Any]], number_of: Mapping[int, int]) -> dict[str, dict]:
    """Ledger facts keyed by catalog number, with the neighbour as a catalog number too."""
    out = {}
    for k, f in enumerate(facts):
        row = {key: v for key, v in f.items() if key != 'neighbor_cat'}
        row['neighbor_number'] = int(number_of[f['neighbor_cat']]) if f['neighbor_cat'] >= 0 else None
        out[str(int(number_of[k]))] = row
    return out


def factors(*, budget: float, seen: float, lin: np.ndarray, alone: np.ndarray, loo: np.ndarray, loo_tail: np.ndarray,
            expected_lin: float) -> dict[str, float]:
    """Campaign factors from per-draw effects. Shares are posterior means of per-draw shares, so
    kept + own + overlap = 1 exactly."""
    ok = lin > 0
    if not ok.any() or budget <= 0:
        return {}
    kept = float(np.mean(loo[ok] / lin[ok]))
    own = float(np.mean((lin[ok] - alone[ok]) / lin[ok]))
    over = float(np.mean((alone[ok] - loo[ok]) / lin[ok]))
    tail = float(np.mean(np.where(loo > 0, loo_tail / np.where(loo > 0, loo, 1.0), 0.0)))
    first = float(np.mean(lin)) / seen if seen > 0 else float('nan')
    typical = expected_lin / seen if seen > 0 and expected_lin > 0 else float('nan')
    geo = first / typical if typical and typical > 0 else float('nan')
    return dict(kept_share=kept, own_loss_share=own, overlap_loss_share=over, saturation_loss_share=own + over,
                tail_share=tail, unseen_share=max(0.0, 1.0 - seen / budget), first_ruble_roas=first,
                typical_first_ruble_roas=typical, geo_factor=geo,
                geo_weight=abs(math.log(geo)) if geo and geo > 0 and not math.isnan(geo) else 0.0,
                potential_turnover_rub=float(np.mean(lin)), alone_turnover_rub=float(np.mean(alone)),
                kept_turnover_rub=float(np.mean(loo)))


def top_units(names: Sequence[str], loss: np.ndarray, *, min_share: float = 0.15, max_n: int = 2) -> list[str]:
    """Up to max_n unit names that carry at least min_share of the campaign's loss (names merged across directions)."""
    tot: dict[str, float] = {}
    for name, v in zip(names, loss):
        tot[name] = tot.get(name, 0.0) + max(float(v), 0.0)
    s = sum(tot.values())
    if s <= 0:
        return []
    return [k for k, v in sorted(tot.items(), key=lambda kv: -kv[1]) if v / s >= min_share][:max_n]
