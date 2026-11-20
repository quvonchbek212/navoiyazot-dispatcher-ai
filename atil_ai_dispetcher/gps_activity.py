"""Shared, bounded GPS history collection and observed daily activity.

ATIL data stays read-only. No driving-risk, engine-idling or road-distance claims.
"""
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import time

from . import config, gps, gps_api, garage

MAX_VEHICLES = 200
MAX_WORKERS = 6
COLLECTION_SECONDS = 90


def unavailable(vehicle, start, end, code):
    return {'vehicle': vehicle, 'source': 'ATIL_API', 'period': {'start': start, 'end': end},
            'points': [], 'complete': False, 'quality': {}, 'error': code, 'fallback_reason': code}


def collect(current, settings):
    """Fetch a history once for both today's summary and the garage window.

    Six concurrent clients; a shared time budget prevents an outage from queuing
    hundreds of full-length timeouts. Every selected vehicle still gets a result.
    """
    end = config.now()
    midnight = end.astimezone(config.TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    start = min(midnight, end - timedelta(hours=settings.garage_hours)) if settings.garage else midnight
    current = current or {}
    rows = current.get('items', [])[:MAX_VEHICLES]
    batch = {'period': {'start': start, 'end': end}, 'items': [], 'daily_summaries': {},
             'total': len(current.get('items', [])),
             'truncated': bool(current.get('truncated')) or len(current.get('items', [])) > MAX_VEHICLES,
             'daily_error': None}
    if not rows:
        batch['daily_error'] = 'NO_GPS_VEHICLES'
        return batch
    if not gps_api.configured():
        batch['items'] = [unavailable({'vehicle_id': r['vehicle_id'], 'plate_number': r.get('plate_number')},
                                     start, end, 'NOT_CONFIGURED') for r in rows]
        batch['daily_error'] = 'NOT_CONFIGURED'
        return batch
    deadline = time.monotonic() + COLLECTION_SECONDS
    permitted = [r['vehicle_id'] for r in rows if r.get('state') != 'ACCESS_REVOKED']
    client = gps_api.GPSClient()
    token = None
    try:
        for offset in range(0, len(permitted), 100):
            batch['daily_summaries'].update(client.daily_summaries(permitted[offset:offset+100]))
        token = getattr(client, 'token', None)
    except gps_api.GPSAPIError as exc:
        batch['daily_error'] = str(exc)
    finally:
        client.close()

    def fetch(row):
        vehicle = {'vehicle_id': row['vehicle_id'], 'plate_number': row.get('plate_number')}
        if row.get('state') == 'ACCESS_REVOKED':
            return unavailable(vehicle, start, end, 'API_ACCESS_REVOKED')
        if batch['daily_error'] in ('ACCESS_DENIED', 'INVALID_TOKEN'):
            return unavailable(vehicle, start, end, batch['daily_error'])
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return unavailable(vehicle, start, end, 'COLLECTION_TIMEOUT')
        history_client = gps_api.GPSClient()
        if token and hasattr(history_client, 'token') and not history_client.token:
            history_client.token = token
        try:
            raw = history_client.history(vehicle['vehicle_id'], start, end, budget_seconds=min(45, remaining))
            return gps.api_history(vehicle, raw, start, end)
        except gps_api.GPSAPIError as exc:
            return unavailable(vehicle, start, end, str(exc))
        except Exception:
            # Worker exceptions never expose provider bodies, URLs or credentials.
            return unavailable(vehicle, start, end, 'HISTORY_UNAVAILABLE')
        finally:
            history_client.close()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='gps-observation') as pool:
        batch['items'] = list(pool.map(fetch, rows))
    return batch


def activity(history, start, end):
    """Sum only connected, trustworthy observation intervals within this day."""
    points, barriers, rejected = garage.normalize_observations(history.get('points', []), start, end)
    distance = 0.0
    covered = stopped = moving = 0.0
    gaps = pairs = classified = 0
    for a, b in zip(points, points[1:]):
        seconds = (b['time'] - a['time']).total_seconds()
        index = bisect_left(barriers, a['time'])
        if seconds > garage.MAX_GAP_SECONDS or (index < len(barriers) and barriers[index] <= b['time']):
            gaps += 1
            continue
        meters = garage.distance(a, b)
        distance += meters / 1000
        covered += seconds
        pairs += 1
        speeds = (a.get('speed_kph'), b.get('speed_kph'))
        if all(v is not None for v in speeds):
            if max(speeds) <= 1 and meters <= garage.STATIONARY_METERS:
                stopped += seconds
                classified += 1
            elif min(speeds) > 1:
                moving += seconds
                classified += 1
    return {'points': len(points), 'distance_km': round(distance, 3) if pairs else None,
            'observed_stop_minutes': round(stopped/60, 2) if classified else None,
            'observed_moving_minutes': round(moving/60, 2) if classified else None,
            'signal_gaps': gaps if points else None,
            'observed_minutes': round(covered/60, 2) if pairs else None,
            'first_signal_at': points[0]['time'] if points else None,
            'last_signal_at': points[-1]['time'] if points else None,
            'rejected': rejected}


def daily_report(batch):
    end = batch['period']['end']
    start = end.astimezone(config.TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    today = start.date().isoformat()
    items = []
    for history in batch.get('items', []):
        vehicle = history['vehicle']
        error = history.get('error')
        denied = error in ('ACCESS_DENIED', 'API_ACCESS_REVOKED')
        metrics = activity(history if not error else {'points': []}, start, end)
        daily = batch.get('daily_summaries', {}).get(vehicle['vehicle_id'])
        distance = metrics['distance_km']
        scope = 'ESTIMATED' if distance is not None else None
        source = 'GPS_POINTS' if distance is not None else None
        distance_at = metrics['last_signal_at'] if distance is not None else None
        daily_valid = (not denied and daily is not None and daily.get('date') == today
                       and daily.get('timezone') == 'Asia/Tashkent'
                       and daily['as_of'].astimezone(config.TIMEZONE).date() == start.date()
                       and -30 <= (end-daily['as_of']).total_seconds() <= 300)
        if daily_valid:
            total = daily.get('distanceKm')
            observed = daily.get('observedDistanceKm')
            if total is not None and daily.get('gps_state') == 'COMPLETE':
                distance, scope, source = total, 'TOTAL', 'ATIL_API'
            elif observed is not None:
                distance, scope, source = observed, 'OBSERVED', 'ATIL_API'
            elif total is not None:
                distance, scope, source = total, 'OBSERVED', 'ATIL_API'
            if source == 'ATIL_API':distance_at = daily['as_of']
        available = distance is not None or metrics['points'] > 0
        quality=history.get('quality',{})
        quality_loss=(quality.get('locally_excluded') or quality.get('limit_exceeded') or quality.get('trailing_untrusted')
                      or any(p.get('excludedCount') or p.get('gapCount') or p.get('limitExceeded') for p in quality.get('pages',[])))
        period=history.get('period',batch['period'])
        full_window=period['start']<=start and period['end']>=end
        # Page completion means all available points were read, not continuous
        # observation from midnight to now. Allow only the documented gap bound.
        edges_covered=(metrics['first_signal_at'] is not None and metrics['last_signal_at'] is not None
                       and (metrics['first_signal_at']-start).total_seconds()<=garage.MAX_GAP_SECONDS
                       and (end-metrics['last_signal_at']).total_seconds()<=garage.MAX_GAP_SECONDS)
        complete = (available and scope == 'TOTAL' and not error and history.get('complete') is True
                    and not quality_loss and full_window and edges_covered
                    and not metrics['signal_gaps'] and not metrics['rejected']
                    and metrics['observed_minutes'] is not None)
        items.append({**vehicle, **metrics, 'distance_km': round(distance, 3) if distance is not None else None,
                      'distance_scope': scope, 'distance_source': source, 'distance_as_of': distance_at,
                      'complete': complete, 'history_complete': history.get('complete') is True,
                      'status': 'COMPLETE' if complete else 'PARTIAL' if available else 'UNAVAILABLE',
                      'error': error, 'source_quality':quality, 'daily_summary_error': batch.get('daily_error') or
                          ('DAILY_WINDOW_UNCONFIRMED' if daily and not daily_valid and not denied else None)})
    def total(key):
        values = [i[key] for i in items if i[key] is not None]
        return round(sum(values), 3) if values else None
    available = sum(i['status'] != 'UNAVAILABLE' for i in items)
    partial = sum(i['status'] == 'PARTIAL' for i in items)
    complete = bool(items) and not batch.get('truncated') and all(i['complete'] for i in items)
    return {'date': today, 'period': {'start': start, 'end': end}, 'timezone': 'Asia/Tashkent',
            'status': 'COMPLETE' if complete else 'PARTIAL' if available else 'UNAVAILABLE', 'items': items,
            'summary': {'vehicles': len(items), 'available': available, 'unavailable': len(items)-available,
                        'partial': partial, 'distance_km': total('distance_km'),
                        'distance_scope': 'TOTAL' if complete else 'OBSERVED',
                        'observed_stop_minutes': total('observed_stop_minutes'), 'signal_gaps': total('signal_gaps')},
            'limitations': ['Hisob Toshkent vaqti bo‘yicha bugun yarim tundan hisob vaqtigacha berilgan.',
                            'GPS kuzatgan masofa to‘liq kunlik masofa tasdiqlanmaganida alohida ko‘rsatiladi.',
                            'Nuqtalardan hisoblangan masofa taxminiy; uzilgan bo‘laklar birlashtirilmaydi.',
                            'Harakat va to‘xtash davomiyligi faqat kuzatilgan oraliqlar uchun. Dvigatel holati aniqlanmaydi.',
                            'Signal yo‘qligi transport ishlamagani yoki bekor turganini anglatmaydi.',
                            'Hisob GPS kuzatuvi tanlangan transportlarni qamraydi; butun avtopark emas.']}
