"""Compact reading view of calculated evidence; never changes the source report."""
from copy import deepcopy


def compact(report, original):
    from .narrative import value, when

    blocks = deepcopy(original)
    by_id = {b['id']: b for b in blocks}
    sections = report.get('sections', {})
    removed = set()
    scopes = []

    def edit(key, text, owner='', action=''):
        b = by_id.get(key)
        if b is None:
            return
        b.update(text=text.strip(), owner=owner, action=action)

    def group(target, title, items):
        if target in by_id and items:
            by_id[target].setdefault('detail_groups', []).append({'title': title, 'items': list(items)})

    def scope(text):
        if text and text not in scopes:
            scopes.append(text)

    # Keep contextual warnings, but give shared qualifications a single home.
    for b in blocks:
        b['owner'] = ''
        if b.get('details'):
            b['details_label'] = 'Dalillar va misollar'

    if 'sections' not in report:
        owners = {'candidates': 'Dispetcher', 'no_points': 'GPS mutaxassisi', 'coverage': 'Dispetcher'}
        for b in blocks:
            if b['action']:
                b['owner'] = owners.get(b['id'], 'Dispetcher')
        return blocks

    o = sections.get('overview', {})
    intro = []
    # Queue counts belong to the queue card, readiness to the resource cards.
    for key, label in [('vehicles', 'ta transport'), ('drivers', 'nafar haydovchi hisobda'),
                       ('active_trips', 'ta reys faol holatda qayd etilgan')]:
        if o.get(key) is not None:
            intro.append(f'{value(o[key])} {label}')
    if o.get('waiting') is not None and 'allocation' not in by_id and 'requests' not in by_id:
        intro.append(f"{value(o['waiting'])} ta ariza navbatda")
    if intro:
        edit('overview', '; '.join(intro) + '.')

    allocation = sections.get('allocation', {})
    counts = allocation.get('summary')
    waiting = sections.get('waiting_diagnostics', {})
    wc = waiting.get('summary', {})
    if counts is not None and 'allocation' in by_id:
        text = f"Navbatda {value(allocation.get('total'))} ta ariza; {counts['considered']} tasi ko‘rildi. "
        text += (f"{counts['recommended']} tasiga transport tavsiya qilindi. " if counts['recommended']
                 else 'Yangi transport tavsiyasi berilmadi. ')
        for key, label in [('already_bound', 'tasida avvalgi biriktirish bor'),
                           ('needs_data', 'tasida ma’lumot yetishmaydi'),
                           ('no_match', 'tasiga mos tayyor transport topilmadi'),
                           ('shortage', 'tasiga mos transportlar boshqa arizalarga tavsiya qilingan')]:
            if counts.get(key):
                text += f'{counts[key]} {label}. '
        if wc.get('missing_amount'):
            text += f"Yuk yoki yo‘lovchi miqdori {wc['missing_amount']} ta arizada yozilmagan."
        if allocation.get('scope_limited'):
            text += ' Tanlov qamrovi qisman.'
        owner = 'Ariza muallifi va dispetcher' if counts.get('needs_data') else 'Dispetcher'
        action = ('Ariza muallifi yuk og‘irligi, hajmi yoki yo‘lovchi sonini kiritsin; '
                  'dispetcher ustuvor arizalardan boshlab tanlovni qayta ishga tushirsin.'
                  if counts.get('needs_data') else
                  'Tavsiya qilingan transport va haydovchining reys shartlariga mosligini tasdiqlab, ATILda biriktiring.'
                  if counts.get('recommended') else
                  'Transport va haydovchi kartalaridagi to‘siqlarni bartaraf etgach, tanlovni qayta ishga tushiring.'
                  if counts.get('no_match') or counts.get('shortage') else '')
        edit('allocation', text, owner if action else '', action)
        for key, title in [('allocation_matches', 'Transport tavsiya qilingan arizalar'),
                           ('allocation_waiting', 'Transport tavsiya qilinmagan arizalar')]:
            if key in by_id:
                group('allocation', title, by_id[key]['details'])
                removed.add(key)
        if 'waiting_diagnostics' in by_id:
            group('allocation', 'Kutish davomiyligi va kuzatilgan to‘siqlar', by_id['waiting_diagnostics']['details'])
            removed.add('waiting_diagnostics')
        if 'requests' in by_id:
            group('allocation', 'Ustuvor arizalar', by_id['requests']['details'])
            removed.add('requests')
        proximity = (f"Yuk olish koordinatasi {value(counts.get('requests_with_origin_coordinates'))} ta arizada mavjud. "
                     f"Tanlovga tayyor transportlardan {value(counts.get('ready_vehicles_with_fresh_gps'))} tasida yangi GPS bor. "
                     'Bu ko‘rsatkichlar butun parkning GPS holatini bildirmaydi.')
        group('allocation', 'Yaqinlik bo‘yicha qamrov', [proximity])
    if 'allocation_scope' in by_id:
        removed.add('allocation_scope')
        for text in allocation.get('limitations', []):
            scope(text)
        scope('Haydovchilar arizalarga taqsimlanmagan; toifa va smena mosligi biriktirishdan oldin alohida tasdiqlanadi.')
    if 'waiting_diagnostics' in by_id or waiting:
        scope('Kutish diagnostikasi hozirgi to‘siqlarni ko‘rsatadi; ariza aynan shu sabab kutgani tasdiqlanmagan.')
        if wc.get('unknown_age'):
            group('allocation' if counts is not None else 'waiting_diagnostics', 'Kutish hisobi chegarasi',
                  [f"{wc['unknown_age']} ta arizaning kutish davomiyligi noma’lum."])

    if counts is None and 'waiting_diagnostics' in by_id:
        text = f"{value(waiting.get('returned'))} ta arizada kutish holati ko‘rildi. "
        if wc.get('with_obstacles'):
            text += f"{wc['with_obstacles']} tasida ochiq to‘siqlar bor. "
        if wc.get('missing_amount'):
            text += f"{wc['missing_amount']} tasida yuk yoki yo‘lovchi miqdori yozilmagan. "
        if not waiting.get('fleet_available'):
            text += 'Transport ma’lumoti olinmagan; moslik noma’lum. '
        if not waiting.get('drivers_available'):
            text += 'Haydovchi tayyorligi ma’lumoti olinmagan.'
        edit('waiting_diagnostics', text, 'Ariza muallifi va dispetcher',
             'Yetishmagan miqdorlarni kiriting; eng uzoq kutayotgan ustuvor arizalarning to‘siqlarini bartaraf eting.')

    fleet = sections.get('fleet', {})
    rows = fleet.get('items', [])
    technical = sum(any('texnik ko‘rik' in why for why in v.get('reasons', [])) for v in rows)
    fs = sections.get('fleet_state')
    if fs and 'fleet_state' in by_id:
        labels = {'operating': 'reys yoki yo‘l varaqasi bo‘yicha ishda', 'reserved': 'biriktirilgan yoki band',
                  'maintenance': 'ta’mir sabab cheklangan', 'restricted': 'foydalanishi cheklangan',
                  'ready': 'asosiy tekshiruvlardan o‘tgan va topshiriqsiz',
                  'unconfirmed': 'topshiriqsiz, tayyorligi tasdiqlanmagan', 'conflict': 'holat yozuvlari zid'}
        parts = [f'{fs["counts"][key]} tasi {label}' for key, label in labels.items() if fs['counts'].get(key)]
        text = f"Ko‘rilgan {fs['returned']} ta transport: " + ('; '.join(parts) + '.' if parts else 'yozuv topilmadi.')
        if fs['returned'] and not fs['counts'].get('ready'):
            text += ' Topshiriqsiz, ishga tayyor transport tasdiqlanmadi.'
        if technical:
            text += f' {technical} tasida bugungi texnik ko‘rik tasdiqlanmagan.'
        action = []
        if technical:
            action.append('Mexanik bugungi texnik ko‘rik natijalarini bazaga kiritsin.')
        if fs['counts'].get('conflict'):
            action.append('Dispetcher faol reys va yo‘l varaqalarining yakun belgilarini haqiqiy bandlikka moslashtirsin.')
        if fs['counts'].get('maintenance'):
            action.append('Mexanik chiqishni cheklovchi ta’mirlar holatini yangilasin.')
        edit('fleet_state', text, 'Mexanik va dispetcher' if action else '', ' '.join(action))
        scope('Transportlar bir martadan sanaladi. Zid yozuvlar boshqa guruhlarga qayta qo‘shilmaydi; reysda qayd etilish GPSdagi harakat tasdig‘i emas.')

    if 'drivers' in by_id:
        drivers = sections['drivers'].get('items', [])
        passed = sum(d.get('basic_checks_passed') is True for d in drivers)
        medical = sum(any('tibbiy ko‘rik' in why for why in d.get('reasons', [])) for d in drivers)
        busy = sum(bool(d.get('busy_trip') or d.get('busy_waybill')) for d in drivers)
        text = f'Ko‘rilgan {len(drivers)} nafar haydovchidan {passed} nafari asosiy tekshiruvlardan o‘tgan.'
        if medical:
            text += f' {medical} nafarida bugungi tibbiy ko‘rik tasdiqlanmagan.'
        if busy:
            text += f' {busy} nafari reys yoki yo‘l varaqasi bilan band.'
        action = []
        if medical:
            action.append('Tibbiyot xodimi bugungi ko‘rik natijalarini kiritsin.')
        if busy:
            action.append('Dispetcher yakunlangan qatnovlarning bandlik yozuvlarini yangilasin.')
        edit('drivers', text, 'Tibbiyot xodimi va dispetcher' if action else '', ' '.join(action))
        scope('Bandlik va ko‘rik to‘siqlari bir yozuvda birga uchrashi mumkin. Tasdiqlanmagan tayyorlik yaroqsizlik isboti emas.')

    change = sections.get('changes')
    if change and 'changes' in by_id and change.get('status') != 'BASELINE':
        fields = [('new_requests', 'ta yangi ariza'), ('completed_trips', 'ta kuzatilgan reys yakunlangan'),
                  ('vehicle_changes', 'ta transport holati o‘zgargan'), ('first_seen_requests', 'ta eski ariza ilk marta ko‘ringan'),
                  ('vanished_requests', 'ta ariza joriy ro‘yxatda topilmagan'), ('vanished_trips', 'ta reys joriy ro‘yxatda topilmagan')]
        changes = [f'{change[k]} {label}' for k, label in fields if change.get(k)]
        unavailable = change.get('unavailable', [])
        if changes:
            text = f"{when(change.get('baseline_at'))} dagi hisobdan beri: " + '; '.join(changes) + '.'
        elif unavailable:
            text = 'Taqqoslash mumkin bo‘lgan manbalarda o‘zgarish aniqlanmadi; qolgan manbalardagi farq noma’lum.'
        else:
            text = f"{when(change.get('baseline_at'))} dagi hisobga nisbatan kuzatilgan o‘zgarish yo‘q."
        if unavailable and changes:
            text += ' Ayrim manbalardagi farq noma’lum.'
        edit('changes', text)
        by_id['changes']['collapsed'] = not changes
        by_id['changes']['collapsed_label'] = 'Farq qisman ma’lum · Ochish' if unavailable else 'O‘zgarish yo‘q · Ochish'
        scope('O‘zgarishlar ikki hisob orasidagi farqdir; barcha oraliq hodisalar tarixi emas. Ro‘yxatdan yo‘qolish yakunlanish hisoblanmaydi.')

    repair = sections.get('repairs', {})
    if 'repairs' in by_id:
        c = repair['summary']
        text = f"{c['active']} ta ochiq ta’mir {c['active_vehicles']} ta transportga tegishli."
        for key, label in [('blocking', 'tasida ishga chiqish cheklangan'), ('plan_overdue', 'tasida reja muddati o‘tgan'),
                           ('no_plan', 'tasida tugash rejasi yozilmagan'), ('conflicts', 'ta yozuvda vaqt yoki yakun holati zid')]:
            if c.get(key):
                text += f' {c[key]} {label}.'
        edit('repairs', text, 'Ta’mir ustasi va mexanik' if c['active'] else '',
             'Ochiq naryadlarda ish bosqichi va tugash rejasini kiriting; cheklovni faqat yakuniy ko‘rikdan so‘ng yangilang.' if c['active'] else '')
        scope('Rejasiz yoki sanalari zid ta’mirlar uchun kechikish va tayyor bo‘lish vaqti taxmin qilinmaydi.')

    # Preserve file coverage as expandable evidence beside document deadlines.
    if 'document_coverage' in by_id and 'documents' in by_id:
        b = by_id['document_coverage']
        group('documents', 'Hujjat fayllari va ularning qamrovi', [b['text'], *b['details']])
        removed.add('document_coverage')
    if 'documents' in by_id:
        c = sections.get('documents', {}).get('summary', {})
        expired = c.get('expired', 0)
        expiring = max(0, c.get('total', 0) - expired)
        parts = []
        if expired:
            parts.append(f'{expired} ta haydovchi hujjatining muddati o‘tgan')
        if expiring:
            parts.append(f'{expiring} tasi kelgusi 30 kunda tugaydi')
        text = '; '.join(parts) + '.' if parts else 'Qayd etilgan haydovchi hujjatlarida yaqin yoki o‘tgan muddat topilmadi.'
        dc = sections.get('document_coverage', {})
        if dc.get('errors'):
            text += ' Hujjat fayllari manbasining bir qismi o‘qilmadi.'
        if 'document_coverage' in removed:
            gaps=[]
            if 'drivers' in dc:
                items=dc['drivers']['items']
                license_missing=sum(not d['license_files'] for d in items)
                medical_missing=sum(not d['medical_files'] for d in items)
                if license_missing:gaps.append(f'{license_missing} haydovchida guvohnoma fayli')
                if medical_missing:gaps.append(f'{medical_missing} haydovchida tibbiy ma’lumotnoma fayli')
            if 'vehicles' in dc:
                missing=sum(not v['records'] for v in dc['vehicles']['items'])
                if missing:gaps.append(f'{missing} transportda hujjat yozuvi')
            if gaps:text+=' '+', '.join(gaps)+' qayd etilmagan.'
            if 'vehicles' in dc:
                items=dc['vehicles']['items']
                expired_vehicle=sum(v['expired'] for v in items)
                expiring_vehicle=sum(v['expiring'] for v in items)
                if expired_vehicle:text+=f' Transport hujjatlaridan {expired_vehicle} tasining muddati o‘tgan.'
                if expiring_vehicle:text+=f' Transport hujjatlaridan {expiring_vehicle} tasi kelgusi 30 kunda tugaydi.'
            text+=' Fayl qamrovi tafsilotlarda; fayl qaydi yo‘qligi hujjatning o‘zi yo‘qligini isbotlamaydi.'
        edit('documents', text, 'Hujjatlar uchun mas’ul xodim',
             'Muddati o‘tgan hujjatlarni yangilang; fayl qaydi yetishmagan yozuvlarga tegishli hujjatni biriktiring.'
             if expired or expiring or dc else '')
    elif 'document_coverage' in by_id:
        edit('document_coverage', by_id['document_coverage']['text'], 'Hujjatlar uchun mas’ul xodim',
             'Yetishmagan fayl va amal qilish sanalarini to‘ldiring; tashkilot talab qiladigan hujjatlar ro‘yxatini belgilang.')

    if 'trips' in by_id:
        trips=sections['trips'];c=trips.get('summary',{})
        text=f"Ko‘rilgan {len(trips.get('items',[]))} ta reysdan "
        parts=[]
        if c.get('PLAN_OVERDUE'):parts.append(f"{c['PLAN_OVERDUE']} tasida reja vaqti o‘tgan")
        if c.get('DATA_CONFLICT'):parts.append(f"{c['DATA_CONFLICT']} ta reysda holat yoki vaqt yozuvlari zid")
        if c.get('NO_ZONED_PLAN'):parts.append(f"{c['NO_ZONED_PLAN']} tasida reja vaqtini solishtirib bo‘lmadi")
        text+=('; '.join(parts)+'.') if parts else 'reja bo‘yicha kechikish yoki zid yozuv topilmadi.'
        if trips.get('truncated'):text+=' Ro‘yxat qisman ko‘rilgan.'
        edit('trips',text)
        # edit resets the action; only actual findings need follow-up work.
        if c.get('PLAN_OVERDUE') or c.get('DATA_CONFLICT'):
            by_id['trips']['action']='Reja vaqti o‘tgan reyslarning holatini yangilang.'
        scope('Reys nazorati mavjud reja bilan solishtirishdir; yetib kelish prognozi emas. Holati zid reyslar kechikkanlar soniga qo‘shilmaydi.')

    if 'gps' in by_id:
        gps=sections['gps'];c=gps.get('summary',{})
        total=c.get('vehicles',len(gps.get('items',[])))
        text=f'GPS kuzatuvida {value(total)} ta transport. '
        if c.get('recent') is not None:text+=f"{c['recent']} tasida signal oxirgi 5 daqiqada kelgan. "
        if c.get('stale'):text+=f"{c['stale']} tasining signali eskirgan. "
        if c.get('access_revoked'):text+=f"{c['access_revoked']} ta transportga GPS ruxsati bekor qilingan. "
        if c.get('recent') is None:text+='Yangi signallar soni noma’lum. '
        if c.get('stale'):text+='Eski signal hozirgi joylashuvni tasdiqlamaydi.'
        sources=[]
        for key,label in [('ATIL_API','ATIL GPS API'),('GPS_ARCHIVE','GPS arxivi')]:
            n=sum(i.get('source')==key for i in gps.get('items',[]))
            if n:sources.append(f'{n} ta transport: {label}.')
        if any(i.get('source')=='ATIL_API' and i.get('point') is not None for i in gps.get('items',[])):
            text+=' Nuqtalar ATIL GPS API orqali olindi.'
        group('gps','Kuzatuv manbalari',sources)
        action=by_id['gps']['action']
        edit('gps',text,action=action)

    # Per-vehicle observations remain complete; repeated cautions move into one
    # expandable scope group. Sample/partial/unknown status stays on its card.
    if 'gps_daily' in by_id and 'coverage' in by_id:
        b=by_id['gps_daily']
        caution='Hisob faqat kelgan GPS kuzatuvlarini qamraydi. Signal kelmagan vaqt ishlamaslik yoki bekor turish deb olinmaydi; to‘xtash dvigatel ishlayotganini tasdiqlamaydi.'
        if caution in b['text']:
            b['text']=b['text'].replace(caution,'').strip()
            scope(caution)
        daily=sections.get('gps_daily',{})
        if daily.get('status')=='UNAVAILABLE':
            b['text']+=' Masofa va to‘xtash vaqti noma’lum.'
    if 'garage' in by_id:
        b=by_id['garage']
        phrase='; buni transportlar kelmagan yoki ishlamagan deb talqin qilib bo‘lmaydi.'
        if phrase in b['text']:
            b['text']=b['text'].replace(phrase,'.')
            scope('GPS tarixi olinmagani transport kelmagani yoki ishlamagani isboti emas.')

    for key, owner, action in [
        ('trips', 'Dispetcher', 'Reja muddati o‘tgan reyslar bo‘yicha haydovchidan haqiqiy holatni oling; yakunlangan reyslarning status va vaqtlarini yangilang.'),
        ('gps', 'GPS mutaxassisi', 'Signali eskirgan yoki ruxsati bekor qilingan transportlarning qurilma va GPS ulanishini tiklang.'),
        ('gps_daily', 'GPS mutaxassisi', 'Hisobi olinmagan transportlar uchun GPS tarixi va uzilgan kuzatuv oraliqlarini tiklang.'),
        ('garage', 'Garaj mas’uli va GPS mutaxassisi', 'Haqiqiy garaj koordinatasi va radiusini tasdiqlang; GPS tarixi ulanishini tiklang.'),
        ('requests', 'Ariza muallifi va dispetcher', 'Ustuvor arizalardagi talablarni to‘ldiring, keyin transport tanlovini bajaring.'),
        ('fleet', 'Mexanik', 'Bugungi texnik ko‘rik natijalarini kiriting va transport cheklovlarini yangilang.'),
    ]:
        if key in by_id and by_id[key]['action']:
            by_id[key].update(owner=owner, action=action)
    if 'garage' in by_id:
        yard = sections.get('garage', {})
        if yard.get('status') == 'NOT_CONFIGURED':
            by_id['garage'].update(owner='Garaj mas’uli', action='Garaj nomi, haqiqiy koordinatasi va radiusini sozlamalarga kiriting.')
        elif not (yard.get('garage') or {}).get('is_example'):
            by_id['garage']['action'] = ('GPS mutaxassisi tarix ulanishini tiklasin; garaj mas’uli kuzatilgan uzoq to‘xtashlarni topshiriqlar bilan solishtirsin.'
                                         if by_id['garage']['action'] else '')

    if scopes:
        if 'coverage' not in by_id:
            from .narrative import block
            b = block('coverage', 'Hisob shartlari va qamrovi tafsilotlarda.', severity='normal')
            blocks.append(b)
            by_id['coverage'] = b
        group('coverage', 'Hisoblash shartlari va cheklovlar', scopes)
    if 'coverage' in by_id:
        by_id['coverage'].update(owner='Ma’lumot manbasi uchun mas’ul xodim',
                                 action='O‘qilmagan manbalarni tiklang; kesilgan ro‘yxat uchun qamrovni kengaytiring.'
                                 if report.get('errors') else '')
    return [b for b in blocks if b['id'] not in removed]
