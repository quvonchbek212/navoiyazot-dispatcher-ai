"""Human-readable dispatcher reports. Facts stay calculated; AI explains their meaning."""
from collections import Counter
from datetime import datetime
import json
import re

from pydantic import BaseModel, ConfigDict, Field
from . import config

SOURCE_NAMES={'overview':'umumiy holat','requests':'arizalar','fleet':'transportlar','drivers':'haydovchilar',
              'trips':'reyslar','gps':'GPS kuzatuvi','gps_daily':'kunlik GPS xulosasi','garage':'garaj kuzatuvi','sources':'ma’lumot manbalari',
              'fleet_state':'transport holatlari','waiting_diagnostics':'kutayotgan arizalar','repairs':'ta’mirlar',
              'document_coverage':'hujjat fayllari','change_index':'o‘zgarishlarni solishtirish manbasi','allocation':'arizalarga transport tanlovi'}

def value(v):
    if v is None:return 'noma’lum'
    return str(round(v,1)).removesuffix('.0') if isinstance(v,(float,int)) else str(v)

def when(v):
    if not v:return 'vaqti ko‘rsatilmagan'
    try:
        t=datetime.fromisoformat(v.replace('Z','+00:00')) if isinstance(v,str) else v
        if t.tzinfo:t=t.astimezone(config.TIMEZONE)
        return t.strftime('%d.%m.%Y %H:%M')
    except (ValueError,AttributeError):return 'vaqti aniqlanmagan'

def reason(text):
    return str(text).replace('Ish holati ACTIVE emas','Ish holati faol deb belgilanmagan').replace(
        'Bugungi FIT tibbiy ko‘rik tasdiqlanmagan','Bugungi tibbiy ko‘rikdan o‘tgani tasdiqlanmagan').replace(
        'Bugungi FIT texnik ko‘rik tasdiqlanmagan','Bugungi texnik ko‘rikdan o‘tgani tasdiqlanmagan')

def block(key,text,action='',severity='normal',details=None):
    return {'id':key,'text':text,'action':action,'severity':severity,'details':details or [],'explanation':''}

def daily_gps_block(report):
    items=report.get('items',[]);stats=report.get('summary',{});period=report.get('period',{})
    available=stats.get('available');unavailable=stats.get('unavailable');partial=stats.get('partial')
    text=f"Kunlik GPS xulosasi: {when(period.get('start'))} dan {when(period.get('end'))} gacha, Toshkent vaqti. "
    text+=f"{value(stats.get('vehicles',len(items)))} ta transport tekshirildi. "
    if report.get('status')=='UNAVAILABLE':
        text+='Bu davr uchun kunlik GPS ma’lumoti olinmadi. '
    else:
        if available is not None:text+=f'{value(available)} ta transport bo‘yicha kuzatuv ma’lumoti bor. '
        if partial:text+=f'{value(partial)} ta transportning hisobi qisman olingan. '
        if unavailable:text+=f'{value(unavailable)} ta transport bo‘yicha hisob olishning imkoni bo‘lmadi. '
        if stats.get('distance_km') is not None:
            distance_label='GPS kuzatgan masofa yig‘indisi' if stats.get('distance_scope')=='OBSERVED' else 'Olingan ma’lumotlarda qayd etilgan masofa yig‘indisi'
            text+=f"{distance_label} {value(stats['distance_km'])} km. "
            if stats.get('distance_scope') in ('OBSERVED','ESTIMATED'):text+='Bu to‘liq kun davomida bosib o‘tilgan yo‘lni tasdiqlamaydi. '
        else:text+='Bosib o‘tilgan masofa noma’lum. '
        if stats.get('observed_stop_minutes') is not None:
            text+=f"GPS kuzatuvida jami {value(stats['observed_stop_minutes'])} daqiqa to‘xtash aniqlangan. "
        else:text+='Kuzatilgan to‘xtash davomiyligi noma’lum. '
        if stats.get('signal_gaps') is not None:text+=f"Tarixda {value(stats['signal_gaps'])} ta signal uzilishi aniqlangan. "
    if any((i.get('distance_source')=='GPS_POINTS' or i.get('distance_scope')=='ESTIMATED') and i.get('distance_km') is not None for i in items):
        text+='GPS nuqtalaridan hisoblangan masofa taxminiy; u yo‘l bo‘ylab aniq masofa emas. '
    text+='Hisob faqat kelgan GPS kuzatuvlarini qamraydi. Signal kelmagan vaqt ishlamaslik yoki bekor turish deb olinmaydi; to‘xtash dvigatel ishlayotganini tasdiqlamaydi.'
    details=[]
    for index,item in enumerate(items,1):
        plate=item.get('plate_number') or f'Transport {index}'
        if item.get('status')=='UNAVAILABLE':
            detail=f'{plate}: bu davr uchun GPS hisobi olinmadi; masofa va to‘xtash vaqti noma’lum.'
        else:
            distance=item.get('distance_km')
            prefix='GPS nuqtalari bo‘yicha taxminan ' if item.get('distance_source')=='GPS_POINTS' or item.get('distance_scope')=='ESTIMATED' else 'GPS kuzatgan masofa ' if item.get('distance_scope')=='OBSERVED' else ''
            distance_text='masofa noma’lum' if distance is None else f'{prefix}{value(distance)} km'
            stop=item.get('observed_stop_minutes');moving=item.get('observed_moving_minutes');gaps=item.get('signal_gaps')
            observations=[distance_text, 'to‘xtash davomiyligi noma’lum' if stop is None else f'{value(stop)} daqiqa kuzatilgan to‘xtash']
            if moving is not None:observations.append(f'{value(moving)} daqiqa kuzatilgan harakat')
            if gaps is not None:observations.append(f'{value(gaps)} ta aniqlangan signal uzilishi')
            detail=f"{plate}: "+'; '.join(observations)+'.'
            if item.get('status')=='PARTIAL' or item.get('complete') is False:detail+=' Hisob qisman; bu davrning to‘liq natijasi emas.'
        if item.get('last_signal_at'):detail+=f" Oxirgi tarix nuqtasi: {when(item['last_signal_at'])}."
        details.append(detail)
    caution=report.get('status')!='COMPLETE'
    action='Hisobi olinmagan yoki qisman olingan transportlarning GPS tarixini tekshiring.' if caution else ''
    return block('gps_daily',text,action,'caution' if caution else 'normal',details)


def snapshot_blocks(report):
    s=report.get('sections',{});o=s.get('overview',{});out=[]
    intro=[]
    for key,label in [('waiting','ta ariza navbatda'),('active_trips','ta reys faol'),('vehicles','ta transport'),('drivers','nafar haydovchi hisobda bor')]:
        if o.get(key) is not None:intro.append(f'{value(o[key])} {label}')
    opening=(', '.join(intro)+'.') if intro else 'Umumiy holat uchun ma’lumot olinmagan.'
    waiting=o.get('waiting');fleet=s.get('fleet');staff=s.get('drivers')
    if waiting and fleet and staff:
        v_ready=sum(i.get('basic_checks_passed') is True for i in fleet.get('items',[]))
        d_ready=sum(i.get('basic_checks_passed') is True for i in staff.get('items',[]))
        if not v_ready or not d_ready:
            opening+=' Navbatdagi arizalarni bajarish uchun tekshirilgan yozuvlarda transport va haydovchi tayyorligi birgalikda tasdiqlanmadi. Avval bandlik, ko‘rik va hujjat to‘siqlarini aniqlashtirish kerak.'
        else:
            opening+=' Asosiy tekshiruvlardan o‘tgan transport va haydovchilar bor. Quyida arizalarga transport tanlovi va ochiq cheklovlar keltirilgan.'
    out.append(block('overview',opening))
    if 'allocation' in s:
        from .allocation import blocks as allocation_blocks
        out.extend(allocation_blocks(s['allocation']))
    from .insight_text import blocks as insight_blocks
    out.extend(insight_blocks(s))
    r=s.get('requests')
    if r is not None and not s.get('waiting_diagnostics',{}).get('returned'):
        items=r.get('items',[]);n=r.get('total',len(items));urgent=[i for i in items if i.get('priority') in ('CRITICAL','URGENT','HIGH')]
        text=f'Navbatda {value(n)} ta ariza bor. '
        if n:text+=f'Ko‘rib chiqilgan {len(items)} ta arizaning {len(urgent)} tasi yuqori ustuvorlikda. Har bir ariza uchun transport va haydovchi holati alohida tekshiriladi.'
        else:text+='Hozir ko‘rib chiqiladigan tasdiqlangan ariza topilmadi.'
        details=[f"{i.get('request_number') or 'Raqamsiz ariza'}: {i.get('origin_location') or 'jo‘nash joyi ko‘rsatilmagan'} → {i.get('destination_location') or 'borish joyi ko‘rsatilmagan'}." for i in (urgent or items)[:2]]
        out.append(block('requests',text,'Avval yuqori ustuvorlikdagi arizalarni bittadan tekshiring.' if urgent else 'Navbatdagi arizani tanlab, mos transport va haydovchi to‘siqlarini tekshiring.' if n else '', 'attention' if n else 'normal',details))
    for key,noun,inspection in [('fleet','transport','texnik'),('drivers','haydovchi','tibbiy')]:
        if key=='fleet' and 'fleet_state' in s:continue
        r=s.get(key)
        if r is None:continue
        items=r.get('items',[]);total=len(items);passed=sum(i.get('basic_checks_passed') is True for i in items)
        busy=sum(bool(i.get('busy_trip') or i.get('busy_waybill')) for i in items)
        unchecked=sum(any(f'{inspection} ko‘rik' in x for x in i.get('reasons',[])) for i in items)
        text=f'Tekshirilgan {total} ta {noun}ning {passed} tasi asosiy tekshiruvlardan o‘tdi. '
        if total:
            text+=f'{busy} tasida bandlik qayd etilgan, {unchecked} tasining bugungi {inspection} ko‘rigi tasdiqlanmagan. '
            if not passed:text+='Hozir bu tekshiruv asosida tayyor nomzodni tasdiqlab bo‘lmaydi. '
            text+='Bandlik va ko‘rik to‘siqlari bir yozuvda birga uchrashi mumkin.'
        else:text+='Tekshiruv uchun yozuv topilmadi.'
        out.append(block(key,text,f'{inspection.capitalize()} ko‘rik va bandlik yozuvlarini aniqlashtiring; ma’lumot yetishmasligini ishga tayyorlik deb qabul qilmang.' if total and passed<total else '', 'attention' if total and not passed else 'normal'))
    r=s.get('trips')
    if r is not None:
        counts=r.get('summary',{});late=counts.get('PLAN_OVERDUE',0);conflict=counts.get('DATA_CONFLICT',0);unknown=counts.get('NO_ZONED_PLAN',0)
        text=f"Ko‘rib chiqilgan {len(r.get('items',[]))} ta faol yoki rejalashtirilgan reysning {late} tasida reja vaqti o‘tgan. "
        text+=f'{conflict} ta reysda holat yoki vaqt yozuvlari bir-biriga zid; ular reja vaqti o‘tgan reyslar soniga qo‘shilmadi. '
        if unknown:text+=f'{unknown} ta reysning reja vaqtini ishonchli solishtirib bo‘lmadi. '
        text+='Bu mavjud reja bilan solishtirish; kelajakdagi yetib kelish vaqti hisoblanmagan.'
        examples=[f"{i.get('trip_number') or 'Raqamsiz reys'}: "+(f"reja tugashidan {value(i.get('overdue_minutes'))} daqiqa o‘tgan." if i.get('control_status')=='PLAN_OVERDUE' else 'holat va vaqt yozuvlarini solishtirish kerak.') for i in r.get('items',[]) if i.get('control_status') in ('PLAN_OVERDUE','DATA_CONFLICT')][:2]
        out.append(block('trips',text,'Reja vaqti o‘tgan reyslarning haqiqiy holatini aniqlang va zid yozuvlarni mas’ul xodim bilan solishtiring.' if late or conflict else '', 'attention' if late or conflict else 'normal',examples))
    r=s.get('documents')
    if r is not None:
        n=r.get('summary',{}).get('total',0);expired=r.get('summary',{}).get('expired',0)
        text=f'Haydovchi hujjatlarida {expired} ta muddati o‘tgan, {max(0,n-expired)} ta kelgusi 30 kun ichida tugaydigan muddat aniqlandi.'
        details=[f"{i.get('name')}: {i.get('document')} muddati {str(i.get('valid_until'))[:10]}." for i in r.get('items',[])[:2]]
        out.append(block('documents',text,'Muddati o‘tgan hujjatlarni tekshiring, yaqinlashayotgan muddatlar bo‘yicha yangilash ishini boshlang.' if n else '', 'attention' if n else 'normal',details))
    r=s.get('gps')
    if r is not None:
        stats=r.get('summary',{});total=stats.get('vehicles',len(r.get('items',[])));fresh=stats.get('recent');stale=stats.get('stale')
        text=f'GPS kuzatuvida {value(total)} ta transport bor. '
        if fresh is not None:text+=f'Shularning {value(fresh)} tasida signal oxirgi 5 daqiqada kelgan. '
        if stale is not None:text+=f'{value(stale)} tasining signali eskirgan. '
        if stats.get('access_revoked'):text+=f"{stats['access_revoked']} ta transportning GPS ma’lumotiga API ruxsati bekor qilingan; ularning joylashuvi ko‘rsatilmagan. "
        text+='Eski signal mashina hozir qayerdaligini yoki harakatlanayotganini tasdiqlamaydi. '
        api_count=sum(i.get('source')=='ATIL_API' and i.get('point') is not None for i in r.get('items',[]))
        archive_count=sum(i.get('source')=='GPS_ARCHIVE' for i in r.get('items',[]))
        if api_count:text+=f'{api_count} ta transportning nuqtasi ATIL GPS API orqali olindi. '
        if archive_count:text+=f'{archive_count} ta transport uchun GPS arxividagi yozuvlardan foydalanildi.'
        elif r.get('api_note') and not api_count:text+='Bu hisobda GPS arxividagi yozuvlardan foydalanildi.'
        out.append(block('gps',text,'GPS signali eskirgan transportlarning joylashuvini aniqlashtiring va signal kelishini tekshiring.' if fresh is None or fresh<total else '', 'attention' if fresh==0 and total else 'normal'))
    if s.get('gps_daily') is not None:out.append(daily_gps_block(s['gps_daily']))
    r=s.get('garage')
    if r is not None:
        if r.get('status')=='NOT_CONFIGURED':
            out.append(block('garage','Garaj hududi hali belgilanmagan. Koordinata va radius kiritilmaguncha kirish-chiqish aniqlanmaydi.','Garaj koordinatasi va radiusini shu oynadagi sozlamalarda kiriting.'))
        elif r.get('status')=='UNAVAILABLE' or (r.get('summary',{}).get('history_available')==0 and r.get('summary',{}).get('history_unavailable')):
            text='Garaj uchun hozir namuna hudud tanlangan. ' if (r.get('garage') or {}).get('is_example') else 'Garaj hududi sozlangan. '
            text+='Tekshirilgan transportlarning GPS tarixi olinmadi. Kirish-chiqish, hududdagi transportlar va to‘xtash davomiyligi noma’lum; buni transportlar kelmagan yoki ishlamagan deb talqin qilib bo‘lmaydi.'
            out.append(block('garage',text,'GPS tarixi ulanishini tekshirib, hisobni yangilang.','caution'))
        else:
            example=(r.get('garage') or {}).get('is_example');counts=r.get('summary',{})
            text='Garaj kuzatuvi namuna hududga nisbatan hisoblangan; bu haqiqiy garaj holati emas. ' if example else 'Garaj kuzatuvi saqlangan hududga nisbatan hisoblandi. '
            if r.get('source')=='ATIL_API':text+='Kuzatuv ATIL GPS API orqali olingan tarixga asoslangan. '
            elif r.get('source')=='GPS_ARCHIVE':text+='Kuzatuv bazadagi GPS arxiviga asoslangan. '
            text+=f"Tanlangan davrda {value(counts.get('entries'))} ta kirish va {value(counts.get('exits'))} ta chiqish tasdiqlangan. "
            if counts.get('garage_stopped') is not None and counts.get('outside_stopped') is not None:
                text+=f"Oxirgi kuzatuvda {value(counts['garage_stopped'])} ta transport hudud ichida, {value(counts['outside_stopped'])} tasi tashqarisida to‘xtagan holatda tasdiqlangan. "
            text+=f"{value(counts.get('observed_long_stops'))} ta tarixiy uzoq to‘xtash epizodi kuzatilgan; bir transportda bir nechta epizod bo‘lishi mumkin. "
            text+=f"{value(counts.get('unknown'))} ta transportning joriy holati tasdiqlanmagan. Signal bo‘shlig‘i bekor turish vaqtiga qo‘shilmaydi."
            if r.get('status')=='PARTIAL':text+=' Ayrim transportlarning tarixi to‘liq olinmagan; hisob qisman.'
            action='Haqiqiy garaj koordinatasini kiriting; namuna hudud natijasini amaliy qarorga asos qilmang.' if example else 'Uzoq to‘xtash kuzatilgan transportlarning topshiriq yoki yuk kutayotganini dispetcher bilan aniqlashtiring.' if counts.get('active_long_stops') else ''
            details=[]
            for event in r.get('events',[])[:2]:
                movement='hududga kirgani' if event.get('kind')=='ENTER' else 'hududdan chiqqani'
                details.append(f"{event.get('plate_number') or 'Transport'}: {when(event.get('occurred_at'))} da {movement} GPS bilan tasdiqlangan.")
            for stop in r.get('stops',[])[:2]:
                place='hudud ichida' if stop.get('place')=='INSIDE' else 'hudud tashqarisida'
                details.append(f"{stop.get('plate_number') or 'Transport'}: {when(stop.get('from_at'))} dan {when(stop.get('to_at'))} gacha {place} {value(stop.get('observed_minutes'))} daqiqa to‘xtash kuzatilgan. Sababi GPSdan aniqlanmaydi.")
            out.append(block('garage',text,action,'caution' if example or r.get('truncated') or r.get('status') in ('PARTIAL','UNAVAILABLE') else 'normal',details))
    limits=[]
    for key,r in s.items():
        if key in ('fleet_state','waiting_diagnostics','allocation'):continue # Same scopes as fleet/requests already listed.
        if not isinstance(r,dict) or not r.get('truncated'):continue
        if key=='garage':
            limits.append('garaj kuzatuvida transportlar yoki ularning GPS nuqtalari hajm chegarasi bilan qisqartirilgan')
        elif r.get('total') is not None and r.get('returned') is not None:
            limits.append(f"{SOURCE_NAMES.get(key,key)} bo‘yicha jami {r['total']} yozuvdan {r['returned']} tasi ko‘rildi")
        else:limits.append(f'{SOURCE_NAMES.get(key,key)} tarixi hajm chegarasi bilan qisqartirilgan')
    errors=report.get('errors',{})
    if errors:limits.append('quyidagi ma’lumotlar olinmadi: '+', '.join(SOURCE_NAMES.get(k,k) for k in errors))
    if limits:out.append(block('coverage','Hisobning chegarasi: '+'; '.join(limits)+'. Qamrovdan tashqaridagi holat haqida xulosa chiqarilmaydi.','Yetishmayotgan ma’lumotlarni to‘ldiring yoki qisqaroq davrni tekshiring.','caution'))
    return out


def selection_blocks(report):
    req=report.get('request',{});s=report.get('summary',{});vehicles=report.get('vehicles',[]);drivers=report.get('drivers',[])
    out=[block('request',f"{req.get('request_number') or 'Tanlangan ariza'} alohida tekshirildi. Yo‘nalish: {req.get('origin_location') or 'ko‘rsatilmagan'} → {req.get('destination_location') or 'ko‘rsatilmagan'}."),
         block('candidates',f"Talab qilingan turdagi {value(s.get('vehicles_of_type'))} ta transport ko‘rib chiqildi. {value(s.get('vehicle_checks_passed'))} ta transport va {value(s.get('driver_checks_passed'))} nafar haydovchi asosiy tekshiruvlardan o‘tdi. Bu natija avtomatik biriktirish yoki reysga ruxsat bermaydi.",
               'Haydovchi toifasi, reys shartlari va mavjud to‘siqlarni tekshirgach, amaldagi tartibda qaror qiling.','attention' if not s.get('vehicle_checks_passed') or not s.get('driver_checks_passed') else 'normal')]
    for key,items,label in [('vehicle_obstacles',vehicles,'Transport'),('driver_obstacles',drivers,'Haydovchi')]:
        reasons=Counter(reason(x) for v in items for x in set(v.get('reasons',[])+v.get('unverified',[])))
        if reasons:
            text=f'{label} tekshiruvlarida ko‘p uchragan sabablar: '+ '; '.join(f'{why.lower()} — {n} ta yozuvda' for why,n in reasons.most_common(4))+'. Bitta yozuvda bir nechta to‘siq bo‘lishi mumkin.'
            details=[f"{i.get('plate_number') or i.get('full_name') or label}: "+'; '.join(reason(x) for x in i.get('reasons',[])+i.get('unverified',[]))+'.' for i in items if i.get('reasons') or i.get('unverified')][:2]
            out.append(block(key,text,details=details,severity='attention'))
    missing=[k for k,v in report.get('data_quality',{}).items() if v]
    if missing:out.append(block('coverage','Nomzodlar ro‘yxati hajm chegarasi bilan qisqartirilgan. Hisob butun park bo‘yicha to‘liq tekshiruv emas.',severity='caution'))
    return out


def gps_blocks(report):
    points=report.get('points',[]);period=report.get('period',{});plate=report.get('vehicle',{}).get('plate_number') or 'Tanlangan transport'
    text=f"{plate} uchun {when(period.get('start'))} dan {when(period.get('end'))} gacha bo‘lgan GPS tarixi tekshirildi. {len(points)} ta yaroqli nuqta olindi. "
    text+='Manba: '+('ATIL GPS xizmati.' if report.get('source')=='ATIL_API' else 'GPS arxivi.')
    out=[block('gps_history',text)]
    if points:
        last=points[-1]
        out.append(block('last_observation',f"Oxirgi olingan nuqta {when(last.get('time'))} da qayd etilgan. "+(f"Shu nuqtadagi tezlik {value(last['speed_kph'])} km/soat." if last.get('speed_kph') is not None else 'Shu nuqtadagi tezlik noma’lum.')+' Tarixdagi nuqta transportning hozirgi joylashuvini tasdiqlamaydi.'))
        breaks=sum(bool(p.get('segment_start')) for p in points)
        if breaks>1:out.append(block('gaps',f'Tarix {breaks} ta alohida kuzatuv bo‘lagidan iborat. Ularning orasidagi harakat yoki to‘xtash taxmin bilan to‘ldirilmadi.',severity='caution'))
    else:out.append(block('no_points','Tanlangan davrda yaroqli GPS nuqtasi topilmadi. Bundan transport ishlamagan yoki bekor turgan degan xulosa kelib chiqmaydi.','Kengroq davrni tanlang yoki GPS signalining kelishini tekshiring.','caution'))
    if not report.get('complete'):out.append(block('coverage','Tarix hajm chegarasi bilan kesilgan. Natijada davrning barcha nuqtalari bo‘lmasligi mumkin.','Qisqaroq davrni tekshiring.','caution'))
    return out


def gps_v3_blocks(report):
    obs=report.get('observation') or {};period=report.get('period',{});plate=report.get('vehicle',{}).get('plate_number') or 'Tanlangan transport'
    points=obs.get('points',0)
    text=f"{plate} uchun {when(period.get('start'))} dan {when(period.get('end'))} gacha bo‘lgan GPS kuzatuvi tekshirildi. {value(points)} ta yaroqli nuqta olindi. "
    if obs.get('distance_km') is not None:
        text+=f"GPS nuqtalari bo‘yicha taxminiy masofa {value(obs['distance_km'])} km. "
    if obs.get('observed_stop_minutes') is not None:
        text+=f"Kuzatilgan to‘xtash {value(obs['observed_stop_minutes'])} daqiqa. "
    if obs.get('observed_moving_minutes') is not None:
        text+=f"Kuzatilgan harakat {value(obs['observed_moving_minutes'])} daqiqa. "
    out=[block('gps_history',text.strip())]
    if not points:
        out.append(block('no_points','Tanlangan davrda yaroqli GPS nuqtasi topilmadi. Bundan transport ishlamagan yoki bekor turgan degan xulosa kelib chiqmaydi.','Kengroq davrni tanlang yoki GPS signalining kelishini tekshiring.','caution'))
    elif obs.get('last_signal_at'):
        out.append(block('last_observation',f"Oxirgi olingan nuqta {when(obs['last_signal_at'])} da qayd etilgan. Tarixdagi nuqta transportning hozirgi joylashuvini tasdiqlamaydi."))
    g=report.get('garage_view') or {}
    if g.get('state') and g.get('state')!='NOT_CONFIGURED':
        name=g.get('name') or 'Garaj'
        prefix='Namuna hudud bo‘yicha ' if g.get('is_example') else ''
        gtext=f"{prefix}{name}: kirish {value(g.get('entries'))}, chiqish {value(g.get('exits'))}, garajda kuzatilgan to‘xtash {value(g.get('stop_minutes'))} daqiqa."
        out.append(block('garage',gtext,severity='caution' if g.get('is_example') else 'normal'))
    if not report.get('complete'):
        out.append(block('coverage','Tarix hajm chegarasi yoki kirish cheklovi sabab qisman olingan.','Qisqaroq davrni tekshiring.','caution'))
    return out


def build(report):
    if 'sections' in report:blocks=snapshot_blocks(report);title='Dispetcher holati bo‘yicha tahlil'
    elif 'request' in report:blocks=selection_blocks(report);title='Ariza bo‘yicha tahlil'
    elif 'points' in report:blocks=gps_blocks(report);title='Transport GPS tarixi bo‘yicha tahlil'
    elif 'observation' in report:blocks=gps_v3_blocks(report);title='Transport GPS tarixi bo‘yicha tahlil'
    else:blocks=[block('legacy','Bu hisobot oldingi ish jarayonida saqlangan. Joriy holat uchun yangi tahlilni ishga tushiring.')];title='Oldingi hisobot'
    from .presentation import compact
    blocks=compact(report,blocks)
    ranked=sorted([b for b in blocks if b['action']],key=lambda b:({'attention':0,'caution':1,'normal':2}[b['severity']],blocks.index(b)))
    return {'version':2,'title':title,'generated_at':report.get('generated_at') or report.get('period',{}).get('end'),
            'source':'calculated','ai_status':'PENDING','blocks':blocks,'priority_ids':[b['id'] for b in ranked[:3]],
            'notice':'AI izohi hali olinmagan. Quyida mavjud ma’lumotlardan tuzilgan tushuntirish berilgan.'}


def ensure(report):
    previous=report.get('narrative')
    if not previous or previous.get('version')!=2:
        report['narrative']=build(report)
        # Reading an older saved report updates its view, never its evidence,
        # timestamp or persisted result, and does not invoke the model again.
        if previous:
            n=report['narrative']
            n.update(ai_status=previous.get('ai_status','PENDING'),notice=previous.get('notice',''))
            old={b['id']:b.get('explanation','') for b in previous.get('blocks',[])}
            for b in n['blocks']:
                b['explanation']=useful_explanation(old.get(b['id'],''),b,n['blocks'])
            n['source']='llm' if any(b['explanation'] for b in n['blocks']) else 'calculated'
    return report['narrative']


def as_text(narrative):
    text=[narrative['title']]
    for b in narrative['blocks']:
        text.append(b['text']+(' '+b['explanation'] if b.get('explanation') else ''))
    actions={b['id']:b['action'] for b in narrative['blocks']}
    owners={b['id']:b.get('owner','') for b in narrative['blocks']}
    text.extend((owners[k]+': ' if owners.get(k) else '')+actions[k] for k in narrative['priority_ids'] if actions.get(k))
    return '\n\n'.join(text)


def useful_explanation(text, fact, blocks):
    """Show an extra interpretation only when it adds to the calculated prose."""
    text=str(text or '').strip()
    if not text:return ''
    if re.search(r'[0-9<>]|\b(?!GPS\b)[A-Z_]{3,}\b',text):return ''
    if re.search(r'jarima|tirband|yoqilg|foiz|xavf.{0,5}ball|avtomatik.{0,20}biriktir|nosoz|malakasiz|aybdor|yaroqsiz',text,re.I):return ''
    if re.search(r'\bGPS\b',text) and 'GPS' not in fact['text']:return ''
    if 'eski' in text.lower() and 'eski' not in fact['text'].lower():return ''
    # An instruction on its own is already represented by the named next action.
    if not re.search(r'chunki|sabab|mumkin|aks holda|oldini|ta.sir|anglat|bildir|tasdiq|bog.li|qaror',text,re.I):return ''
    def words(s):
        return {w[:7] for w in re.findall(r'[a-zа-яёʻ‘’]+',s.lower()) if len(w)>3}
    tokens=words(text)
    existing=[fact['text'],fact.get('action','')]
    existing += [b.get('explanation','') for b in blocks if b is not fact]
    if tokens and any(len(tokens & words(s))/len(tokens)>=.8 for s in existing if s):return ''
    return text


class Explanation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    fact_id:str
    text:str=Field(max_length=240)

class Answer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    explanations:list[Explanation]=Field(min_length=1,max_length=12)
    priority_ids:list[str]=Field(max_length=3)


def validate_answer(raw,narrative):
    from core.ollama_json import extract_json
    answer=Answer.model_validate(extract_json(raw))
    facts={b['id']:b for b in narrative['blocks']}
    ids=[x.fact_id for x in answer.explanations]
    if len(ids)!=len(set(ids)) or set(ids)!=set(facts):raise ValueError('Explanation coverage mismatch')
    allowed={k for k,v in facts.items() if v['action']}
    if len(answer.priority_ids)!=len(set(answer.priority_ids)) or not set(answer.priority_ids)<=allowed:raise ValueError('Unsupported priority')
    if allowed and not answer.priority_ids:raise ValueError('Priorities missing')
    for e in answer.explanations:
        # Quantities, times and identifiers are rendered from source facts only.
        if re.search(r'[0-9<>]|\b(?!GPS\b)[A-Z_]{3,}\b',e.text):raise ValueError('Unverified number or technical code')
        if re.search(r'jarima|tirband|yoqilg|foiz|xavf.{0,5}ball|avtomatik.{0,20}biriktir|nosoz|malakasiz|aybdor|yaroqsiz',e.text,re.I):raise ValueError('Unsupported claim')
        if e.text and e.fact_id=='garage' and 'namuna' in facts[e.fact_id]['text'].lower() and 'namuna' not in e.text.lower():raise ValueError('Sample qualification missing')
        if e.text and e.fact_id in ('gps','gps_daily','last_observation','no_points') and not re.search(r'tasdiq|aniq|eski|yangila|tekshir|noma.lum|kuzatuv',e.text,re.I):raise ValueError('GPS uncertainty missing')
        if e.text and 'GPS' in e.text and 'GPS' not in facts[e.fact_id]['text']:raise ValueError('Unsupported GPS claim')
        if 'eski' in e.text.lower() and 'eski' not in facts[e.fact_id]['text'].lower():raise ValueError('Unsupported stale claim')
    return answer


async def enrich(report,lang='uz'):
    from config import DEFAULT_NUM_CTX
    from ollama_client import ask_llm
    n=ensure(report)
    # Personal names, plate numbers, request identifiers and coordinates remain in
    # locally generated detail sentences, not in the explanation-model prompt.
    facts=[{'fact_id':b['id'],'fact':b['text'],'permitted_action':b['action']} for b in n['blocks']]
    if 'request' in report:facts=[f for f in facts if f['fact_id']!='request']
    if 'points' in report:facts=[{**f,'fact':re.sub(r'^.*? uchun ', 'Tanlangan transport uchun ',f['fact'])} if f['fact_id']=='gps_history' else f for f in facts]
    # All facts already have readable explanations. Bound model output so the
    # recurring report stays useful on a slow local model as well.
    chosen=[facts[0]['fact_id']]
    chosen+= [k for k in n['priority_ids'] if k not in chosen and any(f['fact_id']==k for f in facts)]
    chosen+= [f['fact_id'] for f in facts if f['fact_id'] not in chosen]
    chosen=chosen[:3]
    facts=[f for f in facts if f['fact_id'] in chosen]
    prompt=('Siz o‘zbek tilida sodda va ravon yozadigan dispetcher yordamchisisiz. Berilgan har bir fakt uchun '
            'uning dispetcher qaroriga ta’sirini bitta qisqa jumlada tushuntiring. Jami ko‘pi bilan qirq so‘z. Jadval yozmang. Faktni '
            'yoki permitted_action tavsiyasini boshqa so‘z bilan takrorlamang. Qo‘shimcha foydali talqin bo‘lmasa text="" qaytaring. Yangi fakt, sabab, son, raqam, '
            'ism, transport raqami, foiz, muddat yoki yetib kelish prognozini kiritmang. Ma’lumot yo‘qligi '
            'nosozlik yoki bekor turish isboti emas. Namuna garajga izoh yozsangiz "namuna" so‘zini saqlang. GPS eskirgan deb '
            'faqat aynan berilgan faktda eskirgani aytilgan bo‘lsa yozing. priority_ids uchun faqat '
            'permitted_action bo‘sh bo‘lmagan faktlardan eng muhim ko‘pi bilan uchtasini tanlang. '
            'explanations ichida har bir fact_id aynan bir marta bo‘lsin. Faqat sxemaga mos JSON qaytaring. Faktlar: '+json.dumps(facts,ensure_ascii=False))
    raw=await ask_llm(prompt,{'options':{'temperature':.1,'num_predict':700,'num_ctx':DEFAULT_NUM_CTX},
                             'think':False,'response_json_schema':Answer.model_json_schema()})
    validation_n={**n,'blocks':[b for b in n['blocks'] if b['id'] in {f['fact_id'] for f in facts}]}
    answer=validate_answer(raw,validation_n)
    explanations={e.fact_id:e.text for e in answer.explanations}
    for b in n['blocks']:b['explanation']=explanations.get(b['id'],'')
    # Calculated priorities retain named operational actions even when the model
    # only comments on a smaller selection of facts.
    n.update(source='llm' if any(b['explanation'] for b in n['blocks']) else 'calculated',ai_status='COMPLETE',notice='')
    report['analysis']={'text':as_text(n)}
