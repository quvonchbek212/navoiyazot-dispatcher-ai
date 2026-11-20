"""Javobdagi hamma matn — uch tilda (uz, ru, en).

NIMA UCHUN BU FAYL BOR. Javobning yarmi matn: mezon izohi (`detail`),
kesish sabablari, `data_quality.notes`, juftlik izohi. Ular `rules.py`,
`ranker.py` va `explain.py` ning o'nlab joyida f-string bo'lib yozilgan
edi va faqat o'zbekcha chiqardi. So'rovda `?lang=` berilganda javob
TO'LIQ o'sha tilda bo'lishi kerak — yarmi ruscha, yarmi o'zbekcha javob
eng yomon variant.

Marshrut optimizatsiyasidagi `texts.py` bilan bir xil tuzilma: kalit ->
uchta til. Ikki modul alohida, chunki xabarlar ham alohida; umumiy
bo'lgani — `labels.py` (enum nomlari) va chatbotning til ko'rsatmasi.

KODLAR TARJIMA QILINMAYDI. `blockers[].code`, mezon nomi (`capacity`,
`distance`, ...), jadval va ustun nomlari uch tilda ham bir xil qoladi:
ularni dastur o'qiydi.

SANA VA RAQAM SHU YERDA FORMATLANMAYDI — ular chaqiruvchi tomonda
tayyorlanadi va kalitga parametr bo'lib kiradi.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# `core.lang` atil_chatbot ichida yassi nom bilan import qiladi.
_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from core.lang import answer_instruction  # noqa: E402

#: Qo'llab-quvvatlanadigan tillar. Chatbot va marshrut moduli bilan bir xil.
LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "uz"


def normalize(lang: str | None) -> str:
    """Noma'lum yoki bo'sh til sukut tilga tushadi."""
    value = (lang or "").strip().lower()
    return value if value in LANGS else DEFAULT_LANG


def llm_instruction(lang: str) -> str:
    """LLM promptiga qo'shiladigan til ko'rsatmasi — chatbotnikidan."""
    return answer_instruction(normalize(lang))


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Kalitni tanlangan tilda qaytaradi.

    Kalit topilmasa KALITNING O'ZI qaytadi — javob bo'sh qolmaydi va
    yetishmayotgan matn darrov ko'zga tashlanadi.
    """
    row = MESSAGES.get(key)
    if row is None:
        return key
    text = row.get(normalize(lang)) or row[DEFAULT_LANG]
    return text.format(**kwargs) if kwargs else text


MESSAGES: dict[str, dict[str, str]] = {

    # ------------------------------------------------------ Mezon nomlari
    "criterion.capacity": {"uz": "Sig'im", "ru": "Вместимость", "en": "Capacity"},
    "criterion.distance": {"uz": "Masofa", "ru": "Расстояние", "en": "Distance"},
    "criterion.documents": {"uz": "Hujjat", "ru": "Документы", "en": "Documents"},
    "criterion.shift": {"uz": "Smena", "ru": "Смена", "en": "Shift"},
    "criterion.skill": {"uz": "Malaka", "ru": "Квалификация", "en": "Skill"},
    "criterion.technical": {
        "uz": "Texnik holat", "ru": "Техническое состояние", "en": "Technical condition"},

    # --------------------------------------------------- Kesish sabablari
    "blocker.LICENSE_EXPIRED": {
        "uz": "Haydovchilik guvohnomasi muddati o'tgan",
        "ru": "Срок водительского удостоверения истёк",
        "en": "The driving licence has expired",
    },
    "blocker.LICENSE_CATEGORY_MISMATCH": {
        "uz": "Guvohnoma toifasi talabga mos emas",
        "ru": "Категория удостоверения не соответствует требованию",
        "en": "The licence category does not match the requirement",
    },
    "blocker.NOT_EMPLOYED": {
        "uz": "Haydovchi ishda emas",
        "ru": "Водитель не работает",
        "en": "The driver is not employed",
    },
    "blocker.MEDICAL_UNFIT": {
        "uz": "Tibbiy ko'rikdan yaroqsiz deb o'tgan",
        "ru": "Медосмотр пройден с результатом «не годен»",
        "en": "Failed the medical inspection as unfit",
    },
    "blocker.MEDICAL_MISSING": {
        "uz": "Kunga tibbiy ko'rik yozuvi yo'q",
        "ru": "На эту дату нет записи о медосмотре",
        "en": "No medical inspection record for that day",
    },
    "blocker.MEDICAL_CERT_EXPIRED": {
        "uz": "Tibbiy ma'lumotnoma muddati o'tgan",
        "ru": "Срок медицинской справки истёк",
        "en": "The medical certificate has expired",
    },
    "blocker.SHIFT_OFF": {
        "uz": "Smena jadvalida dam olish/ta'til/kasallik",
        "ru": "В графике смен выходной/отпуск/больничный",
        "en": "The shift schedule shows a day off, leave or sick leave",
    },
    "blocker.DRIVER_BUSY_TRIP": {
        "uz": "Haydovchi aktiv reysda",
        "ru": "Водитель в активном рейсе",
        "en": "The driver is on an active trip",
    },
    "blocker.DRIVER_BUSY_WAYBILL": {
        "uz": "Haydovchida ochiq yo'l varaqasi bor",
        "ru": "У водителя открыт путевой лист",
        "en": "The driver has an open waybill",
    },
    "blocker.VEHICLE_STATUS_BLOCKED": {
        "uz": "Mashina holati yo'lga chiqishga ruxsat bermaydi",
        "ru": "Состояние машины не позволяет выезд",
        "en": "The vehicle status does not allow it to go out",
    },
    "blocker.BLOCKING_REPAIR": {
        "uz": "Chiqishni to'suvchi remont ochiq",
        "ru": "Открыт ремонт, блокирующий выезд",
        "en": "A repair that blocks release is open",
    },
    "blocker.INSPECTION_BLOCKED": {
        "uz": "Texnik ko'rik natijasi: to'silgan",
        "ru": "Результат техосмотра: заблокировано",
        "en": "Technical inspection result: blocked",
    },
    "blocker.TYPE_MISMATCH": {
        "uz": "Transport turi talabga mos emas",
        "ru": "Тип транспорта не соответствует требованию",
        "en": "The transport type does not match the requirement",
    },
    "blocker.DOCUMENT_EXPIRED": {
        "uz": "Mashina hujjati muddati o'tgan",
        "ru": "Срок документа машины истёк",
        "en": "A vehicle document has expired",
    },
    "blocker.INSURANCE_EXPIRED": {
        "uz": "Sug'urta muddati o'tgan",
        "ru": "Срок страховки истёк",
        "en": "The insurance has expired",
    },
    "blocker.CAPACITY_INSUFFICIENT": {
        "uz": "Sig'imi yetmaydi",
        "ru": "Не хватает вместимости",
        "en": "Not enough capacity",
    },
    "blocker.MAINTENANCE_OVERDUE": {
        "uz": "Texnik xizmat muddati o'tgan (chiqish to'silgan)",
        "ru": "Срок технического обслуживания просрочен (выезд заблокирован)",
        "en": "Maintenance is overdue (release blocked)",
    },
    "blocker.VEHICLE_BUSY_TRIP": {
        "uz": "Mashina aktiv reysda",
        "ru": "Машина в активном рейсе",
        "en": "The vehicle is on an active trip",
    },
    "blocker.VEHICLE_BUSY_WAYBILL": {
        "uz": "Mashinada ochiq yo'l varaqasi bor",
        "ru": "У машины открыт путевой лист",
        "en": "The vehicle has an open waybill",
    },

    # ------------------------------------------------------------ Sig'im
    "cap.dim.weight": {"uz": "og'irlik", "ru": "вес", "en": "weight"},
    "cap.dim.volume": {"uz": "hajm", "ru": "объём", "en": "volume"},
    "cap.dim.seats": {"uz": "o'rindiq", "ru": "мест", "en": "seats"},
    "cap.insufficient": {
        "uz": "{dim}: kerak {need} {unit}, sig'im {have} {unit} — yetmaydi",
        "ru": "{dim}: нужно {need} {unit}, вместимость {have} {unit} — не хватает",
        "en": "{dim}: {need} {unit} needed, capacity {have} {unit} — not enough",
    },
    "cap.ratio": {
        "uz": "{dim}: {need}/{have} {unit} = {percent}",
        "ru": "{dim}: {need}/{have} {unit} = {percent}",
        "en": "{dim}: {need}/{have} {unit} = {percent}",
    },
    "cap.reason_vehicle": {
        "uz": "mashinada {dims} sig'imi ko'rsatilmagan",
        "ru": "у машины не указана вместимость: {dims}",
        "en": "the vehicle has no capacity for: {dims}",
    },
    "cap.reason_demand": {
        "uz": "talabda yuk og'irligi/hajmi/yo'lovchi soni berilmagan",
        "ru": "в запросе не указан вес/объём груза или число пассажиров",
        "en": "the request gives no cargo weight/volume or passenger count",
    },

    # ----------------------------------------------------------- Masofa
    "dist.no_vehicle_position": {
        "uz": "mashinaning oxirgi joylashuvi yo'q (`vehicle_telemetry_state`)",
        "ru": "нет последнего местоположения машины (`vehicle_telemetry_state`)",
        "en": "the vehicle has no last position (`vehicle_telemetry_state`)",
    },
    "dist.no_pickup": {
        "uz": "yuklash nuqtasi koordinatasi berilmagan",
        "ru": "не заданы координаты пункта погрузки",
        "en": "no coordinates were given for the pickup point",
    },
    "dist.stamp": {
        "uz": ", oxirgi signal {at}",
        "ru": ", последний сигнал {at}",
        "en": ", last signal {at}",
    },
    "dist.value": {
        "uz": "Yuklash nuqtasigacha {km} km (to'g'ri chiziq{stamp})",
        "ru": "До пункта погрузки {km} км (по прямой{stamp})",
        "en": "{km} km to the pickup point (straight line{stamp})",
    },

    # ---------------------------------------------------------- Hujjatlar
    "doc.vehicle_expired": {
        "uz": "mashinaning {count} ta hujjati muddati o'tgan",
        "ru": "у машины просрочено документов: {count}",
        "en": "{count} vehicle document(s) have expired",
    },
    "doc.vehicle_until": {
        "uz": "mashina hujjati {date} gacha",
        "ru": "документ машины действует до {date}",
        "en": "the vehicle document is valid until {date}",
    },
    "doc.vehicle_none": {
        "uz": "mashinada hujjat yozuvi yo'q (`vehicle_document` bo'sh)",
        "ru": "у машины нет записей о документах (`vehicle_document` пуст)",
        "en": "the vehicle has no document records (`vehicle_document` is empty)",
    },
    "doc.insurance_expired": {
        "uz": "sug'urta {date} da tugagan",
        "ru": "страховка закончилась {date}",
        "en": "the insurance expired on {date}",
    },
    "doc.insurance_until": {
        "uz": "sug'urta {date} gacha",
        "ru": "страховка действует до {date}",
        "en": "the insurance is valid until {date}",
    },
    "doc.license_expired": {
        "uz": "guvohnoma {date} da tugagan",
        "ru": "удостоверение закончилось {date}",
        "en": "the licence expired on {date}",
    },
    "doc.license_until": {
        "uz": "guvohnoma {date} gacha",
        "ru": "удостоверение действует до {date}",
        "en": "the licence is valid until {date}",
    },
    "doc.medical_expired": {
        "uz": "tibbiy ma'lumotnoma {date} da tugagan",
        "ru": "медицинская справка закончилась {date}",
        "en": "the medical certificate expired on {date}",
    },
    "doc.medical_until": {
        "uz": "tibbiy ma'lumotnoma {date} gacha",
        "ru": "медицинская справка действует до {date}",
        "en": "the medical certificate is valid until {date}",
    },
    "doc.no_validity": {
        "uz": "hech qaysi hujjatning amal qilish muddati yozilmagan",
        "ru": "ни у одного документа не записан срок действия",
        "en": "no document has a validity date recorded",
    },
    "doc.days_left": {
        "uz": "Eng erta tugaydigan hujjatgacha {days} kun ({details})",
        "ru": "До окончания ближайшего документа {days} дн. ({details})",
        "en": "{days} day(s) until the earliest document expires ({details})",
    },

    # -------------------------------------------------------------- Smena
    "shift.type": {
        "uz": "Smena turi: {type}",
        "ru": "Тип смены: {type}",
        "en": "Shift type: {type}",
    },
    "shift.no_record": {
        "uz": "bu kunga smena yozuvi yo'q (`driver_shift`)",
        "ru": "на эту дату нет записи о смене (`driver_shift`)",
        "en": "there is no shift record for that day (`driver_shift`)",
    },
    "shift.cancelled": {
        "uz": "Smena bekor qilingan",
        "ru": "Смена отменена",
        "en": "The shift was cancelled",
    },
    "shift.no_window": {
        "uz": "Smena bor: {type} ({status}), reys oynasi bilan solishtirilmadi",
        "ru": "Смена есть: {type} ({status}), с окном рейса не сравнивалась",
        "en": "There is a shift: {type} ({status}), not compared with the trip window",
    },
    "shift.zero_window": {
        "uz": "Smena bor: {type} (reys oynasi nol)",
        "ru": "Смена есть: {type} (окно рейса нулевое)",
        "en": "There is a shift: {type} (the trip window is zero)",
    },
    "shift.covers": {
        "uz": "Smena {type} ({start} — {end}) reys oynasining {percent} ini qoplaydi",
        "ru": "Смена {type} ({start} — {end}) покрывает {percent} окна рейса",
        "en": "The {type} shift ({start} — {end}) covers {percent} of the trip window",
    },

    # ------------------------------------------------------------ Malaka
    "skill.category_mismatch": {
        "uz": "Talab: {required}; haydovchida: {have}",
        "ru": "Требуется: {required}; у водителя: {have}",
        "en": "Required: {required}; the driver has: {have}",
    },
    "skill.none": {"uz": "yo'q", "ru": "нет", "en": "none"},
    "skill.category_ok": {
        "uz": "toifa {required} bor",
        "ru": "категория {required} есть",
        "en": "has category {required}",
    },
    "skill.no_category_required": {
        "uz": "toifa talabi berilmagan",
        "ru": "требование к категории не задано",
        "en": "no licence category was required",
    },
    "skill.no_history": {
        "uz": "{details}; tajriba baholanmadi: reys tarixi yo'q",
        "ru": "{details}; опыт не оценён: нет истории рейсов",
        "en": "{details}; experience not rated: no trip history",
    },
    "skill.history": {
        "uz": "{trips} tugagan reys, {incidents} hodisa (tozalik {clean})",
        "ru": "{trips} завершённых рейсов, {incidents} происшествий (чистота {clean})",
        "en": "{trips} completed trip(s), {incidents} incident(s) (clean rate {clean})",
    },

    # ----------------------------------------------------- Texnik holat
    "tech.status": {
        "uz": "holat: {status}", "ru": "состояние: {status}", "en": "status: {status}"},
    "tech.blocking_repairs": {
        "uz": "{count} ta chiqishni to'suvchi remont ochiq",
        "ru": "открыто ремонтов, блокирующих выезд: {count}",
        "en": "{count} repair(s) blocking release are open",
    },
    "tech.inspection": {
        "uz": "oxirgi ko'rik: {status}{age}",
        "ru": "последний техосмотр: {status}{age}",
        "en": "last inspection: {status}{age}",
    },
    "tech.inspection_age": {
        "uz": ", {days} kun oldin", "ru": ", {days} дн. назад", "en": ", {days} day(s) ago"},
    "tech.no_inspection": {
        "uz": "texnik ko'rik yozuvi yo'q",
        "ru": "нет записи о техосмотре",
        "en": "no technical inspection record",
    },
    "tech.maintenance": {
        "uz": "xizmat rejasi: {status}",
        "ru": "план обслуживания: {status}",
        "en": "maintenance plan: {status}",
    },
    "tech.open_repairs": {
        "uz": "{count} ta ochiq remont (chiqishni to'smaydi)",
        "ru": "открытых ремонтов: {count} (выезд не блокируют)",
        "en": "{count} open repair(s) (they do not block release)",
    },
    "tech.no_records": {
        "uz": "texnik ko'rik, xizmat rejasi va remont yozuvlari yo'q",
        "ru": "нет записей о техосмотре, плане обслуживания и ремонтах",
        "en": "no inspection, maintenance plan or repair records",
    },
    "tech.ok": {"uz": "muammo yo'q", "ru": "проблем нет", "en": "no problems"},

    # --------------------------------------------------------- Bandlik
    "av.vehicle_trip": {
        "uz": "mashina reysda: {id}",
        "ru": "машина в рейсе: {id}",
        "en": "the vehicle is on trip: {id}",
    },
    "av.vehicle_waybill": {
        "uz": "mashinada ochiq yo'l varaqasi: {number}",
        "ru": "у машины открыт путевой лист: {number}",
        "en": "the vehicle has an open waybill: {number}",
    },
    "av.driver_trip": {
        "uz": "haydovchi reysda: {id}",
        "ru": "водитель в рейсе: {id}",
        "en": "the driver is on trip: {id}",
    },
    "av.driver_waybill": {
        "uz": "ochiq yo'l varaqasi: {number}",
        "ru": "открытый путевой лист: {number}",
        "en": "open waybill: {number}",
    },
    "av.employment": {
        "uz": "mehnat holati: {status}",
        "ru": "трудовой статус: {status}",
        "en": "employment status: {status}",
    },
    "av.medical_unfit": {
        "uz": "tibbiy ko'rik {date}: {status}",
        "ru": "медосмотр {date}: {status}",
        "en": "medical inspection {date}: {status}",
    },
    "av.medical_missing": {
        "uz": "{date} ga yaroqli deb topilgan ko'rik yo'q (oxirgisi: {last} / {status})",
        "ru": "нет медосмотра с результатом «годен» на {date} (последний: {last} / {status})",
        "en": "no inspection found fit for {date} (the last one: {last} / {status})",
    },
    "av.medical_none": {"uz": "umuman yo'q", "ru": "отсутствует", "en": "none at all"},

    # ------------------------------------------------- data_quality.notes
    "note.max_vehicles": {
        "uz": "Mashinalar chegarasiga yetildi ({limit}) — ro'yxat qirqilgan "
              "bo'lishi mumkin (`VS_MAX_VEHICLES`)",
        "ru": "Достигнут лимит машин ({limit}) — список мог быть обрезан "
              "(`VS_MAX_VEHICLES`)",
        "en": "The vehicle limit was reached ({limit}) — the list may have been "
              "truncated (`VS_MAX_VEHICLES`)",
    },
    "note.max_drivers": {
        "uz": "Haydovchilar chegarasiga yetildi ({limit}) — ro'yxat qirqilgan "
              "bo'lishi mumkin (`VS_MAX_DRIVERS`)",
        "ru": "Достигнут лимит водителей ({limit}) — список мог быть обрезан "
              "(`VS_MAX_DRIVERS`)",
        "en": "The driver limit was reached ({limit}) — the list may have been "
              "truncated (`VS_MAX_DRIVERS`)",
    },
    "note.max_pairs": {
        "uz": "Juftliklar soni {estimated} ta bo'lardi, chegara {limit} — har "
              "tomondan eng kuchli {keep} tasi olindi (`VS_MAX_PAIRS`)",
        "ru": "Пар было бы {estimated}, лимит {limit} — с каждой стороны взяты "
              "сильнейшие {keep} (`VS_MAX_PAIRS`)",
        "en": "There would be {estimated} pairs, the limit is {limit} — the "
              "strongest {keep} from each side were taken (`VS_MAX_PAIRS`)",
    },
    "note.empty_tables": {
        "uz": "Bo'sh jadvallar: {tables}",
        "ru": "Пустые таблицы: {tables}",
        "en": "Empty tables: {tables}",
    },
    "note.no_driver_category": {
        "uz": "Haydovchi toifasi berilmagan — malaka mezoni toifa mosligini "
              "tekshirmadi (`route.required_driver_category` yoki `driver_category`)",
        "ru": "Категория водителя не задана — критерий квалификации не проверял "
              "соответствие категории (`route.required_driver_category` или "
              "`driver_category`)",
        "en": "No driver category was given — the skill criterion did not check "
              "category matching (`route.required_driver_category` or "
              "`driver_category`)",
    },
    "note.no_pickup_coords": {
        "uz": "Yuklash nuqtasi koordinatasi yo'q — masofa mezoni baholanmadi",
        "ru": "Нет координат пункта погрузки — критерий расстояния не оценивался",
        "en": "The pickup point has no coordinates — the distance criterion was "
              "not rated",
    },

    # -------------------------------------------------------- Juftlik izohi
    "pair.blocked": {
        "uz": "{head}: mos emas — {reasons}",
        "ru": "{head}: не подходит — {reasons}",
        "en": "{head}: not suitable — {reasons}",
    },
    "pair.blocked_short": {
        "uz": "Mos emas: {reasons}",
        "ru": "Не подходит: {reasons}",
        "en": "Not suitable: {reasons}",
    },
    "pair.strong": {
        "uz": "kuchli tomoni: {items}",
        "ru": "сильные стороны: {items}",
        "en": "strengths: {items}",
    },
    "pair.weak": {
        "uz": "zaif tomoni: {items}",
        "ru": "слабые стороны: {items}",
        "en": "weaknesses: {items}",
    },
    "pair.assigned": {
        "uz": "bazada biriktirilgan juftlik",
        "ru": "закреплённая пара в базе",
        "en": "a pair already assigned in the database",
    },
    "pair.skipped": {
        "uz": "baholanmadi: {items}",
        "ru": "не оценено: {items}",
        "en": "not rated: {items}",
    },
    "pair.no_data": {
        "uz": "mezonlar bo'yicha ma'lumot yo'q",
        "ru": "нет данных по критериям",
        "en": "no data for any criterion",
    },

    # ----------------------------------------------------------- Birliklar
    #
    # `criteria[].unit` javobda ko'rinadi va o'zbekcha so'z bo'lib turardi.
    # `km` tarjima qilinmaydi — u xalqaro qisqartma.
    "unit.share": {"uz": "ulush", "ru": "\u0434\u043e\u043b\u044f", "en": "share"},
    "unit.days": {"uz": "kun", "ru": "\u0434\u043d\u0438", "en": "days"},
    "unit.clean_trips": {
        "uz": "toza reys", "ru": "\u0447\u0438\u0441\u0442\u044b\u0445 \u0440\u0435\u0439\u0441\u043e\u0432", "en": "clean trips"},

    # --------------------------------------------------------------- Mayda
    "misc.not_rated": {
        "uz": "Baholanmadi: {reason}",
        "ru": "Не оценено: {reason}",
        "en": "Not rated: {reason}",
    },
    "misc.no_data": {
        "uz": "ma'lumot yo'q", "ru": "нет данных", "en": "no data"},
    "misc.unknown": {"uz": "noma'lum", "ru": "неизвестно", "en": "unknown"},
}
