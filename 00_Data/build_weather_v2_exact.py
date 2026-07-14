"""Build strict v2 weather features for X5 MMM refresh.

Creates a model-ready weather parquet through 2026-05-31 without the old
geo-to-geo weather proxy layer. Network is used only to resolve/fetch explicit
station observations. All station and fill decisions are audited.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from meteostat import Point, daily, normals, stations

ROOT = Path(__file__).resolve().parents[1]
DATA_2025_DIR = ROOT / '00_Data' / '01_2025_first_pass'
V2_DIR = ROOT / '00_Data' / '02_2025_2026Q1_second_pass'
RAW_V2 = V2_DIR / '01_Raw_Data_v2'
AUDIT_DIR = V2_DIR / 'audits'
OLD_WEATHER = DATA_2025_DIR / '01_Raw_Data' / 'weather_features_2024-01-01_to_2026-05-05.parquet'
GEO_REFERENCE = RAW_V2 / 'geo_reference_v2.csv'
OUT_WEATHER = V2_DIR / 'weather_features_2025-01-01_to_2026-05-31_v2_exact.parquet'
OUT_AUDIT = AUDIT_DIR / 'weather_exact_build_audit_v2.csv'
OUT_STATION_REF = RAW_V2 / 'weather_station_reference_v2.csv'

START = pd.Timestamp('2025-01-01')
END = pd.Timestamp('2026-05-31')
MIN_COVERAGE_DAYS = 500
USER_AGENT = 'x5-mmm-weather-v2/1.0'

WEATHER_COLS = [
    'temp_avg_c', 'temp_max_c', 'temp_min_c', 'temp_norm_avg_c', 'temp_dev_from_norm_c',
    'hdd_18', 'cdd_18', 'feels_like_min_c', 'precipitation_mm', 'snow_depth_cm',
    'snow_fall_cm', 'wind_speed_max_ms', 'is_freezing_d', 'is_extreme_cold_d',
    'is_hot_d', 'is_extreme_heat_d', 'is_heatwave_d', 'is_coldwave_d', 'is_rainy_d',
    'is_heavy_rain_d', 'is_snowy_d', 'weather_drives_indoor_d',
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('weather_v2_exact')


def norm_text(value: object) -> str:
    if pd.isna(value):
        return ''
    return ' '.join(str(value).strip().upper().replace('Ё', 'Е').split())


def date_range(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq='D')


def nws_wind_chill_c(temp_c: pd.Series, wind_ms: pd.Series) -> pd.Series:
    wind_kmh = wind_ms.astype(float) * 3.6
    temp = temp_c.astype(float)
    valid = (temp < 10) & (wind_kmh >= 4.8)
    out = temp.copy()
    out.loc[valid] = 13.12 + 0.6215 * temp.loc[valid] - 11.37 * np.power(wind_kmh.loc[valid], 0.16) + 0.3965 * temp.loc[valid] * np.power(wind_kmh.loc[valid], 0.16)
    return out


def consecutive_count(flag: pd.Series) -> pd.Series:
    vals = flag.fillna(0).astype(int).to_numpy()
    out = np.zeros(len(vals), dtype=int)
    run = 0
    for i, val in enumerate(vals):
        run = run + 1 if val else 0
        out[i] = run
    return pd.Series(out, index=flag.index)


def geocode_label(label: str) -> dict:
    query = f'{label}, Россия'
    url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode({'q': query, 'format': 'json', 'limit': 1, 'addressdetails': 1})
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode('utf-8'))
    if not data:
        raise ValueError(f'No geocode for weather station label {label!r}')
    loc = data[0]
    return {'geocode_query': query, 'lat': float(loc['lat']), 'lon': float(loc['lon']), 'geocode_display_name': loc.get('display_name', '')}


def collapse_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()
        time_col = 'time'
    else:
        df = df.reset_index().rename(columns={'index': 'time'})
        time_col = 'time' if 'time' in df.columns else df.columns[0]
    df[time_col] = pd.to_datetime(df[time_col])
    numeric_cols = [c for c in ['temp', 'tmin', 'tmax', 'prcp', 'snwd', 'wspd', 'wpgt', 'pres', 'tsun', 'cldc'] if c in df.columns]
    return df.groupby(time_col, as_index=False)[numeric_cols].mean().rename(columns={time_col: 'date'})


def fetch_daily_station(station_id: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    ts = daily(str(station_id), start.date(), end.date())
    out = ts.fetch(fill=False)
    df = out if out is not None else getattr(ts, '_df', pd.DataFrame())
    return collapse_daily(df)


def fetch_station_coverage(station_id: str, start: pd.Timestamp, end: pd.Timestamp) -> int:
    df = fetch_daily_station(station_id, start, end)
    return 0 if df.empty else int(df['date'].nunique())


def choose_station_for_label(label: str) -> dict:
    geo = geocode_label(label)
    cand = stations.nearby(Point(geo['lat'], geo['lon']), radius=300000, limit=100)
    if cand is None or cand.empty:
        raise ValueError(f'No Meteostat station candidates for {label}')
    best = None
    for station_id, rec in cand.iterrows():
        coverage = fetch_station_coverage(str(station_id), START, END)
        payload = {
            'station_id': str(station_id),
            'station_name': rec.get('name'),
            'station_country': rec.get('country'),
            'station_region': rec.get('region'),
            'station_distance_m': float(rec.get('distance')),
            'coverage_days': int(coverage),
        }
        if best is None or coverage > best['coverage_days']:
            best = payload
        if coverage >= MIN_COVERAGE_DAYS:
            return {'source_label': label, 'station_selection_rule': 'nearest_station_with_min_coverage_days', **geo, **payload}
    if best is None:
        raise ValueError(f'No station coverage could be read for {label}')
    return {'source_label': label, 'station_selection_rule': 'best_available_station_below_threshold', **geo, **best}


def collapse_normals(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=['month', 'norm_temp', 'norm_tmin', 'norm_tmax'])
    if isinstance(df.index, pd.MultiIndex):
        tmp = df.reset_index()
        month_col = 'time'
    else:
        tmp = df.reset_index().rename(columns={'index': 'time'})
        month_col = 'time'
    tmp['month'] = pd.to_numeric(tmp[month_col], errors='coerce')
    rename = {'temp': 'norm_temp', 'tmin': 'norm_tmin', 'tmax': 'norm_tmax'}
    cols = [c for c in rename if c in tmp.columns]
    if not cols:
        return pd.DataFrame(columns=['month', 'norm_temp', 'norm_tmin', 'norm_tmax'])
    return tmp.groupby('month', as_index=False)[cols].mean().rename(columns=rename)


def fetch_normals_station(station_id: str) -> pd.DataFrame:
    last_error = None
    for _ in range(3):
        try:
            ts = normals(str(station_id), start=1991, end=2020)
            out = ts.fetch()
            df = out if out is not None else getattr(ts, '_df', pd.DataFrame())
            collapsed = collapse_normals(df)
            if not collapsed.empty and collapsed.get('norm_temp', pd.Series(dtype=float)).notna().sum() >= 10:
                return collapsed
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    log.warning('No usable normals for station %s: %s', station_id, last_error)
    return pd.DataFrame(columns=['month', 'norm_temp', 'norm_tmin', 'norm_tmax'])


def fill_daily(raw: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    dates = pd.DataFrame({'date': date_range(start, end)})
    out = dates.merge(raw, on='date', how='left')
    observed_days = int(raw['date'].nunique()) if not raw.empty else 0
    temp_cols = [c for c in ['temp', 'tmin', 'tmax'] if c in out.columns]
    original_missing_rows = int(out[temp_cols].isna().all(axis=1).sum()) if temp_cols else len(out)
    for col in ['temp', 'tmin', 'tmax', 'wspd', 'wpgt', 'pres', 'cldc']:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = out[col].astype(float).interpolate(limit_direction='both').ffill().bfill()
    for col in ['prcp', 'snwd', 'tsun']:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = out[col].astype(float).fillna(0.0)
    return out, {
        'observed_days': observed_days,
        'expected_days': int(len(dates)),
        'filled_calendar_days': int(len(dates) - observed_days),
        'temperature_missing_rows_before_fill': original_missing_rows,
    }


def derive_features(raw: pd.DataFrame, normals_df: pd.DataFrame, geo_unit: str, station_label: str, station_id: str) -> tuple[pd.DataFrame, dict]:
    filled, fill_audit = fill_daily(raw, START, END)
    filled['month'] = filled['date'].dt.month
    if normals_df.empty:
        norm_source = 'station_observed_month_median_fallback'
        norm = filled.groupby('month', as_index=False)[['temp', 'tmin', 'tmax']].median().rename(columns={'temp': 'norm_temp', 'tmin': 'norm_tmin', 'tmax': 'norm_tmax'})
    else:
        norm_source = 'meteostat_normals_1991_2020'
        norm = normals_df.copy()
    out = filled.merge(norm, on='month', how='left')
    for col, raw_col in [('norm_temp', 'temp'), ('norm_tmin', 'tmin'), ('norm_tmax', 'tmax')]:
        if col not in out.columns:
            out[col] = np.nan
        if out[col].isna().any():
            out[col] = out[col].fillna(out.groupby('month')[raw_col].transform('median'))
            norm_source += '__partial_month_median_fill'
    wind_ms = out['wspd'].astype(float) / 3.6
    snow_depth_cm = out['snwd'].astype(float) / 10.0
    prcp = out['prcp'].astype(float).clip(lower=0.0)
    features = pd.DataFrame({
        'date': out['date'],
        'geo_unit': geo_unit,
        'weather_station_city': station_label,
        'weather_station_id': station_id,
        'temp_avg_c': out['temp'].astype(float),
        'temp_max_c': out['tmax'].astype(float),
        'temp_min_c': out['tmin'].astype(float),
        'temp_norm_avg_c': out['norm_temp'].astype(float),
        'precipitation_mm': prcp,
        'snow_depth_cm': snow_depth_cm.fillna(0.0).clip(lower=0.0),
        'wind_speed_max_ms': wind_ms.fillna(0.0).clip(lower=0.0),
    })
    features['temp_dev_from_norm_c'] = features['temp_avg_c'] - features['temp_norm_avg_c']
    features['hdd_18'] = np.maximum(0.0, 18.0 - features['temp_avg_c'])
    features['cdd_18'] = np.maximum(0.0, features['temp_avg_c'] - 18.0)
    features['feels_like_min_c'] = nws_wind_chill_c(features['temp_min_c'], features['wind_speed_max_ms'])
    features['snow_fall_cm'] = np.where((features['temp_avg_c'] <= 0) & (features['precipitation_mm'] > 0), features['precipitation_mm'], 0.0)
    features['is_freezing_d'] = (features['temp_min_c'] < -10).astype(int)
    features['is_extreme_cold_d'] = (features['temp_min_c'] < -20).astype(int)
    features['is_hot_d'] = (features['temp_max_c'] > 25).astype(int)
    features['is_extreme_heat_d'] = (features['temp_max_c'] > 30).astype(int)
    features['is_rainy_d'] = (features['precipitation_mm'] > 2).astype(int)
    features['is_heavy_rain_d'] = (features['precipitation_mm'] > 10).astype(int)
    features['is_snowy_d'] = ((features['snow_fall_cm'] > 1) | (features['snow_depth_cm'] > 5)).astype(int)
    hot_run = consecutive_count(features['is_hot_d'])
    features['is_heatwave_d'] = ((hot_run >= 3) | (features['temp_max_c'] > features['temp_norm_avg_c'] + 5)).astype(int)
    cold_run = consecutive_count((features['temp_max_c'] < -15).astype(int))
    features['is_coldwave_d'] = (cold_run >= 3).astype(int)
    features['weather_drives_indoor_d'] = ((features['is_heavy_rain_d'] == 1) | (features['is_snowy_d'] == 1) | (features['is_extreme_cold_d'] == 1) | (features['is_extreme_heat_d'] == 1)).astype(int)
    return features[['date', 'geo_unit', 'weather_station_city', 'weather_station_id'] + WEATHER_COLS], {**fill_audit, 'norm_source': norm_source}


def weighted_tail_features(label: str, station_ref_cache: dict) -> tuple[pd.DataFrame, dict]:
    comps = [(norm_text(name), float(weight)) for name, weight in re.findall(r'([^×,]+)×([0-9.]+)', label.replace('weighted:', ''))]
    if not comps:
        raise ValueError(f'Cannot parse weighted weather label: {label}')
    parts = []
    audits = []
    for city, weight in comps:
        station = station_ref_cache.get(city)
        if station is None:
            station = choose_station_for_label(city)
            station_ref_cache[city] = station
            time.sleep(1.0)
        raw = fetch_daily_station(station['station_id'], START, END)
        norms_df = fetch_normals_station(station['station_id'])
        feat, audit = derive_features(raw, norms_df, city, city, station['station_id'])
        feat['weight'] = weight
        parts.append(feat)
        audits.append({'component': city, 'weight': weight, **station, **audit})
    stack = pd.concat(parts, ignore_index=True)
    continuous = ['temp_avg_c', 'temp_max_c', 'temp_min_c', 'temp_norm_avg_c', 'temp_dev_from_norm_c', 'hdd_18', 'cdd_18', 'feels_like_min_c', 'precipitation_mm', 'snow_depth_cm', 'snow_fall_cm', 'wind_speed_max_ms']
    weighted = []
    for dt, grp in stack.groupby('date'):
        row = {'date': dt, 'geo_unit': label, 'weather_station_city': label, 'weather_station_id': 'weighted_components'}
        w = grp['weight'].to_numpy(dtype=float)
        w = w / w.sum()
        for col in continuous:
            row[col] = float(np.average(grp[col].astype(float), weights=w))
        weighted.append(row)
    out = pd.DataFrame(weighted).sort_values('date')
    out['is_freezing_d'] = (out['temp_min_c'] < -10).astype(int)
    out['is_extreme_cold_d'] = (out['temp_min_c'] < -20).astype(int)
    out['is_hot_d'] = (out['temp_max_c'] > 25).astype(int)
    out['is_extreme_heat_d'] = (out['temp_max_c'] > 30).astype(int)
    out['is_rainy_d'] = (out['precipitation_mm'] > 2).astype(int)
    out['is_heavy_rain_d'] = (out['precipitation_mm'] > 10).astype(int)
    out['is_snowy_d'] = ((out['snow_fall_cm'] > 1) | (out['snow_depth_cm'] > 5)).astype(int)
    out['is_heatwave_d'] = ((consecutive_count(out['is_hot_d']) >= 3) | (out['temp_max_c'] > out['temp_norm_avg_c'] + 5)).astype(int)
    out['is_coldwave_d'] = (consecutive_count((out['temp_max_c'] < -15).astype(int)) >= 3).astype(int)
    out['weather_drives_indoor_d'] = ((out['is_heavy_rain_d'] == 1) | (out['is_snowy_d'] == 1) | (out['is_extreme_cold_d'] == 1) | (out['is_extreme_heat_d'] == 1)).astype(int)
    audit = {'weighted_components': json.dumps(audits, ensure_ascii=False), 'observed_days': int(min(a['observed_days'] for a in audits)), 'expected_days': int((END - START).days + 1), 'filled_calendar_days': int(max(a['filled_calendar_days'] for a in audits)), 'norm_source': 'weighted_component_norms'}
    return out[['date', 'geo_unit', 'weather_station_city', 'weather_station_id'] + WEATHER_COLS], audit


def main() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    geo_ref = pd.read_csv(GEO_REFERENCE)
    geo_ref['geo_label'] = geo_ref['geo_label'].map(norm_text)
    model_geos = sorted(geo_ref['geo_label'].unique())

    old_source = pd.read_parquet(OLD_WEATHER, columns=['date', 'geo_unit', 'weather_station_city'])
    old_source['geo_unit'] = old_source['geo_unit'].map(norm_text)
    old_station_map = old_source[['geo_unit', 'weather_station_city']].drop_duplicates()
    old_station_map = old_station_map[old_station_map['geo_unit'].isin(model_geos)].copy()
    old_geos = set(old_station_map['geo_unit'].unique())
    new_ref = geo_ref[~geo_ref['geo_label'].isin(old_geos)].copy()

    station_ref_cache = {}
    if OUT_STATION_REF.exists():
        cached = pd.read_csv(OUT_STATION_REF)
        station_ref_cache = {row['source_label']: row.dropna().to_dict() for _, row in cached.iterrows()}

    generated_parts = []
    audit_rows = []

    # New v2 geos: explicit station IDs from geo_reference_v2.
    for _, row in new_ref.sort_values('geo_label').iterrows():
        geo = row['geo_label']
        station_id = str(row['weather_station_id'])
        raw = fetch_daily_station(station_id, START, END)
        norms_df = fetch_normals_station(station_id)
        feat, audit = derive_features(raw, norms_df, geo, str(row['weather_station_name']), station_id)
        generated_parts.append(feat)
        audit_rows.append({'geo_label': geo, 'period_type': 'new_geo_full_period', 'weather_source_type': 'station_observations', 'station_id': station_id, 'station_name': row.get('weather_station_name'), 'station_distance_m': row.get('weather_station_distance_m'), 'station_selection_rule': row.get('station_selection_rule'), **audit})
        log.info('new geo weather: %s station=%s observed=%s/%s', geo, station_id, audit['observed_days'], audit['expected_days'])

    # Existing geos: rebuild the full period from the old station label mapping.
    unique_labels = sorted(old_station_map['weather_station_city'].dropna().unique())
    log.info('building full-period old-geo weather for %d station labels: %s -> %s', len(unique_labels), START.date(), END.date())
    label_features = {}
    for label in unique_labels:
        if str(label).startswith('weighted:'):
            feat, audit = weighted_tail_features(str(label), station_ref_cache)
            label_features[label] = feat.copy()
            audit_rows.append({'geo_label': '__weighted_station_label__', 'station_label': label, 'period_type': 'old_geo_full_period_station_label', 'weather_source_type': 'weighted_station_observations', 'station_id': 'weighted_components', 'station_name': label, 'station_distance_m': np.nan, 'station_selection_rule': 'weighted_components_from_old_weather_label', **audit})
            continue
        label_norm = norm_text(label)
        station = station_ref_cache.get(label_norm)
        if station is None:
            station = choose_station_for_label(label_norm)
            station_ref_cache[label_norm] = station
            pd.DataFrame(list(station_ref_cache.values())).drop_duplicates('source_label').to_csv(OUT_STATION_REF, index=False)
            time.sleep(1.0)
        raw = fetch_daily_station(station['station_id'], START, END)
        norms_df = fetch_normals_station(station['station_id'])
        feat, audit = derive_features(raw, norms_df, label_norm, label_norm, station['station_id'])
        label_features[label] = feat.copy()
        audit_rows.append({'geo_label': '__station_label__', 'station_label': label_norm, 'period_type': 'old_geo_full_period_station_label', 'weather_source_type': 'station_observations', 'station_id': station['station_id'], 'station_name': station['station_name'], 'station_distance_m': station['station_distance_m'], 'station_selection_rule': station['station_selection_rule'], **audit})
        log.info('old geo station label: %s station=%s observed=%s/%s', label_norm, station['station_id'], audit['observed_days'], audit['expected_days'])

    old_geo_rows = []
    for _, row in old_station_map.iterrows():
        geo = row['geo_unit']
        label = row['weather_station_city']
        feat = label_features[label].copy()
        feat['geo_unit'] = geo
        feat['weather_station_city'] = label
        old_geo_rows.append(feat)
    if old_geo_rows:
        generated_parts.append(pd.concat(old_geo_rows, ignore_index=True))

    weather = pd.concat(generated_parts, ignore_index=True, sort=False)
    weather['date'] = pd.to_datetime(weather['date'])
    weather['geo_unit'] = weather['geo_unit'].map(norm_text)
    weather = weather[weather['geo_unit'].isin(model_geos)].copy()
    weather = weather.drop_duplicates(['date', 'geo_unit'], keep='last')
    weather = weather.sort_values(['geo_unit', 'date']).reset_index(drop=True)

    expected_n = len(date_range(START, END))
    coverage = weather.groupby('geo_unit')['date'].agg(['min', 'max', 'nunique']).reset_index()
    bad_geos = coverage[(coverage['min'] != START) | (coverage['max'] != END) | (coverage['nunique'] != expected_n)]
    if not bad_geos.empty:
        raise ValueError('Incomplete weather coverage:\n' + bad_geos.to_string(index=False))
    missing_geos = sorted(set(model_geos) - set(weather['geo_unit'].unique()))
    if missing_geos:
        raise ValueError(f'Missing weather geos: {missing_geos}')
    null_cols = {c: int(weather[c].isna().sum()) for c in WEATHER_COLS if c in weather.columns and weather[c].isna().any()}
    if null_cols:
        raise ValueError(f'Weather nulls remain: {null_cols}')

    weather.to_parquet(OUT_WEATHER, index=False, compression='snappy')
    pd.DataFrame(audit_rows).to_csv(OUT_AUDIT, index=False)
    if station_ref_cache:
        pd.DataFrame(list(station_ref_cache.values())).drop_duplicates('source_label').to_csv(OUT_STATION_REF, index=False)

    summary = {
        'output': str(OUT_WEATHER),
        'rows': int(len(weather)),
        'geos': int(weather['geo_unit'].nunique()),
        'date_min': weather['date'].min().date().isoformat(),
        'date_max': weather['date'].max().date().isoformat(),
        'source_policy': 'full_horizon_station_observations_v2; old parquet used only for old geo -> station label mapping',
        'generated_rows': int(sum(len(p) for p in generated_parts)),
        'audit': str(OUT_AUDIT),
        'station_reference': str(OUT_STATION_REF),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
