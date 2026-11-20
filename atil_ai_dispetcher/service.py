"""Match waiting requests to ready vehicles and observe GPS/garage activity."""
import asyncio
import logging
from datetime import timedelta
from fastapi.concurrency import run_in_threadpool
from . import repository,operations,gps,garage,gps_api,gps_activity,config,narrative,insights,allocation,vehicle_ai
from .models import JobRequest,Settings

log=logging.getLogger(__name__)

async def analysis(report,callback,enabled):
    n=narrative.ensure(report)
    if not enabled:
        n.update(ai_status='DISABLED',notice='AI izohi o‘chirilgan. Tushuntirish mavjud ma’lumotlardan tuzildi.')
        report['analysis']={'status':'DISABLED','source':'calculated','text':narrative.as_text(n)};return
    try:
        await asyncio.wait_for(callback(report,lang='uz'),timeout=config.LLM_TIMEOUT)
        if n.get('ai_status')=='COMPLETE' and report.get('analysis',{}).get('text'):report['analysis'].update(status='COMPLETE',source=n.get('source','calculated'))
        else:raise ValueError('Empty explanation')
    except Exception as exc:
        log.warning('Dispatcher explanation unavailable (%s)',type(exc).__name__)
        n=report['narrative']=narrative.build(report)
        n.update(ai_status='UNAVAILABLE',notice='AI izohi olinmadi. Quyidagi tushuntirish bazadan hisoblangan dalillarga asoslangan.')
        report['analysis']={'status':'UNAVAILABLE','source':'calculated','text':narrative.as_text(n)}

async def explain(report,lang='uz'):
    await narrative.enrich(report,lang)

async def snapshot(settings=None):
    result={'contract_version':2,'view_version':3,'generated_at':config.now(),'sections':{},'errors':{}}
    for key,fn in [('requests',repository.requests),('fleet',operations.vehicles),('gps',gps.latest)]:
        try:
            result['sections'][key]=await run_in_threadpool(fn)
            if result['sections'][key].get('errors'):
                result['errors'][key]='Manbaning bir qismi o‘qilmadi; uning holati noma’lum.'
        except Exception as exc:
            code=repository.error_code(exc)
            log.warning('Dispatcher source unavailable: %s (%s; %s)',key,type(exc).__name__,code)
            result['errors'][key]=code+': Manba o‘qilmadi. Natija noma’lum; nol deb hisoblanmaydi.'
    s=result['sections']
    if not s:raise RuntimeError('Baza manbalari o‘qilmadi')
    settings=settings or Settings()
    observations=None
    if gps_api.configured():
        try:
            observations=await run_in_threadpool(gps_activity.collect,s.get('gps'),settings)
            s['gps_daily']=gps_activity.daily_report(observations)
        except Exception as exc:
            log.warning('Dispatcher GPS activity unavailable (%s)',type(exc).__name__)
            result['errors']['gps_daily']='Kunlik GPS kuzatuvi olinmadi. Masofa va to‘xtashlar noma’lum.'
            # An API failure must not start the expensive archive scan.
            end=config.now()
            start=end-timedelta(hours=settings.garage_hours)
            selected=s.get('gps',{}).get('items',[])
            observations={'period':{'start':start,'end':end},'items':[
                gps_activity.unavailable({'vehicle_id':i['vehicle_id'],'plate_number':i.get('plate_number')},start,end,'HISTORY_UNAVAILABLE') for i in selected],
                'total':len(selected),'truncated':True,'daily_error':'HISTORY_UNAVAILABLE'}
            s['gps_daily']=gps_activity.daily_report(observations)
    try:
        s['garage']=await run_in_threadpool(garage.report,settings,observations=observations) if observations is not None else await run_in_threadpool(garage.report,settings)
    except Exception as exc:
        log.warning('Dispatcher source unavailable: garage (%s)',type(exc).__name__)
        result['errors']['garage']='Garaj GPS tarixi o‘qilmadi. Holat noma’lum.'
    # A vehicle must pass type, all stated capacities, current technical inspection
    # and availability checks. Driver reports and explanatory model calls are retired.
    s['allocation']=allocation.plan(s.get('requests'),s.get('fleet'))
    result['status']='PARTIAL' if result['errors'] or any(s.get(k,{}).get('status') in ('PARTIAL','UNAVAILABLE') for k in ('gps_daily','garage')) else 'COMPLETE'
    return result

async def execute(job,store):
    request=JobRequest.model_validate(job['payload'])
    kind=request.kind
    store.stage(job['id'],{'snapshot':'Arizalar va kuzatuv yangilanmoqda','briefing':'Arizalar va kuzatuv yangilanmoqda',
                          'selection':'Bitta ariza tekshirilmoqda','gps':'GPS tarixi olinmoqda'}[kind])
    if kind in ('snapshot','briefing'):
        result=await snapshot(store.settings())
        if 'change_index' in result.get('sections',{}):
            previous=store.latest_snapshot()
            result['sections']['changes']=insights.changes(previous['data'] if previous else None,result)
            store.stage(job['id'],'Holat sodda tilda tushuntirilmoqda')
            await analysis(result,explain,request.analyze)
        return result
    if kind=='selection':
        result=await run_in_threadpool(operations.selection,request.selection.request_id)
        return result
    result=await run_in_threadpool(gps.history,str(request.gps.vehicle_id),request.gps.hours)
    start,end=result['period']['start'],result['period']['end']
    settings=store.settings().model_copy(update={'garage_hours':request.gps.hours})
    yard=garage.report(settings,observations={'period':result['period'],'items':[result],'total':1})
    item=next(iter(yard.get('items',[])),{})
    observed=item.get('quality',{}).get('points',0)>0 and not item.get('error')
    observation={**gps_activity.activity(result,start,end),**vehicle_ai.speed_metrics(result,start,end)}
    report={'contract_version':2,'view_version':3,'generated_at':end,
            'vehicle':result['vehicle'],'period':result['period'],
            'observation':observation,'complete':result.get('complete'),
            'fallback_reason':result.get('fallback_reason'),
            'garage_view':{'name':(yard.get('garage') or {}).get('name'),
                           'is_example':(yard.get('garage') or {}).get('is_example',False),
                           'state':item.get('state','NOT_CONFIGURED'),
                           'entries':item.get('entries') if observed else None,
                           'exits':item.get('exits') if observed else None,
                           'stop_minutes':item.get('observed_garage_stop_minutes') if observed else None,
                           'outside_stop_minutes':item.get('observed_outside_stop_minutes') if observed else None,
                           'long_stops_count':len(item.get('stops') or []) if observed else None}}
    if job.get('payload',{}).get('analyze') is True:
        store.stage(job['id'],'GPS va garaj AI tahlili tayyorlanmoqda')
        report['ai']=await vehicle_ai.enrich(report,result,item)
    return report
