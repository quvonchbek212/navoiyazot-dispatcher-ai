"""ATIL GPS adapter. Credentials stay on the server; response contracts are checked."""
import os
import time
import math
from datetime import datetime, date, timezone
from uuid import UUID
import httpx


class GPSAPIError(RuntimeError):
    pass


def configured():
    return bool((os.getenv('ATIL_GPS_TOKEN') or '').strip() or ((os.getenv('ATIL_GPS_USERNAME') or '').strip() and os.getenv('ATIL_GPS_PASSWORD')))


class GPSClient:
    def __init__(self, transport=None, sleep=time.sleep, clock=time.monotonic):
        base=os.getenv('ATIL_GPS_BASE_URL','https://api-atil.tenzorsoft.uz').rstrip('/')
        if not base.startswith('https://'):
            raise GPSAPIError('HTTPS_REQUIRED')
        self.client=httpx.Client(base_url=base,timeout=httpx.Timeout(8,connect=4),follow_redirects=False,transport=transport)
        token=(os.getenv('ATIL_GPS_TOKEN') or '').strip()
        self.token=token or None
        self.sleep=sleep;self.clock=clock
        self.revoked_vehicle_ids=set()

    def close(self):self.client.close()

    def login(self):
        if self.token:return
        username,password=os.getenv('ATIL_GPS_USERNAME'),os.getenv('ATIL_GPS_PASSWORD')
        if not username or not password:raise GPSAPIError('NOT_CONFIGURED')
        body={'username':username,'password':password}
        if os.getenv('ATIL_GPS_VERIFICATION_CODE'):body['verificationCode']=os.environ['ATIL_GPS_VERIFICATION_CODE']
        try:
            response=self.client.post('/api/v1/auth/login',json=body)
            if response.status_code!=200:raise GPSAPIError('LOGIN_FAILED')
            data=response.json()
            # The document does not specify the token field. A dotted explicit setting
            # supports deployment contracts without printing login responses.
            field=os.getenv('ATIL_GPS_TOKEN_FIELD','accessToken')
            for part in field.split('.'):data=data[part]
            if not isinstance(data,str) or not data:raise ValueError()
            self.token=data
        except GPSAPIError:raise
        except Exception:raise GPSAPIError('TOKEN_CONTRACT_UNCONFIRMED') from None

    def request(self,method,path,**kwargs):
        self.login()
        # Reject whitespace/non-ASCII tokens cleanly before httpx raises UnicodeEncodeError/LocalProtocolError.
        if not isinstance(self.token,str) or not self.token or any(ord(c)<33 or ord(c)>126 for c in self.token):
            raise GPSAPIError('INVALID_TOKEN')
        try:
            response=self.client.request(method,path,headers={'Authorization':'Bearer '+self.token},**kwargs)
        except httpx.HTTPError:raise GPSAPIError('CONNECTION_FAILED') from None
        if response.status_code in (401,403):raise GPSAPIError('ACCESS_DENIED')
        return response

    def history(self,vehicle_id,start,end,*,budget_seconds=45):
        vehicle_id=str(UUID(str(vehicle_id)))
        if not start.tzinfo or not end.tzinfo or start>=end:raise GPSAPIError('INVALID_WINDOW')
        body={'vehicleId':vehicle_id,'fromInstant':start.astimezone(timezone.utc).isoformat(),
              'toExclusive':end.astimezone(timezone.utc).isoformat()}
        if not 0<budget_seconds<=45:raise GPSAPIError('INVALID_BUDGET')
        began=self.clock();recreated=False
        def request(method,path,**kwargs):
            remaining=budget_seconds-(self.clock()-began)
            if remaining<=0:raise GPSAPIError('PENDING_TIMEOUT')
            return self.request(method,path,timeout=min(8,remaining),**kwargs)
        points=[];segments=[];pages=[];cursor=None;seen=set();selection=None
        while self.clock()-began<budget_seconds:
            if selection is None:
                response=request('POST','/api/v1/gps/history-selections',json=body)
                if response.status_code not in (200,202):raise GPSAPIError('SELECTION_FAILED')
                try:selection=str(UUID(response.json()['selectionId']))
                except Exception:raise GPSAPIError('SELECTION_CONTRACT_INVALID') from None
            response=request('GET','/api/v1/gps/history-selections/'+selection,
                                  params={'cursor':cursor} if cursor else {})
            if response.status_code==202:
                self.sleep(min(1,max(0,budget_seconds-(self.clock()-began))));continue
            if response.status_code==410 and not recreated:
                selection=None;cursor=None;seen.clear();points.clear();segments.clear();pages.clear();recreated=True;continue
            if response.status_code!=200:raise GPSAPIError('HISTORY_FAILED_'+str(response.status_code))
            try:
                data=response.json()
                batch=data['points'];complete=data['complete'];offset=data['pointOffset']
                breaks=data.get('segmentStarts',[])
                if (not isinstance(batch,list) or type(complete) is not bool or type(offset) is not int
                        or offset!=len(points) or not all(isinstance(p,dict) for p in batch)
                        or not isinstance(breaks,list) or any(type(i) is not int or i<0 or i>=len(batch) for i in breaks)):
                    raise ValueError()
                if data.get('selectionId',selection)!=selection:raise ValueError()
                if len(points)+len(batch)>10000:raise GPSAPIError('POINT_LIMIT')
                segments.extend(offset+i for i in breaks)
                points.extend(batch)
                pages.append({k:data.get(k) for k in ('gapCount','excludedCount','limitExceeded','totalPoints')})
                if data.get('limitExceeded') is True:
                    return {'points':points,'segment_starts':segments,'complete':False,'pages':pages,'limit_exceeded':True,'selection_id':selection}
                if complete:
                    return {'points':points,'segment_starts':segments,'complete':True,'pages':pages,'limit_exceeded':False,'selection_id':selection}
                new=data.get('nextCursor')
                if not isinstance(new,str) or not new or new in seen:raise ValueError()
                seen.add(new);cursor=new
                if len(pages)>=20:raise GPSAPIError('PAGE_LIMIT')
            except GPSAPIError:raise
            except Exception:raise GPSAPIError('HISTORY_CONTRACT_INVALID') from None
        raise GPSAPIError('PENDING_TIMEOUT')

    def distance(self,selection_id,start,end,*,budget_seconds=8):
        """Distance for the exact selection, never an unqualified daily total."""
        selection_id=str(UUID(str(selection_id)))
        if not start.tzinfo or not end.tzinfo or start>=end:raise GPSAPIError('INVALID_WINDOW')
        if not 0<budget_seconds<=8:raise GPSAPIError('INVALID_BUDGET')
        response=self.request('GET','/api/v1/gps/history-selections/'+selection_id+'/distance',timeout=budget_seconds)
        if response.status_code!=200:raise GPSAPIError('DISTANCE_UNAVAILABLE')
        try:
            data=response.json()
            if str(UUID(data['selectionId']))!=selection_id or type(data['complete']) is not bool:raise ValueError()
            begin=datetime.fromisoformat(data['effectiveFrom'].replace('Z','+00:00'))
            finish=datetime.fromisoformat(data['effectiveTo'].replace('Z','+00:00'))
            if not begin.tzinfo or not finish.tzinfo or begin>=finish or begin<start or finish>end:raise ValueError()
            if type(data['gapCount']) is not int or data['gapCount']<0:raise ValueError()
            values={}
            for key in ('distanceKm','observedDistanceKm'):
                val=data.get(key)
                if val is not None and (isinstance(val,bool) or not isinstance(val,(float,int)) or not math.isfinite(val) or val<0):raise ValueError()
                values[key]=val
            return {**values,'source':data.get('source'),'complete':data['complete'],
                    'gap_count':data['gapCount'],'period':{'start':begin,'end':finish},
                    'window_matches':begin==start and finish==end}
        except Exception:raise GPSAPIError('DISTANCE_CONTRACT_INVALID') from None

    def daily_summaries(self,vehicle_ids):
        """Strict live DailySummary DTO; missing totals stay unknown, never zero."""
        ids=[str(UUID(str(v))) for v in vehicle_ids]
        if not 1<=len(ids)<=100 or len(set(ids))!=len(ids):raise GPSAPIError('BATCH_SIZE')
        # Bulk daily-summaries aggregates up to 100 vehicles and can exceed 8s on a cold cache.
        response=self.request('GET','/api/v1/gps/daily-summaries',params={'vehicleIds':','.join(ids)},timeout=20)
        if response.status_code!=200:raise GPSAPIError('DAILY_FAILED')
        try:
            items=response.json()['items']
            if not isinstance(items,list):raise ValueError()
            output={}
            for item in items:
                vid=str(UUID(item['vehicleId']))
                if vid not in ids or vid in output:raise ValueError()
                day=date.fromisoformat(item['date'])
                at=datetime.fromisoformat(item['asOf'].replace('Z','+00:00'))
                if not at.tzinfo or item['timeZone']!='Asia/Tashkent':raise ValueError()
                values={}
                for key in ('distanceKm','observedDistanceKm'):
                    val=item.get(key)
                    if val is not None and (isinstance(val,bool) or not isinstance(val,(float,int)) or not math.isfinite(val) or val<0):raise ValueError()
                    values[key]=val
                output[vid]={'vehicle_id':vid,'date':day.isoformat(),'timezone':item['timeZone'],
                             'as_of':at,'gps_state':item.get('gpsState'),**values}
            return output
        except Exception:raise GPSAPIError('DAILY_CONTRACT_INVALID') from None

    def current(self,vehicle_ids):
        ids=[str(UUID(str(v))) for v in vehicle_ids]
        if not 1<=len(ids)<=100:raise GPSAPIError('BATCH_SIZE')
        response=self.request('GET','/api/v1/gps/current-batch',params={'vehicleIds':','.join(ids)})
        if response.status_code!=200:raise GPSAPIError('CURRENT_FAILED')
        try:
            data=response.json()
            # Live CurrentBatch wraps each point in entries[].position.
            # Preserve explicit access revocations even if another entry is bad.
            nested=isinstance(data,dict) and 'entries' in data
            if nested:
                revoked=data.get('accessRevokedVehicleIds',[])
                if not isinstance(revoked,list):raise ValueError()
                revoked={str(UUID(v)) for v in revoked}
                if not revoked.issubset(ids):raise ValueError()
                self.revoked_vehicle_ids.update(revoked)
                data=data['entries']
            elif isinstance(data,dict):data=data['items']
            if not isinstance(data,list):raise ValueError()
            output={};seen=set()
            for item in data:
                vid=str(UUID(item['vehicleId']))
                if vid not in ids or vid in seen:raise ValueError()
                seen.add(vid)
                if vid in self.revoked_vehicle_ids:continue
                position=item.get('position') if nested else item
                if nested and position is None:
                    output[vid]=None
                    continue
                if not isinstance(position,dict) or not isinstance(position.get('fixTime'),str):raise ValueError()
                if 'vehicleId' in position and str(UUID(position['vehicleId']))!=vid:raise ValueError()
                output[vid]={**position,'vehicleId':vid}
            return output
        except Exception:raise GPSAPIError('CURRENT_CONTRACT_UNCONFIRMED') from None
