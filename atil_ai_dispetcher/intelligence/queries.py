"""Bounded, indexed reads. This module cannot mutate the ATIL database."""
import time
from datetime import timedelta, timezone
from atil_ai_dispetcher.fleet_yard_llm.queries import _cursor
from atil_ai_dispetcher.dispatcher_assistant.config import ACTIVE_TRIP_STATUSES
from .safety import instant

POINT_LIMIT = 5000
TOTAL_POINT_LIMIT = 50000
VEHICLE_LIMIT = 200
HISTORY_LIMIT = 10000


def read(query, params=()):
    with _cursor() as c:
        c.execute("SET LOCAL statement_timeout = '10000ms'")
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]


def safety_data(request, as_of):
    end = request.end_at or as_of
    if end > as_of:
        raise ValueError('Tahlil davri kelajakda tugashi mumkin emas')
    start = end-timedelta(hours=request.hours)
    vehicles = read('''SELECT v.id::text vehicle_id, v.plate_number
        FROM transport_vehicle v WHERE (%s IS NULL OR upper(v.plate_number)=upper(%s))
        AND EXISTS (SELECT 1 FROM vehicle_gps g WHERE g.vehicle_id=v.id)
        ORDER BY v.id LIMIT %s''', (request.plate_number, request.plate_number, VEHICLE_LIMIT+1))
    errors = []
    truncated = len(vehicles) > VEHICLE_LIMIT
    vehicles = vehicles[:VEHICLE_LIMIT]
    if request.plate_number and len(vehicles) > 1:
        raise ValueError('Bu raqamga bir nechta transport mos keldi')
    ids = [v['vehicle_id'] for v in vehicles]
    assignments = []
    assignment_complete = True
    if ids:
        try:
            assignments = read('''SELECT vehicle_id::text, driver_id::text,
                    actual_departure_at AS start, coalesce(actual_return_at,%s) AS "end", id::text source_id
                FROM waybill WHERE vehicle_id=ANY(%s::uuid[])
                    AND actual_departure_at <= %s AND coalesce(actual_return_at,%s) >= %s
                    AND status NOT IN ('CANCELLED','DRAFT')
                    AND (actual_return_at IS NOT NULL OR status NOT IN ('CLOSED','COMPLETED'))
                UNION ALL
                SELECT vehicle_id::text, driver_id::text, release_departure_instant,
                    coalesce(release_return_instant,%s), id::text
                FROM trip WHERE vehicle_id=ANY(%s::uuid[])
                    AND release_departure_instant <= %s AND coalesce(release_return_instant,%s) >= %s
                    AND status != 'CANCELLED'
                    AND (release_return_instant IS NOT NULL OR status != 'COMPLETED')
                LIMIT 10001''', (end, ids, end, end, start, end, ids, end, end, start))
            assignment_complete = len(assignments) <= 10000
            assignments = [a for a in assignments[:10000] if instant(a['start']) and instant(a['end']) and a['end'] > a['start']]
        except Exception:
            assignment_complete = False
        if not assignment_complete:
            assignments = []
            errors.append('Haydovchi biriktirish tarixi to‘liq o‘qilmadi; risk balli hisoblanmaydi')
    driver_names = {}
    driver_ids = sorted({a['driver_id'] for a in assignments if a.get('driver_id')})
    if driver_ids:
        try:
            driver_names = {r['id']: r['full_name'] for r in read(
                'SELECT id::text, full_name FROM driver WHERE id=ANY(%s::uuid[])', (driver_ids,))}
        except Exception:
            errors.append('Haydovchi ismlari o‘qilmadi; ID bilan ko‘rsatiladi')
    packets = []
    total = 0
    began = time.monotonic()
    for vehicle in vehicles:
        points = []
        error = None
        if total >= TOTAL_POINT_LIMIT or time.monotonic()-began > 60:
            error = 'Umumiy o‘qish chegarasiga yetildi; transportni alohida tanlang'
        else:
            try:
                allowance = min(POINT_LIMIT, TOTAL_POINT_LIMIT-total)
                points = read('''SELECT a.binding_id::text, a.provider_point_id, a.fix_time, a.payload,
                        g.provider_connection AS provider
                    FROM gps_archive_point a LEFT JOIN vehicle_gps g ON g.id=a.binding_id
                    WHERE a.vehicle_id=%s::uuid AND a.fix_time >= %s AND a.fix_time <= %s
                    ORDER BY a.fix_time, a.binding_id, a.provider_point_id LIMIT %s''',
                    (vehicle['vehicle_id'], start, end, allowance+1))
                if len(points) > allowance:
                    error = 'GPS nuqtalari chegarasiga yetildi; davrni qisqartiring'
                points = points[:allowance]
                total += len(points)
            except Exception:
                error = 'GPS arxivini o‘qib bo‘lmadi'
        packets.append({'vehicle': vehicle, 'points': points,
                        'assignments': [a for a in assignments if a['vehicle_id'] == vehicle['vehicle_id']],
                        'complete': error is None and assignment_complete, 'error': error})
    return {'start': start, 'end': end, 'packets': packets, 'errors': errors,
            'vehicles_truncated': truncated, 'point_limit_per_vehicle': POINT_LIMIT,
            'total_point_limit': TOTAL_POINT_LIMIT, 'driver_names': driver_names}


TRIP_SELECT = '''SELECT t.id::text, t.trip_number, t.status, t.vehicle_id::text, t.route_id::text,
    t.actual_departure_at, t.actual_arrival_at, t.scheduled_departure_at, t.scheduled_arrival_at,
    t.release_departure_instant, t.release_return_instant, t.planning_start_instant, t.planning_end_instant,
    v.plate_number, v.transport_type, r.origin_location_id::text, r.destination_location_id::text,
    coalesce(t.work_mode,r.work_mode) AS work_mode, r.trip_type
    FROM trip t LEFT JOIN transport_vehicle v ON v.id=t.vehicle_id
    LEFT JOIN transport_request r ON r.id=t.transport_request_id '''


def eta_data(request, as_of):
    trips = read(TRIP_SELECT+'''WHERE t.status=ANY(%s)
        AND (%s IS NULL OR upper(v.plate_number)=upper(%s))
        AND (t.planning_start_instant IS NULL OR t.planning_start_instant <= %s
             OR t.actual_departure_at IS NOT NULL OR t.release_departure_instant IS NOT NULL)
        ORDER BY t.planning_end_instant ASC NULLS LAST, t.id LIMIT 501''',
        (list(ACTIVE_TRIP_STATUSES), request.plate_number, request.plate_number, as_of+timedelta(hours=request.horizon_hours)))
    # History includes other vehicles on the same corridor; plate filtering it would bias the sample.
    history = read(TRIP_SELECT+'''WHERE t.status='COMPLETED'
        AND t.actual_arrival_at >= %s AND t.actual_arrival_at <= %s
        ORDER BY t.actual_arrival_at DESC, t.id LIMIT %s''',
        ((as_of.astimezone(timezone.utc)-timedelta(days=request.lookback_days)).replace(tzinfo=None),
         as_of.astimezone(timezone.utc).replace(tzinfo=None), HISTORY_LIMIT+1))
    return {'trips': trips[:500], 'history': history[:HISTORY_LIMIT],
            'history_complete': len(history) <= HISTORY_LIMIT, 'trips_truncated': len(trips) > 500}
