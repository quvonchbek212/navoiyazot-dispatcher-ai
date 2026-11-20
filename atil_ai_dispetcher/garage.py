"""Garage crossings and observed standing from bounded GPS observations."""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta
from types import SimpleNamespace

from . import config, gps, repository
from .fleet_yard_llm.models import CircleZone, DetectionPolicy, GPSPoint
from .fleet_yard_llm.rules import evaluate
from .Marshrut_optimizatsiyasi.geo import haversine_km

MAX_VEHICLES=200
MAX_POINTS=2000
MAX_GAP_SECONDS=300
STATIONARY_METERS=50


def distance(a,b):
    return haversine_km(a['latitude'],a['longitude'],b['latitude'],b['longitude'])*1000


def side(point,zone):
    meters=distance(point,zone)
    return 'INSIDE' if meters<=zone['radius_meters']-30 else 'OUTSIDE' if meters>=zone['radius_meters']+30 else 'BOUNDARY'


def normalize(rows,start,end):
    grouped=defaultdict(list);barriers=set();rejected=0
    for row in rows:
        point=gps.point(row['payload'],row['fix_time'],row['provider'])
        if not start<=row['fix_time']<end:continue
        if point is None:
            barriers.add(row['fix_time']);rejected+=1;continue
        point['binding_id']=row['binding_id']
        grouped[point['time']].append(point)
    points=[]
    for at,candidates in sorted(grouped.items()):
        signatures={(p['latitude'],p['longitude'],p['speed_kph'],p['binding_id']) for p in candidates}
        if len(signatures)!=1:
            rejected+=len(candidates);barriers.add(at);continue
        point=candidates[0]
        if points:
            previous=points[-1];seconds=(at-previous['time']).total_seconds()
            if distance(previous,point)/seconds*3.6>400:
                rejected+=1;barriers.add(at);continue
            if previous['binding_id']!=point['binding_id']:barriers.add(at)
        points.append(point)
    return points,sorted(barriers),rejected


def normalize_observations(observations,start,end):
    """Keep API segment boundaries even when points are deduplicated or rejected."""
    grouped=defaultdict(list);barriers=set();rejected=0;break_pending=False
    for item in observations:
        at=item.get('time') if isinstance(item,dict) else None
        if not isinstance(at,datetime) or at.tzinfo is None:
            rejected+=1;break_pending=True
            continue
        if not start<=at<end:continue
        point=gps.point({'fixTime':at.isoformat(),'latitude':item.get('latitude'),
            'longitude':item.get('longitude'),'speedKmh':item.get('speed_kph'),
            'accuracyMeters':item.get('accuracy_meters'),'valid':item.get('quality')!='INVALID'},api=True)
        if point is None:
            rejected+=1;barriers.add(at);continue
        point['quality']=item.get('quality',point['quality'])
        point['segment_start']=break_pending or bool(item.get('segment_start'))
        break_pending=False
        grouped[at].append(point)
    if break_pending:barriers.add(end)
    points=[]
    for at,candidates in sorted(grouped.items()):
        signatures={(p['latitude'],p['longitude'],p['speed_kph']) for p in candidates}
        if len(signatures)!=1:
            rejected+=len(candidates);barriers.add(at);continue
        point=candidates[0]
        if points:
            previous=points[-1];seconds=(at-previous['time']).total_seconds()
            # A break is between points. Marking the point itself would also
            # incorrectly break the next interval within this new segment.
            segment_start=any(p['segment_start'] for p in candidates)
            if segment_start:barriers.add(previous['time']+(at-previous['time'])/2)
            if not segment_start and distance(previous,point)/seconds*3.6>400:
                rejected+=1;barriers.add(at);continue
        points.append(point)
    return points,sorted(barriers),rejected


def vehicle_report(vehicle,rows,settings,start,end):
    truncated=len(rows)>MAX_POINTS
    points,barriers,rejected=normalize(rows[:MAX_POINTS],start,end)
    return observed_vehicle_report(vehicle,points,barriers,rejected,settings,start,end,
        truncated=truncated,source='GPS_ARCHIVE')


def observed_vehicle_report(vehicle,points,barriers,rejected,settings,start,end,*,
                            truncated=False,source='ATIL_API',complete=True,error=None):
    zone=settings.garage.model_dump()
    policy=DetectionPolicy(max_gap_seconds=MAX_GAP_SECONDS)
    yard=evaluate(SimpleNamespace(vehicle_id=vehicle['vehicle_id'],from_at=start,to_at=end,
        zone=CircleZone(**{k:zone[k] for k in ('name','latitude','longitude','radius_meters')}),policy=policy,
        points=[GPSPoint(timestamp=p['time'],latitude=p['latitude'],longitude=p['longitude'],speed_kph=p['speed_kph']) for p in points],
        untrusted_timestamps=barriers))
    intervals=[];covered=0;gap_count=0;stops=[];speed_classified=False
    for a,b in zip(points,points[1:]):
        seconds=(b['time']-a['time']).total_seconds()
        index=bisect_left(barriers,a['time'])
        blocked=index<len(barriers) and barriers[index]<=b['time']
        if blocked or seconds>MAX_GAP_SECONDS:
            gap_count+=1;continue
        covered+=seconds
        place=side(a,zone)
        if a['speed_kph'] is not None and b['speed_kph'] is not None:
            speed_classified=True
        stopped=(place==side(b,zone) and place!='BOUNDARY' and
                 a['speed_kph'] is not None and b['speed_kph'] is not None and
                 max(a['speed_kph'],b['speed_kph'])<=1 and distance(a,b)<=STATIONARY_METERS)
        if not stopped:continue
        # Never join stationary episodes separated by missing/invalid/moving observations.
        if (intervals and intervals[-1]['to_at']==a['time'] and intervals[-1]['place']==place
                and distance(intervals[-1],b)<=STATIONARY_METERS):
            intervals[-1]['to_at']=b['time'];intervals[-1]['seconds']+=seconds
        else:intervals.append({'from_at':a['time'],'to_at':b['time'],'seconds':seconds,'place':place,
                              'latitude':a['latitude'],'longitude':a['longitude']})
    last=points[-1] if points else None
    age=(end-last['time']).total_seconds() if last else None
    untrusted_latest=bool(barriers and (last is None or barriers[-1]>=last['time']))
    location=yard['state_at_window_end']
    state='NO_GPS_DATA' if not last else 'SIGNAL_LOST' if age>MAX_GAP_SECONDS else 'UNKNOWN'
    if last and age<=MAX_GAP_SECONDS and not untrusted_latest and not truncated and complete and not error and location in ('INSIDE','OUTSIDE'):
        state='LOCATION_ONLY' if last['speed_kph'] is None else ('GARAGE_' if location=='INSIDE' else 'OUTSIDE_')+('STOPPED' if last['speed_kph']<=1 else 'MOVING')
    for episode in intervals:
        active=(last is not None and episode['to_at']==last['time'] and
                state==('GARAGE_STOPPED' if episode['place']=='INSIDE' else 'OUTSIDE_STOPPED'))
        if episode['seconds']>=settings.garage_stop_minutes*60:
            stops.append({**episode,'observed_minutes':round(episode['seconds']/60,2),'active':active})
    return {**vehicle,'state':state,'last_signal_at':last['time'] if last else None,
        'last_point':last,'age_seconds':round(age) if age is not None else None,
        'entries':yard['summary']['entries'],'exits':yard['summary']['exits'],
        'events':yard['events'],'visits':yard['visits'],'stops':stops,
        'observed_garage_stop_minutes':round(sum(i['seconds'] for i in intervals if i['place']=='INSIDE')/60,2) if speed_classified else None,
        'observed_outside_stop_minutes':round(sum(i['seconds'] for i in intervals if i['place']=='OUTSIDE')/60,2) if speed_classified else None,
        'active_long_stop':any(s['active'] for s in stops),
        'quality':{'points':len(points),'rejected':rejected,'truncated':truncated,'complete':complete and not truncated and not error,'signal_gaps':gap_count,
                   'observed_interval_minutes':round(covered/60,2),'coverage_percent':round(covered/(end-start).total_seconds()*100,2)},
        'source':source,'error':error}


def report(settings,observations=None):
    end=observations['period']['end'] if observations is not None else config.now()
    start=end-timedelta(hours=settings.garage_hours)
    base={'generated_at':end,'garage':settings.garage.model_dump() if settings.garage else None,'hours':settings.garage_hours,
          'period':{'start':start,'end':end},'stop_threshold_minutes':settings.garage_stop_minutes,
          'max_gap_seconds':MAX_GAP_SECONDS,'source':'GPS_ARCHIVE','items':[],'events':[],'stops':[],'summary':{}}
    if settings.garage is None:return {**base,'status':'NOT_CONFIGURED'}
    if observations is not None:return api_report(settings,observations,base,start,end)
    # Read the time window once instead of rescanning the archive for each vehicle.
    # Each vehicle is bounded independently, so one busy unit cannot hide another.
    vehicles=repository.rows('''SELECT id::text vehicle_id,plate_number,count(*) over() total_vehicles
        FROM transport_vehicle ORDER BY plate_number,id LIMIT %s''',(MAX_VEHICLES,))
    groups={v['vehicle_id']:{'vehicle':{k:v[k] for k in ('vehicle_id','plate_number')},'rows':[]} for v in vehicles}
    data=repository.rows('''WITH numbered AS (
          SELECT a.vehicle_id,a.fix_time,a.payload,a.binding_id,g.provider_connection provider,
            row_number() OVER(PARTITION BY a.vehicle_id ORDER BY a.fix_time,a.provider_point_id) point_number
          FROM gps_archive_point a JOIN vehicle_gps g ON g.id=a.binding_id AND g.vehicle_id=a.vehicle_id
          WHERE a.vehicle_id=any(%s::uuid[]) AND a.fix_time>=%s AND a.fix_time<%s
            AND g.verified_from<=a.fix_time AND (g.unbound_at IS NULL OR a.fix_time<g.unbound_at))
        SELECT vehicle_id::text,fix_time,payload,binding_id::text,provider
        FROM numbered WHERE point_number<=%s ORDER BY vehicle_id,fix_time''',(list(groups),start,end,MAX_POINTS+1),timeout_ms=60000) if groups else []
    for row in data:
        vid=row['vehicle_id']
        groups[vid]['rows'].append(row)
    items=[vehicle_report(g['vehicle'],g['rows'],settings,start,end) for g in groups.values()]
    total=int(vehicles[0]['total_vehicles']) if vehicles else 0
    truncated=total>len(items) or any(v['quality']['truncated'] for v in items)
    return summarize(base,items,total,truncated)


def api_report(settings,observations,base,start,end):
    """Use the shared API batch; unavailable API history never triggers an archive scan."""
    items=[]
    for history in observations.get('items',[])[:MAX_VEHICLES]:
        vehicle=history['vehicle'];raw=history.get('points') or []
        # The shared fetch may also cover today's start, outside the garage window.
        # Filter before enforcing the per-vehicle garage bound.
        raw=[p for p in raw if not isinstance(p,dict) or not isinstance(p.get('time'),datetime)
             or p['time'].tzinfo is None or start<=p['time']<end]
        truncated=len(raw)>MAX_POINTS or bool(history.get('quality',{}).get('limit_exceeded'))
        points,barriers,rejected=normalize_observations(raw[:MAX_POINTS],start,end)
        trailing_untrusted=bool(history.get('quality',{}).get('trailing_untrusted'))
        # API normalization can discard the newest point. Keep its uncertainty
        # without erasing reliable earlier crossings and stationary intervals.
        if trailing_untrusted:barriers=sorted(set(barriers)|{end})
        period=history.get('period',observations['period'])
        window_complete=period['start']<=start and period['end']>=end
        complete=history.get('complete') is True and window_complete
        error=history.get('error')
        if error:
            points=[];barriers=[]
        item=observed_vehicle_report(vehicle,points,barriers,rejected,settings,start,end,
            truncated=truncated,source=history.get('source','ATIL_API'),complete=complete,error=error)
        if error in ('ACCESS_DENIED','API_ACCESS_REVOKED'):
            item['state']='ACCESS_REVOKED'
        item['quality'].update(window_complete=window_complete,trailing_untrusted=trailing_untrusted,
                               source_quality=history.get('quality',{}))
        item['fallback_reason']=history.get('fallback_reason')
        items.append(item)
    total=observations.get('total',len(observations.get('items',[])))
    truncated=bool(observations.get('truncated')) or total>len(items) or any(i['quality']['truncated'] for i in items)
    sources={i['source'] for i in items}
    base={**base,'source':next(iter(sources)) if len(sources)==1 else 'MIXED' if sources else 'ATIL_API',
          'scope':'GPS kuzatuvi uchun tanlangan transportlar; butun avtopark soni emas.'}
    result=summarize(base,items,total,truncated)
    if not items:
        result.update(status='UNAVAILABLE',error=observations.get('daily_error') or 'NO_GPS_OBSERVATIONS')
        result['summary'].update(entries=None,exits=None,garage_stopped=None,outside_stopped=None,
            active_long_stops=None,observed_long_stops=None,unknown=total or None,
            history_unavailable=total)
    return result


def summarize(base,items,total,truncated):
    events=[{**e,'vehicle_id':v['vehicle_id'],'plate_number':v['plate_number']} for v in items for e in v['events']]
    stops=[{**s,'vehicle_id':v['vehicle_id'],'plate_number':v['plate_number']} for v in items for s in v['stops']]
    unavailable=sum(bool(v.get('error')) for v in items)
    partial=sum(not v['quality']['complete'] or v['quality'].get('trailing_untrusted',False)
                for v in items if not v.get('error'))
    return {**base,'status':'PARTIAL' if truncated or unavailable or partial else 'COMPLETE','items':items,
        'events':sorted(events,key=lambda e:e['occurred_at'],reverse=True),
        'stops':sorted(stops,key=lambda s:s['to_at'],reverse=True),
        'truncated':truncated,'total':total,'returned':len(items),
        'summary':{'vehicles':len(items),'entries':sum(v['entries'] for v in items),'exits':sum(v['exits'] for v in items),
                   'garage_stopped':sum(v['state']=='GARAGE_STOPPED' for v in items),
                   'outside_stopped':sum(v['state']=='OUTSIDE_STOPPED' for v in items),
                   'active_long_stops':sum(v['active_long_stop'] for v in items),
                   'observed_long_stops':len(stops),'unknown':sum(v['state'] in ('UNKNOWN','NO_GPS_DATA','SIGNAL_LOST','LOCATION_ONLY','ACCESS_REVOKED') for v in items),
                   'history_available':len(items)-unavailable,'history_unavailable':unavailable,'partial_histories':partial},
        'limitations':['Hisob faqat tanlangan geozonaga nisbatan berilgan.',
            'To‘liq olinmagan tarixdagi kirish-chiqish va to‘xtashlar faqat olingan kuzatuvlar uchun berilgan.',
            'Kirish-chiqish kamida 2 nuqta va 30 soniya bilan tasdiqlanadi; vaqt GPS kuzatuvi bo‘yicha.',
            'Signal uzilishi, eski signal va noma’lum tezlik bekor turish deb olinmaydi.',
            'To‘xtashning ish uchun zarurligi yoki dvigatel ishlashi GPS orqali aniqlanmagan.']}
