import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from atil_ai_dispetcher import PACKAGE_ROOT, service, repository, reading, workspace
from atil_ai_dispetcher.models import JobRequest, Settings, GarageSettings
from security import require_api_credentials

router=APIRouter(prefix='/ai-dispatcher',tags=['AI Dispetcher'])

def store(request:Request):return request.app.state.dispatch_store

async def same_origin(request:Request):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
        raise HTTPException(403,'Boshqa saytdan yozish so‘rovi rad etildi')

api=APIRouter(prefix='/api',dependencies=[Depends(require_api_credentials),Depends(same_origin)])

@router.get('',include_in_schema=False)
@router.get('/',include_in_schema=False)
def ui():
    if not (PACKAGE_ROOT/'frontend/index.html').is_file():raise HTTPException(404)
    return FileResponse(PACKAGE_ROOT/'frontend/index.html',headers={'Cache-Control':'no-cache'})

@router.get('/assets/{name}',include_in_schema=False)
def asset(name:str):
    if name not in ('app.js','style.css'):raise HTTPException(404)
    if not (PACKAGE_ROOT/'frontend'/name).is_file():raise HTTPException(404)
    return FileResponse(PACKAGE_ROOT/'frontend'/name,headers={'Cache-Control':'no-cache'})

@router.get('/taqdimot',include_in_schema=False)
def presentation_redirect():
    if not (PACKAGE_ROOT/'presentation/index.html').is_file():raise HTTPException(404)
    return RedirectResponse('/ai-dispatcher/taqdimot/')

@router.get('/taqdimot/',include_in_schema=False)
def presentation():
    if not (PACKAGE_ROOT/'presentation/index.html').is_file():raise HTTPException(404)
    return FileResponse(PACKAGE_ROOT/'presentation/index.html',headers={'Cache-Control':'no-cache'})

@router.get('/taqdimot/{name}',include_in_schema=False)
def presentation_asset(name:str):
    if name not in ('presentation.css','presentation.js','ATIL_AI_TAQDIMOT.html'):
        raise HTTPException(404)
    if not (PACKAGE_ROOT/'presentation'/name).is_file():raise HTTPException(404)
    return FileResponse(PACKAGE_ROOT/'presentation'/name,
                        filename=name if name=='ATIL_AI_TAQDIMOT.html' else None,
                        headers={'Cache-Control':'no-cache'})

@api.get('/dashboard')
def dashboard(request:Request,user=Depends(require_api_credentials)):
    s=store(request)
    return {'version':2,'user':user,'timezone':'Asia/Tashkent','snapshot':s.latest_snapshot(),'briefing':s.latest_briefing(),'jobs':s.jobs(),
            'notifications':s.notices(),'settings':s.settings(),'execution':{'connected':False,'message':'ATILga biriktirish integratsiyasi ulanmagan. Tasdiqlar shu tizimda saqlanadi.'}}

@api.get('/health')
def health(request:Request,response:Response):
    database=repository.health()
    latest=store(request).latest_snapshot()
    worker=getattr(request.app.state,'dispatch_worker',None)
    running=bool(worker and worker.task and not worker.task.done())
    ready=database['status']=='ok' and running
    if not ready:response.status_code=503
    return {'status':'ready' if ready else 'degraded','database':database,'worker_running':running,
            'last_success_at':latest['data'].get('generated_at') if latest else None}

@api.get('/analysis')
def analysis_view(request:Request,user=Depends(require_api_credentials)):
    s=store(request)
    return reading.workspace(s,user)

@api.get('/workspace')
def work_table(request:Request,user=Depends(require_api_credentials)):
    return workspace.view(store(request),user)

@api.get('/jobs')
def jobs(request:Request):return store(request).jobs()

@api.post('/jobs',status_code=202)
def create_job(body:JobRequest,request:Request,user=Depends(require_api_credentials)):
    try:jid=store(request).enqueue(body.model_dump(mode='json'),user)
    except ValueError as exc:raise HTTPException(429,str(exc))
    return {'id':jid,'status':'queued'}

@api.get('/jobs/{jid}')
def job(jid:str,request:Request):
    result=store(request).job(jid)
    if result is None:raise HTTPException(404,'Vazifa topilmadi')
    return result

@api.get('/jobs/{jid}/export')
def export(jid:str,request:Request):
    result=job(jid,request)
    from fastapi.encoders import jsonable_encoder
    return Response(json.dumps(jsonable_encoder(result),ensure_ascii=False,indent=2),media_type='application/json',
                    headers={'Content-Disposition':f'attachment; filename="dispatch-{result["id"]}.json"'})

@api.get('/jobs/{jid}/reading')
def job_reading(jid:str,request:Request):
    return reading.job(job(jid,request))

@api.get('/jobs/{jid}/view')
def job_view(jid:str,request:Request):
    return workspace.job(job(jid,request))

@api.post('/jobs/{jid}/decision')
async def decide(jid:str,request:Request,user=Depends(require_api_credentials)):
    raise HTTPException(410,'Ko‘p arizali rejalashtirish va eski reja tasdiqlash o‘chirildi.')

@api.put('/settings')
def settings(body:Settings,request:Request):
    store(request).save_settings(body)
    return body

@api.put('/garage')
def garage_settings(body:GarageSettings,request:Request,user=Depends(require_api_credentials)):
    s=store(request)
    updated=Settings.model_validate({**s.settings().model_dump(),**body.model_dump()})
    s.save_settings(updated)
    try:jid=s.enqueue({'kind':'snapshot','analyze':updated.analyze},user)
    except ValueError:jid=None
    return {'settings':updated,'job_id':jid,'message':'Garaj saqlandi. Hisob navbatga qo‘shildi.' if jid else 'Garaj saqlandi. Navbat band; keyingi avtomatik hisobda yangilanadi.'}

@api.post('/notifications/{nid}/read')
def read(nid:str,request:Request):
    if not store(request).read_notice(nid):raise HTTPException(404,'Xabar topilmadi')
    return {'read':True}

@api.get('/developer-report')
def developer_report(request:Request):
    latest=store(request).latest_snapshot()
    if not latest:raise HTTPException(409,'Avval holatni yangilang')
    return {'generated_at':latest['data'].get('generated_at'),'quality':latest['data'].get('sections',{}).get('sources'),
            'errors':latest['data'].get('errors',{}),'integration':'ATIL backend revalidate + idempotent assignment API required; no direct SQL writes.'}

router.include_router(api)
