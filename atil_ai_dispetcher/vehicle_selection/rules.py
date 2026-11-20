"""Tanlash qoidalari — sof arifmetika, bazasiz sinaladi.

BU FAYLDA BIRORTA HAM O'YLAB TOPILGAN CHEGARA YO'Q. Har bir qoida yo
solishtirishning o'zi, yo bazadagi qiymatdan kelib chiqadi:

    yuk og'irligi > mashina sig'imi        ko'tara olmaydi  (chegara kerak emas)
    talab kategoriyasi ∉ haydovchi toifasi mumkin emas      (chegara kerak emas)
    guvohnoma muddati < jo'nash sanasi     amal qilmaydi    (chegara kerak emas)
    bloklovchi remont ochiq                chiqa olmaydi    (chegara kerak emas)
    aktiv reys bor                         band             (chegara kerak emas)

"50 km uzoq", "30 kun qolgani xavfli" kabi raqamlar YO'Q. Uzoqlik va muddat
NISBIY baholanadi: nomzodlar bir-biri bilan solishtiriladi (`ranker.py`
normalizatsiyasi). Shu sababli bu yerdagi ba'zi mezonlar `score` emas,
`value` qaytaradi.

IKKI QATLAM:
  * `blockers` — umuman mumkin emas. Qonuniy yoki fizik cheklov. Juftlik
    ro'yxatga tushmaydi (yoki `include_blocked` bilan sababi ko'rsatiladi).
  * `score`    — 0..1 oralig'idagi ball yoki `null`.

`null` NOLGA AYLANTIRILMAYDI. Sig'imi noma'lum mashina "sig'imi yomon"
degani emas. Ma'lumoti yo'q mezon reytingdan chiqariladi va og'irligi qolgan
mezonlarga qayta taqsimlanadi (`ranker.py`).
"""

from __future__ import annotations

from atil_ai_dispetcher.vehicle_selection import labels, texts
from atil_ai_dispetcher.vehicle_selection.texts import t

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# ---------------------------------------------------------------- Kesish kodlari

#: Kod -> o'zbekcha sabab. Javobda kod ham, matn ham qaytadi: kodni dastur
#: o'qiydi, matnni odam.
#: Kesish sabablarining KODLARI. Matni `texts.py` da uch tilda
#: (`blocker.<KOD>`) — bu yerda faqat ro'yxat qoladi, chunki
#: `blockers[].code` javobda tarjima qilinmaydi.
BLOCKER_CODES = (
    # Haydovchi
    "LICENSE_EXPIRED", "LICENSE_CATEGORY_MISMATCH", "NOT_EMPLOYED",
    "MEDICAL_UNFIT", "MEDICAL_MISSING", "MEDICAL_CERT_EXPIRED",
    "SHIFT_OFF", "DRIVER_BUSY_TRIP", "DRIVER_BUSY_WAYBILL",
    # Mashina
    "VEHICLE_STATUS_BLOCKED", "BLOCKING_REPAIR", "INSPECTION_BLOCKED",
    "TYPE_MISMATCH", "DOCUMENT_EXPIRED", "INSURANCE_EXPIRED",
    "CAPACITY_INSUFFICIENT", "MAINTENANCE_OVERDUE",
    "VEHICLE_BUSY_TRIP", "VEHICLE_BUSY_WAYBILL",
)

#: Uch pog'onali `vehicle_technical_inspection.status` enum'i teng oraliqqa
#: joylandi. BU CHEGARA EMAS — tartibli (ordinal) enum'ning tabiiy raqamli
#: ifodasi: FIT > LIMITED > BLOCKED. BLOCKED baribir kesiladi.
INSPECTION_FACTOR = {"FIT": 1.0, "LIMITED": 0.5, "BLOCKED": 0.0}

#: `maintenance_plan.status` ham shunday tartibli enum.
MAINTENANCE_FACTOR = {
    "PLANNED": 1.0, "ACTIVE": 1.0, "COMPLETED": 1.0, "PAUSED": 1.0,
    "DUE_SOON": 0.5, "OVERDUE": 0.0,
}

#: Yer radiusi (km) — haversine uchun. Fizik doimiy, sozlanmaydi.
EARTH_RADIUS_KM = 6371.0088


@dataclass
class Criterion:
    """Bitta mezon natijasi.

    `score` — 0..1 yoki `None`. `None` ikki xil ma'noda bo'lishi mumkin va
    ikkalasi ham `detail` da ochiq yoziladi:
      * ma'lumot yo'q (`normalize is None`);
      * ball nisbiy, `ranker.py` da nomzodlar solishtirilib hisoblanadi
        (`normalize` to'ldirilgan).
    """

    name: str
    score: float | None = None
    value: float | None = None
    unit: str | None = None
    detail: str = ""
    normalize: str | None = None  # None | "higher_better" | "lower_better"

    @property
    def has_data(self) -> bool:
        return self.score is not None or (self.normalize and self.value is not None)


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki koordinata orasidagi katta doira masofasi, km.

    Yo'l masofasi EMAS, to'g'ri chiziq. Bu farq `detail` da aytiladi:
    haqiqiy yo'l uzunroq bo'ladi, lekin nomzodlarni bir-biri bilan
    solishtirish uchun to'g'ri chiziq ham yetarli tartib beradi.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


# ============================================================== 1. SIG'IM


def capacity(
    vehicle: dict[str, Any],
    demand: dict[str, Any],
    lang: str = texts.DEFAULT_LANG,
) -> tuple[Criterion, list[str]]:
    """Sig'im: yuk mashinaga sig'adimi va qanchalik to'liq foydalaniladi.

    BALL = FOYDALANISH ULUSHI (talab / sig'im). 20 tonnalik mashinaga 1
    tonna yuk ortish — mumkin, lekin isrof; 18 tonna ortish — mos. Shuning
    uchun eng yuqori ball sig'imi eng katta mashinaga emas, yukka eng
    YAQIN mashinaga beriladi. Bu o'ylab topilgan qoida emas, nisbatning
    o'zi.

    Uch o'lcham (og'irlik, hajm, o'rindiq) alohida tekshiriladi va ULARDAN
    ENG KATTASI olinadi: cheklovchi o'lcham qaysi biri bo'lsa, mashina
    to'lganini o'sha belgilaydi.
    """
    pairs = (
        ("cap.dim.weight", _num(demand.get("cargo_weight_kg")),
         _num(vehicle.get("payload_capacity_kg")), "kg"),
        ("cap.dim.volume", _num(demand.get("cargo_volume_m3")),
         _num(vehicle.get("volume_m3")), "m3"),
        ("cap.dim.seats", _num(demand.get("passengers")),
         _num(vehicle.get("seat_count")), ""),
    )

    ratios: list[float] = []
    details: list[str] = []
    blockers: list[str] = []
    missing: list[str] = []

    for dim_key, need, have, unit in pairs:
        nomi = t(lang, dim_key)
        if need is None:
            continue
        if have is None or have <= 0:
            missing.append(nomi)
            continue
        if need > have:
            blockers.append("CAPACITY_INSUFFICIENT")
            details.append(t(lang, "cap.insufficient", dim=nomi,
                             need=f"{need:g}", have=f"{have:g}", unit=unit))
            continue
        ratios.append(need / have)
        details.append(t(lang, "cap.ratio", dim=nomi, need=f"{need:g}",
                         have=f"{have:g}", unit=unit,
                         percent=f"{need / have:.0%}"))

    if blockers:
        return Criterion("capacity", score=0.0, detail="; ".join(details)), blockers

    if ratios:
        return Criterion(
            "capacity",
            score=max(ratios),
            value=max(ratios),
            unit=t(lang, "unit.share"),
            detail="; ".join(details),
        ), []

    # Ma'lumot yo'q — ikki sabab bo'lishi mumkin, ikkalasi ham aytiladi.
    if missing:
        reason = t(lang, "cap.reason_vehicle", dims=", ".join(missing))
    else:
        reason = t(lang, "cap.reason_demand")
    return Criterion(
        "capacity", detail=t(lang, "misc.not_rated", reason=reason)), []


# ============================================================== 2. MASOFA


def distance(
    vehicle: dict[str, Any],
    demand: dict[str, Any],
    lang: str = texts.DEFAULT_LANG,
) -> tuple[Criterion, list[str]]:
    """Masofa: mashina yuklash nuqtasiga qanchalik yaqin.

    BALL BU YERDA HISOBLANMAYDI — faqat km o'lchanadi. "Necha km uzoq
    hisoblanadi" degan savolga bazadagi hech narsa javob bermaydi, shuning
    uchun ball nomzodlarni bir-biri bilan solishtirib chiqariladi
    (`ranker.py`, `lower_better`): eng yaqini 1, eng uzog'i 0.

    Yaqinlik uzoqlik bilan KESILMAYDI: 300 km dagi mashina ham variant
    bo'lishi mumkin, faqat pastroq ballda.
    """
    v_lat, v_lon = _num(vehicle.get("last_latitude")), _num(vehicle.get("last_longitude"))
    d_lat, d_lon = _num(demand.get("origin_latitude")), _num(demand.get("origin_longitude"))

    if v_lat is None or v_lon is None:
        return Criterion("distance", detail=t(
            lang, "misc.not_rated",
            reason=t(lang, "dist.no_vehicle_position"))), []
    if d_lat is None or d_lon is None:
        return Criterion("distance", detail=t(
            lang, "misc.not_rated", reason=t(lang, "dist.no_pickup"))), []

    km = haversine_km(v_lat, v_lon, d_lat, d_lon)
    seen_at = vehicle.get("position_at")
    stamp = t(lang, "dist.stamp", at=seen_at) if seen_at else ""
    return Criterion(
        "distance",
        value=km,
        unit="km",
        normalize="lower_better",
        detail=t(lang, "dist.value", km=f"{km:.1f}", stamp=stamp),
    ), []


# ============================================================== 3. HUJJAT


#: Hujjat tekshiruvi natijasi: (muddatlar, kesish kodlari, izohlar).
#: Mashina va haydovchi ALOHIDA tekshiriladi — shunda juftlik yasashdan
#: OLDIN kesish mumkin bo'ladi. Ball esa ikkalasini birlashtirib chiqadi:
#: reysni eng erta tugaydigan hujjat to'xtatadi, u kimniki bo'lishidan
#: qat'i nazar.
DocumentCheck = tuple[list[date], list[str], list[str]]


def vehicle_documents(
    vehicle: dict[str, Any], *, on_date: date, lang: str = texts.DEFAULT_LANG
) -> DocumentCheck:
    """Mashina hujjatlari jo'nash kuniga amal qiladimi.

    MUDDATI O'TGANI — KESISH. Bu chegara emas, sananing o'zi bilan
    solishtirish.
    """
    deadlines: list[date] = []
    blockers: list[str] = []
    details: list[str] = []

    expired = int(vehicle.get("documents_expired") or 0)
    total = int(vehicle.get("documents_total") or 0)
    if expired:
        blockers.append("DOCUMENT_EXPIRED")
        details.append(t(lang, "doc.vehicle_expired", count=expired))

    doc_min = _to_date(vehicle.get("document_min_expiry"))
    if doc_min is not None and doc_min >= on_date:
        deadlines.append(doc_min)
        details.append(t(lang, "doc.vehicle_until", date=doc_min))
    elif total == 0:
        details.append(t(lang, "doc.vehicle_none"))

    ins = _to_date(vehicle.get("insurance_valid_to"))
    if ins is not None:
        if ins < on_date:
            blockers.append("INSURANCE_EXPIRED")
            details.append(t(lang, "doc.insurance_expired", date=ins))
        else:
            deadlines.append(ins)
            details.append(t(lang, "doc.insurance_until", date=ins))

    return deadlines, blockers, details


def driver_documents(
    driver: dict[str, Any], *, on_date: date, lang: str = texts.DEFAULT_LANG
) -> DocumentCheck:
    """Haydovchi hujjatlari jo'nash kuniga amal qiladimi."""
    deadlines: list[date] = []
    blockers: list[str] = []
    details: list[str] = []

    lic = _to_date(driver.get("license_valid_until"))
    if lic is not None:
        if lic < on_date:
            blockers.append("LICENSE_EXPIRED")
            details.append(t(lang, "doc.license_expired", date=lic))
        else:
            deadlines.append(lic)
            details.append(t(lang, "doc.license_until", date=lic))

    med = _to_date(driver.get("medical_certificate_valid_until"))
    if med is not None:
        if med < on_date:
            blockers.append("MEDICAL_CERT_EXPIRED")
            details.append(t(lang, "doc.medical_expired", date=med))
        else:
            deadlines.append(med)
            details.append(t(lang, "doc.medical_until", date=med))

    return deadlines, blockers, details


def documents(
    vehicle_check: DocumentCheck,
    driver_check: DocumentCheck,
    *,
    on_date: date,
    lang: str = texts.DEFAULT_LANG,
) -> tuple[Criterion, list[str]]:
    """Hujjat mezoni — mashina va haydovchi tekshiruvlarini birlashtiradi.

    BALL — eng erta tugaydigan muddatgacha qolgan kun, NISBIY baholanadi
    (`higher_better`). "30 kun qolsa xavfli" degan raqam yo'q: nomzodlar
    orasida muddati uzoqrog'i yuqoriroq ball oladi, xolos.
    """
    deadlines = [*vehicle_check[0], *driver_check[0]]
    blockers = [*vehicle_check[1], *driver_check[1]]
    details = [*vehicle_check[2], *driver_check[2]]

    if blockers:
        return Criterion("documents", score=0.0, detail="; ".join(details)), blockers

    if not deadlines:
        return Criterion("documents", detail=t(
            lang, "misc.not_rated", reason=t(lang, "doc.no_validity"))), []

    days_left = (min(deadlines) - on_date).days
    return Criterion(
        "documents",
        value=float(days_left),
        unit=t(lang, "unit.days"),
        normalize="higher_better",
        detail=t(lang, "doc.days_left",
                 days=days_left, details="; ".join(details)),
    ), []


# ============================================================== 4. SMENA


def shift(
    driver: dict[str, Any],
    *,
    window_from: datetime | None,
    window_to: datetime | None,
    lang: str = texts.DEFAULT_LANG,
) -> tuple[Criterion, list[str]]:
    """Smena: haydovchi jo'nash vaqtida ish smenasida bormi.

    DAM OLISH/TA'TIL/KASALLIK — KESISH: bu kunlarda haydovchi ishlamaydi.

    BALL = smena reys oynasining qanchasini qoplashi. Oyna to'liq smena
    ichida bo'lsa 1.0, yarmi tushsa 0.5. Bu nisbatning o'zi, o'ylab
    topilgan pog'ona emas.

    Oyna berilmagan bo'lsa: smena bor — 1.0, yo'q — `null`.
    """
    shift_type = driver.get("shift_type")
    shift_status = driver.get("shift_status")
    tur = labels.label("shift_type", shift_type, lang)

    if shift_type in ("DAY_OFF", "VACATION", "SICK_LEAVE"):
        return (
            Criterion("shift", score=0.0,
                      detail=t(lang, "shift.type", type=tur)),
            ["SHIFT_OFF"],
        )

    if shift_type is None:
        return Criterion("shift", detail=t(
            lang, "misc.not_rated", reason=t(lang, "shift.no_record"))), []

    if shift_status == "CANCELLED":
        return Criterion(
            "shift", score=0.0, detail=t(lang, "shift.cancelled")
        ), []

    start = driver.get("planned_start_at")
    end = driver.get("planned_end_at")

    if window_from is None or window_to is None or start is None or end is None:
        return Criterion(
            "shift",
            score=1.0,
            detail=t(lang, "shift.no_window", type=tur,
                     status=labels.label("shift_status", shift_status, lang)),
        ), []

    # Oyna va smenaning kesishgan qismi
    overlap_start = max(_naive(window_from), _naive(start))
    overlap_end = min(_naive(window_to), _naive(end))
    window_seconds = (_naive(window_to) - _naive(window_from)).total_seconds()
    overlap_seconds = max(0.0, (overlap_end - overlap_start).total_seconds())

    if window_seconds <= 0:
        return Criterion(
            "shift", score=1.0,
            detail=t(lang, "shift.zero_window", type=tur)
        ), []

    covered = min(1.0, overlap_seconds / window_seconds)
    return Criterion(
        "shift",
        score=covered,
        value=covered,
        unit=t(lang, "unit.share"),
        detail=t(lang, "shift.covers", type=tur, start=start, end=end,
                 percent=f"{covered:.0%}"),
    ), []


def _naive(value: Any) -> datetime:
    """Vaqt mintaqasi bor/yo'q qiymatlarni solishtirish uchun bir xillashtirish.

    `driver_shift.planned_start_at` — `timestamptz`, so'rovdagi vaqt esa
    mintaqasiz kelishi mumkin. Ularni to'g'ridan-to'g'ri solishtirish
    `TypeError` beradi.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    return datetime.fromisoformat(str(value)).replace(tzinfo=None)


# ============================================================== 5. MALAKA


def skill(
    driver: dict[str, Any],
    demand: dict[str, Any],
    lang: str = texts.DEFAULT_LANG,
) -> tuple[Criterion, list[str]]:
    """Malaka: toifa mosligi, tajriba va xavfsizlik tarixi.

    TOIFA MOS KELMASA — KESISH. Bu qonuniy talab: `route` da
    `required_driver_category` NOT NULL va u haydovchining
    `driver_license_category` ro'yxatida bo'lishi shart.

    BALL ikki o'lchangan qismdan quriladi:
        tajriba     — tugatilgan reyslar soni (nisbiy, `higher_better`)
        tozalik     — tugatilgan / (tugatilgan + hodisalar)
    Ikkalasi KO'PAYTIRILADI: 5 reysdan 5 tasi toza — 1.0, 5 dan 3 tasi
    toza — 0.6. Bu nisbatning o'zi, jarima balli o'ylab topilmagan.

    Ko'paytuvchi `ranker.py` ga `value` orqali beriladi: tajriba nisbiy
    baholanadi, tozalik esa unga ko'paytiriladi (`skill_multiplier`).
    """
    required = demand.get("required_driver_category")
    have = list(driver.get("license_categories") or [])
    details: list[str] = []

    if required:
        if required not in have:
            return (
                Criterion(
                    "skill",
                    score=0.0,
                    detail=t(lang, "skill.category_mismatch",
                             required=required,
                             have=", ".join(have) or t(lang, "skill.none")),
                ),
                ["LICENSE_CATEGORY_MISMATCH"],
            )
        details.append(t(lang, "skill.category_ok", required=required))
    else:
        details.append(t(lang, "skill.no_category_required"))

    # Tajriba: `trip` dan hisoblangani ishonchliroq — `driver_completed_trip`
    # 22.08.2026 da bo'sh edi, `trip` da esa 29 ta tugagan reys bor.
    completed = int(driver.get("completed_trips") or 0)
    logged = int(driver.get("completed_trips_logged") or 0)
    trips = max(completed, logged)

    incidents = (
        int(driver.get("recent_speed_violations") or 0)
        + int(driver.get("recent_incidents") or 0)
        + int(driver.get("recent_accidents") or 0)
    )

    if trips == 0 and incidents == 0:
        return Criterion(
            "skill",
            detail=t(lang, "skill.no_history", details="; ".join(details)),
        ), []

    clean = trips / (trips + incidents) if (trips + incidents) else 1.0
    details.append(t(lang, "skill.history", trips=trips, incidents=incidents,
                     clean=f"{clean:.0%}"))

    return Criterion(
        "skill",
        value=float(trips) * clean,
        unit=t(lang, "unit.clean_trips"),
        normalize="higher_better",
        detail="; ".join(details),
    ), []


# ============================================================== 6. TEXNIK HOLAT


def technical(
    vehicle: dict[str, Any], *, on_date: date, lang: str = texts.DEFAULT_LANG
) -> tuple[Criterion, list[str]]:
    """Texnik holat: mashina yo'lga yaroqlimi.

    KESISH: holati BLOCKED/IN_MAINTENANCE/DECOMMISSIONED, chiqishni
    to'suvchi remont ochiq, yoki oxirgi texnik ko'rik BLOCKED bergan.

    BALL — uchta mustaqil ko'paytuvchi:
        ko'rik    — FIT 1.0 / LIMITED 0.5   (tartibli enum, chegara emas)
        xizmat    — OVERDUE 0.0 / DUE_SOON 0.5 / qolgani 1.0
        remont    — 1/(1+ochiq_remontlar)   (arifmetik pasayish)
    Noma'lum ko'paytuvchi TASHLAB KETILADI, nolga aylantirilmaydi.
    Uchalasi ham noma'lum bo'lsa mezon `null`.
    """
    blockers: list[str] = []
    details: list[str] = []
    factors: list[float] = []

    status = vehicle.get("current_status")
    if status in ("IN_MAINTENANCE", "BLOCKED", "DECOMMISSIONED"):
        blockers.append("VEHICLE_STATUS_BLOCKED")
        details.append(t(lang, "tech.status",
                         status=labels.label("vehicle_status", status, lang)))

    blocking = int(vehicle.get("blocking_repairs") or 0)
    if blocking:
        blockers.append("BLOCKING_REPAIR")
        details.append(t(lang, "tech.blocking_repairs", count=blocking))

    inspection = vehicle.get("last_inspection_status")
    if inspection == "BLOCKED":
        blockers.append("INSPECTION_BLOCKED")
    if inspection in INSPECTION_FACTOR:
        factors.append(INSPECTION_FACTOR[inspection])
        seen = _to_date(vehicle.get("last_inspection_at"))
        age = (t(lang, "tech.inspection_age", days=(on_date - seen).days)
               if seen else "")
        details.append(t(
            lang, "tech.inspection",
            status=labels.label("inspection", inspection, lang), age=age))
    else:
        details.append(t(lang, "tech.no_inspection"))

    maintenance = vehicle.get("maintenance_status")
    if maintenance in MAINTENANCE_FACTOR:
        factors.append(MAINTENANCE_FACTOR[maintenance])
        details.append(t(
            lang, "tech.maintenance",
            status=labels.label("maintenance", maintenance, lang)))
        if maintenance == "OVERDUE":
            blockers.append("MAINTENANCE_OVERDUE")

    open_repairs = int(vehicle.get("open_repairs") or 0)
    if open_repairs:
        factors.append(1.0 / (1.0 + open_repairs))
        details.append(t(lang, "tech.open_repairs", count=open_repairs))

    if blockers:
        return Criterion("technical", score=0.0, detail="; ".join(details)), blockers

    if not factors:
        return Criterion("technical", detail=t(
            lang, "misc.not_rated", reason=t(lang, "tech.no_records"))), []

    score = 1.0
    for f in factors:
        score *= f
    return Criterion(
        "technical", score=score, value=score,
        detail="; ".join(details) or t(lang, "tech.ok")
    ), []


# ====================================================== Bandlik va ish holati


def vehicle_availability(
    vehicle: dict[str, Any], lang: str = texts.DEFAULT_LANG
) -> tuple[list[str], list[str]]:
    """Mashina bandmi — mezon emas, KESISH.

    Bandlik BAYROQDAN emas, hodisa jadvallaridan olinadi (sababi
    `queries.py` da yozilgan: `current_status` yangilanmayapti).
    `trip` va `waybill` ning BIRLASHMASI: bittasi band desa band.

    Qaytadi: (kesish kodlari, izohlar).
    """
    blockers: list[str] = []
    notes: list[str] = []

    if vehicle.get("busy_trip_id"):
        blockers.append("VEHICLE_BUSY_TRIP")
        notes.append(t(lang, "av.vehicle_trip", id=vehicle["busy_trip_id"]))
    if vehicle.get("open_waybill_number"):
        blockers.append("VEHICLE_BUSY_WAYBILL")
        notes.append(t(lang, "av.vehicle_waybill",
                       number=vehicle["open_waybill_number"]))

    return blockers, notes


def driver_availability(
    driver: dict[str, Any],
    *,
    on_date: date,
    require_medical: bool,
    lang: str = texts.DEFAULT_LANG,
) -> tuple[list[str], list[str]]:
    """Haydovchi bandmi va ishga yaroqlimi — mezon emas, KESISH.

    Tibbiy ko'rik `medical_inspection` JADVALIDAN olinadi,
    `driver.medical_cleared_today` BAYROG'IDAN emas: 22.08.2026 da bayroq
    92 ta haydovchida `true` bo'lgani holda jadvalda o'sha kunga FIT
    ko'rik atigi 27 ta edi.

    Qaytadi: (kesish kodlari, izohlar).
    """
    blockers: list[str] = []
    notes: list[str] = []

    if driver.get("busy_trip_id"):
        blockers.append("DRIVER_BUSY_TRIP")
        notes.append(t(lang, "av.driver_trip", id=driver["busy_trip_id"]))
    if driver.get("open_waybill_number"):
        blockers.append("DRIVER_BUSY_WAYBILL")
        notes.append(t(lang, "av.driver_waybill",
                       number=driver["open_waybill_number"]))
    if driver.get("employment_status") != "ACTIVE":
        blockers.append("NOT_EMPLOYED")
        notes.append(t(lang, "av.employment", status=labels.label(
            "employment", driver.get("employment_status"), lang)))

    med_status = driver.get("medical_status")
    med_date = _to_date(driver.get("medical_shift_date"))
    if med_status == "UNFIT" and med_date == on_date:
        blockers.append("MEDICAL_UNFIT")
        notes.append(t(lang, "av.medical_unfit", date=med_date,
                       status=labels.label("medical", med_status, lang)))
    elif require_medical and (med_date != on_date or med_status != "FIT"):
        blockers.append("MEDICAL_MISSING")
        notes.append(t(
            lang, "av.medical_missing", date=on_date,
            last=med_date or t(lang, "av.medical_none"),
            status=labels.label("medical", med_status, lang) if med_status else "-",
        ))

    return blockers, notes


def type_blockers(vehicle: dict[str, Any], demand: dict[str, Any]) -> list[str]:
    """Transport turi talabga mos kelmasa — kesish."""
    required = demand.get("required_transport_type")
    if required and vehicle.get("transport_type") != required:
        return ["TYPE_MISMATCH"]
    return []


def blocker_text(code: str, lang: str = texts.DEFAULT_LANG) -> str:
    """Kesish sababining tanlangan tildagi matni.

    Noma'lum kod KODNING O'ZI bo'lib qaytadi — matn o'ylab topilmaydi.
    """
    key = f"blocker.{code}"
    return t(lang, key) if key in texts.MESSAGES else code
