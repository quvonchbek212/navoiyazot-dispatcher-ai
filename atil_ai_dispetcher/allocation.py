"""One-to-one queue recommendations from observed availability; no DB writes.

Priority-ordered augmenting paths preserve already served higher-priority
requests while moving their vehicles when that can serve another request.
Vehicles are used once in the entire proposal, even across different dates.
"""
from collections import Counter, deque
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from . import config, operations
from .Marshrut_optimizatsiyasi.geo import haversine_km

PRIORITY = {'CRITICAL': 0, 'URGENT': 1, 'HIGH': 2}
AMOUNTS = ('cargo_weight_kg', 'cargo_volume_m3', 'passengers')


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def order_time(value):
    try:
        t = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return t.timestamp() if t and t.tzinfo else float('inf')
    except (ValueError, AttributeError, OverflowError):
        return float('inf')


def request_order(r):
    return (PRIORITY.get(r.get('priority'), 3), order_time(r.get('planned_at')),
            order_time(r.get('created_at')), str(r.get('request_id') or ''))


def available(v):
    return (v.get('current_status') == 'ACTIVE' and v.get('busy_trip') is False
            and v.get('busy_waybill') is False
            and not any(v.get(k) for k in ('blocking_repair', 'trip_conflict', 'waybill_conflict', 'request_bound')))


def best_fit(req, v):
    # Capacity preference, not a money/distance/time optimization claim.
    extra = Decimal(0)
    for need, capacity in zip(AMOUNTS, ('capacity_kg', 'cargo_volume_m3', 'seat_count')):
        amount = number(req.get(need))
        if amount is not None and amount > 0:
            extra += (number(v.get(capacity)) - amount) / amount
    return extra, str(v.get('plate_number') or ''), str(v['vehicle_id'])


def coordinates(latitude, longitude):
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return None
    lat, lon = number(latitude), number(longitude)
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return float(lat), float(lon)


def origin(req):
    """Use a whole coordinate pair from one source, never mix missing halves."""
    direct = coordinates(req.get('origin_latitude'), req.get('origin_longitude'))
    if direct is not None:
        return direct, 'REQUEST'
    catalog = coordinates(req.get('origin_catalog_latitude'), req.get('origin_catalog_longitude'))
    return (catalog, 'LOCATION_CATALOG') if catalog is not None else (None, None)


def fresh_positions(report, as_of):
    """Validate actual point age again: a saved RECENT label can itself be old."""
    if not report:
        return {}
    freshness = number(report.get('freshness_seconds', 300))
    if freshness is None or freshness <= 0:
        return {}
    freshness = float(min(freshness, Decimal(300)))
    now = order_time(as_of)
    checked = order_time(report.get('checked_at'))
    if not 0 <= now - checked <= freshness:
        return {}
    rows = report.get('items', [])
    counts = Counter(row.get('vehicle_id') for row in rows)
    positions = {}
    for row in rows:
        vid, point = row.get('vehicle_id'), row.get('point') or {}
        pair = coordinates(point.get('latitude'), point.get('longitude'))
        age = now - order_time(point.get('time'))
        if (vid and counts[vid] == 1 and row.get('state') == 'RECENT' and pair is not None
                and point.get('quality') in ('VALID', 'API_VALIDITY_NOT_EXPOSED')
                and 0 <= age <= freshness):
            positions[vid] = {'coordinates': pair, 'time': point['time'], 'source': row.get('source')}
    return positions


def matching(edges):
    """Maximum matching, retaining the served priority prefix, without recursion."""
    owner, assigned = {}, {}
    possible = len({v for edge in edges for v in edge})
    for root in range(len(edges)):
        if len(owner) == possible:
            break
        pending, visited, via = deque([root]), {root}, {}
        free = None
        while pending and free is None:
            rid = pending.popleft()
            for vid in edges[rid]:
                if vid in via:
                    continue
                via[vid] = rid
                if vid not in owner:
                    free = vid
                    break
                previous = owner[vid]
                if previous not in visited:
                    visited.add(previous)
                    pending.append(previous)
        while free is not None:
            rid = via[free]
            old = assigned.get(rid)
            assigned[rid], owner[free] = free, rid
            free = old
    return assigned


def plan(requests, fleet, drivers=None, gps_report=None):
    report = {'version': 1, 'generated_at': config.now(), 'status': 'UNAVAILABLE',
              'total': requests.get('total') if requests is not None else None,
              'returned': 0, 'items': [], 'summary': None,
              'scope_limited': False, 'execution': 'REVIEW_ONLY',
              'limitations': ['Bu tavsiya; transport band qilinmadi va bazada biriktirish bajarilmadi.',
                             'Bandlik va ko‘rik hozirgi yozuvlar bo‘yicha. Kelajak smenasi, yo‘lga yetib borish vaqti va marshrut masofasi tekshirilmagan.',
                             'Bir transport bu tavsiyada faqat bitta arizaga beriladi. Yuklar birlashtirilmaydi.']}
    if requests is None or fleet is None:
        report['unavailable'] = [k for k, v in (('arizalar', requests), ('transportlar', fleet)) if v is None]
        return report
    rows = sorted(requests.get('items', []), key=request_order)
    positions = fresh_positions(gps_report, report['generated_at'])
    origins = [origin(req) for req in rows]
    vehicles = [{**v, **{k: number(v.get(k)) for k in ('capacity_kg', 'cargo_volume_m3', 'seat_count')}} for v in fleet.get('items', [])]
    vehicle_ids = Counter(v.get('vehicle_id') for v in vehicles)
    request_ids = Counter(r.get('request_id') for r in rows)
    # Already-bound requests are not allocated again, and their vehicles cannot
    # be offered to another waiting request even if a trip has not been opened.
    bound = {r.get('binding_vehicle_id') for r in rows if r.get('binding_vehicle_id')}
    by_type = {}
    usable = {}
    for v in vehicles:
        vid = v.get('vehicle_id')
        if not vid or vehicle_ids[vid] != 1:
            continue
        by_type.setdefault(v.get('transport_type'), []).append(v)
        if available(v) and v.get('basic_checks_passed') is True and not v.get('reasons') and vid not in bound:
            usable[vid] = v
    edges, items = [], []
    distances = []
    for index, req in enumerate(rows):
        item = {k: req.get(k) for k in ('request_id', 'request_number', 'priority', 'planned_at',
                                      'origin_location', 'destination_location', 'required_transport_type')}
        item.update(status='NEEDS_DATA', vehicle_id=None, plate_number=None, reasons=[], candidate_count=0)
        candidates = []
        measured = {}
        if not req.get('request_id') or request_ids[req.get('request_id')] != 1:
            item['reasons'].append('Arizaning yagona identifikatori tasdiqlanmagan.')
        elif req.get('binding_vehicle_id'):
            item['status'] = 'ALREADY_BOUND'
            item['reasons'].append('Arizada avvalgi biriktirish mavjud. Qayta transport tavsiya qilinmadi.')
        elif req.get('status') not in ('APPROVED', 'READY_FOR_PLANNING'):
            item['reasons'].append('Ariza rejalashtirish navbatida emas.')
        elif not req.get('required_transport_type'):
            item['reasons'].append('Kerakli transport turi ko‘rsatilmagan.')
        elif any(req.get(k) is not None and (number(req[k]) is None or number(req[k]) < 0) for k in AMOUNTS):
            item['reasons'].append('Yuk yoki yo‘lovchi miqdori noto‘g‘ri yozilgan.')
        elif not any(number(req.get(k)) is not None and number(req[k]) > 0 for k in AMOUNTS):
            item['reasons'].append('Yuk og‘irligi, hajmi yoki yo‘lovchi sonini kiriting.')
        else:
            typed = by_type.get(req['required_transport_type'], [])
            normalized = {**req, **{k: number(req.get(k)) for k in AMOUNTS}}
            checks = [(v, operations.assess_vehicle(normalized, v)) for v in typed]
            candidates = [v for v, check in checks if v['vehicle_id'] in usable and check['status'] == 'BASIC_CHECKS_PASSED']
            start, _ = origins[index]
            if start is not None:
                measured = {v['vehicle_id']: haversine_km(*start, *positions[v['vehicle_id']]['coordinates'])
                            for v in candidates if v['vehicle_id'] in positions}
            candidates.sort(key=lambda v: (v['vehicle_id'] not in measured,
                                            measured.get(v['vehicle_id'], float('inf')), *best_fit(req, v)))
            item['candidate_count'] = len(candidates)
            item['status'] = 'SHORTAGE' if candidates else 'NO_MATCH'
            if not typed:
                item['reasons'].append('Ko‘rilgan parkda kerakli turdagi transport topilmadi.')
            elif not candidates:
                obstacles = Counter(why for _, c in checks for why in set(c['reasons'] + c['unverified']))
                item['reasons'] = [f'{why} ({n} ta transportda).' for why, n in sorted(obstacles.items(), key=lambda x: (-x[1], x[0]))[:4]]
                if any(v['vehicle_id'] in bound for v in typed):
                    item['reasons'].append('Ayrim transportlar navbatdagi boshqa arizalarda allaqachon biriktirilgan.')
                if not item['reasons']:
                    item['reasons'].append('Transportning bo‘shligi va ishga tayyorligi to‘liq tasdiqlanmagan.')
        edges.append([v['vehicle_id'] for v in candidates])
        distances.append(measured)
        item['candidates_with_distance'] = len(measured)
        items.append(item)
    groups = {}
    for index, req in enumerate(rows):
        groups.setdefault(req.get('required_transport_type'), []).append(index)
    assigned = {}
    for indices in groups.values():
        for local_index, vid in matching([edges[i] for i in indices]).items():
            assigned[indices[local_index]] = vid
    for index, item in enumerate(items):
        if index in assigned:
            v = usable[assigned[index]]
            item.update(status='RECOMMENDED', vehicle_id=v['vehicle_id'], plate_number=v.get('plate_number'),
                        reasons=['Transport turi va arizada yozilgan sig‘im talablari mos. Hozirgi bandlik va asosiy ko‘rik tekshiruvlaridan o‘tgan.'])
            vid = v['vehicle_id']
            start, source = origins[index]
            position = positions.get(vid)
            item['proximity'] = {'status': 'NO_ORIGIN_COORDINATES' if start is None else 'NO_FRESH_GPS' if position is None else 'AVAILABLE',
                                 'distance_km': round(distances[index][vid], 2) if vid in distances[index] else None,
                                 'method': 'STRAIGHT_LINE', 'origin_source': source,
                                 'gps_source': position['source'] if position else None,
                                 'gps_time': position['time'] if position else None}
        elif item['status'] == 'SHORTAGE':
            item['reasons'] = ['Mos bo‘sh transportlar ushbu tavsiyadagi boshqa arizalarga tanlangan; qo‘shimcha transport kerak.']
    limited = bool(requests.get('truncated') or fleet.get('truncated'))
    report.update(status='PARTIAL' if limited else 'COMPLETE', returned=len(rows), items=items, scope_limited=limited,
                  summary={'considered': len(rows), 'recommended': len(assigned),
                           'needs_data': sum(i['status'] == 'NEEDS_DATA' for i in items),
                           'no_match': sum(i['status'] == 'NO_MATCH' for i in items),
                           'shortage': sum(i['status'] == 'SHORTAGE' for i in items),
                           'already_bound': sum(i['status'] == 'ALREADY_BOUND' for i in items),
                           'available_vehicles': sum(available(v) for v in vehicles), 'ready_vehicles': len(usable),
                           'requests_with_origin_coordinates': sum(p is not None for p, _ in origins),
                           'ready_vehicles_with_fresh_gps': len(set(usable) & set(positions)),
                           'recommendations_with_distance': sum(i.get('proximity', {}).get('status') == 'AVAILABLE' for i in items),
                           'recommendations_without_distance': sum(i['status'] == 'RECOMMENDED' and i.get('proximity', {}).get('status') != 'AVAILABLE' for i in items),
                           'driver_checks_passed': sum(d.get('basic_checks_passed') is True for d in drivers.get('items', [])) if drivers is not None else None})
    report['limitations'].append('Yaqinlik faqat yangi GPS nuqtasi va yuk olish joyining koordinatasi bo‘lsa hisoblanadi. Masofa to‘g‘ri chiziq bo‘yicha taxmin; yo‘l masofasi yoki yetib borish vaqti emas. Koordinata yetishmasligi mos transportni tanlovdan chiqarmaydi.')
    report['limitations'].append('Mos transportlar avval o‘lchangan yaqinlik, keyin sig‘im bo‘yicha saralanadi. Ko‘proq arizani qamrash uchun transportlar qayta taqsimlanishi mumkin; har bir arizaga mutlaq eng yaqin transport kafolatlanmaydi.')
    if limited:
        report['limitations'].append('Arizalar yoki transportlar ro‘yxati kesilgan; tavsiya faqat ko‘rilgan yozuvlar bo‘yicha.')
    return report


def blocks(report):
    from .narrative import block, reason, value
    if report['status'] == 'UNAVAILABLE':
        return [block('allocation', 'Arizalarga transport tanlash bajarilmadi: '+', '.join(report['unavailable'])+' ma’lumoti olinmagan.', 'Ma’lumot kelgach umumiy tahlilni yangilang.', 'caution')]
    c = report['summary']
    text = f"Navbatdagi {value(report['total'])} ta arizadan {c['considered']} tasi birgalikda tekshirildi. {c['recommended']} tasiga alohida transport tavsiya qilindi. "
    if c['no_match']:text += f"{c['no_match']} tasiga mos tayyor transport topilmadi. "
    if c['shortage']:text += f"{c['shortage']} tasiga mos transportlar boshqa arizalarga tanlangan. "
    if c['needs_data']:text += f"{c['needs_data']} tasida ariza ma’lumotini aniqlashtirish kerak. "
    if c['already_bound']:text += f"{c['already_bound']} tasida avvalgi biriktirish bor. "
    text += f"Ko‘rilgan parkda {c['available_vehicles']} ta transportda bandlik yoki ishlash cheklovi qayd etilmagan; {c['ready_vehicles']} tasi ko‘rik bilan birga tanlov talablaridan o‘tgan. "
    text += 'Arizalar ustuvorlik va reja vaqtiga ko‘ra ko‘rildi. Bir transport bir nechta arizaga tanlanmaydi.'
    text += f" Yuk olish koordinatasi {c.get('requests_with_origin_coordinates', 0)} ta arizada mavjud. Tanlovga tayyor transportlardan {c.get('ready_vehicles_with_fresh_gps', 0)} tasining GPS nuqtasi yangi."
    if report['scope_limited']:
        text += ' Ro‘yxat qisqartirilgan: barcha arizalar yoki transportlar qamralmagan.'
    action = 'Tavsiya va ochiq to‘siqlarni tekshirib, amaldagi ATIL jarayonida biriktiring.' if c['recommended'] else 'Avval arizadagi ma’lumotlar va transportning tayyorligini aniqlashtiring, keyin tanlovni yangilang.' if c['considered'] else ''
    out = [block('allocation', text, action,
                 'attention' if c['considered'] != c['recommended'] else 'normal')]
    recommended, waiting = [], []
    def place(raw, fallback):
        if not raw:return fallback
        try:UUID(str(raw));return fallback
        except (ValueError, AttributeError):return str(raw)
    for i in report['items']:
        prefix = f"{i.get('request_number') or 'Raqamsiz ariza'} · {place(i.get('origin_location'), 'jo‘nash joyi nomi noma’lum')} → {place(i.get('destination_location'), 'borish joyi nomi noma’lum')}: "
        if i['status'] == 'RECOMMENDED':
            detail = prefix+f"{i.get('plate_number') or 'raqami ko‘rsatilmagan transport'} tavsiya qilindi. "+' '.join(reason(r) for r in i['reasons'])
            proximity = i.get('proximity', {})
            if proximity.get('status') == 'AVAILABLE':
                detail += f" Yangi GPS nuqtasidan yuk olish joyigacha to‘g‘ri chiziq bo‘yicha taxminan {value(proximity['distance_km'])} km; yo‘l masofasi hisoblanmagan."
            elif proximity.get('status') == 'NO_ORIGIN_COORDINATES':
                detail += ' Yuk olish joyining koordinatasi yo‘q; yaqinligi solishtirilmadi.'
            elif proximity.get('status') == 'NO_FRESH_GPS':
                detail += ' Yangi GPS nuqtasi yo‘q; yaqinligi solishtirilmadi.'
            recommended.append(detail)
        else:
            waiting.append(prefix+' '.join(reason(r) for r in i['reasons']))
    if recommended:
        out.append(block('allocation_matches', f'{len(recommended)} ta ariza uchun takrorlanmaydigan transport tanlovi:', details=recommended))
    if waiting:
        out.append(block('allocation_waiting', f'{len(waiting)} ta ariza bo‘yicha transport tavsiya qilinmagan. Har birining sababi:', details=waiting, severity='attention'))
    text = ' '.join(report['limitations'])
    text += f" Haydovchilardan {value(c['driver_checks_passed'])} nafari asosiy tekshiruvlardan o‘tgan; ular bu hisobda arizalarga taqsimlanmagan. Haydovchi toifasi, reys va vaqt shartlarini biriktirishdan oldin tekshiring."
    out.append(block('allocation_scope', text, severity='caution'))
    return out
