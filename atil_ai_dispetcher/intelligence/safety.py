"""Deterministic calculations; missing evidence never becomes a zero risk score."""
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from .models import SafetyPolicy


def instant(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    return value if isinstance(value, datetime) and value.tzinfo is not None else None


def numeric(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and not isinstance(value, bool) else None
    except (ValueError, TypeError):
        return None


def normalize(row, units):
    """Keep invalid observations as barriers: filtering them would bridge data gaps."""
    t = instant(row.get('fix_time'))
    if t is None:
        return None
    try:
        p = row.get('payload') or {}
        p = json.loads(p) if isinstance(p, str) else p
        if not isinstance(p, dict):
            p = {}
    except (ValueError, TypeError):
        p = {}
    speed = numeric(p.get('speed'))
    multiplier = {'knots': 1.852, 'kph': 1, 'mph': 1.609344, 'mps': 3.6}.get(units.get(str(row.get('provider', '')).upper()))
    speed = speed * multiplier if speed is not None and multiplier else None
    lat, lon = numeric(p.get('latitude')), numeric(p.get('longitude'))
    valid = (p.get('valid') is True and speed is not None and 0 <= speed <= 200
             and lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180)
    heading = numeric(p.get('course'))
    return {'time': t, 'speed': speed if valid else None,
            'heading': heading if heading is not None and 0 <= heading < 360 else None,
            'id': str(row.get('provider_point_id', '')), 'binding': str(row.get('binding_id', '')),
            'latitude': lat, 'longitude': lon}


def attribution(assignments, start, end):
    # Even a partially overlapping conflicting assignment makes attribution unsafe.
    overlaps = [a for a in assignments if a['start'] < end and a['end'] > start]
    drivers = {str(a['driver_id']) for a in overlaps if a.get('driver_id')}
    if len(drivers) != 1 or any(not a.get('driver_id') for a in overlaps):
        return None
    driver = next(iter(drivers))
    if any(a['start'] <= start and a['end'] >= end and str(a.get('driver_id')) == driver for a in overlaps):
        return driver
    return None


def distance(a, b):
    phi1, phi2 = math.radians(a['latitude']), math.radians(b['latitude'])
    dphi = phi2-phi1
    dlambda = math.radians(b['longitude']-a['longitude'])
    h = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def vehicle_report(vehicle, rows, assignments, policy: SafetyPolicy, units, start, end, complete=True):
    points = [p for row in rows if (p := normalize(row, units)) and start <= p['time'] <= end]
    points.sort(key=lambda p: p['time'])
    # Equal-time conflicting observations cannot be resolved by arbitrary row order.
    grouped = defaultdict(list)
    for p in points:
        grouped[p['time']].append(p)
    unique = []
    conflicts = 0
    for group in grouped.values():
        p = dict(group[0])
        if any((q['speed'], q['heading'], q['binding'], q['latitude'], q['longitude']) !=
               (p['speed'], p['heading'], p['binding'], p['latitude'], p['longitude']) for q in group):
            p['speed'] = None
            conflicts += 1
        unique.append(p)
    stats = defaultdict(lambda: {'driving_seconds': 0., 'high_frequency_seconds': 0.,
                                'heading_seconds': 0., 'speed_severity_seconds': 0.,
                                'speeding_seconds': 0., 'maneuvers': 0})
    events, gaps = [], []
    observed, high_frequency, heading_seconds, rejected = 0., 0., 0., 0
    run = None
    previous_harsh = {}
    limit = policy.speed_limit_kph

    def finish_run():
        nonlocal run
        if run and run['duration_seconds'] >= policy.minimum_speeding_seconds:
            events.append(run)
        run = None

    def event(kind, a, b, driver, **extra):
        key = f"{vehicle['vehicle_id']}|{kind}|{a['time'].isoformat()}|{b['time'].isoformat()}|{policy.name}"
        return {'id': hashlib.sha256(key.encode()).hexdigest()[:24], 'kind': kind,
                'vehicle_id': str(vehicle['vehicle_id']), 'plate_number': vehicle.get('plate_number'),
                'driver_id': driver, 'start': a['time'], 'end': b['time'],
                'duration_seconds': (b['time']-a['time']).total_seconds(),
                'source_point_ids': [a['id'], b['id']], 'evidence': 'GPS_DERIVED', **extra}

    for a, b in zip(unique, unique[1:]):
        dt = (b['time']-a['time']).total_seconds()
        gaps.append(dt)
        good = (0 < dt <= policy.max_gap_seconds and a['binding'] == b['binding']
                and a['speed'] is not None and b['speed'] is not None)
        if good and distance(a, b)/dt > 200/3.6:
            good = False
        if not good:
            rejected += 1
            finish_run()
            previous_harsh = {}
            continue
        driver = attribution(assignments, a['time'], b['time'])
        moving = min(a['speed'], b['speed']) >= 5
        if moving:
            observed += dt
            if driver:
                stats[driver]['driving_seconds'] += dt
        over = limit is not None and min(a['speed'], b['speed']) > limit + policy.tolerance_kph
        if over:
            if run and run['end'] == a['time'] and run['driver_id'] == driver:
                run['end'] = b['time']
                run['duration_seconds'] += dt
                run['max_speed_kph'] = max(run['max_speed_kph'], b['speed'])
                run['source_point_ids'][-1] = b['id']
            else:
                finish_run()
                run = event('SPEEDING', a, b, driver, max_speed_kph=max(a['speed'], b['speed']), limit_kph=limit)
            if driver:
                # All observed excess intervals contribute, including short observations.
                stats[driver]['speeding_seconds'] += dt
                severity = min(1, ((a['speed']+b['speed'])/2-limit-policy.tolerance_kph)/limit)
                stats[driver]['speed_severity_seconds'] += severity*dt
        else:
            finish_run()
        if dt > policy.harsh_gap_seconds:
            previous_harsh = {}
            continue
        if moving:
            high_frequency += dt
            if driver:
                stats[driver]['high_frequency_seconds'] += dt
        acceleration = (b['speed']-a['speed']) / 3.6 / dt
        values = {'HARD_BRAKING': max(0, -acceleration), 'RAPID_ACCELERATION': max(0, acceleration)}
        thresholds = {'HARD_BRAKING': policy.braking_mps2, 'RAPID_ACCELERATION': policy.acceleration_mps2,
                      'HARSH_CORNERING': policy.cornering_mps2}
        if a['heading'] is not None and b['heading'] is not None and moving:
            heading_seconds += dt
            if driver:
                stats[driver]['heading_seconds'] += dt
            turn = abs((b['heading']-a['heading']+180) % 360-180)
            values['HARSH_CORNERING'] = (a['speed']+b['speed'])/7.2 * math.radians(turn)/dt
        current_harsh = {}
        for kind, value in values.items():
            if value < thresholds[kind]:
                continue
            previous = previous_harsh.get(kind)
            if previous and previous['end'] == a['time'] and previous['driver_id'] == driver:
                previous['end'] = b['time']
                previous['duration_seconds'] += dt
                previous['peak_mps2'] = max(previous['peak_mps2'], value)
                previous['source_point_ids'][-1] = b['id']
                current_harsh[kind] = previous
            else:
                item = event(kind, a, b, driver, peak_mps2=value)
                events.append(item)
                current_harsh[kind] = item
                if driver:
                    stats[driver]['maneuvers'] += 1
        previous_harsh = current_harsh
    finish_run()
    drivers = []
    for driver, s in stats.items():
        reasons = []
        if not complete:
            reasons.append('Manba to‘liq o‘qilmagan')
        if limit is None:
            reasons.append('Tezlik chegarasi sozlanmagan')
        if s['driving_seconds'] < policy.minimum_driving_minutes*60:
            reasons.append('Haydovchiga tegishli kuzatilgan harakat vaqti yetarli emas')
        speed_index = (min(100, 100*s['speed_severity_seconds']/s['driving_seconds'])
                       if s['driving_seconds'] and not reasons else None)
        score = speed_index
        if policy.include_maneuvers_in_score:
            coverage = s['heading_seconds']/s['driving_seconds'] if s['driving_seconds'] else 0
            if coverage < .9:
                reasons.append('Keskin harakatlar uchun yuqori chastota va yo‘nalish qamrovi 90% dan kam')
                score = None
            elif score is not None:
                maneuver_index = min(100, 100*s['maneuvers']/(s['high_frequency_seconds']/3600)/policy.maneuver_events_per_hour_at_100)
                score = .5*score + .5*maneuver_index
        drivers.append({'driver_id': driver, 'vehicle_id': str(vehicle['vehicle_id']),
                        'score': round(score, 1) if score is not None else None,
                        'speed_index': round(speed_index, 1) if speed_index is not None else None,
                        'scope': 'SPEED_AND_MANEUVERS' if policy.include_maneuvers_in_score else 'SPEED_ONLY',
                        'status': 'ASSESSED' if score is not None else 'INSUFFICIENT_DATA',
                        'reasons': reasons, **{k: round(v, 2) for k, v in s.items()}})
    return {**vehicle, 'events': events, 'drivers': drivers,
            'quality': {'points': len(points), 'valid_points': sum(p['speed'] is not None for p in unique),
                        'conflicting_timestamps': conflicts, 'rejected_intervals': rejected,
                        'median_gap_seconds': median(gaps) if gaps else None,
                        'observed_driving_seconds': observed, 'high_frequency_seconds': high_frequency,
                        'heading_seconds': heading_seconds, 'complete': complete,
                        'last_signal': unique[-1]['time'] if unique else None,
                        'unattributed_driving_seconds': observed-sum(s['driving_seconds'] for s in stats.values())},
            'speed_status': 'ASSESSED_INTERVALS' if limit is not None and observed else 'INSUFFICIENT_DATA',
            'maneuver_status': 'PARTIAL_OBSERVATION' if high_frequency else 'INSUFFICIENT_FREQUENCY'}
