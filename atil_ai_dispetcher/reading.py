"""Small reading-oriented projections; raw evidence remains in the saved report."""
from copy import deepcopy
from . import narrative

def job(item):
    result={k:item.get(k) for k in ('id','kind','status','stage','created','finished','error')}
    report=deepcopy(item.get('result'))
    result['narrative']=narrative.ensure(report) if report is not None else None
    return result

def workspace(store,user):
    latest=store.latest_snapshot();settings=store.settings()
    report=deepcopy(latest['data']) if latest else None
    sections=report.get('sections',{}) if report else {}
    n=narrative.ensure(report) if report else None
    # A changed garage must never silently reuse analysis of the previous zone.
    if n and sections.get('garage'):
        old=sections['garage'];configured=settings.garage.model_dump() if settings.garage else None
        if old.get('garage')!=configured or old.get('hours')!=settings.garage_hours or old.get('stop_threshold_minutes')!=settings.garage_stop_minutes:
            n['blocks']=[b for b in n['blocks'] if b['id']!='garage']
            n['blocks'].append(narrative.block('garage','Garaj sozlamalari o‘zgargan. Yangi hudud hisobi tayyor bo‘lguncha oldingi hudud natijalari chiqarilmaydi.',severity='caution'))
            n['priority_ids']=[k for k in n['priority_ids'] if k!='garage']
    requests=[{'id':r['request_id'],'label':f"{r.get('request_number') or 'Ariza'} · {r.get('origin_location') or '?'} → {r.get('destination_location') or '?'}"}
              for r in sections.get('requests',{}).get('items',[]) if r.get('request_id')]
    # This selector is for GPS history, not the complete allocation fleet.
    # Stale/no-signal vehicles still have useful history; revoked access does not.
    gps_section=sections.get('gps',{})
    if isinstance(gps_section.get('items'),list):
        candidates=gps_section['items']
    else:
        candidates=[v for v in sections.get('fleet',{}).get('items',[])
                    if v.get('gps_bound') is True]
    distinct={v['vehicle_id']:{'id':v['vehicle_id'],'label':v.get('plate_number') or 'Transport'}
              for v in candidates if v.get('vehicle_id') and v.get('state')!='ACCESS_REVOKED'}
    vehicles=sorted(distinct.values(),key=lambda v:(v['label'].casefold(),v['id']))
    return {'version':1,'user':user,'narrative':n,'job_id':latest['job_id'] if latest else None,
            'options':{'requests':requests,'vehicles':vehicles},'settings':settings,'jobs':store.jobs()}
