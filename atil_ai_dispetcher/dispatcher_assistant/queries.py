"""Bazadan o'qish — FAQAT SELECT, parametrli.

BAZAGA ZARAR YETMASLIGI uch qatlam bilan kafolatlangan (boshqa modullar
kabi):
  1. bu faylda bitta ham yozuv amali yo'q — faqat `select`;
  2. ulanish `default_transaction_read_only=on` bilan ochiladi;
  3. `.env` dagi baza foydalanuvchisida faqat SELECT huquqi bor.

Sanalar va id'lar FOYDALANUVCHIDAN keladi, shuning uchun ular matnga
yopishtirilmaydi — psycopg2 parametrlari (`%s`) ishlatiladi.

VAQT TIPLARI ARALASH. `trip.scheduled_*` — `timestamp` (zonasiz),
`vehicle_telemetry_state.last_event_at` — `timestamptz` (zonali). Ularni
bevosita solishtirish Postgres'da ham, Python'da ham muammo beradi,
shuning uchun "hozir" har bir so'rovga PARAMETR bo'lib boradi va
ustunning o'z tipiga keltiriladi. Bu bir vaqtning o'zida testni ham
yengillashtiradi: "hozir" ni ko'chirib, kechagi holatni qayta
tiklash mumkin.

O'LCHOV, CHEGARA EMAS. Bu fayldagi hech bir so'rovda "30 daqiqadan ko'p
kechikkan" yoki "2 soatdan ko'p turgan" degan qattiq raqam yo'q.
Filtrlar chaqiruvchidan keladi va sukut bo'yicha O'CHIQ.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

# `db.connect_db_for_server` paket ichida yassi nom bilan import qiladi,
# shuning uchun `atil_chatbot` sys.path da bo'lishi shart.
_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

import psycopg2  # noqa: E402
from psycopg2 import sql as sql_builder

from db.connect_db_for_server import read_only_cursor  # noqa: E402

from atil_ai_dispetcher.dispatcher_assistant import config  # noqa: E402

logger = logging.getLogger(__name__)

#: Har bir endpoint o'qiydigan jadvallar — `data_quality.row_counts` uchun.
SOURCE_TABLES = {
    "delayed": ("trip", "trip_event", "route", "transport_request",
                "transport_vehicle", "driver"),
    "deviations": ("vehicle_telemetry_state", "telematics_event", "trip",
                   "route", "route_point", "transport_vehicle", "driver"),
    "idle": ("vehicle_telemetry_state", "telematics_event", "trip",
             "transport_vehicle", "driver"),
    "documents": ("driver", "driver_credential", "vehicle_document",
                  "insurance_policy", "transport_vehicle"),
}


class DispatcherDataError(RuntimeError):
    """Bazadan o'qib bo'lmadi — router buni 503 ga aylantiradi."""


def _select(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    try:
        with read_only_cursor() as cur:
            cur.execute(sql, tuple(params or ()))
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as exc:
        message = (getattr(exc, "pgerror", None) or str(exc)).strip().splitlines()[0]
        logger.warning("Dispetcher so'rovi bajarilmadi: %s", message[:300])
        raise DispatcherDataError(message[:300]) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bazaga ulanishda kutilmagan xato")
        raise DispatcherDataError(f"{type(exc).__name__}: {exc}"[:300]) from exc


def to_float(value: Any) -> float | None:
    """`numeric` ustunlar psycopg2 dan `Decimal` bo'lib keladi — JSON uchun float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def row_counts(tables: Sequence[str]) -> dict[str, int]:
    """Exact counts; stale PostgreSQL statistics are not data availability."""
    if not tables:
        return {}
    allowed = {name for group in SOURCE_TABLES.values() for name in group}
    if any(name not in allowed for name in tables):
        raise ValueError('Unsupported source table')
    query = sql_builder.SQL(' union all ').join(
        sql_builder.SQL('select {} as table_name,count(*) as row_count from {}').format(
            sql_builder.Literal(name), sql_builder.Identifier(name)) for name in tables)
    rows = _select(query)
    counts = {name: 0 for name in tables}
    counts.update({r["table_name"]: int(r["row_count"] or 0) for r in rows})
    return counts


# =========================================================== 1. Kechikish


DELAYED_SQL = """
select
    t.id::text                    as trip_id,
    t.trip_number,
    t.status,
    coalesce((nullif(to_jsonb(t)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.scheduled_departure_at) as scheduled_departure_at,
    coalesce((nullif(to_jsonb(t)->>'release_departure_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.actual_departure_at) as actual_departure_at,
    coalesce((nullif(to_jsonb(t)->>'planning_end_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.scheduled_arrival_at) as scheduled_arrival_at,

    -- Ikki xil kechikish bir ustunda ARALASHTIRILMAYDI: turi ham,
    -- daqiqasi ham alohida hisoblanadi.
    case when coalesce((nullif(to_jsonb(t)->>'release_departure_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.actual_departure_at) is null
         then 'NOT_DEPARTED' else 'LATE_EN_ROUTE' end          as kind,
    case when coalesce((nullif(to_jsonb(t)->>'release_departure_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.actual_departure_at) is null
         then extract(epoch from (%s::timestamp - coalesce((nullif(to_jsonb(t)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.scheduled_departure_at))) / 60.0
         else extract(epoch from (%s::timestamp - coalesce((nullif(to_jsonb(t)->>'planning_end_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.scheduled_arrival_at))) / 60.0
    end                                                        as delay_minutes,

    t.vehicle_id::text            as vehicle_id,
    v.plate_number,
    t.driver_id::text             as driver_id,
    d.full_name                   as driver_name,
    d.phone                       as driver_phone,

    t.route_id::text              as route_id,
    r.route_number,
    tr.request_number,
    coalesce(tr.destination_location, tr.to_warehouse_name) as destination,

    -- Reys qayerda to'xtab qolganini oxirgi hodisa ko'rsatadi.
    ev.event_type                 as last_event_type,
    ev.event_time                 as last_event_at
from trip t
left join transport_vehicle v  on v.id  = t.vehicle_id
left join driver d             on d.id  = t.driver_id
left join route r              on r.id  = t.route_id
left join transport_request tr on tr.id = t.transport_request_id
left join lateral (
    select e.event_type, e.event_time
    from trip_event e
    where e.trip_id = t.id
    order by e.event_time desc
    limit 1
) ev on true
where t.status = any(%s)
  and (
        (coalesce((nullif(to_jsonb(t)->>'release_departure_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.actual_departure_at) is null
         and coalesce((nullif(to_jsonb(t)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.scheduled_departure_at) is not null
         and coalesce((nullif(to_jsonb(t)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.scheduled_departure_at) < %s::timestamp)
     or (coalesce((nullif(to_jsonb(t)->>'release_departure_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.actual_departure_at) is not null
         and coalesce((nullif(to_jsonb(t)->>'release_return_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.actual_arrival_at) is null
         and coalesce((nullif(to_jsonb(t)->>'planning_end_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.scheduled_arrival_at) is not null
         and coalesce((nullif(to_jsonb(t)->>'planning_end_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),t.scheduled_arrival_at) < %s::timestamp)
      )
order by delay_minutes desc
limit %s
"""


def fetch_delayed(*, now: datetime, limit: int) -> list[dict[str, Any]]:
    """Kechikayotgan aktiv reyslar — eng ko'p kechikkani birinchi.

    "Kechikish" bu yerda MEYOR EMAS, SOLISHTIRISH: rejadagi vaqt hozirgi
    vaqtdan oldinmi. Ya'ni chegara o'ylab topilmagan, u soatning o'zi.

    Ikki holat ajratiladi va bu MUHIM:
      * jo'nash vaqti o'tgan, hali chiqmagan  -> dispetcher to'xtata oladi
      * yo'lda, yetib borish vaqti o'tgan     -> faqat ogohlantirish qoladi
    """
    naive = now.replace(tzinfo=None)
    return _select(
        DELAYED_SQL,
        (naive, naive, list(config.ACTIVE_TRIP_STATUSES), naive, naive, int(limit)),
    )


# ================================================= 2. Yo'nalishdan og'ish


TELEMETRY_SQL = """
select
    ts.vehicle_id::text           as vehicle_id,
    v.plate_number,
    ts.deviation_active,
    ts.deviation_threshold_meters,
    ts.stop_active,
    ts.stop_candidate_since,
    ts.idle_time_seconds,
    ts.moving_time_seconds,
    ts.last_engine_on,
    ts.last_speed_kph,
    ts.last_heading,
    ts.last_latitude,
    ts.last_longitude,
    ts.last_event_at,
    ts.route_points_json,
    ts.current_trip_id::text      as trip_id,
    ts.current_route_id::text     as route_id,
    t.trip_number,
    r.route_number,
    coalesce(t.driver_id, v.assigned_driver_id)::text as driver_id,
    d.full_name                   as driver_name,
    d.phone                       as driver_phone,

    -- Oxirgi GPS yozuvidan beri o'tgan vaqt. GPS uzilgan mashina ham
    -- "to'xtagan" bo'lib ko'rinadi — ikkalasini shu ajratadi.
    extract(epoch from (%s::timestamptz - ts.last_event_at)) / 60.0
                                  as minutes_since_last_event
from vehicle_telemetry_state ts
left join transport_vehicle v on v.id = ts.vehicle_id
left join trip t              on t.id = ts.current_trip_id
left join route r             on r.id = ts.current_route_id
left join driver d            on d.id = coalesce(t.driver_id, v.assigned_driver_id)
where {condition}
order by {order}
limit %s
"""


def fetch_deviations(*, now: datetime, limit: int) -> list[dict[str, Any]]:
    """Yo'nalishdan og'gan mashinalar.

    OG'ISHNI BU MODUL ANIQLAMAYDI. Uni telematika xizmati aniqlaydi va
    `deviation_active` ga yozadi; chegara ham bazada
    (`deviation_threshold_meters`). Bu yerda o'sha bayroq o'qiladi.

    Nima uchun qayta hisoblanmaydi: telematika xizmati har bir GPS
    nuqtasini ko'radi, bu endpoint esa faqat oxirgi holatni. Qayta
    hisoblasak, kamroq ma'lumot bilan boshqa javob chiqarib, ikki xil
    haqiqat yaratgan bo'lardik.
    """
    sql = TELEMETRY_SQL.format(
        condition="ts.deviation_active",
        order="ts.last_event_at desc nulls last",
    )
    return _select(sql, (now, int(limit)))


def fetch_idle(*, now: datetime, limit: int) -> list[dict[str, Any]]:
    """Bekor turgan mashinalar — eng uzoq turgani birinchi.

    "Uzoq" degan chegara YO'Q: `stop_active` ni telematika xizmati
    qo'yadi, bu yerda faqat davomiylik hisoblanadi va ro'yxat shu
    bo'yicha saralanadi. Kesish kerak bo'lsa chaqiruvchi `min_minutes`
    beradi.
    """
    sql = TELEMETRY_SQL.format(
        condition="ts.stop_active",
        order="ts.stop_candidate_since asc nulls last",
    )
    return _select(sql, (now, int(limit)))


ROUTE_POINTS_SQL = """
select
    p.route_id::text as route_id,
    p.sequence_number,
    p.latitude,
    p.longitude
from route_point p
where p.route_id = any(%s::uuid[])
  and p.latitude is not null and p.longitude is not null
order by p.route_id, p.sequence_number
"""


def fetch_route_points(route_ids: Sequence[str]) -> dict[str, list[tuple[float, float]]]:
    """Marshrut nuqtalari — yo'ldan chetlanish masofasini o'lchash uchun.

    `vehicle_telemetry_state.route_points_json` bo'sh bo'lsa shu
    ishlatiladi. Ikkalasi ham bo'lmasa masofa `null` bo'lib qoladi va
    javobda faqat bayroqning o'zi ko'rinadi — nol deb yozilmaydi.
    """
    if not route_ids:
        return {}
    rows = _select(ROUTE_POINTS_SQL, ([str(x) for x in route_ids],))
    result: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        latitude = to_float(row.get("latitude"))
        longitude = to_float(row.get("longitude"))
        if latitude is None or longitude is None:
            continue
        result.setdefault(row["route_id"], []).append((latitude, longitude))
    return result


# ======================================================= 4. Hujjat muddati


DOCUMENTS_SQL = """
select * from (
    -- Haydovchilik guvohnomasi. `driver` da NOT NULL, ya'ni bu manba
    -- har doim to'liq ishlaydi.
    select
        'DRIVER'                as subject_type,
        d.id::text              as subject_id,
        d.full_name             as subject_name,
        'LICENSE'               as document_type,
        d.driver_license_number as document_label,
        d.license_valid_until   as valid_until,
        d.phone                 as driver_phone,
        d.position              as department,
        'driver'                as source_table
    from driver d
    where d.license_valid_until is not null

    union all

    -- Tibbiy sertifikat (uzoq muddatli). Kunlik ko'rik EMAS —
    -- `medical_inspection` bu yerga kirmaydi.
    select
        'DRIVER', d.id::text, d.full_name,
        'MEDICAL_CERTIFICATE', null,
        d.medical_certificate_valid_until,
        d.phone, d.position, 'driver'
    from driver d
    where d.medical_certificate_valid_until is not null

    union all

    -- Kirish kartasi / QR. Bekor qilinganlari hisobga olinmaydi.
    select
        'DRIVER', c.driver_id::text, d.full_name,
        'CREDENTIAL', coalesce(c.label, c.credential_type),
        c.expires_at::date,
        d.phone, d.position, 'driver_credential'
    from driver_credential c
    left join driver d on d.id = c.driver_id
    where c.expires_at is not null and c.active and c.revoked_at is null

    union all

    -- Mashina hujjatlari: ro'yxatdan o'tish, ruxsatnoma, ijara shartnomasi...
    select
        'VEHICLE', vd.vehicle_id::text, v.plate_number,
        'VEHICLE_DOCUMENT',
        concat_ws(' ', vd.document_type, vd.document_number),
        vd.expiry_date,
        null, null, 'vehicle_document'
    from vehicle_document vd
    left join transport_vehicle v on v.id = vd.vehicle_id
    where vd.expiry_date is not null

    union all

    -- Sug'urta. Bekor qilingan polis muddati tugashi yangilik emas.
    select
        'VEHICLE', ip.vehicle_id::text, v.plate_number,
        'INSURANCE',
        concat_ws(' ', ip.kind, ip.policy_number, ip.insurer_name),
        ip.valid_to,
        null, null, 'insurance_policy'
    from insurance_policy ip
    left join transport_vehicle v on v.id = ip.vehicle_id
    where ip.valid_to is not null
      and coalesce(ip.status, '') <> 'CANCELLED'
) doc
where (%s::integer is null or (doc.valid_until - %s::date) <= %s::integer)
order by doc.valid_until
limit %s
"""


def fetch_documents(
    *, today: Any, days: int | None, limit: int
) -> list[dict[str, Any]]:
    """Muddati tugagan yoki tugayotgan hujjatlar — eng eskisi birinchi.

    `days` — OYNA, MEYOR EMAS. Berilmasa (`None`) hamma hujjat qaytadi
    va ro'yxat muddat bo'yicha saralangan bo'ladi: muddati o'tganlar
    tepada. "30 kun qolgani xavfli" degan qaror chaqiruvchida.

    KUNLIK KO'RIKLAR (`medical_inspection`, `vehicle_technical_inspection`)
    ATAYLAB KIRMAYDI: ular har kuni yangilanadi va "ertaga tugaydi"
    holati NORMAL. Ro'yxatga qo'shilsa kuniga 200 dan ortiq qator
    chiqib, haqiqiy muammoni ko'mib tashlardi.
    """
    return _select(DOCUMENTS_SQL, (days, today, days, int(limit)))
