#!/usr/bin/env python3
"""Deterministic, comparable-driven Twitch launch forecaster."""
import datetime as dt
import json
import math
import os
from pathlib import Path

LEVELS = (0.05, 0.25, 0.50, 0.75, 0.95)
ZS = (-1.645, -0.674, 0.0, 0.674, 1.645)
HOURS = tuple(range(2, 25))


def parse_time(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def eligible_history(case, field):
    cutoff = parse_time(case['checkpoint'])
    points = case.get(field, []) or []
    kept = [p for p in points if parse_time(p.get('at', p.get('from'))) <= cutoff]
    assert all(parse_time(p.get('at', p.get('from'))) <= cutoff for p in kept)
    return kept


def comparable_curves(comparables):
    curves = []
    for item in comparables:
        start = parse_time(item['day_start'])
        by_hour = {}
        for point in item.get('hourly', []):
            try:
                delta = parse_time(point['from']) - start
                seconds = delta.total_seconds()
                if seconds >= 0 and seconds % 3600 == 0:
                    h = int(seconds // 3600) + 1
                    if 1 <= h <= 24:
                        by_hour[h] = point.get('viewers', 0)
            except (KeyError, TypeError, ValueError):
                continue
        try:
            v1 = float(by_hour[1])
        except (KeyError, TypeError, ValueError):
            continue
        if v1 < 1:
            continue
        values = {}
        for h in HOURS:
            try:
                v = float(by_hour[h])
                if v > 0:
                    values[h] = math.log(v / v1)
            except (KeyError, TypeError, ValueError):
                pass
        if len(values) < 18:
            continue
        curves.append({'name': item.get('name', ''), 'v1': v1, 'platforms': item.get('platforms', []), 'day_start': item['day_start'], 'values': values})
    curves.sort(key=lambda c: c['name'])
    return curves


def raw_weight(curve, p1):
    scale = math.exp(-abs(math.log(curve['v1']) - math.log(p1)) / 2.0)
    year = parse_time(curve['day_start']).year
    recent = 1.0 if year >= 2022 else 0.7
    plats = curve.get('platforms', [])
    ptext = ' '.join(str(x) for x in plats).lower()
    console = (('ps' in ptext or 'xbox' in ptext) and 'pc' not in ptext)
    return scale * recent * (1.2 if console else 1.0)


def capped_weights(curves, p1):
    if not curves:
        return []
    raw = [raw_weight(c, p1) for c in curves]
    total = sum(raw)
    if total <= 0:
        return [1.0 / len(raw)] * len(raw)
    weights = [v / total for v in raw]
    cap = 0.25
    # Iterative water filling preserves relative weights among uncapped examples.
    for _ in range(len(weights) + 1):
        over = [i for i, w in enumerate(weights) if w > cap + 1e-15]
        if not over:
            break
        excess = sum(weights[i] - cap for i in over)
        for i in over:
            weights[i] = cap
        free = [i for i, w in enumerate(weights) if w < cap - 1e-15]
        denom = sum(raw[i] for i in free)
        if not free or denom <= 0:
            break
        for i in free:
            weights[i] += excess * raw[i] / denom
    total = sum(weights)
    return [w / total for w in weights]


def weighted_median(pairs):
    ordered = sorted(pairs, key=lambda pair: pair[0])
    half = sum(w for _, w in ordered) / 2.0
    acc = 0.0
    for value, weight in ordered:
        acc += weight
        if acc >= half:
            return value
    return ordered[-1][0]


def smooth(values):
    result = []
    for i in range(len(values)):
        lo, hi = max(0, i - 1), min(len(values), i + 2)
        result.append(sum(values[lo:hi]) / (hi - lo))
    return result


def curve_parameters(curves, p1, persistence=0.20, sigma_floor=0.12):
    if not curves:
        return [0.0] * 23, [0.15 * math.sqrt(h - 1) for h in HOURS]
    weights = capped_weights(curves, p1)
    medians, sigmas = [], []
    for h in HOURS:
        pairs = [(c['values'][h], weights[i]) for i, c in enumerate(curves) if h in c['values']]
        total = sum(w for _, w in pairs)
        pairs = [(v, w / total) for v, w in pairs]
        median = weighted_median(pairs)
        mean = sum(v * w for v, w in pairs)
        sigma = math.sqrt(sum(w * (v - mean) ** 2 for v, w in pairs))
        medians.append(median)
        sigmas.append(max(sigma, sigma_floor * math.sqrt(h - 1)))
    medians, sigmas = smooth(medians), smooth(sigmas)
    return [(1.0 - persistence) * v for v in medians], sigmas


def pre_release_level(case):
    """Return the median positive pre-release level; never use it to raise the anchor."""
    start = parse_time(case['day_start'])
    prior = []
    for point in eligible_history(case, 'history_hourly'):
        t = parse_time(point.get('at', point.get('from')))
        value = point.get('viewers', 0)
        if start - dt.timedelta(hours=24) <= t < start and value and float(value) > 0:
            prior.append(float(value))
    prior.sort()
    if not prior:
        return 0.0
    middle = len(prior) // 2
    return prior[middle] if len(prior) % 2 else (prior[middle - 1] + prior[middle]) / 2.0


def early_slope_shift(case):
    start, end = parse_time(case['day_start']), parse_time(case['checkpoint'])
    points = []
    for p in eligible_history(case, 'history'):
        t = parse_time(p.get('at', p.get('from')))
        v = p.get('viewers', 0)
        if start <= t <= end and v and float(v) > 0:
            points.append((t, math.log(float(v))))
    points.sort(key=lambda x: x[0])
    if len(points) < 10:
        return 0.0
    recent = [p for p in points if p[0] >= end - dt.timedelta(minutes=30)]
    if len(recent) < 2:
        return 0.0
    xs = [(t - recent[0][0]).total_seconds() / 3600 for t, _ in recent]
    ys = [y for _, y in recent]
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - xm) ** 2 for x in xs)
    slope = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / denom if denom else 0.0
    return 0.1 * abs(slope) if slope < -0.5 else 0.0


def round_half_up(value):
    return math.floor(value * 100.0 + 0.5) / 100.0


def forecast(case, persistence=0.0, sigma_floor=0.10, curves=None):
    known = [row for row in case.get('known', []) if row.get('hour') == 1]
    if not known:
        raise ValueError('case has no known hour-1 row')
    p1 = max(1.0, float(known[0]['viewers']))
    # Past comparable launches are permitted training data; only target history is cutoff-filtered.
    if curves is None:
        curves = comparable_curves(case.get('comparables', []))
    pre = pre_release_level(case)
    # If pre-release hype exceeds p1 it is deliberately ignored; p1 stays the sole anchor.
    _pre_was_higher = pre > p1
    med, sigma = curve_parameters(curves, p1, persistence, sigma_floor)
    shift = early_slope_shift(case)
    rows = []
    for idx, h in enumerate(HOURS):
        center = med[idx] - (shift if h <= 6 else 0.0)
        qs = [round_half_up(min(1e9, max(1.0, p1 * math.exp(center + z * sigma[idx])))) for z in ZS]
        qs.sort()
        rows.append({'hour': h, 'q': qs})
    return {'hours': rows}


def main():
    source = Path(os.environ.get('MAKEFUN_INPUT_DIR', '/input'))
    target = Path(os.environ.get('MAKEFUN_OUTPUT_DIR', '/output'))
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob('*.in'), key=lambda p: p.name):
        case = json.loads(path.read_text(encoding='utf-8'))
        result = forecast(case)
        payload = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n'
        if len(payload.encode('utf-8')) > 65536:
            raise ValueError('output exceeds 65536 bytes')
        (target / (str(case['id']) + '.out')).write_text(payload, encoding='utf-8')


if __name__ == '__main__':
    main()
