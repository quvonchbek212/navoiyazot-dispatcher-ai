"""Javobdagi hamma matn — uch tilda (uz, ru, en).

NIMA UCHUN BU FAYL BOR. Javobning matn qismi — `data_quality.notes`,
`summary.worst` va shablon xulosasi — `service.py` va `explain.py` da
f-string bo'lib yozilgan edi va faqat o'zbekcha chiqardi.

BU MODUL AGENTGA HAM ISHLAYDI. `atil_agent` ning to'rt kuzatuvchisi
(`delayed`, `deviation`, `idle`, `document`) ro'yxatni shu moduldan
oladi va uning `data_quality.notes` ini xabarga qo'shadi. Shu izohlar
tarjimasiz qolgani uchun agent xabarida ruscha matn ichida o'zbekcha
jumla chiqib turardi — shu yerdagi tarjima o'sha teshikni yopadi.

KODLAR TARJIMA QILINMAYDI. `kind` (`NOT_DEPARTED`, `LATE_EN_ROUTE`),
`document_type`, `subject_type`, jadval va ustun nomlari uch tilda ham
bir xil qoladi: ularni dastur o'qiydi.
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

#: Qo'llab-quvvatlanadigan tillar — boshqa modullar bilan bir xil.
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

    # -------------------------------------------------------- Ro'yxat nomlari
    "kind.delayed": {
        "uz": "kechikayotgan reyslar", "ru": "опаздывающие рейсы",
        "en": "delayed trips"},
    "kind.deviations": {
        "uz": "yo'nalishdan og'ish", "ru": "отклонения от маршрута",
        "en": "route deviations"},
    "kind.idle": {
        "uz": "bekor turgan mashinalar", "ru": "простаивающие машины",
        "en": "idle vehicles"},
    "kind.documents": {
        "uz": "muddati tugayotgan hujjatlar", "ru": "истекающие документы",
        "en": "expiring documents"},

    #: `_limit_note` ichida ishlatiladi — "… ro'yxati qirqilgan".
    "what.delayed": {"uz": "kechikish", "ru": "опозданий", "en": "delays"},
    "what.deviation": {"uz": "og'ish", "ru": "отклонений", "en": "deviations"},
    "what.idle": {"uz": "bekor turish", "ru": "простоев", "en": "idling"},
    "what.document": {"uz": "hujjat", "ru": "документов", "en": "documents"},

    # ------------------------------------------------- data_quality.notes
    "note.limit": {
        "uz": "Chegaraga yetildi ({limit}) — {what} ro'yxati qirqilgan bo'lishi "
              "mumkin. `limit` ni oshiring yoki filtrni toraytiring",
        "ru": "Достигнут лимит ({limit}) — список {what} мог быть обрезан. "
              "Увеличьте `limit` или сузьте фильтр",
        "en": "The limit was reached ({limit}) — the list of {what} may have "
              "been truncated. Raise `limit` or narrow the filter",
    },
    "note.trip_empty": {
        "uz": "`trip` jadvali bo'sh — kechikish tekshirilmadi",
        "ru": "Таблица `trip` пуста — опоздания не проверялись",
        "en": "The `trip` table is empty — delays were not checked",
    },
    "note.no_trip_events": {
        "uz": "Kechikkan reyslarning hech birida `trip_event` yozuvi yo'q — "
              "reys qayerda to'xtab qolganini aytib bo'lmaydi",
        "ru": "Ни у одного опоздавшего рейса нет записей `trip_event` — "
              "невозможно сказать, где рейс остановился",
        "en": "None of the delayed trips has a `trip_event` record — it is "
              "impossible to say where the trip stopped",
    },
    "note.telemetry_deviation": {
        "uz": "`vehicle_telemetry_state` bo'sh — yo'nalishdan og'ish TEKSHIRILMADI. "
              "Bo'sh ro'yxat \"og'ish yo'q\" degani emas: GPS integratsiyasi ulanmagan",
        "ru": "`vehicle_telemetry_state` пуст — отклонения от маршрута НЕ "
              "ПРОВЕРЯЛИСЬ. Пустой список не означает «отклонений нет»: "
              "интеграция GPS не подключена",
        "en": "`vehicle_telemetry_state` is empty — route deviations were NOT "
              "CHECKED. An empty list does not mean \"no deviations\": the GPS "
              "integration is not connected",
    },
    "note.unmeasured_deviation": {
        "uz": "{count} ta mashinada yo'ldan chetlanish masofasi o'lchanmadi — "
              "marshrut nuqtalari yo'q (`route_points_json` va `route_point` "
              "bo'sh). Og'ish bayrog'ining o'zi ko'rsatilgan",
        "ru": "У {count} машин расстояние отклонения не измерено — нет точек "
              "маршрута (`route_points_json` и `route_point` пусты). Показан "
              "сам флаг отклонения",
        "en": "For {count} vehicle(s) the deviation distance was not measured — "
              "there are no route points (`route_points_json` and `route_point` "
              "are empty). Only the deviation flag itself is shown",
    },
    "note.telemetry_idle": {
        "uz": "`vehicle_telemetry_state` bo'sh — bekor turish TEKSHIRILMADI. "
              "Bo'sh ro'yxat \"hamma mashina ishlayapti\" degani emas",
        "ru": "`vehicle_telemetry_state` пуст — простои НЕ ПРОВЕРЯЛИСЬ. Пустой "
              "список не означает «все машины работают»",
        "en": "`vehicle_telemetry_state` is empty — idling was NOT CHECKED. An "
              "empty list does not mean \"every vehicle is working\"",
    },
    "note.unknown_engine": {
        "uz": "{count} ta mashinada dvigatel holati noma'lum (`last_engine_on` "
              "bo'sh) — yoqilg'i behuda yonayotganini aytib bo'lmaydi",
        "ru": "У {count} машин состояние двигателя неизвестно (`last_engine_on` "
              "пуст) — нельзя сказать, жжётся ли топливо впустую",
        "en": "For {count} vehicle(s) the engine state is unknown "
              "(`last_engine_on` is empty) — it cannot be said whether fuel is "
              "being burned for nothing",
    },
    "note.empty_document_sources": {
        "uz": "Bo'sh manbalar: {tables} — bu hujjat turlari TEKSHIRILMADI "
              "(mashina hujjatlari va sug'urta shu jadvallarda)",
        "ru": "Пустые источники: {tables} — эти виды документов НЕ ПРОВЕРЯЛИСЬ "
              "(документы машин и страховка хранятся в этих таблицах)",
        "en": "Empty sources: {tables} — these document types were NOT CHECKED "
              "(vehicle documents and insurance live in those tables)",
    },
    "note.daily_inspections": {
        "uz": "Kunlik ko'riklar (`medical_inspection`, "
              "`vehicle_technical_inspection`) bu ro'yxatga ATAYLAB kirmaydi: "
              "ular har kuni yangilanadi va \"ertaga tugaydi\" holati normal. "
              "Reysga tayyorlikni `/vehicle-selection/rank` tekshiradi",
        "ru": "Ежедневные осмотры (`medical_inspection`, "
              "`vehicle_technical_inspection`) в этот список НАМЕРЕННО не "
              "входят: они обновляются каждый день и состояние «истекает "
              "завтра» для них нормально. Готовность к рейсу проверяет "
              "`/vehicle-selection/rank`",
        "en": "Daily inspections (`medical_inspection`, "
              "`vehicle_technical_inspection`) are DELIBERATELY excluded from "
              "this list: they are renewed every day, so \"expires tomorrow\" is "
              "normal for them. Readiness for a trip is checked by "
              "`/vehicle-selection/rank`",
    },

    # ---------------------------------------------------- summary.worst
    "worst.delayed": {
        "uz": "{trip} — {hours} soat ({kind})",
        "ru": "{trip} — {hours} ч ({kind})",
        "en": "{trip} — {hours} h ({kind})",
    },
    "delay.not_departed": {
        "uz": "jo'namagan", "ru": "не выехал", "en": "not departed"},
    "delay.en_route": {"uz": "yo'lda", "ru": "в пути", "en": "en route"},
    "worst.deviation": {
        "uz": "{who} — yo'ldan {km} km chetda",
        "ru": "{who} — в {km} км от маршрута",
        "en": "{who} — {km} km off the route",
    },
    "worst.deviation_unmeasured": {
        "uz": "{who} — og'ish belgilangan (masofa o'lchanmadi)",
        "ru": "{who} — отклонение отмечено (расстояние не измерено)",
        "en": "{who} — deviation flagged (distance not measured)",
    },
    "worst.idle": {
        "uz": "{who} — {hours} soat turibdi{engine}",
        "ru": "{who} — простаивает {hours} ч{engine}",
        "en": "{who} — standing for {hours} h{engine}",
    },
    "worst.idle_engine": {
        "uz": ", dvigatel ishlab turgan", "ru": ", двигатель работает",
        "en": ", the engine is running"},
    "worst.document_expired": {
        "uz": "{who} — {type} muddati {days} kun oldin o'tgan",
        "ru": "{who} — {type}: срок истёк {days} дн. назад",
        "en": "{who} — {type}: expired {days} day(s) ago",
    },
    "worst.document_expires": {
        "uz": "{who} — {type} {days} kundan keyin tugaydi",
        "ru": "{who} — {type}: истекает через {days} дн.",
        "en": "{who} — {type}: expires in {days} day(s)",
    },

    # ------------------------------------------------- Shablon xulosasi
    "analysis.blocked": {
        "uz": "Ro'yxat bo'sh, lekin bu \"muammo yo'q\" degani EMAS: {source} "
              "bo'lgani uchun {label} umuman tekshirilmadi.",
        "ru": "Список пуст, но это НЕ значит «проблем нет»: {label} вообще не "
              "проверялись, потому что {source}.",
        "en": "The list is empty, but that does NOT mean \"no problems\": "
              "{label} were not checked at all because {source}.",
    },
    "analysis.nothing": {
        "uz": "Hozircha {label} topilmadi.",
        "ru": "Пока {label} не найдено.",
        "en": "No {label} found so far.",
    },
    "analysis.expired": {
        "uz": "{count} ta hujjat muddati O'TGAN — ular bilan reysga chiqib "
              "bo'lmaydi.",
        "ru": "У {count} документов срок ИСТЁК — с ними выезжать в рейс нельзя.",
        "en": "{count} document(s) have EXPIRED — a trip cannot be made with them.",
    },
    "analysis.no_expired": {
        "uz": "Muddati o'tgan hujjat yo'q.",
        "ru": "Просроченных документов нет.",
        "en": "There are no expired documents.",
    },
    "analysis.documents_total": {
        "uz": "Jami {count} ta hujjat ko'rib chiqildi.",
        "ru": "Всего рассмотрено {count} документов.",
        "en": "{count} document(s) were reviewed in total.",
    },
    "analysis.found": {
        "uz": "{count} ta {label} topildi.",
        "ru": "Найдено {count} {label}.",
        "en": "{count} {label} found.",
    },
    "analysis.worst": {
        "uz": "Eng og'iri — {worst}.",
        "ru": "Самое серьёзное — {worst}.",
        "en": "The most serious one — {worst}.",
    },
    "analysis.by_kind": {
        "uz": "Taqsimot — {parts}.",
        "ru": "Распределение — {parts}.",
        "en": "Breakdown — {parts}.",
    },
    "analysis.attention": {
        "uz": "DIQQAT: {note}", "ru": "ВНИМАНИЕ: {note}", "en": "NOTE: {note}",
    },
}


#: `data_quality.notes` ichida "tekshirilmadi" degan izohni topish uchun.
#: Til bo'yicha o'zgargani sababli kalit so'z ham uch tilda kerak —
#: ilgari kod faqat o'zbekcha "TEKSHIRILMADI" ni qidirardi va ruscha
#: javobda hech narsa topmasdi.
UNCHECKED_MARKERS = ("TEKSHIRILMADI", "НЕ ПРОВЕРЯЛИСЬ", "NOT CHECKED")


def is_unchecked(note: str) -> bool:
    """Izoh "bu qism umuman tekshirilmadi" deyaptimi."""
    upper = (note or "").upper()
    return any(marker in upper for marker in UNCHECKED_MARKERS)
