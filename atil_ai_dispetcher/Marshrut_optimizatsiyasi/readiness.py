"""Baza rejalashtirishga tayyormi — va tayyor bo'lmasa NIMA TO'LDIRILSIN.

NIMA UCHUN BU FAYL BOR. Modul bugun bazadan reja tuza olmaydi: arizalarda
koordinata yo'q, `vehicle_telemetry_state` bo'sh, `payload_capacity_kg`
to'ldirilmagan. Bunday holatda javob "reja chiqmadi" deb turishi mumkin
edi va ATIL tomonidagi odam NIMANI to'ldirish kerakligini taxmin qilib
o'tirardi.

Shuning uchun javobda `data_quality.requirements` bor: har bir talab
uchun QAYSI JADVAL, QAYSI USTUN kerakligi, hozir u yerda nechta yaroqli
qator borligi va to'lmasa REJAGA NIMA BO'LISHI yozilgan. Ma'lumot
kiritilgan sari `ready` o'zi `true` ga aylanadi — KOD O'ZGARMAYDI.

IKKI DARAJA:

    blocking=true   busiz reja UMUMAN chiqmaydi
    blocking=false  reja chiqadi, lekin bir cheklov tekshirilmay qoladi
                    (masalan sig'im yoki vaqt oynasi)

MANBALAR ZANJIR BO'LIB YOZILADI. Koordinata uch joydan kelishi mumkin
(`transport_request_point` -> `transport_request` -> `reference_data`) va
ULARDAN BITTASI yetadi. Shuning uchun `sources` ro'yxati kod qaraydigan
TARTIBDA turadi va talab `ready` bo'lishi uchun bittasining to'lishi
kifoya. Sig'im esa boshqacha: mashinada ham, arizada ham raqam bo'lishi
SHART — u yerda ikkala manba ham talab qilinadi.

MATN SHU YERDA YOZILMAYDI. `title`, `impact` va `hint` — uch tilda
(`texts.py`), bu yerda faqat KALIT turadi. Jadval va ustun nomlari esa
tarjima qilinmaydi: ular bazadagi aniq identifikatorlar.

RAQAMLAR SHU YERDA O'YLAB TOPILMAYDI. `usable_rows` — `queries.py` dagi
haqiqiy `fetch_*` shartlari bo'yicha sanalgan qator soni; kalibrovka
talablarida esa `ready` ni snapshot emas, KALIBROVKANING O'ZI hal qiladi
(o'lchov fizik filtrdan o'tmasligi mumkin) va farqi `note` da yoziladi.
"""

from __future__ import annotations

from typing import Any, Sequence

from atil_ai_dispetcher.Marshrut_optimizatsiyasi import config, queries, texts
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.calibration import Calibration
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.texts import t


def _source(
    table: str,
    columns: Sequence[str],
    *,
    rows: int,
    usable: int,
    need: int = 1,
    ready: bool | None = None,
) -> dict[str, Any]:
    """Bitta jadval-manba: jami qator, yaroqli qator, yetadimi.

    `ready` odatda `usable >= need` dan chiqadi. Lekin manba ZANJIRNING
    BIR HALQASI bo'lsa (masalan `transport_vehicle.branch_id` faqat
    BRANCHES katalogi bilan birga ishlaydi) uni tashqaridan berish
    kerak — aks holda javobda `ready: true` manba `ready: false`
    talabning ichida turib, o'qiyotgan odamni chalg'itadi.
    """
    return {
        "table": table,
        "columns": list(columns),
        "rows": int(rows),
        "usable_rows": int(usable),
        "ready": (int(usable) >= int(need)) if ready is None else bool(ready),
    }


def _need(
    key: str,
    *,
    lang: str,
    blocking: bool,
    sources: list[dict[str, Any]],
    match: str = "any",
    ready: bool | None = None,
    note: str = "",
    **hint_kwargs: Any,
) -> dict[str, Any]:
    """Bitta talab. Matni `texts.py` dan `req.<kalit>.*` bo'yicha olinadi.

    `match="any"` — manbalardan bittasi yetadi (zanjir).
    `match="all"` — hamma manba kerak.
    `ready` berilsa manbalar emas, SHU qiymat hal qiladi: kalibrovka
    talablarida haqiqiy o'lchov natijasi manbadagi qator sonidan
    ishonchliroq.
    """
    if ready is None:
        ok = [s["ready"] for s in sources]
        ready = all(ok) if match == "all" else any(ok)
    return {
        "need": key,
        "title": t(lang, f"req.{key}.title"),
        "blocking": blocking,
        "ready": bool(ready),
        "impact": t(lang, f"req.{key}.impact"),
        "sources": sources,
        "hint": t(lang, f"req.{key}.hint", **hint_kwargs),
        "note": note,
    }


#: Talab kaliti -> `texts.py` dagi matn kaliti. Ikkisi bir xil emas:
#: `need` javobda turadigan barqaror kod, matn kaliti esa qisqartma.
_TEXT_KEY = {
    "requests": "requests",
    "request_coordinates": "coords",
    "vehicles": "vehicles",
    "vehicle_start_point": "start",
    "speed": "speed",
    "road_factor": "road",
    "service_time": "service",
    "capacity": "capacity",
    "busy_windows": "busy",
    "driver_shift": "shift",
    "hazard": "hazard",
    "dock": "dock",
}


def build(
    snapshot: dict[str, int],
    cal: Calibration,
    *,
    depot_given: bool,
    statuses: Sequence[str],
    lang: str = texts.DEFAULT_LANG,
) -> tuple[bool, list[dict[str, Any]]]:
    """Talablar ro'yxatini yig'adi.

    Qaytadi: (`ready`, `requirements`). `ready` — BLOKLOVCHI talablarning
    hammasi bajarilganmi, ya'ni "bazadan reja tuzsa bo'ladimi".
    """
    s = snapshot.get
    minimum = config.MIN_CALIBRATION_SAMPLES
    status_text = ", ".join(statuses) or t(lang, "misc.all")

    def need(key: str, **kwargs: Any) -> dict[str, Any]:
        """`need` kodini saqlab, matnni qisqartma kalit bo'yicha oladi."""
        item = _need(_TEXT_KEY[key], lang=lang, **kwargs)
        item["need"] = key
        return item

    items: list[dict[str, Any]] = []

    # ------------------------------------------------------- BLOKLOVCHI
    items.append(need(
        "requests",
        blocking=True,
        sources=[_source(
            "transport_request", ["status", "planned_departure_at", "priority"],
            rows=s("rows_transport_request", 0), usable=s("ok_request_status", 0),
        )],
        statuses=status_text,
    ))

    items.append(need(
        "request_coordinates",
        blocking=True,
        sources=[
            _source(
                "transport_request_point", ["latitude", "longitude", "point_type"],
                rows=s("rows_transport_request_point", 0), usable=s("ok_point_coords", 0),
            ),
            _source(
                "transport_request",
                ["origin_latitude", "origin_longitude",
                 "destination_latitude", "destination_longitude"],
                rows=s("rows_transport_request", 0), usable=s("ok_request_coords", 0),
            ),
            _source(
                "reference_data (catalog_type='LOCATIONS')",
                ["latitude", "longitude", "active"],
                rows=s("rows_reference_data", 0), usable=s("ok_location_catalog", 0),
            ),
        ],
    ))

    items.append(need(
        "vehicles",
        blocking=True,
        sources=[_source(
            "transport_vehicle", ["transport_type", "current_status"],
            rows=s("rows_transport_vehicle", 0), usable=s("ok_vehicle_status", 0),
        )],
        blocked=", ".join(queries.BLOCKED_VEHICLE_STATUSES),
    ))

    depot_only = depot_given and not (
        s("ok_vehicle_position", 0) or s("ok_branch_catalog", 0)
    )
    items.append(need(
        "vehicle_start_point",
        blocking=True,
        ready=(
            s("ok_vehicle_position", 0) > 0
            or s("ok_branch_catalog", 0) > 0
            or depot_given
        ),
        sources=[
            _source(
                "vehicle_telemetry_state", ["last_latitude", "last_longitude"],
                rows=s("rows_vehicle_telemetry_state", 0), usable=s("ok_vehicle_position", 0),
            ),
            _source(
                "reference_data (catalog_type='BRANCHES')",
                ["latitude", "longitude", "active"],
                rows=s("rows_reference_data", 0), usable=s("ok_branch_catalog", 0),
            ),
            # Filial ID si o'zi chiqish nuqtasini BERMAYDI: u BRANCHES
            # katalogidagi koordinata bilan juftlikda ishlaydi. Shuning
            # uchun `ready` zanjirning ikkala uchiga qaraydi.
            _source(
                "transport_vehicle", ["branch_id"],
                rows=s("rows_transport_vehicle", 0), usable=s("ok_vehicle_branch", 0),
                ready=bool(s("ok_vehicle_branch", 0) and s("ok_branch_catalog", 0)),
            ),
        ],
        note=t(lang, "req.start.note_depot") if depot_only else "",
    ))

    # -------------------------------------------------- BLOKLAMAYDIGAN
    items.append(need(
        "speed",
        blocking=False,
        ready=cal.time_aware,
        sources=[
            _source(
                "trip",
                ["status='COMPLETED'", "actual_departure_at", "actual_arrival_at",
                 "actual_distance_km"],
                rows=s("rows_trip", 0), usable=s("ok_trip_speed", 0), need=minimum,
            ),
            _source(
                "route_point",
                ["distance_from_previous_km", "drive_duration_from_previous_minutes"],
                rows=s("rows_route_point", 0), usable=s("ok_route_point_speed", 0),
                need=minimum,
            ),
        ],
        minimum=minimum,
        note=_speed_note(
            cal, s("ok_trip_speed", 0) + s("ok_route_point_speed", 0), minimum, lang),
    ))

    road_factor_ready = (
        cal.road_factor is not None and cal.road_factor_source != "straight_line"
    )
    items.append(need(
        "road_factor",
        blocking=False,
        ready=road_factor_ready,
        sources=[_source(
            "route_point", ["distance_from_previous_km", "latitude", "longitude"],
            rows=s("rows_route_point", 0), usable=s("ok_road_factor_pairs", 0), need=minimum,
        )],
        note=_filter_note(
            s("ok_road_factor_pairs", 0), minimum,
            cal.road_factor_samples, road_factor_ready, lang,
        ),
    ))

    items.append(need(
        "service_time",
        blocking=False,
        ready=cal.service_minutes is not None,
        sources=[_source(
            "trip_event", ["event_type", "event_time", "trip_id"],
            rows=s("rows_trip_event", 0), usable=s("ok_service_pairs", 0), need=minimum,
        )],
    ))

    items.append(need(
        "capacity",
        blocking=False,
        match="all",
        sources=[
            _source(
                "transport_vehicle", ["payload_capacity_kg"],
                rows=s("rows_transport_vehicle", 0), usable=s("ok_vehicle_capacity", 0),
            ),
            _source(
                "transport_request", ["cargo_weight_kg"],
                rows=s("rows_transport_request", 0), usable=s("ok_request_weight", 0),
            ),
        ],
    ))

    items.append(need(
        "busy_windows",
        blocking=False,
        sources=[
            _source(
                "trip", ["scheduled_departure_at", "scheduled_arrival_at", "status"],
                rows=s("rows_trip", 0), usable=s("ok_trip_schedule", 0),
            ),
            _source(
                "waybill", ["planned_departure_at", "planned_return_at", "status"],
                rows=s("rows_waybill", 0), usable=s("ok_waybill_schedule", 0),
            ),
        ],
    ))

    items.append(need(
        "driver_shift",
        blocking=False,
        sources=[_source(
            "driver_shift", ["driver_id", "shift_date", "planned_start_at", "planned_end_at"],
            rows=s("rows_driver_shift", 0), usable=s("ok_driver_shift", 0),
        )],
    ))

    items.append(need(
        "hazard",
        blocking=False,
        match="all",
        sources=[
            _source(
                "shipment", ["hazard_profile_id"],
                rows=s("rows_shipment", 0), usable=s("ok_shipment_hazard", 0),
            ),
            _source(
                "hazard_profile", ["requires_special_tank", "requires_adr", "un_number"],
                rows=s("rows_hazard_profile", 0), usable=s("rows_hazard_profile", 0),
            ),
        ],
    ))

    items.append(need(
        "dock",
        blocking=False,
        sources=[_source(
            "dock_slot", ["location_id", "status"],
            rows=s("rows_dock_slot", 0), usable=s("rows_dock_slot", 0),
        )],
    ))

    # To'lmagani yuqorida: avval bloklovchilar, keyin qolganlari, oxirida
    # tayyorlari. Dispetcher birinchi qatorni o'qib ishga kirisha oladi.
    items.sort(key=lambda item: (item["ready"], not item["blocking"]))
    ready = all(item["ready"] for item in items if item["blocking"])
    return ready, items


def _speed_note(cal: Calibration, usable: int, minimum: int, lang: str) -> str:
    if cal.speed_source == "request":
        return t(lang, "req.speed.note_request")
    if cal.time_aware:
        return t(
            lang, "req.speed.note_measured",
            speed=round(cal.average_speed_kph or 0.0, 1),
            source=cal.speed_source,
            samples=cal.speed_samples,
        )
    if usable >= minimum:
        return t(lang, "req.speed.note_range")
    return ""


def _filter_note(
    usable: int, minimum: int, measured: int, ok: bool, lang: str
) -> str:
    """Qator bor-u o'lchov chiqmagan holatni ajratib yozadi.

    "Ma'lumot yo'q" va "ma'lumot bor, lekin xato" — bular ikki boshqa
    muammo va ularni bir xil ko'rsatish ATIL tomonini noto'g'ri joyga
    yuborardi.
    """
    if ok:
        return ""
    if usable >= minimum and measured < minimum:
        return t(
            lang, "req.road.note_filtered",
            usable=usable, reason=t(lang, "req.road.filter_reason"),
        )
    return ""
