"""Javobdagi hamma matn — uch tilda (uz, ru, en).

NIMA UCHUN BU FAYL BOR. Modul javobining yarmi matn: joylanmagan
arizaning sababi, `data_quality.notes`, `requirements` dagi tushuntirish,
marshrut izohi. Ular kodning o'n xil joyida f-string bo'lib yozilgan edi
va faqat o'zbekcha chiqardi. So'rovda `lang` berilganda javob TO'LIQ
o'sha tilda bo'lishi kerak — yarmi ruscha, yarmi o'zbekcha javob eng
yomon variant.

Shuning uchun hamma matn shu yerda, KALIT bo'yicha yig'ilgan. Kod
`t(lang, "note.busy", count=43)` deb chaqiradi, tilni bilmaydi.

KODLAR TARJIMA QILINMAYDI. `reason_code`, `need`, `kind`, jadval va
ustun nomlari — bular mashina o'qiydigan qiymatlar va uch tilda ham
bir xil qoladi. Tarjima faqat ODAM o'qiydigan matnga tegishli.

TRANSPORT TURLARI BU YERDA TAKRORLANMAYDI. Ularning uch tildagi nomi
`atil_chatbot/core/lang.py` da allaqachon bor (chatbot promptida
ishlatiladi) va `status_dictionary()` orqali olinadi. Ikkinchi nusxa
yozilsa ikkalasi vaqt o'tib bir-biridan uzoqlashardi.

YANGI TIL QO'SHISH: `LANGS` ga kod qo'shiladi va har bir kalitga o'sha
til yoziladi. `tests/test_route_optimization.py` dagi test hamma kalitda
hamma til borligini tekshiradi — biror joyi tushib qolsa darrov yiqiladi.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# `core.lang` atil_chatbot ichida yassi nom bilan import qiladi.
_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from core.lang import answer_instruction, status_dictionary  # noqa: E402

#: Qo'llab-quvvatlanadigan tillar. Chatbot bilan bir xil ro'yxat.
LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "uz"


def normalize(lang: str | None) -> str:
    """Noma'lum yoki bo'sh til sukut tilga tushadi."""
    value = (lang or "").strip().lower()
    return value if value in LANGS else DEFAULT_LANG


def transport_name(code: str | None, lang: str) -> str | None:
    """Transport turi kodining o'qiladigan nomi.

    Manba — chatbotning lug'ati (`core.lang.status_dictionary`), ya'ni
    prompt va API bir xil so'zni ishlatadi.

    Ingliz tilidagi ro'yxat ataylab qisqa: `BUS`, `VAN`, `TRACTOR` kabi
    kodlarning o'zi inglizcha so'z, ularni faqat o'qishga qulay yozish
    kerak. Noma'lum kod uz/ru da KODNING O'ZI bo'lib qaytadi — tarjima
    o'ylab topilmaydi, aks holda sxemaga qo'shilgan yangi tur jimgina
    noto'g'ri nom olardi.
    """
    if not code:
        return None
    name = status_dictionary(lang).get(code)
    if name:
        return name
    if lang == "en":
        return code.replace("_", " ").lower()
    return code


def priority_name(code: str | None, lang: str) -> str | None:
    """Ariza muhimligining o'qiladigan nomi.

    `transport_name` dan farqli o'laroq manba chatbot lug'ati EMAS: u
    yerda to'rt qiymatdan faqat ikkitasi bor (`HIGH`, `CRITICAL`) va
    ingliz tilida umuman yo'q. Yarim lug'atga tayanib qolgan ikkitasini
    boshqa joydan olish chalkash bo'lardi, shuning uchun to'rttasi ham
    shu faylda, `priority.*` kaliti bilan turadi.

    Noma'lum qiymat KODNING O'ZI bo'lib qaytadi.
    """
    if not code:
        return None
    key = f"priority.{code}"
    return t(lang, key) if key in MESSAGES else code


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


# ---------------------------------------------------------------- Matnlar

MESSAGES: dict[str, dict[str, str]] = {

    # ---------------------------------------- Joylanmaslik sabablari
    "reason.NO_COORDINATES": {
        "uz": "Yuklash yoki tushirish nuqtasining koordinatasi yo'q — "
              "masofa hisoblab bo'lmaydi",
        "ru": "Нет координат пункта погрузки или разгрузки — расстояние "
              "рассчитать невозможно",
        "en": "The pickup or delivery point has no coordinates — distance "
              "cannot be computed",
    },
    "reason.NO_MATCHING_VEHICLE": {
        "uz": "Talab qilingan transport turida bo'sh mashina yo'q",
        "ru": "Нет свободной машины требуемого типа транспорта",
        "en": "No free vehicle of the required transport type",
    },
    "reason.CAPACITY": {
        "uz": "Hech bir bo'sh mashinaning sig'imi yetmadi",
        "ru": "Ни у одной свободной машины не хватает грузоподъёмности",
        "en": "No free vehicle has enough capacity",
    },
    "reason.TIME_WINDOW": {
        "uz": "Vaqt oynasiga ulgurib bo'lmaydi",
        "ru": "В отведённое временное окно уложиться невозможно",
        "en": "The time window cannot be met",
    },
    "reason.SHIFT_LIMIT": {
        "uz": "Smena yoki reys davomiyligi chegarasidan oshib ketadi",
        "ru": "Превышается лимит смены или длительности рейса",
        "en": "It would exceed the shift or trip duration limit",
    },
    "reason.HAZARD": {
        "uz": "Xavfli yuk maxsus sisterna talab qiladi, bo'shi yo'q",
        "ru": "Опасный груз требует специальной цистерны, свободной нет",
        "en": "The hazardous cargo needs a special tanker, none is free",
    },
    "reason.BOUND_VEHICLE_UNAVAILABLE": {
        "uz": "Ariza bazada mashinaga biriktirilgan (`binding_vehicle_id`), "
              "lekin o'sha mashina bo'sh emas yoki arizani ko'tara olmaydi",
        "ru": "Заявка закреплена за машиной в базе (`binding_vehicle_id`), "
              "но эта машина занята или не может взять заявку",
        "en": "The request is bound to a vehicle in the database "
              "(`binding_vehicle_id`), but that vehicle is busy or cannot "
              "take the request",
    },
    "reason.NO_VEHICLE_LEFT": {
        "uz": "Bo'sh mashina qolmadi — barchasi to'lgan",
        "ru": "Свободных машин не осталось — все загружены",
        "en": "No free vehicle left — all are full",
    },

    # ------------------------------------------------- data_quality.notes
    "note.locked": {
        "uz": "{count} ta ariza bazada mashinaga BIRIKTIRILGAN "
              "(`binding_vehicle_id`) — ular o'sha mashinada qoldirildi, "
              "reja qolgan arizalar bo'yicha tuzildi",
        "ru": "{count} заявок ЗАКРЕПЛЕНЫ за машиной в базе "
              "(`binding_vehicle_id`) — они оставлены на своей машине, план "
              "построен по остальным заявкам",
        "en": "{count} request(s) are BOUND to a vehicle in the database "
              "(`binding_vehicle_id`) — they were kept on that vehicle and "
              "the plan was built around them",
    },
    "note.tank": {
        "uz": "{count} ta arizada xavfli yuk maxsus sisterna talab qiladi "
              "(`hazard_profile.requires_special_tank`) — faqat {types} "
              "turlari ko'rib chiqildi",
        "ru": "В {count} заявках опасный груз требует специальной цистерны "
              "(`hazard_profile.requires_special_tank`) — рассматривались "
              "только типы {types}",
        "en": "In {count} request(s) the hazardous cargo needs a special "
              "tanker (`hazard_profile.requires_special_tank`) — only the "
              "types {types} were considered",
    },
    "note.adr": {
        "uz": "{count} ta arizada yuk ADR talab qiladi. Haydovchining ADR "
              "ruxsati bazada alohida ustun sifatida yo'q — bu cheklov "
              "TEKSHIRILMADI, haydovchini qo'lda tasdiqlang",
        "ru": "В {count} заявках груз требует ADR. Допуск водителя ADR "
              "отдельным столбцом в базе не хранится — это ограничение НЕ "
              "ПРОВЕРЕНО, подтвердите водителя вручную",
        "en": "In {count} request(s) the cargo requires ADR. The driver's ADR "
              "permit is not stored as a separate column in the database — "
              "this constraint was NOT CHECKED, confirm the driver manually",
    },
    "note.missing_weight": {
        "uz": "{count} ta arizada yuk og'irligi ko'rsatilmagan "
              "(`cargo_weight_kg`) — ular uchun sig'im TEKSHIRILMADI, "
              "nol deb hisoblanmadi",
        "ru": "В {count} заявках не указан вес груза (`cargo_weight_kg`) — "
              "для них грузоподъёмность НЕ ПРОВЕРЯЛАСЬ и нулём не считалась",
        "en": "{count} request(s) have no cargo weight (`cargo_weight_kg`) — "
              "capacity was NOT CHECKED for them and was not treated as zero",
    },
    "note.coords_resolved": {
        "uz": "{count} ta nuqtaning koordinatasi `route_point` katalogidan yechildi",
        "ru": "Координаты {count} пунктов найдены в каталоге `route_point`",
        "en": "Coordinates for {count} point(s) were resolved from the "
              "`route_point` catalogue",
    },
    "note.busy": {
        "uz": "{count} ta mashina reja oynasida BAND (reys yoki ochiq yo'l "
              "varaqasi shu vaqtga to'g'ri keladi) — rejaga kiritilmadi",
        "ru": "{count} машин ЗАНЯТЫ в окне планирования (рейс или открытый "
              "путевой лист попадает на это время) — в план не включены",
        "en": "{count} vehicle(s) are BUSY within the planning window (a trip "
              "or an open waybill overlaps it) — they were left out of the plan",
    },
    "note.repair": {
        "uz": "{count} ta mashinada bloklovchi remont ochiq",
        "ru": "У {count} машин открыт блокирующий ремонт",
        "en": "{count} vehicle(s) have a blocking repair open",
    },
    "note.no_position": {
        "uz": "{count} ta mashinaning turgan joyi noma'lum: "
              "`vehicle_telemetry_state` bo'sh, filial koordinatasi "
              "(`reference_data`, BRANCHES) yo'q va `depot_latitude`/"
              "`depot_longitude` berilmagan",
        "ru": "Местоположение {count} машин неизвестно: "
              "`vehicle_telemetry_state` пуст, координат филиала "
              "(`reference_data`, BRANCHES) нет, `depot_latitude`/"
              "`depot_longitude` не переданы",
        "en": "The position of {count} vehicle(s) is unknown: "
              "`vehicle_telemetry_state` is empty, the branch has no "
              "coordinates (`reference_data`, BRANCHES) and no "
              "`depot_latitude`/`depot_longitude` was given",
    },
    "note.param_depot": {
        "uz": "{count} ta mashina so'rovdagi UMUMIY garajdan chiqadi deb "
              "hisoblandi. Aniqroq bo'lishi uchun `reference_data` da "
              "filiallarning (BRANCHES) koordinatasi to'ldirilsin",
        "ru": "{count} машин считаются выезжающими из ОБЩЕГО гаража из "
              "запроса. Для точности заполните координаты филиалов "
              "(BRANCHES) в `reference_data`",
        "en": "{count} vehicle(s) were assumed to start from the SHARED depot "
              "given in the request. For better accuracy fill in the branch "
              "(BRANCHES) coordinates in `reference_data`",
    },
    "note.gps": {
        "uz": "{count} ta mashina o'zining oxirgi GPS nuqtasidan hisoblandi",
        "ru": "{count} машин рассчитаны от своей последней точки GPS",
        "en": "{count} vehicle(s) were computed from their last GPS position",
    },
    "note.missing_capacity": {
        "uz": "{count} ta mashinada sig'im ko'rsatilmagan "
              "(`payload_capacity_kg`) — ular uchun sig'im cheklovi QO'LLANMADI",
        "ru": "У {count} машин не указана грузоподъёмность "
              "(`payload_capacity_kg`) — ограничение по вместимости для них "
              "НЕ ПРИМЕНЯЛОСЬ",
        "en": "{count} vehicle(s) have no capacity (`payload_capacity_kg`) — "
              "the capacity constraint was NOT APPLIED to them",
    },
    "note.time_budget": {
        "uz": "Vaqt byudjeti ({seconds} s) tugadi — reja to'liq, lekin yanada "
              "yaxshilanishi mumkin edi (`RO_TIME_BUDGET_SECONDS`)",
        "ru": "Бюджет времени ({seconds} с) исчерпан — план полный, но мог бы "
              "быть ещё лучше (`RO_TIME_BUDGET_SECONDS`)",
        "en": "The time budget ({seconds} s) ran out — the plan is complete "
              "but could have been improved further (`RO_TIME_BUDGET_SECONDS`)",
    },
    "note.empty_matrix": {
        "uz": "Hech bir nuqtaning koordinatasi yo'q — masofa matritsasi bo'sh. "
              "Reja tuzilmadi (arizalar `NO_COORDINATES` bilan qaytdi)",
        "ru": "Ни у одного пункта нет координат — матрица расстояний пуста. "
              "План не построен (заявки вернулись с `NO_COORDINATES`)",
        "en": "No point has coordinates — the distance matrix is empty. No "
              "plan was built (requests came back with `NO_COORDINATES`)",
    },
    "note.not_ready": {
        "uz": "Baza rejalashtirishga TAYYOR EMAS. To'ldirilishi kerak: {items}. "
              "Batafsil: `data_quality.requirements`",
        "ru": "База НЕ ГОТОВА к планированию. Требуется заполнить: {items}. "
              "Подробно: `data_quality.requirements`",
        "en": "The database is NOT READY for planning. What must be filled in: "
              "{items}. Details: `data_quality.requirements`",
    },
    "note.max_vehicles": {
        "uz": "Mashinalar chegarasiga yetildi ({limit}) — ro'yxat qirqilgan "
              "bo'lishi mumkin (`RO_MAX_VEHICLES`)",
        "ru": "\u0414\u043e\u0441\u0442\u0438\u0433\u043d\u0443\u0442 \u043b\u0438\u043c\u0438\u0442 \u043c\u0430\u0448\u0438\u043d ({limit}) \u2014 \u0441\u043f\u0438\u0441\u043e\u043a \u043c\u043e\u0433 \u0431\u044b\u0442\u044c "
              "\u043e\u0431\u0440\u0435\u0437\u0430\u043d (`RO_MAX_VEHICLES`)",
        "en": "The vehicle limit was reached ({limit}) — the list may have "
              "been truncated (`RO_MAX_VEHICLES`)",
    },
    "note.max_requests": {
        "uz": "Arizalar chegarasiga yetildi ({limit}) — ro'yxat qirqilgan "
              "bo'lishi mumkin (`RO_MAX_REQUESTS`)",
        "ru": "Достигнут лимит заявок ({limit}) — список мог быть обрезан "
              "(`RO_MAX_REQUESTS`)",
        "en": "The request limit was reached ({limit}) — the list may have "
              "been truncated (`RO_MAX_REQUESTS`)",
    },
    "note.depot_not_found": {
        "uz": "Garaj manzili topilmadi: {location_id}",
        "ru": "Адрес гаража не найден: {location_id}",
        "en": "Depot location not found: {location_id}",
    },
    "note.dock_missing": {
        "uz": "Yuklash joylarida dock sloti topilmadi (`dock_slot` bo'sh) — "
              "navbat cheklovi hisobga OLINMADI",
        "ru": "На пунктах погрузки не найдено ни одного дока (`dock_slot` "
              "пуст) — ограничение по очереди НЕ УЧТЕНО",
        "en": "No dock slot was found at the loading points (`dock_slot` is "
              "empty) — the queueing constraint was NOT taken into account",
    },
    "note.dock_queue": {
        "uz": "{used} ta mashina rejalashtirildi, bo'sh dock sloti "
              "{available} ta — yuklashda navbat bo'lishi mumkin",
        "ru": "Запланировано {used} машин, свободных доков {available} — при "
              "погрузке возможна очередь",
        "en": "{used} vehicle(s) were planned but only {available} dock "
              "slot(s) are free — a queue is possible at loading",
    },
    "note.manual": {
        "uz": "Reja so'rovdagi ma'lumot bo'yicha tuzildi — bazaga murojaat qilinmadi",
        "ru": "План построен по данным из запроса — база не запрашивалась",
        "en": "The plan was built from the data in the request — the database "
              "was not queried",
    },

    # ------------------------------------------------- calibration.notes
    "cal.road_not_measured": {
        "uz": "Yo'l koeffitsienti o'lchanmadi: `route_point` da mos o'lchov "
              "{count} ta, kerak {need} ta (masofa va ikkala nuqtaning "
              "koordinatasi bir vaqtda kerak)",
        "ru": "Дорожный коэффициент не измерен: подходящих замеров в "
              "`route_point` {count}, нужно {need} (одновременно нужны "
              "расстояние и координаты обеих точек)",
        "en": "The road factor could not be measured: `route_point` has "
              "{count} usable sample(s), {need} are needed (distance and the "
              "coordinates of both points are required together)",
    },
    "cal.road_error": {
        "uz": "Yo'l koeffitsienti o'lchanmadi: {error}",
        "ru": "Дорожный коэффициент не измерен: {error}",
        "en": "The road factor could not be measured: {error}",
    },
    "cal.straight_line": {
        "uz": "Masofa TO'G'RI CHIZIQ bo'yicha olindi (koeffitsient 1.0) — "
              "haqiqiy yo'l undan uzun bo'ladi. `RO_OSRM_URL` yoki "
              "`RO_FALLBACK_ROAD_FACTOR` berilsa aniqroq bo'ladi",
        "ru": "Расстояние взято ПО ПРЯМОЙ (коэффициент 1.0) — реальная дорога "
              "будет длиннее. Точнее будет с `RO_OSRM_URL` или "
              "`RO_FALLBACK_ROAD_FACTOR`",
        "en": "Distance was taken as a STRAIGHT LINE (factor 1.0) — the real "
              "road is longer. Set `RO_OSRM_URL` or `RO_FALLBACK_ROAD_FACTOR` "
              "for better accuracy",
    },
    "cal.speed_not_measured": {
        "uz": "O'rtacha tezlik o'lchanmadi: `trip` va `route_point` da mos "
              "o'lchov {count} ta, kerak {need} ta",
        "ru": "Средняя скорость не измерена: подходящих замеров в `trip` и "
              "`route_point` {count}, нужно {need}",
        "en": "Average speed could not be measured: `trip` and `route_point` "
              "have {count} usable sample(s), {need} are needed",
    },
    "cal.speed_from_trip": {
        "uz": "Tezlik `trip` dan olindi \u2014 u reysning TO'LIQ vaqtini "
              "o'lchaydi (jo'nash \u2192 nuqtada ish \u2192 qaytish), sof yo'l vaqtini "
              "emas. Nuqtadagi vaqt xizmat vaqti sifatida ALOHIDA "
              "qo'shilgani uchun reja pessimistik chiqadi. Aniqroq manba \u2014 "
              "`route_point.drive_duration_from_previous_minutes`",
        "ru": "\u0421\u043a\u043e\u0440\u043e\u0441\u0442\u044c \u0432\u0437\u044f\u0442\u0430 \u0438\u0437 `trip` \u2014 \u043e\u043d \u0438\u0437\u043c\u0435\u0440\u044f\u0435\u0442 \u041f\u041e\u041b\u041d\u041e\u0415 \u0432\u0440\u0435\u043c\u044f "
              "\u0440\u0435\u0439\u0441\u0430 (\u0432\u044b\u0435\u0437\u0434 \u2192 \u0440\u0430\u0431\u043e\u0442\u0430 \u043d\u0430 \u043f\u0443\u043d\u043a\u0442\u0435 \u2192 \u0432\u043e\u0437\u0432\u0440\u0430\u0442), \u0430 \u043d\u0435 \u0447\u0438\u0441\u0442\u043e\u0435 "
              "\u0432\u0440\u0435\u043c\u044f \u0432 \u043f\u0443\u0442\u0438. \u0412\u0440\u0435\u043c\u044f \u043d\u0430 \u043f\u0443\u043d\u043a\u0442\u0435 \u0434\u043e\u0431\u0430\u0432\u043b\u044f\u0435\u0442\u0441\u044f \u041e\u0422\u0414\u0415\u041b\u042c\u041d\u041e, "
              "\u043f\u043e\u044d\u0442\u043e\u043c\u0443 \u043f\u043b\u0430\u043d \u043f\u043e\u043b\u0443\u0447\u0430\u0435\u0442\u0441\u044f \u043f\u0435\u0441\u0441\u0438\u043c\u0438\u0441\u0442\u0438\u0447\u043d\u044b\u043c. \u0422\u043e\u0447\u043d\u0435\u0435 \u2014 "
              "`route_point.drive_duration_from_previous_minutes`",
        "en": "Speed was taken from `trip` \u2014 it measures the WHOLE trip "
              "(departure \u2192 work on site \u2192 return), not pure driving time. "
              "Time on site is added SEPARATELY as service time, so the plan "
              "comes out pessimistic. The precise source is "
              "`route_point.drive_duration_from_previous_minutes`",
    },
    "cal.speed_error": {
        "uz": "O'rtacha tezlik o'lchanmadi: {error}",
        "ru": "Средняя скорость не измерена: {error}",
        "en": "Average speed could not be measured: {error}",
    },
    "cal.speed_unknown": {
        "uz": "TEZLIK NOMA'LUM — vaqt hisoblanmadi. Vaqt oynasi, smena "
              "chegarasi va xizmat vaqti TEKSHIRILMADI, reja faqat masofa "
              "bo'yicha qurildi. `average_speed_kph` parametri yoki "
              "`RO_FALLBACK_SPEED_KPH` bering",
        "ru": "СКОРОСТЬ НЕИЗВЕСТНА — время не рассчитывалось. Временные окна, "
              "лимит смены и время обслуживания НЕ ПРОВЕРЕНЫ, план построен "
              "только по расстоянию. Передайте `average_speed_kph` или "
              "`RO_FALLBACK_SPEED_KPH`",
        "en": "SPEED IS UNKNOWN — no time was computed. Time windows, shift "
              "limits and service time were NOT CHECKED; the plan was built on "
              "distance alone. Provide `average_speed_kph` or "
              "`RO_FALLBACK_SPEED_KPH`",
    },
    "cal.service_not_measured": {
        "uz": "Xizmat vaqti o'lchanmadi: `trip_event` da ketma-ket "
              "\"yetib bordi -> yukladi/tushirdi\" juftligi {count} ta, "
              "kerak {need} ta",
        "ru": "Время обслуживания не измерено: последовательных пар "
              "\"прибыл -> загрузил/разгрузил\" в `trip_event` {count}, "
              "нужно {need}",
        "en": "Service time could not be measured: `trip_event` has {count} "
              "consecutive \"arrived -> loaded/unloaded\" pair(s), {need} are "
              "needed",
    },
    "cal.service_error": {
        "uz": "Xizmat vaqti o'lchanmadi: {error}",
        "ru": "Время обслуживания не измерено: {error}",
        "en": "Service time could not be measured: {error}",
    },
    "cal.service_optimistic": {
        "uz": "Xizmat vaqti noma'lum — jadval faqat yo'l vaqtidan qurildi, "
              "yuklash/tushirishga vaqt ajratilmadi (reja optimistik)",
        "ru": "Время обслуживания неизвестно — расписание построено только по "
              "времени в пути, на погрузку/разгрузку время не заложено (план "
              "оптимистичный)",
        "en": "Service time is unknown — the schedule was built from driving "
              "time only, with no allowance for loading/unloading (the plan is "
              "optimistic)",
    },
    "cal.objective_fallback": {
        "uz": "Maqsad `{objective}` so'ralgan edi, lekin tezlik noma'lum — "
              "reja `distance` bo'yicha tuzildi",
        "ru": "Была запрошена цель `{objective}`, но скорость неизвестна — "
              "план построен по `distance`",
        "en": "The objective `{objective}` was requested, but speed is "
              "unknown — the plan was built on `distance`",
    },

    # ---------------------------------------------- Marshrut izohi va xavf
    "route.head": {
        "uz": "{plate}: {requests} ta ariza, {stops} ta to'xtash, {km} km",
        "ru": "{plate}: заявок {requests}, остановок {stops}, {km} км",
        "en": "{plate}: {requests} request(s), {stops} stop(s), {km} km",
    },
    "route.hours": {
        "uz": "{hours} soat",
        "ru": "{hours} ч",
        "en": "{hours} h",
    },
    "route.utilization": {
        "uz": "sig'imning {percent} i ishlatilgan",
        "ru": "использовано {percent} вместимости",
        "en": "{percent} of capacity used",
    },
    "route.capacity_unknown": {
        "uz": "sig'im noma'lum",
        "ru": "вместимость неизвестна",
        "en": "capacity unknown",
    },
    "route.late": {
        "uz": "{minutes} daqiqa kechikish",
        "ru": "опоздание {minutes} мин",
        "en": "{minutes} min late",
    },
    "warn.late": {
        "uz": "Jami {minutes} daqiqa kechikish bor (vaqt oynasi qattiq emas)",
        "ru": "Суммарное опоздание {minutes} мин (временное окно не жёсткое)",
        "en": "Total lateness is {minutes} min (the time window is not hard)",
    },
    "warn.over_capacity": {
        "uz": "Yuk sig'imdan oshgan — sig'im cheklovi o'chirilgan",
        "ru": "Груз превышает вместимость — ограничение по вместимости отключено",
        "en": "The load exceeds capacity — the capacity constraint is disabled",
    },

    # ------------------------------------------------------------ Xatolar
    "error.nothing_to_plan": {
        "uz": "{date} sanasiga rejalashtiriladigan ariza topilmadi "
              "(holatlar: {statuses})",
        "ru": "На дату {date} не найдено заявок для планирования "
              "(статусы: {statuses})",
        "en": "No request to plan was found for {date} (statuses: {statuses})",
    },
    "error.db": {
        "uz": "Bazadan o'qib bo'lmadi: {error}",
        "ru": "Не удалось прочитать из базы: {error}",
        "en": "Could not read from the database: {error}",
    },
    "error.analysis": {
        "uz": "Tahlil olinmadi: LLM serveri javob bermadi. Keyinroq urinib ko'ring",
        "ru": "Анализ не получен: сервер LLM не ответил. Попробуйте позже",
        "en": "Analysis unavailable: the LLM server did not respond. Try again later",
    },

    # ------------------------------------------------- Ariza muhimligi
    #
    # `transport_request.priority` — dispetcher ko'radigan qiymat, ya'ni
    # javobda kod emas, NOM bo'lib chiqadi.
    "priority.CRITICAL": {"uz": "jiddiy", "ru": "критический", "en": "critical"},
    "priority.URGENT": {"uz": "shoshilinch", "ru": "срочный", "en": "urgent"},
    "priority.HIGH": {"uz": "yuqori", "ru": "высокий", "en": "high"},
    "priority.NORMAL": {"uz": "oddiy", "ru": "обычный", "en": "normal"},

    # ------------------------------------------------------------- Mayda
    "misc.depot": {"uz": "Garaj", "ru": "Гараж", "en": "Depot"},
    "misc.all": {"uz": "hammasi", "ru": "все", "en": "all"},
    "misc.or": {"uz": " yoki ", "ru": " или ", "en": " or "},
    "misc.start_point": {
        "uz": "Chiqish nuqtasi", "ru": "Точка выезда", "en": "Start point",
    },
    "misc.last_gps": {
        "uz": "Oxirgi GPS nuqtasi",
        "ru": "Последняя точка GPS",
        "en": "Last GPS position",
    },
    "misc.branch_depot": {
        "uz": "Filial garaji", "ru": "Гараж филиала", "en": "Branch depot",
    },

    # ------------------------------------------------ Tayyorlik talablari
    "req.requests.title": {
        "uz": "Rejalashtiriladigan ariza",
        "ru": "Заявка для планирования",
        "en": "A request to plan",
    },
    "req.requests.impact": {
        "uz": "Ariza bo'lmasa reja umuman tuzilmaydi — endpoint 404 qaytaradi.",
        "ru": "Без заявок план вообще не строится — endpoint вернёт 404.",
        "en": "With no requests no plan is built at all — the endpoint returns 404.",
    },
    "req.requests.hint": {
        "uz": "`status` shu holatlardan biri bo'lsin: {statuses} (`.env` dagi "
              "`RO_REQUEST_STATUSES`). `planned_departure_at` bo'sh bo'lsa "
              "ariza baribir olinadi — sana bo'yicha kesilmaydi.",
        "ru": "`status` должен быть одним из: {statuses} (`RO_REQUEST_STATUSES` "
              "в `.env`). Пустой `planned_departure_at` не мешает — по дате "
              "заявка не отсекается.",
        "en": "`status` must be one of: {statuses} (`RO_REQUEST_STATUSES` in "
              "`.env`). An empty `planned_departure_at` is fine — the request "
              "is not filtered out by date.",
    },
    "req.coords.title": {
        "uz": "Yuklash va tushirish nuqtasining koordinatasi",
        "ru": "Координаты пунктов погрузки и разгрузки",
        "en": "Coordinates of the pickup and delivery points",
    },
    "req.coords.impact": {
        "uz": "Koordinatasiz masofa hisoblanmaydi: ariza rejaga tushmaydi va "
              "`unassigned` da `NO_COORDINATES` bilan qaytadi. HOZIRGI ASOSIY TO'SIQ.",
        "ru": "Без координат расстояние не считается: заявка не попадёт в план "
              "и вернётся в `unassigned` с `NO_COORDINATES`. СЕЙЧАС ЭТО "
              "ГЛАВНОЕ ПРЕПЯТСТВИЕ.",
        "en": "Without coordinates distance cannot be computed: the request "
              "stays out of the plan and comes back in `unassigned` with "
              "`NO_COORDINATES`. THIS IS THE MAIN BLOCKER RIGHT NOW.",
    },
    "req.coords.hint": {
        "uz": "Uchtasidan BITTASI yetadi. Eng arzoni — `transport_request` ning "
              "o'z `origin_*`/`destination_*` ustunlari. `reference_data` "
              "(LOCATIONS) to'ldirilsa arizada faqat `origin_location_id` "
              "turishi ham kifoya: modul koordinatani katalogdan o'zi yechadi.",
        "ru": "Достаточно ОДНОГО из трёх. Дешевле всего — собственные столбцы "
              "`origin_*`/`destination_*` в `transport_request`. Если заполнить "
              "`reference_data` (LOCATIONS), в заявке хватит и одного "
              "`origin_location_id`: модуль сам возьмёт координаты из каталога.",
        "en": "ONE of the three is enough. The cheapest is "
              "`transport_request`'s own `origin_*`/`destination_*` columns. If "
              "`reference_data` (LOCATIONS) is filled in, a plain "
              "`origin_location_id` on the request is enough — the module "
              "resolves the coordinates from the catalogue itself.",
    },
    "req.vehicles.title": {
        "uz": "Rejaga yaroqli mashina",
        "ru": "Машина, пригодная для плана",
        "en": "A vehicle usable for the plan",
    },
    "req.vehicles.impact": {
        "uz": "Mashina qolmasa ariza `NO_VEHICLE_LEFT` bilan qaytadi.",
        "ru": "Если машин не остаётся, заявка вернётся с `NO_VEHICLE_LEFT`.",
        "en": "If no vehicle is left the request comes back with `NO_VEHICLE_LEFT`.",
    },
    "req.vehicles.hint": {
        "uz": "`current_status` {blocked} bo'lmasin. `transport_type` arizadagi "
              "`required_transport_type` bilan bir xil yozilsin — mos turi "
              "topilmagan ariza `NO_MATCHING_VEHICLE` bo'ladi.",
        "ru": "`current_status` не должен быть {blocked}. `transport_type` "
              "должен совпадать с `required_transport_type` в заявке — иначе "
              "заявка получит `NO_MATCHING_VEHICLE`.",
        "en": "`current_status` must not be {blocked}. `transport_type` must "
              "match the request's `required_transport_type` — otherwise the "
              "request gets `NO_MATCHING_VEHICLE`.",
    },
    "req.start.title": {
        "uz": "Mashinaning chiqish nuqtasi",
        "ru": "Точка выезда машины",
        "en": "The vehicle's start point",
    },
    "req.start.impact": {
        "uz": "Chiqish nuqtasi noma'lum mashina rejaga UMUMAN kirmaydi — park "
              "to'la bo'lsa ham `vehicles_considered` nol bo'lib qoladi.",
        "ru": "Машина с неизвестной точкой выезда В ПЛАН НЕ ПОПАДАЕТ — даже "
              "при полном парке `vehicles_considered` останется нулём.",
        "en": "A vehicle with an unknown start point does NOT enter the plan at "
              "all — `vehicles_considered` stays zero even with a full fleet.",
    },
    "req.start.hint": {
        "uz": "Uch bosqich, aniqdan taxminiyga: GPS holati -> mashinaning O'Z "
              "filiali (`transport_vehicle.branch_id` -> `reference_data` "
              "BRANCHES) -> so'rovdagi `depot_latitude`/`depot_longitude`. "
              "So'rovdagi garaj butun parkni BITTA nuqtadan chiqaradi; "
              "filiallar koordinatasi to'lsa reja aniqroq bo'ladi.",
        "ru": "Три ступени, от точного к приблизительному: состояние GPS -> "
              "СВОЙ филиал машины (`transport_vehicle.branch_id` -> "
              "`reference_data` BRANCHES) -> `depot_latitude`/"
              "`depot_longitude` из запроса. Гараж из запроса выпускает весь "
              "парк из ОДНОЙ точки; с координатами филиалов план точнее.",
        "en": "Three steps, from precise to approximate: GPS state -> the "
              "vehicle's OWN branch (`transport_vehicle.branch_id` -> "
              "`reference_data` BRANCHES) -> `depot_latitude`/"
              "`depot_longitude` from the request. The depot from the request "
              "sends the whole fleet out from ONE point; with branch "
              "coordinates the plan gets more accurate.",
    },
    "req.start.note_depot": {
        "uz": "So'rovda `depot_latitude`/`depot_longitude` berilgani uchun "
              "talab bajarilgan hisoblandi — bazadagi manba hali bo'sh.",
        "ru": "Требование считается выполненным, так как в запросе переданы "
              "`depot_latitude`/`depot_longitude` — источник в базе ещё пуст.",
        "en": "The requirement counts as met because "
              "`depot_latitude`/`depot_longitude` were given in the request — "
              "the database source is still empty.",
    },
    "req.speed.title": {
        "uz": "O'rtacha tezlik (vaqt hisobi)",
        "ru": "Средняя скорость (расчёт времени)",
        "en": "Average speed (time computation)",
    },
    "req.speed.impact": {
        "uz": "Tezlik noma'lum bo'lsa VAQT UMUMAN hisoblanmaydi: vaqt oynasi, "
              "smena va xizmat vaqti tekshirilmaydi "
              "(`calibration.time_aware=false`), maqsad avtomatik `distance` "
              "ga tushadi.",
        "ru": "Если скорость неизвестна, ВРЕМЯ НЕ СЧИТАЕТСЯ ВООБЩЕ: временные "
              "окна, смена и время обслуживания не проверяются "
              "(`calibration.time_aware=false`), цель автоматически "
              "переключается на `distance`.",
        "en": "If speed is unknown, TIME IS NOT COMPUTED AT ALL: time windows, "
              "shifts and service time are not checked "
              "(`calibration.time_aware=false`) and the objective falls back "
              "to `distance`.",
    },
    "req.speed.hint": {
        "uz": "Har bir manbadan kamida {minimum} ta o'lchov kerak "
              "(`RO_MIN_CALIBRATION_SAMPLES`). Kutmasdan ishlatish uchun "
              "so'rovda `average_speed_kph` berilsin.",
        "ru": "От каждого источника нужно минимум {minimum} замеров "
              "(`RO_MIN_CALIBRATION_SAMPLES`). Чтобы не ждать, передайте "
              "`average_speed_kph` в запросе.",
        "en": "At least {minimum} samples are needed from each source "
              "(`RO_MIN_CALIBRATION_SAMPLES`). To use it right away, pass "
              "`average_speed_kph` in the request.",
    },
    "req.speed.note_request": {
        "uz": "Tezlik so'rovda berilgan — bazadagi o'lchov ishlatilmadi.",
        "ru": "Скорость передана в запросе — замер из базы не использовался.",
        "en": "Speed was given in the request — the measurement from the "
              "database was not used.",
    },
    "req.speed.note_measured": {
        "uz": "O'lchandi: {speed} km/soat, manba `{source}`, {samples} ta o'lchov.",
        "ru": "Измерено: {speed} км/ч, источник `{source}`, замеров {samples}.",
        "en": "Measured: {speed} km/h, source `{source}`, {samples} sample(s).",
    },
    "req.speed.note_range": {
        "uz": "Yaroqli qator yetarli, lekin o'lchovlar 1-120 km/soat "
              "oralig'idan chiqib ketdi — masofa yoki vaqt ustunida xato bor.",
        "ru": "Пригодных строк достаточно, но замеры вышли за диапазон "
              "1-120 км/ч — ошибка в столбце расстояния или времени.",
        "en": "There are enough usable rows, but the samples fall outside the "
              "1-120 km/h range — the distance or time column has bad data.",
    },
    "req.road.title": {
        "uz": "Yo'l koeffitsienti (to'g'ri chiziq -> haqiqiy yo'l)",
        "ru": "Дорожный коэффициент (прямая -> реальная дорога)",
        "en": "Road factor (straight line -> real road)",
    },
    "req.road.impact": {
        "uz": "Masofa TO'G'RI CHIZIQ bo'yicha olinadi — haqiqiy yo'l undan "
              "uzun, ya'ni reja optimistik chiqadi.",
        "ru": "Расстояние берётся ПО ПРЯМОЙ — реальная дорога длиннее, значит "
              "план получается оптимистичным.",
        "en": "Distance is taken as a STRAIGHT LINE — the real road is longer, "
              "so the plan comes out optimistic.",
    },
    "req.road.hint": {
        "uz": "`route_point` da ketma-ket ikki nuqtaning koordinatasi VA "
              "`distance_from_previous_km` bir vaqtda to'lgan bo'lishi kerak. "
              "Muqobil yo'l: `RO_OSRM_URL` ga yo'l xizmati ulansa masofa "
              "haqiqiy yo'l bo'yicha olinadi va bu talab umuman kerak bo'lmaydi.",
        "ru": "В `route_point` должны быть одновременно заполнены координаты "
              "двух соседних точек И `distance_from_previous_km`. "
              "Альтернатива: подключить дорожный сервис к `RO_OSRM_URL` — "
              "тогда расстояние берётся по реальной дороге и это требование "
              "вообще не нужно.",
        "en": "In `route_point` the coordinates of two consecutive points AND "
              "`distance_from_previous_km` must be filled in together. "
              "Alternative: connect a routing service to `RO_OSRM_URL` — then "
              "distance comes from the real road and this requirement is not "
              "needed at all.",
    },
    "req.road.note_filtered": {
        "uz": "{usable} ta yaroqli qator topildi, lekin {reason}.",
        "ru": "Найдено {usable} пригодных строк, но {reason}.",
        "en": "{usable} usable row(s) were found, but {reason}.",
    },
    "req.road.filter_reason": {
        "uz": "koeffitsient 1.0-5.0 oralig'idan chiqib ketdi (koordinata yoki "
              "masofa ustunida xato bor)",
        "ru": "коэффициент вышел за диапазон 1.0-5.0 (ошибка в координатах или "
              "в столбце расстояния)",
        "en": "the factor fell outside the 1.0-5.0 range (bad data in the "
              "coordinates or the distance column)",
    },
    "req.service.title": {
        "uz": "Nuqtadagi yuklash/tushirish vaqti",
        "ru": "Время погрузки/разгрузки на пункте",
        "en": "Loading/unloading time at a point",
    },
    "req.service.impact": {
        "uz": "Jadval faqat yo'l vaqtidan quriladi — yuklash/tushirishga vaqt "
              "ajratilmaydi va reja optimistik bo'ladi.",
        "ru": "Расписание строится только по времени в пути — на "
              "погрузку/разгрузку время не закладывается и план получается "
              "оптимистичным.",
        "en": "The schedule is built from driving time only — no time is "
              "allowed for loading/unloading and the plan is optimistic.",
    },
    "req.service.hint": {
        "uz": "Bitta reys ichida `TRIP_ARRIVED_AT_POINT` dan keyin "
              "`TRIP_LOADED` yoki `TRIP_UNLOADED` ketma-ket yozilsin — o'lchov "
              "shu ikki hodisa orasidagi vaqtdan olinadi. Muqobil: `.env` dagi "
              "`RO_FALLBACK_SERVICE_MINUTES` yoki so'rovdagi `service_minutes`.",
        "ru": "Внутри одного рейса после `TRIP_ARRIVED_AT_POINT` должно "
              "следовать `TRIP_LOADED` или `TRIP_UNLOADED` — замер берётся из "
              "промежутка между этими событиями. Альтернатива: "
              "`RO_FALLBACK_SERVICE_MINUTES` в `.env` или `service_minutes` в "
              "запросе.",
        "en": "Within one trip a `TRIP_ARRIVED_AT_POINT` must be followed by "
              "`TRIP_LOADED` or `TRIP_UNLOADED` — the measurement is the gap "
              "between those two events. Alternative: "
              "`RO_FALLBACK_SERVICE_MINUTES` in `.env` or `service_minutes` in "
              "the request.",
    },
    "req.capacity.title": {
        "uz": "Sig'im cheklovi",
        "ru": "Ограничение по вместимости",
        "en": "Capacity constraint",
    },
    "req.capacity.impact": {
        "uz": "Sig'im TEKSHIRILMAYDI: bitta mashinaga sig'maydigan yuk ham "
              "qo'yilib ketishi mumkin. Noma'lum og'irlik NOL deb hisoblanmaydi.",
        "ru": "Вместимость НЕ ПРОВЕРЯЕТСЯ: на машину может быть назначен груз, "
              "который в неё не помещается. Неизвестный вес НЕ считается нулём.",
        "en": "Capacity is NOT CHECKED: cargo that does not fit may still be "
              "assigned to a vehicle. An unknown weight is NOT treated as zero.",
    },
    "req.capacity.hint": {
        "uz": "Ikkala tomon ham kerak: mashinada `payload_capacity_kg`, arizada "
              "`cargo_weight_kg` (yoki `shipment.cargo_weight_kg` / "
              "`shipment.weight_tons`). Bittasi bo'lmasa cheklov qo'llanmaydi.",
        "ru": "Нужны обе стороны: у машины `payload_capacity_kg`, у заявки "
              "`cargo_weight_kg` (или `shipment.cargo_weight_kg` / "
              "`shipment.weight_tons`). Без одной из них ограничение не "
              "применяется.",
        "en": "Both sides are needed: `payload_capacity_kg` on the vehicle and "
              "`cargo_weight_kg` on the request (or "
              "`shipment.cargo_weight_kg` / `shipment.weight_tons`). Without "
              "either one the constraint is not applied.",
    },
    "req.busy.title": {
        "uz": "Reys va yo'l varaqasining vaqti (bandlik)",
        "ru": "Время рейса и путевого листа (занятость)",
        "en": "Trip and waybill times (busyness)",
    },
    "req.busy.impact": {
        "uz": "Vaqti NOMA'LUM aktiv reys yoki ochiq yo'l varaqasi BAND deb "
              "hisoblanadi (xavfsiz tomon) — mashina amalda bo'sh bo'lsa ham "
              "rejadan chiqib ketadi.",
        "ru": "Активный рейс или открытый путевой лист с НЕИЗВЕСТНЫМ временем "
              "считается ЗАНЯТОСТЬЮ (безопасная сторона) — машина выпадает из "
              "плана, даже если фактически свободна.",
        "en": "An active trip or open waybill with an UNKNOWN time counts as "
              "BUSY (the safe side) — the vehicle drops out of the plan even "
              "if it is actually free.",
    },
    "req.busy.hint": {
        "uz": "Reys/varaqa vaqtlari to'lsa bandlik OYNA bo'yicha kesiladi: "
              "ertalabki reysini tugatgan mashina tushdan keyingi rejaga kiradi.",
        "ru": "Когда времена рейса/листа заполнены, занятость определяется ПО "
              "ОКНУ: машина, завершившая утренний рейс, попадёт в план на "
              "вторую половину дня.",
        "en": "Once trip/waybill times are filled in, busyness is decided BY "
              "WINDOW: a vehicle that finished its morning trip is available "
              "for the afternoon plan.",
    },
    "req.shift.title": {
        "uz": "Haydovchi smenasi",
        "ru": "Смена водителя",
        "en": "Driver shift",
    },
    "req.shift.impact": {
        "uz": "Smena chegarasi tekshirilmaydi — marshrut ish vaqtidan "
              "tashqariga cho'zilib ketishi mumkin.",
        "ru": "Лимит смены не проверяется — маршрут может выйти за пределы "
              "рабочего времени.",
        "en": "The shift limit is not checked — a route may run past working "
              "hours.",
    },
    "req.shift.hint": {
        "uz": "Smena mashinaning biriktirilgan haydovchisi bo'yicha topiladi "
              "(`transport_vehicle.assigned_driver_id` -> "
              "`driver_shift.driver_id`) va `shift_date` reja sanasiga teng "
              "bo'lishi kerak.",
        "ru": "Смена ищется по закреплённому за машиной водителю "
              "(`transport_vehicle.assigned_driver_id` -> "
              "`driver_shift.driver_id`), а `shift_date` должна совпадать с "
              "датой плана.",
        "en": "The shift is looked up by the vehicle's assigned driver "
              "(`transport_vehicle.assigned_driver_id` -> "
              "`driver_shift.driver_id`) and `shift_date` must match the plan "
              "date.",
    },
    "req.hazard.title": {
        "uz": "Xavfli yuk", "ru": "Опасный груз", "en": "Hazardous cargo",
    },
    "req.hazard.impact": {
        "uz": "Xavflilik aniqlanmaydi: sisterna talab qiladigan yuk oddiy "
              "mashinaga tushib qolishi mumkin.",
        "ru": "Опасность не определяется: груз, требующий цистерны, может "
              "попасть на обычную машину.",
        "en": "Hazard is not detected: cargo that needs a tanker may end up on "
              "an ordinary vehicle.",
    },
    "req.hazard.hint": {
        "uz": "Zanjir: `transport_request.wms_shipment_id` -> "
              "`shipment.hazard_profile_id` -> `hazard_profile`. Xavflilik "
              "so'rovda so'ralmaydi — u ayrim arizaga tegishli xususiyat.",
        "ru": "Цепочка: `transport_request.wms_shipment_id` -> "
              "`shipment.hazard_profile_id` -> `hazard_profile`. Опасность в "
              "запросе не спрашивается — это свойство отдельной заявки.",
        "en": "The chain: `transport_request.wms_shipment_id` -> "
              "`shipment.hazard_profile_id` -> `hazard_profile`. Hazard is not "
              "asked for in the request — it is a property of an individual "
              "request.",
    },
    "req.dock.title": {
        "uz": "Yuklash joyidagi slotlar",
        "ru": "Доки на пункте погрузки",
        "en": "Dock slots at the loading point",
    },
    "req.dock.impact": {
        "uz": "Navbat ogohlantirishi berilmaydi — bir joyga bir vaqtda nechta "
              "mashina kelayotgani tekshirilmaydi.",
        "ru": "Предупреждение об очереди не выдаётся — не проверяется, сколько "
              "машин приезжает в одно место одновременно.",
        "en": "No queue warning is issued — how many vehicles arrive at one "
              "place at the same time is not checked.",
    },
    "req.dock.hint": {
        "uz": "Bu QATTIQ CHEKLOV EMAS, ogohlantirish: `dock_slot` da ish vaqti "
              "ham, xizmat davomiyligi ham yo'q, shuning uchun faqat slotlar "
              "soni bilan solishtiriladi.",
        "ru": "Это НЕ ЖЁСТКОЕ ОГРАНИЧЕНИЕ, а предупреждение: в `dock_slot` нет "
              "ни рабочего времени, ни длительности обслуживания, поэтому "
              "сравнение идёт только по количеству доков.",
        "en": "This is NOT A HARD CONSTRAINT but a warning: `dock_slot` has "
              "neither working hours nor service duration, so only the number "
              "of slots is compared.",
    },
}
