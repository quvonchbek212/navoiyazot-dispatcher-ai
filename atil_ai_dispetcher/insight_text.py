"""Plain Uzbek explanations of the additional calculated evidence."""
from .insights import FLEET_GROUPS

def blocks(sections):
    from .narrative import block,when,value,reason
    s=sections;out=[]
    r=s.get('changes')
    if r:
        if r['status']=='BASELINE':
            text='Taqqoslash uchun oldingi mos hisob hali yo‘q. Ushbu hisob boshlang‘ich holat sifatida saqlanadi; keyingi hisobdan o‘zgarishlar ko‘rinadi.'
        else:
            text=f"{when(r['baseline_at'])} dagi oldingi hisob bilan solishtirildi. "
            if r['new_requests'] is not None:text+=f"Oraliqda yaratilgan {r['new_requests']} ta yangi ariza aniqlandi. "
            if r['first_seen_requests']:text+=f"Yana {r['first_seen_requests']} ta ariza birinchi marta ko‘rindi, lekin yaratilish vaqti shu oraliqqa mos emas; ular yangi deb sanalmadi. "
            if r['completed_trips'] is not None:text+=f"{r['completed_trips']} ta oldindan kuzatilgan reys holati yakunlangan holatga o‘tdi. "
            if r['vehicle_changes'] is not None:text+=f"{r['vehicle_changes']} ta transportning hisoblangan holat guruhi o‘zgardi. "
            removed=(r.get('vanished_requests') or 0)+(r.get('vanished_trips') or 0)
            if removed:text+=f'{removed} ta avvalgi yozuv hozirgi to‘liq ro‘yxatda topilmadi; yo‘qolish yakunlanish deb olinmadi. '
            text+='Bu ikki hisob orasidagi farq; ularning orasida bo‘lgan barcha hodisalar tarixi emas.'
            if r['unavailable']:text+=' Ayrim manbalar uchun mos yoki to‘liq oldingi hisob yo‘q; ularning farqi noma’lum.'
        out.append(block('changes',text,severity='caution' if r['unavailable'] else 'normal'))
    r=s.get('fleet_state')
    if r:
        c=r['counts'];text=f"Tekshirilgan {r['returned']} ta transport quyidagi guruhlarga ajratildi: "
        text+='; '.join(f'{c[k]} tasi {label}' for k,label in FLEET_GROUPS.items())+'. '
        text+='Har bir transport faqat bir marta sanaldi. Zid yozuvlilar band yoki ta’mir guruhiga qayta qo‘shilmadi. Reysda deb qayd etilgani GPSda hozir harakatlanayotganini anglatmaydi. Asosiy tekshiruvdan o‘tish aynan tanlangan arizaga moslikni kafolatlamaydi.'
        details=[f"{v.get('plate_number') or 'Transport'}: {FLEET_GROUPS[v['group']]}. "+'; '.join(v.get('conflict_reasons',[])) for v in r['items'] if v['group'] in ('conflict','maintenance','restricted')][:3]
        out.append(block('fleet_state',text,'Avval zid bandlik va ta’mir yozuvlarini aniqlashtiring.' if c['conflict'] else 'Tayyorligi tasdiqlanmagan transportlarning ko‘rik va holat yozuvlarini tekshiring.' if c['unconfirmed'] else '',
                         'attention' if c['conflict'] or c['unconfirmed'] else 'normal',details))
    r=s.get('waiting_diagnostics')
    if r and r['returned']:
        c=r['summary'];text=f"Navbatdagi jami {r['total']} ta arizadan {r['returned']} tasi tekshirildi. "
        text+=f"{c['with_obstacles']} tasida hozir tekshiriladigan to‘siqlar bor. {c['missing_amount']} tasida yuk yoki yo‘lovchi miqdori ko‘rsatilmagan. "
        if r['fleet_available']:text+=f"{c['no_vehicle_pass']} ta ariza uchun tekshirilgan parkdan barcha asosiy talablardan o‘tgan transport topilmadi. "
        else:text+='Transport ma’lumoti olinmagan; transport yetishmasligi haqida xulosa yo‘q. '
        if r['drivers_available']:text+=f"Tekshirilgan haydovchilardan {value(c['driver_passes'])} nafari asosiy talablardan o‘tgan. "
        else:text+='Haydovchi tayyorligi ma’lumoti olinmagan. '
        text+='Bular hozirgi to‘siqlar; ariza aynan shu sabab kutgani tasdiqlanmagan. '
        if c['unknown_age']:text+=f"{c['unknown_age']} ta ariza uchun vaqtni ishonchli hisoblab bo‘lmadi. "
        if r['candidate_scope_limited']:text+='Nomzodlar ro‘yxati qisqartirilgan; tekshiruv butun parkni qamramaydi.'
        details=[]
        for item in r['items'][:3]:
            age=f"{item['age_basis']} beri {value(item['age_hours'])} soat o‘tgan" if item['age_hours'] is not None else 'kutish davomiyligi noma’lum'
            example=f"{item.get('request_number') or 'Ariza'}: {age}. "+(' '.join(item['obstacles']) or 'Ushbu tekshiruvlarda aniq to‘siq topilmadi; toifa va reys shartlari hali alohida tekshiriladi.')
            frequencies=sorted(item['vehicle_obstacles'].items(),key=lambda x:(-x[1],x[0]))[:2]
            if frequencies:example+=' Transportlarda: '+'; '.join(f'{reason(why).lower()} — {n} ta' for why,n in frequencies)+'.'
            details.append(example)
        out.append(block('waiting_diagnostics',text,'Arizadagi miqdorlarni to‘ldiring, ustuvor arizadan boshlab nomzodlarning aniq to‘siqlarini tekshiring.',
                         'attention' if c['with_obstacles'] else 'normal',details))
    r=s.get('repairs')
    if r and r.get('total'):
        c=r['summary'];text=f"Ko‘rib chiqilgan {r['returned']} ta ta’mir yozuvidan {c['active']} tasi ochiq; ular {c['active_vehicles']} ta transportga tegishli. "
        text+=f"Ochiq ta’mirlarning {c['blocking']} tasida transportni ishga chiqarish cheklangan. "
        text+=f"{c['plan_overdue']} ta ochiq ta’mirda yozilgan reja tugash vaqti o‘tgan. "
        if c['no_plan']:text+=f"{c['no_plan']} ta ochiq ta’mirda tugash rejasi yo‘q; ular uchun kechikish yoki tayyor bo‘lish sanasi taxmin qilinmadi. "
        if c['conflicts']:text+=f"{c['conflicts']} ta yozuvda vaqt yoki yakun holati zid; davomiylik xulosasi chiqarilmadi."
        details=[]
        active=sorted((i for i in r['items'] if i['active']),key=lambda i:-(i['age_hours'] or 0))
        for item in active[:3]:
            age=f"ochilganidan beri {value(item['age_hours'])} soat o‘tgan" if item['age_hours'] is not None else 'vaqt yozuvini tekshirish kerak'
            example=f"{item.get('plate_number') or 'Transport'} · {item.get('repair_number') or 'ta’mir'}: {item['stage_label']}, {age}. "
            example+=f"{item.get('work_total',0)} ta ish bandining {item.get('work_done',0)} tasi bajarilgan deb qayd etilgan."
            if item.get('work_examples'):example+=' Qayd etilgan ishlar: '+'; '.join(item['work_examples'])+'.'
            if item['plan_overdue']:example+=f" Reja vaqtidan {value(item['overdue_hours'])} soat o‘tgan."
            details.append(example)
        out.append(block('repairs',text,'Ochiq ta’mirlarning bajarilayotgan ishlari va rejalashtirilgan tugash vaqtini mas’ul xodim bilan aniqlashtiring.' if c['active'] else '',
                         'attention' if c['plan_overdue'] or c['conflicts'] else 'caution' if c['no_plan'] else 'normal',details))
    r=s.get('document_coverage')
    if r and (r.get('records') or r.get('errors')):
        text='';details=[]
        if 'drivers' in r:
            rows=r['drivers']['items'];n=len(rows);license=sum(i['license_files']>0 for i in rows);medical=sum(i['medical_files']>0 for i in rows)
            text+=f'Tekshirilgan {n} nafar haydovchining {license} nafariga guvohnoma, {medical} nafariga tibbiy ma’lumotnoma fayli biriktirilgani bazada qayd etilgan. '
            text+=f'{n-license} nafarida guvohnoma fayli, {n-medical} nafarida tibbiy ma’lumotnoma fayli qaydi tasdiqlanmadi. Bir haydovchiga bir nechta fayl biriktirilgani odam sonini ko‘paytirmaydi. '
            for i in rows:
                missing=[]
                if not i['license_files']:missing.append('guvohnoma fayli')
                if not i['medical_files']:missing.append('tibbiy ma’lumotnoma fayli')
                if missing:details.append(f"{i['owner_label']}: {', '.join(missing)} qaydi tasdiqlanmadi.")
        if 'vehicles' in r:
            rows=r['vehicles']['items'];with_docs=sum(i['records']>0 for i in rows);without_files=sum(i['records']-i['attachments'] for i in rows)
            text+=f"Tekshirilgan {len(rows)} ta transportning {with_docs} tasida hujjat yozuvi bor, {len(rows)-with_docs} tasida yo‘q. "
            text+=f"Transport hujjatlarida {sum(i['expired'] for i in rows)} ta muddat o‘tgan, {sum(i['expiring'] for i in rows)} tasi kelgusi 30 kun ichida tugaydi, {sum(i['unknown_expiry'] for i in rows)} tasida tugash sanasi yo‘q. "
            if without_files:text+=f'{without_files} ta hujjat yozuviga fayl biriktirilmagan. '
            if any(i['conflicting_dates'] for i in rows):text+='Ayrim transport hujjatlari sanalari zid; ularni tekshirish kerak. '
        if r.get('errors'):text+='Hujjat manbalarining bir qismi o‘qilmadi; uning holati noma’lum. '
        text+='Majburiy hujjatlar ro‘yxati berilmagan: yo‘q fayl qoidabuzarlik yoki haydovchida hujjatning o‘zi yo‘q degani emas. Fayllarning ochilishi va hujjat haqiqiyligi tekshirilmagan.'
        out.append(block('document_coverage',text,'Fayl qaydi yetishmagan yozuvlarni tekshiring va tashkilotning talab qilinadigan hujjatlar ro‘yxatini aniqlashtiring.','caution',details[:3]))
    return out
