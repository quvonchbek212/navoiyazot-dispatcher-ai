"""Small table projections for the dispatcher's two operational tasks."""
from uuid import UUID


def label(value, fallback='—'):
    if not value:
        return fallback
    try:
        UUID(str(value))
        return fallback
    except (ValueError, AttributeError):
        return str(value)


def allocations(sections):
    plan = sections.get('allocation') or {}
    requests = {r['request_id']: r for r in sections.get('requests', {}).get('items', []) if r.get('request_id')}
    fleet = {v['vehicle_id']: v for v in sections.get('fleet', {}).get('items', []) if v.get('vehicle_id')}
    rows = []
    for item in plan.get('items', []):
        request = requests.get(item.get('request_id'), {})
        existing = item.get('status') == 'ALREADY_BOUND'
        vehicle_id = request.get('binding_vehicle_id') if existing else item.get('vehicle_id')
        vehicle = fleet.get(vehicle_id, {})
        rows.append({
            'id': item.get('request_id'),
            'name': label(request.get('request_title'), label(item.get('request_number'), 'Ariza')),
            'number': item.get('request_number'),
            'origin': label(item.get('origin_location')),
            'destination': label(item.get('destination_location')),
            'transport_type': item.get('required_transport_type'),
            'weight_kg': request.get('cargo_weight_kg'),
            'volume_m3': request.get('cargo_volume_m3'),
            'passengers': request.get('passengers'),
            'status': item.get('status'),
            'vehicle': {'id': vehicle_id, 'plate': vehicle.get('plate_number') or item.get('plate_number'),
                        'model': ' '.join(str(vehicle[k]) for k in ('brand', 'model') if vehicle.get(k)),
                        'capacity_kg': vehicle.get('capacity_kg'), 'volume_m3': vehicle.get('cargo_volume_m3'),
                        'seats': vehicle.get('seat_count'), 'technical_date': vehicle.get('technical_date')}
                       if vehicle_id else None,
            'reason': '' if item.get('status') == 'RECOMMENDED' else
                      'Avval biriktirilgan; bu hisobda qayta tanlanmadi.' if existing else
                      ' '.join(item.get('reasons', [])[:2]),
        })
    counts = plan.get('summary') or {}
    return {'status': plan.get('status', 'UNAVAILABLE'), 'total': plan.get('total'),
            'returned': len(rows), 'truncated': bool(plan.get('scope_limited')),
            'recommended': counts.get('recommended'), 'already_bound': counts.get('already_bound'),
            'items': rows}


def tracking(sections, settings):
    current = sections.get('gps') or {}
    daily = sections.get('gps_daily') or {}
    yard = sections.get('garage') or {}
    zone = settings.garage.model_dump() if settings.garage else None
    changed = bool(yard and (yard.get('garage') != zone or yard.get('hours') != settings.garage_hours
                           or yard.get('stop_threshold_minutes') != settings.garage_stop_minutes))
    daily_rows = {r['vehicle_id']: r for r in daily.get('items', [])}
    yard_rows = {} if changed else {r['vehicle_id']: r for r in yard.get('items', [])}
    current_rows = {r['vehicle_id']: r for r in current.get('items', []) if r.get('vehicle_id')}
    ids = dict.fromkeys([*current_rows, *daily_rows, *yard_rows])
    rows = []
    for vid in ids:
        c, d, g = current_rows.get(vid, {}), daily_rows.get(vid, {}), yard_rows.get(vid, {})
        point = c.get('point') or {}
        observed = not g.get('error') and (g.get('quality') or {}).get('points', 0) > 0
        rows.append({'id': vid, 'plate': c.get('plate_number') or d.get('plate_number') or g.get('plate_number'),
                     'signal': c.get('state', 'NO_VALID_SIGNAL'), 'last_signal_at': point.get('time'),
                     'speed_kph': point.get('speed_kph'),
                     'source': c.get('source'),
                     'garage_state': 'PENDING' if changed else g.get('state', 'NOT_CONFIGURED' if not zone else 'UNKNOWN'),
                     'entries': g.get('entries') if observed else None, 'exits': g.get('exits') if observed else None,
                     'distance_km': d.get('distance_km'), 'distance_scope': d.get('distance_scope'),
                     'stop_minutes': d.get('observed_stop_minutes'),
                     'garage_stop_minutes': g.get('observed_garage_stop_minutes') if observed else None,
                     'partial': d.get('status') == 'PARTIAL' or bool(observed and not g.get('quality', {}).get('complete'))})
    denied = current.get('api_note') == 'ACCESS_DENIED' or any(r.get('error') == 'ACCESS_DENIED' for r in daily_rows.values())
    issue = ('GPS xizmatiga kirish rad etilgan. API tokeni va kirish huquqini tekshiring.' if denied else
             'GPS manbasi hozir mavjud emas. Oxirgi kuzatuvlar ko‘rsatilmoqda.' if current.get('api_note') not in (None, 'NOT_CONFIGURED') else '')
    return {'items': sorted(rows, key=lambda r: r['plate'] or ''), 'issue': issue,
            'garage_changed': changed, 'garage': zone, 'garage_hours': settings.garage_hours,
            'period': daily.get('period'), 'truncated': bool(current.get('truncated') or yard.get('truncated'))}


def view(store, user):
    latest = store.latest_snapshot()
    report = latest['data'] if latest else {}
    settings = store.settings()
    sections = report.get('sections') or {}
    jobs = store.jobs()
    # Completed report history and raw evidence are not part of the work table.
    active = [{k: j.get(k) for k in ('id', 'kind', 'status', 'stage')} for j in jobs if j['status'] in ('queued', 'running')]
    latest_job = jobs[0] if jobs else {}
    return {'version': 3, 'user': user, 'job_id': latest['job_id'] if latest else None,
            'generated_at': report.get('generated_at'), 'allocation': allocations(sections),
            'tracking': tracking(sections, settings), 'settings': settings,
            'active_jobs': active,
            'last_error': 'Oxirgi yangilash bajarilmadi. Oldingi natija ko‘rsatilmoqda.'
                          if latest_job.get('status') in ('failed', 'interrupted') else None,
            'source_errors': [key for key in ('requests', 'fleet', 'gps', 'gps_daily', 'garage') if key in report.get('errors', {})]}


def job(item):
    out = {k: item.get(k) for k in ('id', 'kind', 'status', 'stage', 'error')}
    result = item.get('result') or {}
    out['observation'] = result.get('observation')
    out['vehicle'] = result.get('vehicle')
    out['period'] = result.get('period')
    out['garage'] = result.get('garage_view')
    out['fallback_reason'] = result.get('fallback_reason')
    out['complete'] = result.get('complete')
    if 'ai' in result:
        out['ai'] = result['ai']
    return out
