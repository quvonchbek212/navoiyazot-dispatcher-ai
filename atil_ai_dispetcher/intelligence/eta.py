"""Historical trip-completion ETA. No return-to-base or LLM timestamps are substituted."""
from datetime import datetime, timedelta, timezone
from statistics import median
import pytz
from .safety import instant


def local_time(value, zone):
    if not value or not zone:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.year < 2000:
        return None
    return value if value.tzinfo else pytz.timezone(zone).localize(value)


def time_value(row, modern, legacy, zone):
    value = instant(row.get(modern)) or local_time(row.get(legacy), zone)
    return value if value and value.year >= 2000 else None


def quantile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered)-1)*fraction
    low = int(position)
    high = min(low+1, len(ordered)-1)
    return ordered[low] + (ordered[high]-ordered[low])*(position-low)


def corridor(row):
    keys = ('origin_location_id', 'destination_location_id', 'transport_type', 'work_mode', 'trip_type')
    values = tuple(str(row.get(k) or '') for k in keys)
    return values if all(values) else None


def duration(row, as_of, lookback_days):
    # A shared legacy offset cancels in a duration. For historical membership use
    # the latest possible instant (UTC) so a Tashkent/UTC ambiguity cannot leak future arrivals.
    departure = local_time(row.get('actual_departure_at'), 'UTC')
    arrival = local_time(row.get('actual_arrival_at'), 'UTC')
    if row.get('status') != 'COMPLETED' or not departure or not arrival:
        return None
    seconds = (arrival-departure).total_seconds()
    if arrival > as_of or arrival < as_of-timedelta(days=lookback_days) or not 60 <= seconds <= 72*3600:
        return None
    # A known modern departure inconsistent with either legacy convention is rejected.
    modern = instant(row.get('release_departure_instant'))
    if modern and min(abs((departure-modern).total_seconds()), abs((departure-modern).total_seconds()-18000)) > 120:
        return None
    return seconds


def predict(trip, history, request, as_of, history_complete=True):
    start = time_value(trip, 'release_departure_instant', 'actual_departure_at', request.legacy_timezone)
    planned_start = time_value(trip, 'planning_start_instant', 'scheduled_departure_at', request.legacy_timezone)
    deadline = time_value(trip, 'planning_end_instant', 'scheduled_arrival_at', request.legacy_timezone)
    result = {'trip_id': str(trip['id']), 'trip_number': trip.get('trip_number'),
              'vehicle_id': str(trip.get('vehicle_id') or ''), 'plate_number': trip.get('plate_number'),
              'target': 'TRIP_ARRIVAL', 'as_of': as_of, 'planned_arrival': deadline,
              'eta': None, 'earliest': None, 'latest': None, 'delay_minutes': None,
              'sample_count': 0, 'status': 'INSUFFICIENT_DATA', 'reason': None,
              'delay_status': 'OVERDUE' if deadline and deadline < as_of else 'UNKNOWN',
              'method': 'historical_duration_v1', 'history_complete': history_complete}

    def unavailable(reason, invalid=False):
        result['reason'] = reason
        if invalid:
            result['delay_status'] = 'UNKNOWN'
        return result

    if not history_complete:
        return unavailable('Tarix to‘liq o‘qilmagan; transportni alohida tanlang')
    if trip.get('actual_arrival_at') or trip.get('release_return_instant'):
        return unavailable('Yakunlanganlik belgisi bilan faol holat zid; reys holatini tekshiring', True)
    if start and start > as_of:
        return unavailable('Haqiqiy jo‘nash vaqti kelajakda', True)
    legacy_start = local_time(trip.get('actual_departure_at'), request.legacy_timezone)
    modern_start = instant(trip.get('release_departure_instant'))
    if legacy_start and modern_start and abs((legacy_start-modern_start).total_seconds()) > 120:
        return unavailable('Zonali va eski jo‘nash vaqtlari zid; backend vaqtlarini tekshiring', True)
    if deadline and planned_start and deadline < planned_start:
        return unavailable('Reja yetib kelish vaqti jo‘nashdan oldin', True)
    if not start and trip.get('actual_departure_at') and not request.legacy_timezone:
        return unavailable('Haqiqiy jo‘nash vaqtining zonasi tasdiqlanmagan')
    if not start and trip.get('status') not in ('PLANNED', 'SCHEDULED', 'CREATED', 'ASSIGNED', 'READY'):
        return unavailable('Yo‘ldagi reysning jo‘nash vaqti noma’lum')
    if not start and not planned_start:
        return unavailable('Jo‘nash vaqti noma’lum')
    anchor = start or max(planned_start, as_of)
    result['start_basis'] = 'ACTUAL_DEPARTURE' if start else 'ASSUMED_DEPARTURE'
    result['departure'] = anchor
    eligible = [(row, d) for row in history if str(row['id']) != str(trip['id'])
                and (d := duration(row, as_of, request.lookback_days)) is not None]
    same_route = [d for row, d in eligible if trip.get('route_id') and row.get('route_id') == trip['route_id']
                  and trip.get('transport_type') and row.get('transport_type') == trip['transport_type']
                  and row.get('work_mode') == trip.get('work_mode')]
    group = corridor(trip)
    values = same_route
    result['cohort'] = 'SAME_ROUTE_AND_VEHICLE_TYPE'
    if len(values) < request.minimum_samples:
        values = [d for row, d in eligible if group and corridor(row) == group]
        result['cohort'] = 'SAME_CORRIDOR_TYPE_AND_WORK_MODE'
    result['cohort_samples'] = len(values)
    elapsed = max(0, (as_of-anchor).total_seconds()) if start else 0
    # Condition on still being in transit; do not clip a past ETA to "now + 1 minute".
    values = [v for v in values if v > elapsed]
    result['sample_count'] = len(values)
    if len(values) < request.minimum_samples:
        return unavailable('O‘xshash, hali davom etayotgan safarga mos yakunlangan reyslar yetarli emas')
    low, center, high = quantile(values, .1), median(values), quantile(values, .9)
    result.update(status='ESTIMATED', eta=anchor+timedelta(seconds=center),
                  earliest=anchor+timedelta(seconds=low), latest=anchor+timedelta(seconds=high),
                  duration_minutes=round(center/60, 1))
    if deadline:
        result['delay_minutes'] = round((result['eta']-deadline).total_seconds()/60, 1)
        if deadline < as_of:
            result['delay_status'] = 'OVERDUE'
        elif result['eta'] > deadline:
            result['delay_status'] = 'LIKELY_DELAY'
        elif result['latest'] > deadline:
            result['delay_status'] = 'POSSIBLE_DELAY'
        else:
            result['delay_status'] = 'WITHIN_HISTORICAL_RANGE'
    return result
