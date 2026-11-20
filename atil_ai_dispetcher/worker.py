import asyncio
import hashlib
import logging
from uuid import uuid4
from . import config,service

log=logging.getLogger(__name__)

def schedule(store,now):
    settings=store.settings()
    if not settings.schedule_enabled:return
    bucket=int(now.timestamp())//(settings.monitor_minutes*60)
    store.enqueue({'kind':'snapshot','analyze':settings.analyze},'scheduler',f'v2:monitor:{settings.monitor_minutes}:{bucket}')
    if now.strftime('%H:%M')>=settings.daily_time:
        store.schedule_briefing({'kind':'briefing','analyze':settings.analyze},now,settings.monitor_minutes)

def notices(store,job,result):
    for p in result.get('priorities',[]):
        # One daily operational reminder per condition/count; source errors are separate.
        key=f"v2:{config.now().date()}:{p['code']}:{p['count']}"
        store.notice(key,p['action'],f"{p['count']} ta. Hisobotdagi qamrov va dalillarni ko‘ring.",job['id'])
    if result.get('errors'):
        key=hashlib.sha256(','.join(sorted(result['errors'])).encode()).hexdigest()[:12]
        store.notice('v2:partial:'+str(config.now().date())+key,'Hisobot qisman yangilandi',
                     'Ayrim manbalar o‘qilmadi. Ma’lumot holatini tekshiring.',job['id'])
    if job['kind']=='briefing' or job['actor']!='scheduler':
        store.notice('job:'+job['id'],'Dispetcher hisoboti tayyor','Natijani ochib ko‘ring.',job['id'])

class Worker:
    def __init__(self,store):self.store=store;self.owner=uuid4().hex;self.task=None
    def start(self):self.task=asyncio.create_task(self.loop())
    async def stop(self):
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
    async def heartbeat(self,jid):
        while True:
            self.store.beat(jid,self.owner);await asyncio.sleep(15)
    async def loop(self):
        while True:
            heartbeat=None
            try:
                try:schedule(self.store,config.now())
                except ValueError:pass
                job=self.store.claim(self.owner)
                if not job:
                    await asyncio.sleep(2);continue
                heartbeat=asyncio.create_task(self.heartbeat(job['id']))
                try:
                    result=await service.execute(job,self.store)
                    self.store.finish(job['id'],self.owner,result=result)
                    notices(self.store,job,result)
                except asyncio.CancelledError:raise
                except Exception as exc:
                    log.warning('Dispatcher job failed: %s (%s)',job['id'],type(exc).__name__)
                    self.store.finish(job['id'],self.owner,error='Hisob bajarilmadi. Manba ulanishi va kirish parametrlarini tekshiring.')
                    self.store.notice('error:'+job['id'],'Hisob bajarilmadi','Oldingi ma’lumotni yangi deb qabul qilmang.',job['id'])
            except asyncio.CancelledError:raise
            except Exception:
                log.exception('Dispatcher worker error');await asyncio.sleep(5)
            finally:
                if heartbeat:
                    heartbeat.cancel()
                    try:await heartbeat
                    except asyncio.CancelledError:pass
