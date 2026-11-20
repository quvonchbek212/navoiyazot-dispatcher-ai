"""Shared read model: exact aggregates, explicit timestamps and missingness.

No database statistics used as row counts. Optional new columns are read
through to_jsonb so old ATIL schemas still work. Large GPS archives are not
scanned by dashboard refreshes.
"""
import sys
from atil_ai_dispetcher import PROJECT_ROOT
sys.path.insert(0,str(PROJECT_ROOT/'atil_chatbot'))
from db.connect_db_for_server import read_only_cursor

WAITING = ['APPROVED','READY_FOR_PLANNING']
START = "coalesce(nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz,r.planned_departure_at AT TIME ZONE 'Asia/Tashkent')"

def error_code(exc):
    """Expose an actionable category, never a DB address, username or password."""
    message=str(exc).lower()
    if any(s in message for s in ('permission denied','10013','access permissions','forbidden')):
        return 'DATABASE_NETWORK_BLOCKED'
    if any(s in message for s in ('password authentication','authentication failed','no password')):
        return 'DATABASE_AUTH_FAILED'
    if getattr(exc,'pgcode',None)=='57014':return 'DATABASE_QUERY_TIMEOUT'
    if any(s in message for s in ('timed out','timeout expired','connection timeout')):
        return 'DATABASE_CONNECT_TIMEOUT'
    return 'DATABASE_UNAVAILABLE'


def health():
    try:
        value=rows("SELECT current_timestamp checked_at,current_setting('transaction_read_only') read_only")[0]
        return {'status':'ok',**value}
    except Exception as exc:
        return {'status':'unavailable','code':error_code(exc)}


def rows(query,params=(),*,timeout_ms=10000):
    if isinstance(timeout_ms,bool) or not isinstance(timeout_ms,int) or not 1000<=timeout_ms<=60000:
        raise ValueError('Read timeout must be between 1000 and 60000 ms')
    with read_only_cursor() as c:
        c.execute("SET TRANSACTION READ ONLY")
        c.execute("SELECT set_config('statement_timeout',%s,true)",(str(timeout_ms),))
        c.execute("SET LOCAL TIME ZONE 'Asia/Tashkent'")
        c.execute(query,params)
        return [dict(r) for r in c.fetchall()]

def overview():
    return rows('''select
      (select count(*) from transport_vehicle) as vehicles,
      (select count(*) from driver where to_jsonb(driver)->>'deleted_at' is null) as drivers,
      (select count(*) from transport_request where status=any(%s)) as waiting,
      (select count(*) from trip where status in ('STARTED','ARRIVED_AT_POINT','LOADED','UNLOADED')) as active_trips,
      (select count(distinct vehicle_id) from vehicle_gps where active and unbound_at is null and verified_from<=current_timestamp) as gps_bound,
      current_timestamp as checked_at''',(WAITING,))[0]

def requests():
    result=rows(f'''select r.id::text as request_id,r.request_number,r.status,r.priority,
        coalesce(nullif(to_jsonb(r)->>'title',''),nullif(to_jsonb(r)->>'name','')) as request_title,
        r.required_transport_type,r.origin_location,r.destination_location,r.department_name,
        {START} as planned_at,r.created_at,r.submitted_at,r.transport_head_approved_at,
        coalesce(r.cargo_weight_kg,nullif(to_jsonb(r)->>'cargo_weight_tons','')::numeric*1000) as cargo_weight_kg,
        r.cargo_volume_m3,r.binding_vehicle_id::text,r.binding_driver_id::text,
        r.origin_location_id::text,r.destination_location_id::text,
        nullif(to_jsonb(r)->>'origin_latitude','') as origin_latitude,
        nullif(to_jsonb(r)->>'origin_longitude','') as origin_longitude,
        origin_catalog.latitude as origin_catalog_latitude,origin_catalog.longitude as origin_catalog_longitude,
        nullif(to_jsonb(r)->>'passenger_count','')::integer as passengers,
        count(*) over() as total_count,
        ({START}<current_timestamp) as overdue
      from transport_request r
      left join lateral (
        select case when count(distinct (rd.latitude,rd.longitude))=1 then min(rd.latitude) end as latitude,
               case when count(distinct (rd.latitude,rd.longitude))=1 then min(rd.longitude) end as longitude
        from reference_data rd
        where rd.catalog_type='LOCATIONS' and rd.active
          and (rd.id=r.origin_location_id or rd.location_id=r.origin_location_id)
          and rd.latitude between -90 and 90 and rd.longitude between -180 and 180
      ) origin_catalog on true
      where r.status=any(%s)
      order by case r.priority when 'CRITICAL' then 0 when 'URGENT' then 1 when 'HIGH' then 2 else 3 end,
        {START} nulls last,r.created_at,r.id limit 2000''',(WAITING,))
    total=int(result[0]['total_count']) if result else 0
    return {'total':total,'returned':len(result),'truncated':total>len(result),'statuses':WAITING,'items':result}

def fleet():
    return rows('''select v.id::text as vehicle_id,v.plate_number,v.brand,v.model,v.transport_type,v.current_status,
      coalesce(v.payload_capacity_kg,nullif(to_jsonb(v)->>'cargo_capacity_tons','')::numeric*1000) as capacity_kg,
      coalesce(v.seat_count,nullif(to_jsonb(v)->>'passenger_capacity','')::integer) as seats,
      exists(select 1 from vehicle_gps g where g.vehicle_id=v.id and g.active and g.unbound_at is null and g.verified_from<=current_timestamp) as gps_bound,
      exists(select 1 from trip t where t.vehicle_id=v.id and t.status in ('STARTED','ARRIVED_AT_POINT','LOADED','UNLOADED')) as active_trip
      from transport_vehicle v order by v.plate_number nulls last,v.id limit 1000''')

def quality():
    definitions=[
      ('capacity','Transport yuk sig‘imi','transport_vehicle','payload_capacity_kg / cargo_capacity_tons',
       "coalesce(payload_capacity_kg,nullif(to_jsonb(transport_vehicle)->>'cargo_capacity_tons','')::numeric*1000)>0",
       'Yuk tashuvchi transportlar uchun sig‘imni kg yoki tonnada kiriting. Turlar bo‘yicha talabni belgilang.'),
      ('coordinates','Arizadagi bevosita koordinatalar','transport_request','origin_latitude, origin_longitude, destination_latitude, destination_longitude',
       'origin_latitude between -90 and 90 and origin_longitude between -180 and 180 and destination_latitude between -90 and 90 and destination_longitude between -180 and 180',
       'Boshlanish va tugash nuqtalarini to‘ldiring yoki yaroqli nuqta/manzil katalogiga ulang. Bu o‘lchov zaxira manbalarni qamramaydi.'),
      ('point_coordinates','Ariza nuqtalari koordinatalari','transport_request_point','latitude, longitude',
       'latitude between -90 and 90 and longitude between -180 and 180','Har bir yuklash va tushirish nuqtasiga koordinata kiriting.'),
      ('license','Haydovchi guvohnomasi sanasi','driver','license_valid_until','license_valid_until is not null',
       'Yetishmagan amal qilish sanalarini kiriting. To‘ldirilganlik hujjat hali amal qilishini anglatmaydi.'),
      ('telemetry','Joriy telematika','vehicle_telemetry_state','last_event_at','last_event_at is not null',
       'GPS arxividan joriy holatni yangilash quvurini ulang. GPS bog‘lanishi yangi signal borligini isbotlamaydi.'),
      ('shifts','Haydovchi smenalari','driver_shift','planned_start_at, planned_end_at','planned_start_at is not null and planned_end_at is not null',
       'Kelgusi reja kunlari uchun haydovchi smenalarini kiriting. Bu butun haydovchilar qamrovi emas.'),
      ('insurance','Sug‘urta yozuvlari','insurance_policy','valid_to','valid_to is not null',
       'Transport sug‘urtasi va amal qilish muddatlarini ulang.'),
    ]
    items=[]
    for key,title,table,columns,condition,fix in definitions:
        # Identifiers and conditions are static constants above, never user input.
        metric=rows(f'select count(*) as total,count(*) filter(where {condition}) as filled from {table}')[0]
        items.append(dict(code=key,title=title,table=table,columns=columns,fix=fix,**metric,
                          status='empty' if not metric['total'] else 'complete' if metric['filled']==metric['total'] else 'incomplete'))
    return {'items':items,'scope':'Barcha yozuvlar; to‘ldirilganlik tayyorlik yoki hujjat haqiqiyligi emas.'}

def versions(request_ids, vehicle_ids):
    """Capture revision evidence for approval review; not an assignment lock."""
    return {
      'requests':rows('select id::text,status,version,binding_vehicle_id::text,binding_driver_id::text from transport_request where id=any(%s::uuid[]) order by id',(request_ids,)),
      'vehicles':rows('select id::text,updated_at,current_status,assigned_driver_id::text from transport_vehicle where id=any(%s::uuid[]) order by id',(vehicle_ids,)),
    }

