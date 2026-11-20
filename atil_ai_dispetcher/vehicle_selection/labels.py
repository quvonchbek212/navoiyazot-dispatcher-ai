"""Bazadagi enum qiymatlarining nomlari — uch tilda (uz, ru, en).

NIMA UCHUN KERAK (01.09.2026): javob matni o'zbekcha, lekin uning ichiga
bazaning XOM qiymatlari qo'yilardi — "mehnat holati: ACTIVE", "Smena bor:
DAY (CONFIRMED)", "oxirgi ko'rik: FIT", "holat: IN_MAINTENANCE". Bu
matnlar `criteria[].detail` ga tushadi, u yerdan LLM tahliliga va
dispetcherning ekraniga boradi. Natijada o'zbekcha jumla ichida inglizcha
so'zlar chiqib turardi.

UCH TIL (05.09.2026): so'rovdagi `?lang=` javobning hamma matnini
belgilaydi, shu jumladan enum nomlarini.

QIYMATLAR O'YLAB TOPILMAGAN. Kalitlar ro'yxati `atil_chatbot/ddl.sql`
dagi CHECK cheklovidan ko'chirilgan (u bazadan avtomatik hosil qilinadi),
ya'ni bu yerda bazada BO'LISHI MUMKIN bo'lgan hamma qiymat bor — bugun
ishlatilayotgani ham, ishlatilmayotgani ham. `tests/test_vs_labels.py`
ikkalasini solishtirib turadi: sxemaga yangi qiymat qo'shilsa test yiqiladi.

BIR XIL SO'Z HAR JOYDA BIR XIL MA'NO ANGLATMAYDI, shuning uchun xarita
MAYDON BO'YICHA bo'lingan: `ACTIVE` mashina uchun "faol", xodim uchun
"ishda", xizmat rejasi uchun "amalda". Aynan shu sabab bu yerdagi
lug'atni chatbotning YASSI lug'ati (`core.lang.status_dictionary`) bilan
almashtirib bo'lmaydi — u maydonni ajratmaydi.
"""

from __future__ import annotations

#: Har bir qiymat: kod -> {til: nom}.
#: `driver_shift.shift_type`
SHIFT_TYPE = {
    "DAY": {"uz": "kunduzgi smena", "ru": "дневная смена", "en": "day shift"},
    "NIGHT": {"uz": "tungi smena", "ru": "ночная смена", "en": "night shift"},
    "SPLIT": {"uz": "bo'lingan smena", "ru": "разделённая смена", "en": "split shift"},
    "STANDBY": {"uz": "navbatchilik", "ru": "дежурство", "en": "standby"},
    "DAY_OFF": {"uz": "dam olish kuni", "ru": "выходной", "en": "day off"},
    "VACATION": {"uz": "ta'til", "ru": "отпуск", "en": "vacation"},
    "SICK_LEAVE": {"uz": "kasallik varaqasi", "ru": "больничный", "en": "sick leave"},
}

#: `driver_shift.status`
SHIFT_STATUS = {
    "PLANNED": {"uz": "rejalashtirilgan", "ru": "запланирована", "en": "planned"},
    "CONFIRMED": {"uz": "tasdiqlangan", "ru": "подтверждена", "en": "confirmed"},
    "COMPLETED": {"uz": "yakunlangan", "ru": "завершена", "en": "completed"},
    "CANCELLED": {"uz": "bekor qilingan", "ru": "отменена", "en": "cancelled"},
}

#: `transport_vehicle.current_status`
VEHICLE_STATUS = {
    "ACTIVE": {"uz": "faol", "ru": "активна", "en": "in service"},
    "RESERVED": {"uz": "band qilingan", "ru": "зарезервирована", "en": "reserved"},
    "IN_OPERATION": {"uz": "reysda", "ru": "в рейсе", "en": "on a trip"},
    "IN_MAINTENANCE": {
        "uz": "texnik xizmatda", "ru": "на техобслуживании", "en": "under maintenance"},
    "BLOCKED": {"uz": "to'silgan", "ru": "заблокирована", "en": "blocked"},
    "DECOMMISSIONED": {
        "uz": "hisobdan chiqarilgan", "ru": "списана", "en": "decommissioned"},
}

#: `driver.employment_status`
EMPLOYMENT_STATUS = {
    "ACTIVE": {"uz": "ishda", "ru": "работает", "en": "employed"},
    "ON_LEAVE": {"uz": "ta'tilda", "ru": "в отпуске", "en": "on leave"},
    "SUSPENDED": {
        "uz": "vaqtincha chetlatilgan", "ru": "временно отстранён", "en": "suspended"},
    "TERMINATED": {"uz": "ishdan bo'shatilgan", "ru": "уволен", "en": "terminated"},
}

#: `driver.driver_availability_status`
AVAILABILITY_STATUS = {
    "AVAILABLE": {"uz": "bo'sh", "ru": "свободен", "en": "available"},
    "RESERVED_FOR_TRIP": {
        "uz": "reysga band qilingan", "ru": "зарезервирован под рейс",
        "en": "reserved for a trip"},
    "ON_TRIP": {"uz": "reysda", "ru": "в рейсе", "en": "on a trip"},
    "REST_REQUIRED": {
        "uz": "dam olishi kerak", "ru": "требуется отдых", "en": "rest required"},
    "SICK_LEAVE": {
        "uz": "kasallik varaqasida", "ru": "на больничном", "en": "on sick leave"},
    "BLOCKED": {"uz": "to'silgan", "ru": "заблокирован", "en": "blocked"},
    "UNAVAILABLE": {"uz": "mavjud emas", "ru": "недоступен", "en": "unavailable"},
}

#: `medical_inspection.status`
MEDICAL_STATUS = {
    "FIT": {"uz": "yaroqli", "ru": "годен", "en": "fit"},
    "RESTRICTED": {
        "uz": "cheklov bilan yaroqli", "ru": "годен с ограничениями",
        "en": "fit with restrictions"},
    "UNFIT": {"uz": "yaroqsiz", "ru": "не годен", "en": "unfit"},
    "CANCELLED": {"uz": "bekor qilingan", "ru": "отменён", "en": "cancelled"},
}

#: `vehicle_technical_inspection.status`
INSPECTION_STATUS = {
    "FIT": {"uz": "yaroqli", "ru": "годен", "en": "fit"},
    "LIMITED": {"uz": "cheklangan", "ru": "ограниченно годен", "en": "limited"},
    "BLOCKED": {"uz": "to'silgan", "ru": "заблокировано", "en": "blocked"},
}

#: `maintenance_plan.status`
MAINTENANCE_STATUS = {
    "DUE": {"uz": "xizmat muddati kelgan", "ru": "наступил срок обслуживания", "en": "service due"},
    "UNKNOWN": {"uz": "noma’lum", "ru": "неизвестно", "en": "unknown"},
    "PLANNED": {"uz": "rejalashtirilgan", "ru": "запланировано", "en": "planned"},
    "ACTIVE": {"uz": "amalda", "ru": "действует", "en": "active"},
    "DUE_SOON": {"uz": "muddati yaqin", "ru": "срок подходит", "en": "due soon"},
    "OVERDUE": {"uz": "muddati o'tgan", "ru": "просрочено", "en": "overdue"},
    "PAUSED": {"uz": "to'xtatilgan", "ru": "приостановлено", "en": "paused"},
    "COMPLETED": {"uz": "yakunlangan", "ru": "завершено", "en": "completed"},
}

#: `transport_vehicle.transport_type` — LLM promptidagi `talab.transport_turi`
#: aynan shu qiymatni oladi, ya'ni tarjimasiz javobga "DUMP_TRUCK" chiqardi.
TRANSPORT_TYPE = {
    "ELECTRIC_VEHICLE": {"uz": "elektromobil", "ru": "электромобиль", "en": "electric vehicle"},
    "MOBILE_CRANE": {"uz": "avtokran", "ru": "автокран", "en": "mobile crane"},
    "AERIAL_PLATFORM": {
        "uz": "havo platformasi", "ru": "автовышка", "en": "aerial platform"},
    "TRACTOR": {"uz": "traktor", "ru": "трактор", "en": "tractor"},
    "WATER_TRUCK": {"uz": "suv tashuvchi", "ru": "водовоз", "en": "water truck"},
    "EXCAVATOR": {"uz": "ekskavator", "ru": "экскаватор", "en": "excavator"},
    "FRONT_LOADER": {
        "uz": "g'ildirakli yuklagich", "ru": "фронтальный погрузчик",
        "en": "front loader"},
    "DUMP_TRUCK": {"uz": "samosval", "ru": "самосвал", "en": "dump truck"},
    "LONG_LOAD_TRUCK": {
        "uz": "uzun yuk tashuvchi", "ru": "длинномер", "en": "long-load truck"},
    "FLATBED": {"uz": "platforma", "ru": "бортовой", "en": "flatbed"},
    "MANIPULATOR": {"uz": "manipulyator", "ru": "манипулятор", "en": "manipulator"},
    "PASSENGER_CAR": {
        "uz": "yengil avtomobil", "ru": "легковой автомобиль", "en": "passenger car"},
    "BUS": {"uz": "avtobus", "ru": "автобус", "en": "bus"},
    "VAN": {"uz": "furgon", "ru": "фургон", "en": "van"},
    "BULLDOZER": {"uz": "buldozer", "ru": "бульдозер", "en": "bulldozer"},
    "CONCRETE_PUMP": {
        "uz": "beton nasosi", "ru": "бетононасос", "en": "concrete pump"},
    "CONCRETE_MIXER": {
        "uz": "beton aralashtirgich", "ru": "бетоносмеситель", "en": "concrete mixer"},
    "FIRE_TRUCK": {
        "uz": "o't o'chirish mashinasi", "ru": "пожарная машина", "en": "fire truck"},
    "AMBULANCE": {"uz": "tez yordam", "ru": "скорая помощь", "en": "ambulance"},
    "TRUCK": {"uz": "yuk mashinasi", "ru": "грузовик", "en": "truck"},
    "TANKER": {"uz": "sisterna", "ru": "цистерна", "en": "tanker"},
    "REFRIGERATED": {"uz": "refrijerator", "ru": "рефрижератор", "en": "refrigerated"},
    "SPECIALIZED": {"uz": "maxsus texnika", "ru": "спецтехника", "en": "specialized"},
    "MINIBUS": {"uz": "mikroavtobus", "ru": "микроавтобус", "en": "minibus"},
    "PICKUP": {"uz": "pikap", "ru": "пикап", "en": "pickup"},
    "TRAILER": {"uz": "tirkama", "ru": "прицеп", "en": "trailer"},
    "OTHER": {"uz": "boshqa", "ru": "прочее", "en": "other"},
}


#: Maydon nomi -> xarita. `tests/test_vs_labels.py` shu ro'yxat bo'yicha
#: `ddl.sql` bilan solishtiradi.
GROUPS: dict[str, tuple[str, str, dict[str, dict[str, str]]]] = {
    # nom              (jadval,                        ustun,             xarita)
    "shift_type":      ("driver_shift", "shift_type", SHIFT_TYPE),
    "shift_status":    ("driver_shift", "status", SHIFT_STATUS),
    "vehicle_status":  ("transport_vehicle", "current_status", VEHICLE_STATUS),
    "employment":      ("driver", "employment_status", EMPLOYMENT_STATUS),
    "availability":    ("driver", "driver_availability_status", AVAILABILITY_STATUS),
    "medical":         ("medical_inspection", "status", MEDICAL_STATUS),
    "inspection":      ("vehicle_technical_inspection", "status", INSPECTION_STATUS),
    "maintenance":     ("maintenance_plan", "status", MAINTENANCE_STATUS),
    "transport_type":  ("transport_vehicle", "transport_type", TRANSPORT_TYPE),
}


def label(group: str, value: str | None, lang: str = "uz") -> str:
    """Enum qiymatini tanlangan tilga o'giradi.

    Noma'lum qiymat QAYTARILADI, tarjima O'YLAB TOPILMAYDI: sxemaga yangi
    qiymat qo'shilgan bo'lsa uni yashirgandan ko'ra xom ko'rsatgan
    ma'qulroq. Bunday holatni `tests/test_vs_labels.py` ushlaydi.
    """
    if value is None:
        return _UNKNOWN.get(lang, _UNKNOWN["uz"])
    row = GROUPS[group][2].get(value)
    if not row:
        return value
    return row.get(lang) or row["uz"]


def code_of(group: str, value: str | None) -> str | None:
    """Nomni KODGA qaytaradi — filtr uchun.

    NIMA UCHUN KERAK. Javobda endi nom chiqadi ("yengil avtomobil"), va
    foydalanuvchi o'sha nomni filtrga qaytarib yozadi. Ilgari bu
    ishlamasdi: filtr faqat `PASSENGER_CAR` ni tanirdi va so'rov jimgina
    bo'sh natija qaytarardi. Endi ikkalasi ham qabul qilinadi.

    Qidiruv UCHALA TILDA va katta-kichik harfga qaramasdan. Kod bo'lsa
    o'zi qaytadi; hech qayerda topilmasa BERILGAN QIYMAT qaytadi — uni
    jimgina tashlab yuborish "filtr ishlamadi" degan sirli holatni
    yaratardi.
    """
    if not value:
        return value
    xarita = GROUPS[group][2]
    berilgan = value.strip()
    if berilgan in xarita:
        return berilgan
    # Kod katta harfda yozilgan bo'lishi mumkin: `passenger_car`.
    if berilgan.upper() in xarita:
        return berilgan.upper()
    pastki = _qidiruv_shakli(berilgan)
    for kod, qatorlar in xarita.items():
        if any(_qidiruv_shakli(nom) == pastki for nom in qatorlar.values()):
            return kod
    return berilgan


#: O'zbek lotin yozuvidagi apostrofning har xil belgilari. Rasmiy imloda
#: `ʻ` (U+02BB), telefon klaviaturasida ko'pincha `‘`/`’` chiqadi; lug'atda
#: esa oddiy `'` yozilgan. 15.09.2026: `gʻildirakli yuklagich` topilmas edi.
_APOSTROFLAR = str.maketrans({ch: "'" for ch in "ʻʼ‘’`´"})


def _qidiruv_shakli(matn: str) -> str:
    """Solishtirish uchun: apostrof bir xil, katta-kichik harf va ortiqcha bo'shliq yo'q."""
    return " ".join(matn.translate(_APOSTROFLAR).casefold().split())


#: `label(..., None)` uchun.
_UNKNOWN = {"uz": "noma'lum", "ru": "неизвестно", "en": "unknown"}
