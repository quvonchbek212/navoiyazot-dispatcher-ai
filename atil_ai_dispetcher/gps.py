"""GPS observation only: no inferred risk, legal limits, fuel or arrival prediction."""
from datetime import datetime,timedelta
import json
import math
from . import config,repository,gps_api
from .fleet_yard_llm.config import ARCHIVE_SPEED_UNITS


def number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None


def point(payload,timestamp=None,provider=None,api=False):
    try:
        p=json.loads(payload) if isinstance(payload,str) else payload
        t=timestamp or datetime.fromisoformat(p['fixTime'].replace('Z','+00:00'))
        if not isinstance(p,dict) or not t.tzinfo:raise ValueError()
        lat,lon=number(p.get('latitude')),number(p.get('longitude'))
        if lat is None or lon is None or not(-90<=lat<=90 and -180<=lon<=180):raise ValueError()
        if p.get('valid') is False or (not api and p.get('valid') is not True):raise ValueError()
        explicit_kph=p.get('speedKmh') if api else (p.get('speedKmh') if p.get('speedKmh') is not None else p.get('speed_kph'))
        speed=number(explicit_kph) if explicit_kph is not None else number(p.get('speed'))
        if not api and explicit_kph is None:
            factor={'knots':1.852,'kph':1,'mph':1.609344,'mps':3.6}.get(ARCHIVE_SPEED_UNITS.get(str(provider).upper()))
            speed=speed*factor if speed is not None and factor is not None else None
        if speed is not None and not 0<=speed<=200:speed=None
        return {'time':t,'latitude':lat,'longitude':lon,'speed_kph':round(speed,2) if speed is not None else None,
                'accuracy_meters':number(p.get('accuracyMeters') if api else p.get('accuracy')),
                'quality':'API_VALIDITY_NOT_EXPOSED' if api and 'valid' not in p else 'VALID'}
    except (ValueError,TypeError,KeyError,AttributeError):return None


def latest():
    as_of=config.now()
    rows=repository.rows('''SELECT v.id::text vehicle_id,v.plate_number,p.fix_time,p.payload,p.provider
        FROM transport_vehicle v JOIN (SELECT DISTINCT vehicle_id FROM vehicle_gps
        WHERE active AND unbound_at IS NULL AND verified_from<=current_timestamp) g ON g.vehicle_id=v.id
        LEFT JOIN LATERAL (SELECT a.fix_time,a.payload,b.provider_connection provider
          FROM gps_archive_point a JOIN vehicle_gps b ON b.id=a.binding_id AND b.vehicle_id=a.vehicle_id
          WHERE a.vehicle_id=v.id AND b.verified_from<=a.fix_time AND (b.unbound_at IS NULL OR a.fix_time<b.unbound_at)
          ORDER BY a.fix_time DESC LIMIT 1) p ON true ORDER BY v.plate_number,v.id LIMIT 201''')
    truncated=len(rows)>200;rows=rows[:200]
    api_points={};fallback='NOT_CONFIGURED';client=None;revoked=set()
    if gps_api.configured() and rows:
        try:
            client=gps_api.GPSClient()
            for i in range(0,len(rows),100):api_points.update(client.current([r['vehicle_id'] for r in rows[i:i+100]]))
            fallback=None
        except gps_api.GPSAPIError as exc:fallback=str(exc)
        finally:
            if client:
                revoked.update(client.revoked_vehicle_ids)
                client.close()
    items=[]
    for row in rows:
        vid=row['vehicle_id'];p=point(api_points.get(vid),api=True) if vid in api_points else None
        denied=vid in revoked
        if denied:p=None
        source='ATIL_API' if p or denied else 'GPS_ARCHIVE'
        if not p and not denied:p=point(row['payload'],row['fix_time'],row['provider'])
        age=(as_of-p['time']).total_seconds() if p else None
        state='ACCESS_REVOKED' if denied else 'NO_VALID_SIGNAL' if age is None else 'FUTURE_TIME' if age<0 else 'RECENT' if age<=300 else 'STALE'
        items.append({'vehicle_id':vid,'plate_number':row['plate_number'],'point':p,'source':source,
                      'state':state,'age_seconds':round(age) if age is not None else None,
                      'fallback_reason':'API_ACCESS_REVOKED' if denied else (fallback or ('NO_VALID_API_POINT' if vid in api_points else 'VEHICLE_NOT_IN_API_RESPONSE')) if source=='GPS_ARCHIVE' else None})
    return {'checked_at':as_of,'items':items,'truncated':truncated,'freshness_seconds':300,
            'summary':{'vehicles':len(items),'recent':sum(i['state']=='RECENT' for i in items),
                       'stale':sum(i['state']=='STALE' for i in items),'access_revoked':len(revoked)},'api_configured':gps_api.configured(),
            'api_note':fallback}


def api_history(vehicle,raw,start,end):
    """Normalize one API window for both garage and daily observations."""
    items=[];break_pending=True;excluded=0;last=None
    for index,item in enumerate(raw['points']):
        p=point(item,api=True)
        if not p or not start<=p['time']<end:
            excluded+=1;break_pending=True;continue
        if last and p['time']<last:raise gps_api.GPSAPIError('HISTORY_ORDER_INVALID')
        p['segment_start']=break_pending or index in raw['segment_starts']
        items.append(p);last=p['time'];break_pending=False
    return {'vehicle':vehicle,'source':'ATIL_API','period':{'start':start,'end':end},'points':items,
            'complete':raw['complete'],'quality':{'pages':raw['pages'],'locally_excluded':excluded,
            'trailing_untrusted':bool(excluded and break_pending),
            'limit_exceeded':raw['limit_exceeded']},'fallback_reason':None}


def history(vehicle_id,hours):
    end=config.now();start=end-timedelta(hours=hours)
    vehicle=repository.rows('SELECT id::text vehicle_id,plate_number FROM transport_vehicle WHERE id=%s::uuid',(str(vehicle_id),))
    if not vehicle:raise ValueError('Transport topilmadi')
    fallback='NOT_CONFIGURED';client=None
    if gps_api.configured():
        try:
            client=gps_api.GPSClient();raw=client.history(vehicle_id,start,end)
            return api_history(vehicle[0],raw,start,end)
        except gps_api.GPSAPIError as exc:fallback=str(exc)
        finally:
            if client:client.close()
    rows=repository.rows('''SELECT a.fix_time,a.payload,a.binding_id::text,g.provider_connection provider
        FROM gps_archive_point a JOIN vehicle_gps g ON g.id=a.binding_id AND g.vehicle_id=a.vehicle_id
        WHERE a.vehicle_id=%s::uuid AND a.fix_time>=%s AND a.fix_time<%s
          AND g.verified_from<=a.fix_time AND (g.unbound_at IS NULL OR a.fix_time<g.unbound_at)
        ORDER BY a.fix_time,a.provider_point_id LIMIT 5001''',(str(vehicle_id),start,end))
    items=[];last=None;last_binding=None;excluded=0;break_pending=True
    for row in rows[:5000]:
        p=point(row['payload'],row['fix_time'],row['provider'])
        if not p:excluded+=1;break_pending=True;continue
        p['segment_start']=break_pending or last is None or row['binding_id']!=last_binding or (p['time']-last).total_seconds()>120
        last=p['time'];last_binding=row['binding_id'];items.append(p);break_pending=False
    return {'vehicle':vehicle[0],'source':'GPS_ARCHIVE','period':{'start':start,'end':end},'points':items,
            'complete':len(rows)<=5000,'quality':{'locally_excluded':excluded,'limit_exceeded':len(rows)>5000,
            'gap_rule_seconds':120},'fallback_reason':fallback}
