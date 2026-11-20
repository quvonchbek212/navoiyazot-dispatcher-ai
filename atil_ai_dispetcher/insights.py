"""Additional dispatcher evidence. No assignments, invented policies or causal claims."""
from collections import Counter,defaultdict
from datetime import datetime
from . import config,repository,operations

FLEET_GROUPS={
    'operating':'reys yoki yo‘l varaqasi bo‘yicha ishda',
    'reserved':'arizaga biriktirilgan, rejalashtirilgan reys yoki ochiq yo‘l varaqasi bilan band',
    'maintenance':'ta’mirda yoki ochiq ta’mir sabab chiqishi cheklangan',
    'restricted':'bloklangan yoki foydalanishdan chiqarilgan',
    'ready':'topshiriqsiz, asosiy tekshiruvlardan o‘tgan',
    'unconfirmed':'topshiriqsiz, tayyorligi tasdiqlanmagan',
    'conflict':'holat yozuvlari zid',
}
REPAIR_STAGES={
    'CREATED':'ochilgan','NEW':'yangi','OPEN':'ochiq','PENDING_ARM_APPROVAL':'ta’mir tasdig‘ini kutmoqda',
    'APPROVED_BY_ARM':'ta’mir tasdiqlangan','ARM_DIAGNOSIS':'diagnostikada','DIAGNOSING':'diagnostikada',
    'WAITING_PARTS_APPROVAL':'ehtiyot qism tasdig‘ini kutmoqda','WAITING_PARTS':'ehtiyot qism kutmoqda',
    'PARTS_APPROVED':'ehtiyot qismlar tasdiqlangan','PARTS_ISSUED':'ehtiyot qismlar berilgan',
    'REPAIR_IN_PROGRESS':'ta’mir bajarilmoqda','REPAIRING':'ta’mir bajarilmoqda','IN_PROGRESS':'ish davom etmoqda',
    'COMPLETED_BY_ARM':'ta’mirchi yakunlagan, yopilish kutilmoqda','PENDING_ARM_CLOSURE':'yopilish tasdig‘ini kutmoqda',
    'PENDING_FINAL_MECHANIC_INSPECTION':'yakuniy ko‘rikni kutmoqda','FINAL_INSPECTION_PASSED':'yakuniy ko‘rikdan o‘tgan',
    'FINAL_INSPECTION_FAILED':'yakuniy ko‘rikdan o‘tmagan','NOT_REPAIRED':'ta’mir bajarilmagan',
}

def moment(value):
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
        return d if isinstance(d,datetime) and d.tzinfo is not None else None
    except (TypeError,ValueError):return None

def fleet_state(fleet):
    items=[]
    for v in fleet['items']:
        status=v.get('current_status')
        busy=bool(v.get('busy_trip') or v.get('busy_waybill') or v.get('request_bound'))
        repair=status=='IN_MAINTENANCE' or bool(v.get('blocking_repair'))
        restricted=status in ('BLOCKED','DECOMMISSIONED')
        conflict=bool(v.get('trip_conflict') or v.get('waybill_conflict') or (busy and (repair or restricted)))
        conflict_reasons=[]
        if v.get('trip_conflict'):conflict_reasons.append('Reys faol holatda, ammo yakun belgisi yoki kelajakdagi jo‘nash vaqti bor')
        if v.get('waybill_conflict'):conflict_reasons.append('Yo‘l varaqasi ochiq, ammo qaytish belgisi yoki kelajakdagi jo‘nash vaqti bor')
        if busy and repair:conflict_reasons.append('Bandlik bilan ta’mir cheklovi birga qayd etilgan')
        if busy and restricted:conflict_reasons.append('Bandlik bilan foydalanish cheklovi birga qayd etilgan')
        if conflict:group='conflict'
        elif restricted:group='restricted'
        elif repair:group='maintenance'
        elif v.get('operating_trip') or v.get('operating_waybill'):group='operating'
        elif busy:group='reserved'
        elif status=='ACTIVE' and v.get('basic_checks_passed') is True:group='ready'
        else:group='unconfirmed'
        items.append({'vehicle_id':v.get('vehicle_id'),'plate_number':v.get('plate_number'),'group':group,'conflict_reasons':conflict_reasons})
    counts={k:0 for k in FLEET_GROUPS};counts.update(Counter(v['group'] for v in items))
    return {'version':2,'items':items,'counts':counts,'total':fleet.get('total',len(items)),
            'returned':len(items),'truncated':fleet.get('truncated',False),
            'scope':'Har transport bir guruhda. Ishda — bazadagi reys holati; GPS bilan harakat tasdig‘i emas.'}

def repair_analysis(rows,as_of):
    items=[]
    for row in rows:
        r=dict(row);opened=moment(r.get('opened_at'));end=moment(r.get('completed_at'));plan=moment(r.get('estimated_completion_time'))
        active=r['status'] not in operations.TERMINAL_REPAIRS
        conflict=not opened or opened>as_of or bool(end and (end<opened or end>as_of)) or bool(plan and plan<opened)
        conflict=conflict or bool(r.get('completed_at') and not end) or bool(r.get('estimated_completion_time') and not plan)
        conflict=bool(conflict or (active and end is not None))
        r.update(active=active,time_conflict=conflict,
                 age_hours=round((as_of-opened).total_seconds()/3600,1) if active and not conflict else None,
                 plan_overdue=bool(active and not conflict and plan and plan<as_of),
                 overdue_hours=round((as_of-plan).total_seconds()/3600,1) if active and not conflict and plan and plan<as_of else None,
                 stage_label=REPAIR_STAGES.get(r['status'],'bosqichni aniqlashtirish kerak') if active else 'yopilgan yoki bekor qilingan')
        items.append(r)
    active=[r for r in items if r['active']]
    total=int(rows[0]['total_count']) if rows else 0
    return {'items':items,'total':total,'returned':len(items),'truncated':total>len(items),'checked_at':as_of,
            'summary':{'active':len(active),'active_vehicles':len({r['vehicle_id'] for r in active}),
                       'blocking':sum(bool(r['blocks_release']) for r in active),
                       'plan_overdue':sum(r['plan_overdue'] for r in active),
                       'no_plan':sum(r.get('estimated_completion_time') is None for r in active),
                       'conflicts':sum(r['time_conflict'] for r in items)}}

def repairs():
    rows=repository.rows('''SELECT r.id::text repair_id,r.vehicle_id::text,r.repair_number,v.plate_number,
        r.status,r.opened_at,r.completed_at,r.estimated_completion_time,r.blocks_release,r.rework_count,
        coalesce(w.total,0) work_total,coalesce(w.done,0) work_done,
        ARRAY(SELECT x.description FROM vehicle_repair_work_items x WHERE x.repair_id=r.id
              AND nullif(btrim(x.description),'') IS NOT NULL ORDER BY x.completed ASC NULLS FIRST,x.id LIMIT 2) work_examples,
        count(*) OVER() total_count
        FROM vehicle_repair r LEFT JOIN transport_vehicle v ON v.id=r.vehicle_id
        LEFT JOIN LATERAL (SELECT count(*) total,count(*) FILTER(WHERE completed) done
                          FROM vehicle_repair_work_items w WHERE w.repair_id=r.id) w ON true
        ORDER BY (r.status=ANY(%s)),r.opened_at,r.id LIMIT 2000''',(operations.TERMINAL_REPAIRS,))
    return repair_analysis(rows,config.now())

def document_coverage():
    queries={
        'drivers':'''SELECT d.id::text owner_id,d.full_name owner_label,
          count(dd.id) records,
          count(dd.id) FILTER(WHERE dd.kind='DRIVER_LICENSE_SCAN' AND nullif(btrim(dd.s3_url),'') IS NOT NULL AND dd.size_bytes>0) license_files,
          count(dd.id) FILTER(WHERE dd.kind='MEDICAL_CERTIFICATE_SCAN' AND nullif(btrim(dd.s3_url),'') IS NOT NULL AND dd.size_bytes>0) medical_files,
          count(dd.id) FILTER(WHERE nullif(btrim(dd.s3_url),'') IS NULL OR dd.size_bytes<=0) incomplete_files,
          count(*) OVER() total_count
          FROM driver d LEFT JOIN driver_document dd ON dd.driver_id=d.id
          WHERE d.deleted_at IS NULL GROUP BY d.id ORDER BY d.id LIMIT 2000''',
        'vehicles':'''SELECT v.id::text owner_id,v.plate_number owner_label,count(vd.id) records,
          count(vd.id) FILTER(WHERE vd.attachment_id IS NOT NULL) attachments,
          count(vd.id) FILTER(WHERE vd.expiry_date<current_date) expired,
          count(vd.id) FILTER(WHERE vd.expiry_date BETWEEN current_date AND current_date+30) expiring,
          count(vd.id) FILTER(WHERE vd.expiry_date IS NULL) unknown_expiry,
          count(vd.id) FILTER(WHERE vd.issued_at>current_date OR vd.expiry_date<vd.issued_at) conflicting_dates,
          count(*) OVER() total_count
          FROM transport_vehicle v LEFT JOIN vehicle_document vd ON vd.vehicle_id=v.id
          GROUP BY v.id ORDER BY v.id LIMIT 2000'''
    }
    result={'required_policy_available':False,'errors':{},'checked_at':config.now()}
    for key,query in queries.items():
        try:
            rows=repository.rows(query);total=int(rows[0]['total_count']) if rows else 0
            result[key]={'items':rows,'total':total,'returned':len(rows),'truncated':total>len(rows)}
        except Exception as exc:result['errors'][key]=repository.error_code(exc)
    if len(result['errors'])==len(queries):raise RuntimeError('Document sources unavailable')
    result['records']=sum(r['records'] for key in queries for r in result.get(key,{}).get('items',[]))
    result['truncated']=any(result.get(k,{}).get('truncated',False) for k in queries)
    return result

def waiting_diagnostics(requests,fleet,drivers,as_of):
    by_type=defaultdict(list)
    for v in (fleet or {}).get('items',[]):by_type[v.get('transport_type')].append(v)
    driver_passes=None if drivers is None else sum(d.get('basic_checks_passed') is True for d in drivers.get('items',[]))
    items=[]
    for req in requests.get('items',[]):
        created=moment(req.get('created_at'));submitted=moment(req.get('submitted_at'));approved=moment(req.get('transport_head_approved_at'))
        dates=[d for d in (created,submitted,approved) if d]
        bad_time=any(d>as_of for d in dates) or bool(created and submitted and submitted<created) or bool(created and approved and approved<created) or bool(submitted and approved and approved<submitted)
        start=approved or submitted or created
        age=None if bad_time or not start else round((as_of-start).total_seconds()/3600,1)
        basis='tasdiqlanganidan' if approved else 'yuborilganidan' if submitted else 'yaratilganidan'
        vtype=req.get('required_transport_type');matches=by_type.get(vtype,[]) if fleet is not None and vtype else None
        checks=[operations.assess_vehicle(req,v) for v in matches] if matches is not None else None
        ready=sum(c['status']=='BASIC_CHECKS_PASSED' for c in checks) if checks is not None else None
        obstacles=[]
        if not vtype:obstacles.append('Arizada transport turi ko‘rsatilmagan.')
        if matches is not None and not matches:obstacles.append('Tekshirilgan parkda talab qilingan turdagi transport topilmadi.')
        if checks and not ready:obstacles.append('Tekshirilgan shu turdagi transportlardan hech biri barcha asosiy talablardan o‘tmadi.')
        missing_amount=not any(req.get(k) and req[k]>0 for k in ('cargo_weight_kg','cargo_volume_m3','passengers'))
        if missing_amount:obstacles.append('Yuk yoki yo‘lovchi miqdori ko‘rsatilmagan; sig‘imga moslik tasdiqlanmaydi.')
        if driver_passes==0:obstacles.append('Tekshirilgan haydovchilardan asosiy talablardan o‘tgan nomzod topilmadi.')
        frequencies=Counter(x for c in (checks or []) for x in set(c['reasons']+c['unverified']))
        items.append({'request_id':req.get('request_id'),'request_number':req.get('request_number'),
                      'age_hours':age,'age_basis':basis,'time_conflict':bad_time,'missing_amount':missing_amount,
                      'vehicle_matches':len(matches) if matches is not None else None,'vehicle_passes':ready,
                      'obstacles':obstacles,'vehicle_obstacles':dict(frequencies)})
    items.sort(key=lambda i:(i['age_hours'] is None,-(i['age_hours'] or 0),i.get('request_number') or ''))
    return {'items':items,'total':requests.get('total',len(items)),'returned':len(items),
            'truncated':requests.get('truncated',False),'checked_at':as_of,
            'fleet_available':fleet is not None,'drivers_available':drivers is not None,
            'candidate_scope_limited':bool((fleet or {}).get('truncated') or (drivers or {}).get('truncated')),
            'summary':{'with_obstacles':sum(bool(i['obstacles']) for i in items),
                       'missing_amount':sum(i['missing_amount'] for i in items),
                       'no_vehicle_pass':sum(i['vehicle_passes']==0 for i in items),
                       'driver_passes':driver_passes,'unknown_age':sum(i['age_hours'] is None for i in items)},
            'scope':'Hozir ko‘rinayotgan to‘siqlar. Ariza aynan shu sabab kutgani tasdiqlanmagan; smena va toifa mosligi alohida tekshiriladi.'}

def change_index():
    """All-status identities, never infer completion from a capped active list."""
    index={'version':1,'datasets':{}}
    for key,table in [('requests','transport_request'),('trips','trip')]:
        rows=repository.rows(f'''SELECT id::text id,status,created_at,count(*) OVER() total_count,
            current_timestamp captured_at FROM {table} ORDER BY id LIMIT 20000''')
        total=int(rows[0]['total_count']) if rows else 0
        index['datasets'][key]={'total':total,'truncated':total>len(rows),
                               'captured_at':rows[0]['captured_at'] if rows else config.now(),
                               'items':[{'id':r['id'],'status':r['status'],'created_at':r['created_at']} for r in rows]}
    return index

def changes(previous,current):
    old=previous.get('sections',{}) if previous else {};new=current.get('sections',{})
    result={'baseline_at':previous.get('generated_at') if previous else None,'current_at':current.get('generated_at'),
            'status':'BASELINE','new_requests':None,'first_seen_requests':None,'completed_trips':None,
            'vehicle_changes':None,'vanished_requests':None,'vanished_trips':None,'unavailable':[]}
    prior_time=moment(result['baseline_at']);current_time=moment(result['current_at'])
    if not prior_time or not current_time or current_time<=prior_time:
        result['unavailable']=['requests','trips','fleet'];return result
    before=old.get('change_index',{});after=new.get('change_index',{})
    for key in ('requests','trips'):
        a=before.get('datasets',{}).get(key);b=after.get('datasets',{}).get(key)
        if not a or not b or a.get('truncated') or b.get('truncated') or before.get('version')!=after.get('version'):
            result['unavailable'].append(key);continue
        start=moment(a.get('captured_at'));end=moment(b.get('captured_at'))
        if not start or not end or end<=start:result['unavailable'].append(key);continue
        left={r['id']:r for r in a['items']};right={r['id']:r for r in b['items']}
        result['status']='COMPARED'
        result['vanished_'+key]=len(left.keys()-right.keys())
        if key=='requests':
            unseen=[right[i] for i in right.keys()-left.keys()]
            result['new_requests']=sum(bool(moment(r.get('created_at')) and start<moment(r['created_at'])<=end) for r in unseen)
            result['first_seen_requests']=len(unseen)-result['new_requests']
        else:result['completed_trips']=sum(left[i]['status']!='COMPLETED' and right[i]['status']=='COMPLETED' for i in left.keys()&right.keys())
    a=old.get('fleet_state');b=new.get('fleet_state')
    if a and b and not a.get('truncated') and not b.get('truncated') and a.get('version')==b.get('version'):
        left={r['vehicle_id']:r['group'] for r in a['items']};right={r['vehicle_id']:r['group'] for r in b['items']}
        result['vehicle_changes']=sum(left[i]!=right[i] for i in left.keys()&right.keys());result['status']='COMPARED'
    else:result['unavailable'].append('fleet')
    return result
