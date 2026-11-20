from atil_ai_dispetcher import config
from atil_ai_dispetcher.fleet_yard_llm.config import ARCHIVE_SPEED_UNITS
from . import queries
from .models import SafetyRequest, ETARequest
from .safety import vehicle_report
from .eta import predict


def safety(payload):
    request = SafetyRequest.model_validate(payload or {})
    as_of = config.now()
    data = queries.safety_data(request, as_of)
    names = data.pop('driver_names')
    vehicles = []
    for packet in data.pop('packets'):
        report = vehicle_report(packet['vehicle'], packet['points'], packet['assignments'],
                                request.policy, ARCHIVE_SPEED_UNITS, data['start'], data['end'], packet['complete'])
        report['error'] = packet['error']
        for item in report['drivers'] + report['events']:
            item['driver_name'] = names.get(item.get('driver_id'))
        vehicles.append(report)
    events = sorted([e for v in vehicles for e in v['events']], key=lambda e: e['start'], reverse=True)
    drivers = [d for v in vehicles for d in v['drivers']]
    partial = bool(data['errors'] or data['vehicles_truncated'] or any(v['error'] for v in vehicles))
    return {'generated_at': as_of, 'status': 'PARTIAL' if partial else ('COMPLETE' if vehicles else 'EMPTY'),
            'policy': request.policy.model_dump(), 'period': {'start': data['start'], 'end': data['end']},
            'vehicles': vehicles, 'drivers': drivers, 'events': events[:1000],
            'summary': {'vehicles': len(vehicles), 'events': len(events),
                        'assessed_driver_vehicle_pairs': sum(d['score'] is not None for d in drivers),
                        'unattributed_events': sum(e['driver_id'] is None for e in events)},
            'data_quality': {**data, 'display_events_truncated': len(events)>1000},
            'method': {'version': 'safety-v1', 'score': '100 × excess severity seconds / attributed observed driving seconds',
                       'severity': 'min(1, (average speed - limit - tolerance) / limit); both endpoints must exceed threshold',
                       'maneuvers': 'Optional: 50% speed index + 50% capped events/hour index; requires 90% high-frequency heading coverage',
                       'meaning': 'Kuzatilgan davr va transport bo‘yicha indeks. Avariya ehtimoli yoki umumiy haydovchi reytingi emas.',
                       'limits': 'Korxona kiritgan tezlik chegarasi; yo‘ldagi qonuniy tezlik limiti aniqlanmaydi. GPSdan olingan hodisalar tekshiruv talab qiladi.'}}


def eta(payload):
    request = ETARequest.model_validate(payload or {})
    as_of = config.now()
    data = queries.eta_data(request, as_of)
    items = [predict(t, data['history'], request, as_of, data['history_complete']) for t in data['trips']]
    return {'generated_at': as_of, 'status': 'PARTIAL' if data['trips_truncated'] or not data['history_complete'] else 'COMPLETE',
            'items': items, 'parameters': request.model_dump(),
            'summary': {'trips': len(items), 'predicted': sum(i['eta'] is not None for i in items),
                        'warnings': sum(i['delay_status'] in ('OVERDUE','LIKELY_DELAY','POSSIBLE_DELAY') for i in items)},
            'data_quality': {'history_rows': len(data['history']), 'history_complete': data['history_complete'],
                             'trips_truncated': data['trips_truncated']},
            'method': {'version': 'historical_duration_v1', 'target': 'trip.actual_arrival_at — reysning yetib kelish vaqti',
                       'interval': 'O‘xshash tarixdagi davomiylikning 10–90 percentil oralig‘i; kafolat yoki kalibrlangan ehtimol emas.',
                       'limits': 'Tirbandlik, ob-havo va jonli GPS marshrut taraqqiyoti modelga kiritilmagan. Garajga qaytish vaqti ETA o‘rniga ishlatilmaydi.',
                       'legacy_time': 'Tarixda juft legacy vaqtlar farqi; faol reysda zonali vaqt yoki operator tasdiqlagan legacy zona talab qilinadi.'}}
