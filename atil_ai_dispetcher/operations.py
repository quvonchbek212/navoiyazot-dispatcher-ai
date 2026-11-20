"""Source-backed operations: one request is checked independently, never pooled."""
from collections import Counter
from datetime import timedelta
from . import config,repository

ACTIVE=['PLANNED','ASSIGNED','STARTED','ARRIVED_AT_POINT','LOADED','UNLOADED']
TERMINAL_REPAIRS=['CLOSED','COMPLETED','CANCELLED','ARM_CLOSED','REJECTED','REPAIRED']

def drivers():
    today=config.now().date()
    rows=repository.rows('''SELECT d.id::text driver_id,d.full_name,d.employment_status,d.driver_availability_status,
        d.license_valid_until,d.medical_certificate_valid_until,
        m.status medical_status,m.shift_date medical_date,
        EXISTS(SELECT 1 FROM trip t WHERE t.driver_id=d.id AND t.status=ANY(%s)) busy_trip,
        EXISTS(SELECT 1 FROM waybill w WHERE w.driver_id=d.id AND w.status IN ('ISSUED','IN_USE')) busy_waybill,
        count(*) OVER() total_count
        FROM driver d LEFT JOIN LATERAL (SELECT status,shift_date FROM medical_inspection m
          WHERE m.driver_id=d.id AND m.shift_date<=%s AND m.inspected_at<=current_timestamp ORDER BY shift_date DESC,inspected_at DESC LIMIT 1) m ON true
        WHERE to_jsonb(d)->>'deleted_at' IS NULL ORDER BY d.full_name,d.id LIMIT 2000''',(ACTIVE,today))
    for d in rows:
        reasons=[]
        if d['employment_status']!='ACTIVE':reasons.append('Ish holati ACTIVE emas')
        if d.get('driver_availability_status') not in (None,'AVAILABLE'):reasons.append('Haydovchining ishga chiqish holati cheklangan')
        if d['busy_trip']:reasons.append('Faol reys bilan band')
        if d['busy_waybill']:reasons.append('Ochiq yo‘l varaqasi bor')
        if not d['license_valid_until']:reasons.append('Guvohnoma muddati noma’lum')
        elif d['license_valid_until']<today:reasons.append('Guvohnoma muddati o‘tgan')
        if d['medical_date']!=today or d['medical_status']!='FIT':reasons.append('Bugungi FIT tibbiy ko‘rik tasdiqlanmagan')
        if d['medical_certificate_valid_until'] and d['medical_certificate_valid_until']<today:reasons.append('Tibbiy ma’lumotnoma muddati o‘tgan')
        d['reasons']=reasons;d['basic_checks_passed']=not reasons
    return {'items':rows,'total':int(rows[0]['total_count']) if rows else 0,'returned':len(rows),
            'truncated':bool(rows and rows[0]['total_count']>len(rows)),
            'summary':{'basic_checks_passed':sum(d['basic_checks_passed'] for d in rows)},'on_date':today}

def vehicles():
    today=config.now().date()
    rows=repository.rows('''SELECT v.id::text vehicle_id,v.plate_number,v.brand,v.model,v.transport_type,v.current_status,
        coalesce(v.payload_capacity_kg,v.cargo_capacity_tons*1000) capacity_kg,
        coalesce(v.seat_count,v.passenger_capacity) seat_count,v.volume_m3 cargo_volume_m3,
        t.status technical_status,t.inspected_at::date technical_date,
        EXISTS(SELECT 1 FROM trip tr WHERE tr.vehicle_id=v.id AND tr.status=ANY(%s)) busy_trip,
        EXISTS(SELECT 1 FROM waybill w WHERE w.vehicle_id=v.id AND w.status IN ('ISSUED','IN_USE')) busy_waybill,
        EXISTS(SELECT 1 FROM trip tr WHERE tr.vehicle_id=v.id AND tr.status IN ('STARTED','ARRIVED_AT_POINT','LOADED','UNLOADED')) operating_trip,
        EXISTS(SELECT 1 FROM waybill w WHERE w.vehicle_id=v.id AND w.status='IN_USE') operating_waybill,
        EXISTS(SELECT 1 FROM trip tr WHERE tr.vehicle_id=v.id AND tr.status=ANY(%s)
          AND (tr.actual_arrival_at IS NOT NULL OR tr.release_return_instant IS NOT NULL
               OR tr.release_departure_instant>current_timestamp)) trip_conflict,
        EXISTS(SELECT 1 FROM waybill w WHERE w.vehicle_id=v.id AND w.status IN ('ISSUED','IN_USE')
          AND (w.actual_return_at IS NOT NULL OR w.actual_departure_at>current_timestamp)) waybill_conflict,
        EXISTS(SELECT 1 FROM vehicle_repair r WHERE r.vehicle_id=v.id AND NOT(r.status=ANY(%s)) AND r.blocks_release) blocking_repair,
        EXISTS(SELECT 1 FROM transport_request r WHERE r.binding_vehicle_id=v.id AND r.status=ANY(%s)) request_bound,
        count(*) OVER() total_count
        FROM transport_vehicle v LEFT JOIN LATERAL (SELECT status,inspected_at
          FROM vehicle_technical_inspection t WHERE t.vehicle_id=v.id AND t.inspected_at<=current_timestamp
          ORDER BY inspected_at DESC,t.created_at DESC LIMIT 1) t ON true
        ORDER BY v.plate_number,v.id LIMIT 2000''',(ACTIVE,ACTIVE,TERMINAL_REPAIRS,repository.WAITING))
    for v in rows:
        reasons=[]
        if v['current_status']!='ACTIVE':reasons.append('Transport holati tekshiruv talab qiladi')
        if v.get('blocking_repair'):reasons.append('Ishga chiqishni cheklovchi ochiq ta’mir bor')
        if v.get('trip_conflict') or v.get('waybill_conflict'):reasons.append('Bandlik va yakun yoki vaqt yozuvlari zid')
        if v['busy_trip']:reasons.append('Faol reys bilan band')
        if v['busy_waybill']:reasons.append('Ochiq yo‘l varaqasi bor')
        if v.get('request_bound'):reasons.append('Navbatdagi arizaga avvaldan biriktirilgan')
        if v['technical_status']!='FIT' or v['technical_date']!=today:reasons.append('Bugungi FIT texnik ko‘rik tasdiqlanmagan')
        v['reasons']=reasons;v['basic_checks_passed']=not reasons
    return {'items':rows,'total':int(rows[0]['total_count']) if rows else 0,'returned':len(rows),
            'truncated':bool(rows and rows[0]['total_count']>len(rows)),'on_date':today}

def trips():
    as_of=config.now()
    rows=repository.rows('''SELECT t.id::text trip_id,t.trip_number,t.status,v.plate_number,d.full_name driver_name,
        t.planning_start_instant planned_start,t.planning_end_instant planned_end,
        t.release_departure_instant actual_start,
        (t.actual_arrival_at IS NOT NULL OR t.release_return_instant IS NOT NULL) completion_mark,
        t.updated_at,count(*) OVER() total_count
        FROM trip t LEFT JOIN transport_vehicle v ON v.id=t.vehicle_id LEFT JOIN driver d ON d.id=t.driver_id
        WHERE t.status=ANY(%s) ORDER BY t.updated_at DESC,t.id LIMIT 500''',(ACTIVE,))
    for r in rows:
        conflict=r['completion_mark'] or (r['planned_start'] and r['planned_end'] and r['planned_end']<r['planned_start'])
        conflict=conflict or any(r[k] and r[k].year<2000 for k in ('planned_start','planned_end'))
        conflict=conflict or bool(r.get('actual_start') and r['actual_start']>as_of)
        state='DATA_CONFLICT' if conflict else 'NO_ZONED_PLAN' if not r['planned_end'] else 'PLAN_OVERDUE' if r['planned_end']<as_of else 'WITHIN_PLAN'
        r['control_status']=state
        r['overdue_minutes']=round((as_of-r['planned_end']).total_seconds()/60) if state=='PLAN_OVERDUE' else None
    return {'items':rows,'total':int(rows[0]['total_count']) if rows else 0,'returned':len(rows),
            'truncated':bool(rows and rows[0]['total_count']>len(rows)),
            'summary':dict(Counter(r['control_status'] for r in rows)),'checked_at':as_of,
            'scope':'Reja vaqti nazorati; kelajakdagi yetib kelish prognozi emas. Faqat zonali reja vaqti ishlatiladi.'}

def documents(driver_report):
    today=config.now().date();items=[]
    for d in driver_report['items']:
        for key,label in [('license_valid_until','Haydovchilik guvohnomasi'),('medical_certificate_valid_until','Tibbiy ma’lumotnoma')]:
            expiry=d.get(key)
            if expiry and expiry<=today+timedelta(days=30):
                items.append({'driver_id':d['driver_id'],'name':d['full_name'],'document':label,
                              'valid_until':expiry,'days_left':(expiry-today).days,'expired':expiry<today})
    return {'items':items,'summary':{'total':len(items),'expired':sum(i['expired'] for i in items)},
            'scope':'Haydovchining bazada mavjud muddatlari; sug‘urta va bo‘sh hujjat manbalari hisobga olinmaydi.'}

def sources():
    names=['transport_request','transport_vehicle','driver','trip','waybill','medical_inspection',
           'vehicle_technical_inspection','vehicle_gps']
    items=[]
    for name in names:
        n=repository.rows(f'SELECT count(*) n FROM {name}')[0]['n']
        items.append({'table':name,'rows':n,'state':'PRESENT' if n else 'EMPTY'})
    return {'items':items,'scope':'Faol loyiha manbalari. Qator borligi barcha ustunlar to‘liq ekanini bildirmaydi.'}

def assess_vehicle(req,v):
    """Shared single-request checks, reused by queue diagnostics without DB N+1."""
    missing=[];reasons=list(v.get('reasons',[]))
    if any(req.get(k) is not None and req[k]<0 for k in ('cargo_weight_kg','cargo_volume_m3','passengers')):
        missing.append('Yuk yoki yo‘lovchi miqdori noto‘g‘ri yozilgan')
    for need,capacity,title in [('cargo_weight_kg','capacity_kg','Yuk og‘irligi / transport sig‘imi'),
                                ('cargo_volume_m3','cargo_volume_m3','Yuk hajmi / transport hajmi'),
                                ('passengers','seat_count','Yo‘lovchilar / o‘rindiqlar')]:
        amount=req.get(need)
        if amount is not None and amount>0:
            if not v.get(capacity) or v[capacity]<=0:missing.append(title+' noma’lum')
            elif amount>v[capacity]:reasons.append(title+' yetmaydi')
    if not any(req.get(k) and req[k]>0 for k in ('cargo_weight_kg','cargo_volume_m3','passengers')):
        missing.append('Ariza yuk yoki yo‘lovchi miqdori ko‘rsatilmagan')
    return {'reasons':reasons,'unverified':missing,
            'status':'BLOCKED' if reasons else 'NEEDS_REVIEW' if missing else 'BASIC_CHECKS_PASSED'}

def selection(request_id):
    req=repository.rows('''SELECT id::text request_id,request_number,status,required_transport_type,
        origin_location,destination_location,coalesce(cargo_weight_kg,cargo_weight_tons*1000) cargo_weight_kg,cargo_volume_m3,
        passenger_count passengers FROM transport_request WHERE id=%s::uuid''',(str(request_id),))
    if not req:raise ValueError('Ariza topilmadi')
    req=req[0]
    if req['status'] not in repository.WAITING:raise ValueError('Ariza rejalashtirish navbatida emas; holatni yangilang')
    if not req['required_transport_type']:raise ValueError('Arizada transport turi ko‘rsatilmagan')
    fleet=vehicles();staff=drivers();candidates=[]
    for v in fleet['items']:
        if v['transport_type']!=req['required_transport_type']:continue
        candidates.append({**v,**assess_vehicle(req,v)})
    candidates.sort(key=lambda v:({'BASIC_CHECKS_PASSED':0,'NEEDS_REVIEW':1,'BLOCKED':2}[v['status']],v['plate_number'] or ''))
    return {'contract_version':2,'generated_at':config.now(),'request':req,'vehicles':candidates,'drivers':staff['items'],
            'summary':{'vehicles_of_type':len(candidates),'vehicle_checks_passed':sum(v['status']=='BASIC_CHECKS_PASSED' for v in candidates),
                       'driver_checks_passed':staff['summary']['basic_checks_passed']},
            'data_quality':{'vehicles_truncated':fleet['truncated'],'drivers_truncated':staff['truncated']},
            'execution':{'status':'REVIEW_ONLY','message':'Bitta ariza alohida tekshirildi. Transport yoki haydovchi biriktirilmadi.'},
            'limitations':['Bandlik hozirgi faol yozuvlar bo‘yicha; kelajak smena bandligi hisoblanmaydi.',
                           'Haydovchi toifasining aynan shu transportga mosligi dispetcher tomonidan tekshiriladi.',
                           'Moslik tekshiruvi biriktirishga ruxsat yoki kafolat emas.']}
