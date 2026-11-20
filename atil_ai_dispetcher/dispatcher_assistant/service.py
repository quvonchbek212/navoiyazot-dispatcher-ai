"""Orkestratsiya — to'rtta hisobotni yig'ish.

BU FAYLDA SQL YO'Q (u `queries.py` da) va MATEMATIKA YO'Q (u
`rules.py` da). Bu yerda faqat: o'qish, filtrlash, saralash, konvertga
solish.

BO'SH RO'YXAT "MUAMMO YO'Q" DEGANI EMAS. Har bir hisobot manba
jadvalining bo'sh-to'laligini tekshiradi va bo'sh bo'lsa buni
`data_quality.notes` da OCHIQ yozadi. Aks holda telematika ulanmagani
uchun bo'sh chiqqan "yo'ldan og'ish" ro'yxati dispetcherga "hammasi
joyida" deb ko'rinardi — bu modulning eng xavfli xatosi bo'lardi.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any, Sequence

from atil_ai_dispetcher.dispatcher_assistant import config, queries, rules, texts
from atil_ai_dispetcher.dispatcher_assistant.texts import t

logger = logging.getLogger(__name__)


def _f(value: Any) -> float | None:
    return queries.to_float(value)


def _envelope(
    *,
    now: datetime,
    filters: dict[str, Any],
    items: list[dict[str, Any]],
    total: int,
    by_kind: dict[str, int],
    worst: str | None,
    expired: int | None = None,
    counts: dict[str, int],
    notes: list[Any],
    started: float,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    # Izohlar KALIT bo'lib yig'ilgan. So'ralgan til `notes` ga tushadi;
    # uchalasi `notes_by_lang` da qoladi va uni `atil_agent` ishlatadi —
    # u xabarni sikl paytida yozib, boshqa tilda o'qishi mumkin.
    # Qo'shimcha bazaga murojaat yo'q, bu faqat matn qurish.
    return {
        "generated_at": datetime.now(),
        "scope": {"checked_at": now, "filters": filters},
        "summary": {
            "total": total,
            "returned": len(items),
            "by_kind": by_kind,
            "worst": worst,
            "expired": expired,
        },
        "analysis": {"text": "", "source": "template", "items_considered": 0},
        "items": items,
        "data_quality": {
            "row_counts": counts,
            "notes": [_render_note(n, lang) for n in notes],
            "notes_by_lang": {
                til: [_render_note(n, til) for n in notes]
                for til in texts.LANGS
            },
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _note(key: str, **params: Any) -> dict[str, Any]:
    """Izoh — matn emas, KALIT. Renderlash `_envelope` da bir joyda."""
    return {"key": key, "params": params}


def _render_note(note: Any, lang: str) -> str:
    """Kalitni matnga aylantiradi; ichki kalitlar ham yechiladi."""
    if isinstance(note, str):
        return note
    params = {
        name: _render_note(value, lang) if isinstance(value, dict) else value
        for name, value in (note.get("params") or {}).items()
    }
    return t(lang, note["key"], **params)


def _limit_note(
    rows: Sequence[Any], limit: int, notes: list[str], what: str,
    lang: str = texts.DEFAULT_LANG,
) -> None:
    if len(rows) >= limit:
        notes.append(_note("note.limit", limit=limit, what=_note(what)))


# =========================================================== 1. Kechikish


def delayed(
    *,
    now: datetime | None = None,
    min_minutes: float | None = None,
    kind: str | None = None,
    limit: int = config.DEFAULT_LIMIT,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    """Kechikayotgan reyslar.

    `min_minutes` — FILTR, meyor emas. Berilmasa hamma kechikish
    qaytadi va ro'yxat og'irligi bo'yicha saralangan bo'ladi.
    """
    started = time.perf_counter()
    now = now or datetime.now()
    notes: list[str] = []

    # Bazadan `MAX_ROWS` gacha o'qiladi — foydalanuvchi limitiga BOG'LIQ
    # EMAS. Sababi: `summary.total` haqiqiy son bo'lishi kerak.
    # `limit=5` so'ralganda 5 tagina o'qisak, "jami 5 ta" degan yolg'on
    # chiqardi; aslida 400 ta bo'lishi mumkin.
    rows = queries.fetch_delayed(now=now, limit=config.MAX_ROWS)

    items: list[dict[str, Any]] = []
    by_kind: dict[str, int] = {}
    for row in rows:
        minutes = _f(row.get("delay_minutes")) or 0.0
        if min_minutes is not None and minutes < min_minutes:
            continue
        row_kind = row.get("kind") or "NOT_DEPARTED"
        if kind and row_kind != kind:
            continue
        by_kind[row_kind] = by_kind.get(row_kind, 0) + 1
        items.append(
            {
                "kind": row_kind,
                "trip_id": row["trip_id"],
                "trip_number": row.get("trip_number"),
                "status": row.get("status"),
                "delay_minutes": round(minutes, 1),
                "scheduled_departure_at": row.get("scheduled_departure_at"),
                "actual_departure_at": row.get("actual_departure_at"),
                "scheduled_arrival_at": row.get("scheduled_arrival_at"),
                "vehicle_id": row.get("vehicle_id"),
                "plate_number": row.get("plate_number"),
                "driver_id": row.get("driver_id"),
                "driver_name": row.get("driver_name"),
                "driver_phone": row.get("driver_phone"),
                "route_id": row.get("route_id"),
                "route_number": row.get("route_number"),
                "request_number": row.get("request_number"),
                "destination": row.get("destination"),
                "last_event_type": row.get("last_event_type"),
                "last_event_at": row.get("last_event_at"),
            }
        )

    total = len(items)
    items = items[:limit]
    counts = queries.row_counts(queries.SOURCE_TABLES["delayed"])
    _limit_note(rows, config.MAX_ROWS, notes, "what.delayed", lang)

    if not counts.get("trip"):
        notes.append(_note("note.trip_empty"))
    if items and not any(i["last_event_type"] for i in items):
        notes.append(_note("note.no_trip_events"))

    worst = None
    if items:
        top = items[0]
        hours = top["delay_minutes"] / 60.0
        worst = t(
            lang, "worst.delayed",
            trip=top.get("trip_number") or top["trip_id"][:8],
            hours=f"{hours:.1f}",
            kind=t(lang, "delay.not_departed" if top["kind"] == "NOT_DEPARTED"
                   else "delay.en_route"),
        )

    return _envelope(
        now=now,
        filters={"min_minutes": min_minutes, "kind": kind, "limit": limit},
        items=items, total=total, by_kind=by_kind, worst=worst,
        counts=counts, notes=notes, started=started, lang=lang,
    )


# ================================================= 2. Yo'nalishdan og'ish


def deviations(
    *,
    now: datetime | None = None,
    min_meters: float | None = None,
    limit: int = config.DEFAULT_LIMIT,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    """Yo'nalishdan og'gan mashinalar.

    Og'ish faktini telematika xizmati belgilaydi (`deviation_active`),
    bu yerda unga MASOFA qo'shiladi: mashina rejadagi yo'ldan qancha
    chetda. Masofa hisoblanmasa `null` bo'ladi va filtr uni kesmaydi —
    "o'lchanmadi" ni "yo'ldan chiqmagan" deb hisoblash xato bo'lardi.
    """
    started = time.perf_counter()
    now = now or datetime.now()
    notes: list[str] = []

    rows = queries.fetch_deviations(now=now, limit=config.MAX_ROWS)

    # Marshrut nuqtalari: avval telematikaning o'z nusxasi, bo'lmasa
    # `route_point` dan.
    missing_routes = [
        row["route_id"] for row in rows
        if row.get("route_id") and not rules.parse_route_points(row.get("route_points_json"))
    ]
    fallback = queries.fetch_route_points(sorted(set(missing_routes))) if missing_routes else {}

    items: list[dict[str, Any]] = []
    unmeasured = 0
    for row in rows:
        points = rules.parse_route_points(row.get("route_points_json"))
        source_used = "telemetry"
        if not points and row.get("route_id"):
            points = fallback.get(row["route_id"], [])
            source_used = "route_point"

        latitude = _f(row.get("last_latitude"))
        longitude = _f(row.get("last_longitude"))
        meters = rules.distance_from_route_meters(latitude, longitude, points)
        if meters is None:
            unmeasured += 1
        elif min_meters is not None and meters < min_meters:
            continue

        items.append(
            {
                "vehicle_id": row["vehicle_id"],
                "plate_number": row.get("plate_number"),
                "driver_id": row.get("driver_id"),
                "driver_name": row.get("driver_name"),
                "driver_phone": row.get("driver_phone"),
                "deviation_active": bool(row.get("deviation_active")),
                "threshold_meters": _f(row.get("deviation_threshold_meters")),
                "distance_from_route_meters": None if meters is None else round(meters, 1),
                "trip_id": row.get("trip_id"),
                "trip_number": row.get("trip_number"),
                "route_id": row.get("route_id"),
                "route_number": row.get("route_number"),
                "latitude": latitude,
                "longitude": longitude,
                "speed_kph": _f(row.get("last_speed_kph")),
                "heading": _f(row.get("last_heading")),
                "last_event_at": row.get("last_event_at"),
                "minutes_since_last_event": _round(row.get("minutes_since_last_event")),
                "_source": source_used,
            }
        )

    # Masofasi o'lchanganlar tepada, keyin o'lchanmaganlar.
    items.sort(
        key=lambda i: (
            i["distance_from_route_meters"] is None,
            -(i["distance_from_route_meters"] or 0.0),
        )
    )
    for item in items:
        item.pop("_source", None)

    total = len(items)
    items = items[:limit]
    counts = queries.row_counts(queries.SOURCE_TABLES["deviations"])

    if not counts.get("vehicle_telemetry_state"):
        notes.append(_note("note.telemetry_deviation"))
    if unmeasured:
        notes.append(_note("note.unmeasured_deviation", count=unmeasured))
    _limit_note(rows, config.MAX_ROWS, notes, "what.deviation", lang)

    worst = None
    if items and items[0]["distance_from_route_meters"] is not None:
        top = items[0]
        worst = t(
            lang, "worst.deviation",
            who=top.get("plate_number") or top["vehicle_id"][:8],
            km=f"{top['distance_from_route_meters'] / 1000:.1f}",
        )
    elif items:
        top = items[0]
        worst = t(
            lang, "worst.deviation_unmeasured",
            who=top.get("plate_number") or top["vehicle_id"][:8],
        )

    return _envelope(
        now=now,
        filters={"min_meters": min_meters, "limit": limit},
        items=items, total=total, by_kind={}, worst=worst,
        counts=counts, notes=notes, started=started, lang=lang,
    )


def _round(value: Any, digits: int = 1) -> float | None:
    number = queries.to_float(value)
    return None if number is None else round(number, digits)


# ========================================================= 3. Bekor turish


def idle(
    *,
    now: datetime | None = None,
    min_minutes: float | None = None,
    limit: int = config.DEFAULT_LIMIT,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    """Bekor turgan mashinalar — eng uzoq turgani birinchi.

    `engine_on` alohida qaraladi: dvigatel ishlab turib to'xtagan
    mashina yoqilg'ini behuda yoqadi, o'chirilgani esa shunchaki
    kutayotgan bo'lishi mumkin. Ikkalasi bir xil emas.
    """
    started = time.perf_counter()
    now = now or datetime.now()
    notes: list[str] = []

    rows = queries.fetch_idle(now=now, limit=config.MAX_ROWS)

    items: list[dict[str, Any]] = []
    by_kind: dict[str, int] = {}
    for row in rows:
        stopped_minutes = rules.minutes_between(now, row.get("stop_candidate_since"))
        if min_minutes is not None and (stopped_minutes or 0.0) < min_minutes:
            continue

        engine_on = row.get("last_engine_on")
        key = "ENGINE_ON" if engine_on else ("ENGINE_OFF" if engine_on is False else "UNKNOWN")
        by_kind[key] = by_kind.get(key, 0) + 1

        items.append(
            {
                "vehicle_id": row["vehicle_id"],
                "plate_number": row.get("plate_number"),
                "driver_id": row.get("driver_id"),
                "driver_name": row.get("driver_name"),
                "driver_phone": row.get("driver_phone"),
                "stop_active": bool(row.get("stop_active")),
                "stopped_since": row.get("stop_candidate_since"),
                "stopped_minutes": None if stopped_minutes is None else round(stopped_minutes, 1),
                "idle_time_seconds": row.get("idle_time_seconds"),
                "moving_time_seconds": row.get("moving_time_seconds"),
                "engine_on": engine_on,
                "speed_kph": _f(row.get("last_speed_kph")),
                "latitude": _f(row.get("last_latitude")),
                "longitude": _f(row.get("last_longitude")),
                "trip_id": row.get("trip_id"),
                "trip_number": row.get("trip_number"),
                "route_number": row.get("route_number"),
                "last_event_at": row.get("last_event_at"),
                "minutes_since_last_event": _round(row.get("minutes_since_last_event")),
            }
        )

    total = len(items)
    items = items[:limit]
    counts = queries.row_counts(queries.SOURCE_TABLES["idle"])

    if not counts.get("vehicle_telemetry_state"):
        notes.append(_note("note.telemetry_idle"))
    unknown_engine = by_kind.get("UNKNOWN", 0)
    if unknown_engine:
        notes.append(_note("note.unknown_engine", count=unknown_engine))
    _limit_note(rows, config.MAX_ROWS, notes, "what.idle", lang)

    worst = None
    if items and items[0]["stopped_minutes"] is not None:
        top = items[0]
        worst = t(
            lang, "worst.idle",
            who=top.get("plate_number") or top["vehicle_id"][:8],
            hours=f"{top['stopped_minutes'] / 60:.1f}",
            engine=t(lang, "worst.idle_engine") if top["engine_on"] else "",
        )

    return _envelope(
        now=now,
        filters={"min_minutes": min_minutes, "limit": limit},
        items=items, total=total, by_kind=by_kind, worst=worst,
        counts=counts, notes=notes, started=started, lang=lang,
    )


# ======================================================= 4. Hujjat muddati


def documents(
    *,
    today: date | None = None,
    days: int | None = None,
    subject_type: str | None = None,
    document_type: str | None = None,
    limit: int = config.DEFAULT_LIMIT,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    """Muddati tugagan yoki tugayotgan hujjatlar — eng eskisi birinchi.

    `days` — OYNA: "shuncha kun ichida tugaydiganlar". Berilmasa hamma
    hujjat qaytadi. Muddati o'tganlar HAR DOIM ro'yxatda bo'ladi
    (`days_left` manfiy) — ular oynadan tashqarida qolib ketmasligi
    kerak.
    """
    started = time.perf_counter()
    today = today or date.today()
    notes: list[str] = []

    rows = queries.fetch_documents(
        today=today, days=days, limit=config.MAX_ROWS
    )

    items: list[dict[str, Any]] = []
    by_kind: dict[str, int] = {}
    for row in rows:
        if subject_type and row.get("subject_type") != subject_type:
            continue
        if document_type and row.get("document_type") != document_type:
            continue
        valid_until = row.get("valid_until")
        if valid_until is None:
            continue
        days_left = (valid_until - today).days
        doc_type = row.get("document_type") or "OTHER"
        by_kind[doc_type] = by_kind.get(doc_type, 0) + 1
        items.append(
            {
                "subject_type": row.get("subject_type"),
                "subject_id": row.get("subject_id"),
                "subject_name": row.get("subject_name"),
                "document_type": doc_type,
                "document_label": row.get("document_label"),
                "valid_until": valid_until,
                "days_left": days_left,
                "expired": days_left < 0,
                "source_table": row.get("source_table"),
                "driver_phone": row.get("driver_phone"),
                "department": row.get("department"),
            }
        )

    total = len(items)
    expired = sum(1 for i in items if i["expired"])
    items = items[:limit]
    counts = queries.row_counts(queries.SOURCE_TABLES["documents"])
    _limit_note(rows, config.MAX_ROWS, notes, "what.document", lang)

    empty = [
        name for name in ("driver_credential", "vehicle_document", "insurance_policy")
        if not counts.get(name)
    ]
    if empty:
        notes.append(
            _note("note.empty_document_sources", tables=", ".join(empty)))
    notes.append(_note("note.daily_inspections"))

    worst = None
    if items:
        top = items[0]
        kim = top.get("subject_name") or top["subject_id"][:8]
        if top["expired"]:
            worst = t(lang, "worst.document_expired", who=kim,
                      type=top["document_type"], days=abs(top["days_left"]))
        else:
            worst = t(lang, "worst.document_expires", who=kim,
                      type=top["document_type"], days=top["days_left"])

    return _envelope(
        now=datetime.combine(today, datetime.min.time()),
        filters={
            "days": days, "subject_type": subject_type,
            "document_type": document_type, "limit": limit,
        },
        items=items, total=total, by_kind=by_kind, worst=worst,
        expired=expired,
        counts=counts, notes=notes, started=started, lang=lang,
    )
