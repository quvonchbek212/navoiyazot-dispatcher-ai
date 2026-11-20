"""Bazadan tanlash uchun ma'lumot o'qish — FAQAT SELECT, parametrli.

BAZAGA ZARAR YETMASLIGI uch qatlam bilan kafolatlangan (oil_detection dagi
kabi):
  1. bu faylda bitta ham yozuv amali yo'q — faqat `select`;
  2. ulanish `default_transaction_read_only=on` bilan ochiladi;
  3. `.env` dagi baza foydalanuvchisida faqat SELECT huquqi bor.

Sanalar va id'lar FOYDALANUVCHIDAN keladi, shuning uchun ular matnga
yopishtirilmaydi — psycopg2 parametrlari (`%s`) ishlatiladi.

"BO'SH" QAYERDAN OLINADI — bu modulning eng nozik joyi.
`ddl.sql` izohi "bo'sh mashinalar current_status='ACTIVE' bo'yicha olinadi"
deydi, lekin 22.08.2026 da bazada tekshirilganda bu bayroq YANGILANMAGANI
aniqlandi:

    aktiv reysdagi 10 haydovchining 10 tasi ham hali `AVAILABLE`
    aktiv reysdagi 10 mashinaning  10 tasi ham hali `ACTIVE`
    driver.medical_cleared_today=true 92 ta, medical_inspection da bugun FIT 27 ta

Shuning uchun bandlik BAYROQDAN emas, HODISA jadvallaridan olinadi:
`trip` (aktiv holatlar) va `waybill` (ochiq holatlar). Ikkalasining
BIRLASHMASI olinadi — bir manba band desa band, chunki band mashinani
"bo'sh" deb ko'rsatish, bo'shini "band" deyishdan qimmatroq xato.

Bayroqlar baribir o'qiladi va javobda ko'rsatiladi, lekin qaror ular bilan
chiqarilmaydi.
"""

from __future__ import annotations

import logging
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

# `db.connect_db_for_server` paket ichida yassi nom bilan import qiladi
# (`from config import ...`), shuning uchun `atil_chatbot` sys.path da
# bo'lishi shart. main.py buni allaqachon qiladi; bu yerdagi takror shu
# modulni alohida ham (`python -m atil_ai_dispetcher.vehicle_selection.ranker`) ishlata olish uchun.
_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

import psycopg2  # noqa: E402

from db.connect_db_for_server import read_only_cursor  # noqa: E402

logger = logging.getLogger(__name__)

#: Reys tugamagan hisoblanadigan holatlar — mashina/haydovchi band.
#: COMPLETED, CANCELLED va INTERRUPTED bu ro'yxatga kirmaydi: ular tugagan.
ACTIVE_TRIP_STATUSES = (
    "PLANNED", "ASSIGNED", "STARTED", "ARRIVED_AT_POINT", "LOADED", "UNLOADED",
)

#: Yo'l varaqasi ochiq — mashina yo'lda. `RETURNED` kirmaydi: qaytib kelgan.
OPEN_WAYBILL_STATUSES = ("ISSUED", "IN_USE")

#: Mashina yo'lga chiqa olmaydigan holatlar.
BLOCKED_VEHICLE_STATUSES = ("IN_MAINTENANCE", "BLOCKED", "DECOMMISSIONED")

#: Remont yopilgan hisoblanadigan holatlar — qolganlari ochiq.
#: `vehicle_repair.status` da 25 dan ortiq qiymat bor, shuning uchun
#: "ochiq" ro'yxati emas, "yopiq" ro'yxati sanaladi: yangi holat qo'shilsa
#: u OCHIQ deb hisoblanadi, ya'ni xato xavfsiz tomonga ketadi.
CLOSED_REPAIR_STATUSES = (
    "CLOSED", "COMPLETED", "CANCELLED", "ARM_CLOSED", "REJECTED", "REPAIRED",
)

#: Modul o'qiydigan jadvallar — `data_quality.row_counts` da shular chiqadi.
SOURCE_TABLES = (
    "transport_vehicle",
    "driver",
    "driver_license_category",
    "medical_inspection",
    "vehicle_technical_inspection",
    "vehicle_repair",
    "vehicle_document",
    "insurance_policy",
    "vehicle_telemetry_state",
    "driver_shift",
    "trip",
    "waybill",
    "route",
    "route_point",
    "vehicle_assigned_drivers",
)


class SelectionDataError(RuntimeError):
    """Bazadan o'qib bo'lmadi — router buni 503 ga aylantiradi."""


def _select(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    try:
        with read_only_cursor() as cur:
            cur.execute(sql, tuple(params or ()))
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as exc:
        message = (getattr(exc, "pgerror", None) or str(exc)).strip().splitlines()[0]
        logger.warning("Tanlash so'rovi bajarilmadi: %s", message[:300])
        raise SelectionDataError(message[:300]) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bazaga ulanishda kutilmagan xato")
        raise SelectionDataError(f"{type(exc).__name__}: {exc}"[:300]) from exc


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


def row_counts(tables: Sequence[str] = SOURCE_TABLES) -> dict[str, int]:
    """Jadvallardagi yozuvlar soni — javobdagi `data_quality` uchun.

    NIMA UCHUN `count(*)`, `pg_stat_user_tables` EMAS. Ilgari bu yerda
    `n_live_tup` o'qilardi — u yengil, lekin bu bazada YOLG'ON: statistika
    hech qachon yig'ilmagan (`last_analyze` ham, `last_autoanalyze` ham
    NULL), shuning uchun 128 qatorli `transport_vehicle` javobda "0"
    bo'lib ko'rinardi. Undan chiqarilgan "Bo'sh jadvallar: ..." izohi ham
    yolg'on bo'lardi — o'sha javobning o'zida o'sha jadvaldan o'qilgan
    mashinalar turgan holda.

    Bo'sh jadval natijani jimgina o'zgartirib yuboradi, shuning uchun bu
    maydon javobda ko'rinishi shart — va TO'G'RI ko'rinishi shart.

    Aniq son bu yerda qimmat emas: jadvallar kichik va hammasi BITTA
    so'rovda, bitta borib-kelishda sanaladi.
    """
    # Jadval nomlari `SOURCE_TABLES` dan keladi (foydalanuvchidan emas),
    # lekin baribir tekshiriladi: SQL ga nom yopishtirilayotgani uchun
    # bu yerda ehtiyot bo'lish kerak.
    names = [name for name in tables if re.fullmatch(r"[a-z_][a-z0-9_]*", name)]
    if not names:
        return {}
    sql = " union all ".join(
        f"select '{name}' as table_name, count(*) as row_count from {name}"
        for name in names
    )
    counts = {name: 0 for name in tables}
    counts.update({r["table_name"]: int(r["row_count"] or 0) for r in _select(sql)})
    return counts


# ------------------------------------------------------------------- Talab


ROUTE_DEMAND_SQL = """
select
    r.id::text                    as route_id,
    r.route_number,
    r.name                        as route_name,
    r.required_driver_category,
    r.required_transport_type,
    coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at) as planned_departure_at,
    coalesce((nullif(to_jsonb(r)->>'planning_end_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_arrival_at) as planned_arrival_at,
    r.planned_duration_minutes,
    r.status,
    r.assigned_driver_id::text    as assigned_driver_id,
    r.assigned_vehicle_id::text   as assigned_vehicle_id,
    r.latitude                    as origin_latitude,
    r.longitude                   as origin_longitude,
    (select sum(p.distance_from_previous_km) from route_point p where p.route_id = r.id)
                                  as total_distance_km,
    (select p.latitude  from route_point p where p.route_id = r.id
      and p.latitude is not null order by p.sequence_number limit 1) as first_point_latitude,
    (select p.longitude from route_point p where p.route_id = r.id
      and p.longitude is not null order by p.sequence_number limit 1) as first_point_longitude
from route r
where r.id = %s::uuid
"""


def fetch_route_demand(route_id: str) -> dict[str, Any] | None:
    """Marshrutdan talabni o'qiydi — eng to'liq manba.

    `required_driver_category` va `required_transport_type` `route` da
    NOT NULL, ya'ni marshrut berilgan bo'lsa malaka va tur talabi aniq.

    Yuklash nuqtasi koordinatasi ikki joydan qidiriladi: avval `route` ning
    o'zidan, bo'lmasa birinchi `route_point` dan. 22.08.2026 holatiga
    `route.latitude` 56/56 bo'sh, `route_point` da esa 62 dan 38 tasida bor.
    """
    rows = _select(ROUTE_DEMAND_SQL, (route_id,))
    return rows[0] if rows else None


# ------------------------------------------------------------------- Manzil


LOCATION_SQL = """
select
    p.location_id::text as location_id,
    p.location_name,
    p.latitude,
    p.longitude
from route_point p
where p.location_id = %s::uuid
order by (p.latitude is not null) desc, p.sequence_number
limit 1
"""


def fetch_location(location_id: str) -> dict[str, Any] | None:
    """Manzilni id bo'yicha yechadi — nomi va koordinatasi.

    NIMA UCHUN `route_point`, `reference_data` EMAS (22.08.2026 tekshiruvi):
        reference_data.catalog_type='LOCATIONS'   -> 0 yozuv
        reference_data da koordinata              -> 521 yozuvning 0 tasida
        route_point dagi 44 ta manzildan
          reference_data da topilgani             -> 0 ta

    Ya'ni manzil katalogi `ddl.sql` da rejalashtirilgan (`LOCATIONS` check
    ro'yxatida bor), lekin to'ldirilmagan. Marshrutlar AMALDA `route_point`
    dagi id'larni ishlatadi va 44 tadan 16 tasida koordinata bor, shuning
    uchun manzil shu yerdan yechiladi.

    Koordinatalisi ustun qo'yiladi: bir xil manzil bir necha marshrutda
    uchraganda ba'zisida koordinata bo'lmasligi mumkin.

    `reference_data.LOCATIONS` to'ldirilganda shu funksiyani o'zgartirish
    kifoya — chaqiruvchi joylar tegilmaydi.
    """
    rows = _select(LOCATION_SQL, (location_id,))
    return rows[0] if rows else None


# ----------------------------------------------------------------- Mashinalar


VEHICLES_SQL = """
select
    v.id::text                 as vehicle_id,
    v.plate_number,
    v.brand,
    v.model,
    v.transport_type,
    v.category,
    v.current_status,
    v.ownership_type,
    v.usage_mode,
    coalesce(v.payload_capacity_kg,nullif(to_jsonb(v)->>'cargo_capacity_tons','')::numeric*1000) as payload_capacity_kg,
    v.volume_m3,
    coalesce(v.seat_count,nullif(to_jsonb(v)->>'passenger_capacity','')::integer) as seat_count,
    v.branch_id::text          as branch_id,
    v.department_id::text      as department_id,
    v.assigned_driver_id::text as assigned_driver_id,
    v.gps_device_id,

    -- Bandlik: hodisa jadvallaridan, bayroqdan emas.
    -- Vaqt oynasi berilgan bo'lsa reyslar shu oyna bilan kesishishiga
    -- qaraladi; berilmasa aktiv reysning o'zi band deb olinadi.
    (select t.id::text from trip t
      where t.vehicle_id = v.id
        and t.status = any(%s)
        and (%s::timestamp is null or %s::timestamp is null
             or (t.scheduled_departure_at, t.scheduled_arrival_at)
                 overlaps (%s::timestamp, %s::timestamp))
      order by t.scheduled_departure_at limit 1)          as busy_trip_id,
    (select w.waybill_number from waybill w
      where w.vehicle_id = v.id and w.status = any(%s)
      order by w.issue_date desc limit 1)                 as open_waybill_number,

    -- Texnik holat
    (select count(*) from vehicle_repair r
      where r.vehicle_id = v.id and r.blocks_release
        and not (r.status = any(%s)))                     as blocking_repairs,
    (select count(*) from vehicle_repair r
      where r.vehicle_id = v.id and not r.blocks_release
        and not (r.status = any(%s)))                     as open_repairs,
    ti.status                  as last_inspection_status,
    ti.inspected_at            as last_inspection_at,
    mp.status                  as maintenance_status,
    mp.next_due_at             as maintenance_next_due_at,

    -- Hujjatlar: eng erta tugaydigan muddat va allaqachon o'tganlari soni
    (select min(vd.expiry_date) from vehicle_document vd
      where vd.vehicle_id = v.id and vd.expiry_date is not null)  as document_min_expiry,
    (select count(*) from vehicle_document vd
      where vd.vehicle_id = v.id and vd.expiry_date is not null
        and vd.expiry_date < %s::date)                            as documents_expired,
    (select count(*) from vehicle_document vd
      where vd.vehicle_id = v.id)                                 as documents_total,
    (select max(ip.valid_to) from insurance_policy ip
      where ip.vehicle_id = v.id and ip.status <> 'CANCELLED')    as insurance_valid_to,

    -- Joylashuv (masofa mezoni uchun)
    ts.last_latitude,
    ts.last_longitude,
    ts.last_event_at           as position_at
from transport_vehicle v
left join lateral (
    select i.status, i.inspected_at from vehicle_technical_inspection i
    where i.vehicle_id = v.id and i.inspection_type = 'PRE_TRIP'
    order by i.inspected_at desc limit 1
) ti on true
left join lateral (
    select m.status, m.next_due_at from maintenance_plan m
    where m.vehicle_id = v.id
    order by (m.status = 'OVERDUE') desc, m.next_due_at nulls last limit 1
) mp on true
left join vehicle_telemetry_state ts on ts.vehicle_id = v.id
where (%s::text is null or v.transport_type = %s::text)
order by v.plate_number
limit %s
"""


def fetch_vehicles(
    *,
    on_date: str,
    window_from: str | None = None,
    window_to: str | None = None,
    transport_type: str | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    """Nomzod mashinalar — hamma mezon uchun kerakli ustunlar bilan.

    BU YERDA KESISH YO'Q (turdan va bo'limdan tashqari): band, remontda
    yoki hujjati o'tgan mashina ham qaytadi. Kesish qarori `rules.py` da
    chiqariladi va SABABI bilan javobga yoziladi — "nega bu mashina
    ro'yxatda yo'q" degan savolga javob bera olish uchun.

    `transport_type` bu yerda filtr, chunki u talabning qat'iy sharti va
    127 ta mashinadan 4-48 tasini qoldiradi — bazaga bekorga yuk bo'lmasin.
    Berilmasa hammasi qaytadi.
    """
    return _select(
        VEHICLES_SQL,
        (
            list(ACTIVE_TRIP_STATUSES),
            window_from, window_to, window_from, window_to,
            list(OPEN_WAYBILL_STATUSES),
            list(CLOSED_REPAIR_STATUSES),
            list(CLOSED_REPAIR_STATUSES),
            on_date,
            transport_type, transport_type,
            limit,
        ),
    )


# --------------------------------------------------------------- Haydovchilar


DRIVERS_SQL = """
select
    d.id::text                as driver_id,
    d.full_name,
    d.table_number,
    d.phone,
    d.position,
    d.employment_status,
    d.driver_availability_status,
    d.license_valid_until,
    d.medical_certificate_valid_until,
    d.medical_cleared_today,
    d.branch_id::text         as branch_id,
    d.department_id::text     as department_id,

    coalesce((select array_agg(c.license_category order by c.license_category)
                from driver_license_category c where c.driver_id = d.id),
             '{}')            as license_categories,

    -- Bandlik: mashinadagi bilan bir xil mantiq
    (select t.id::text from trip t
      where t.driver_id = d.id
        and t.status = any(%s)
        and (%s::timestamp is null or %s::timestamp is null
             or (t.scheduled_departure_at, t.scheduled_arrival_at)
                 overlaps (%s::timestamp, %s::timestamp))
      order by t.scheduled_departure_at limit 1)          as busy_trip_id,
    (select w.waybill_number from waybill w
      where w.driver_id = d.id and w.status = any(%s)
      order by w.issue_date desc limit 1)                 as open_waybill_number,

    -- Tibbiy ko'rik: BAYROQ EMAS, jadvalning o'zi (bayroq eskirgan)
    mi.status                 as medical_status,
    mi.shift_date             as medical_shift_date,
    mi.alcohol_promille,

    -- Smena
    sh.shift_type,
    sh.status                 as shift_status,
    sh.planned_start_at,
    sh.planned_end_at,
    sh.planned_hours,

    -- Tajriba va xavfsizlik tarixi (malaka mezoni uchun)
    --
    -- `count(*)` EMAS, `count(distinct t.route_id)`. Sabab: marshrut
    -- optimizatsiyasi bitta fizik reysga bir necha arizani qo'yadi, va
    -- `trip.transport_request_id` NOT NULL bo'lgani uchun har ariza
    -- alohida `trip` qatori bo'lib yoziladi. Ya'ni bir kunda uch ariza
    -- bajargan haydovchiga uchta `trip` yoziladi va `count(*)` uning
    -- tajribasini UCH BAROBAR ko'rsatib yuborardi.
    --
    -- `route_id` `trip` da NOT NULL, shuning uchun bu hisob bugun ham
    -- (1 ariza = 1 marshrut) bir xil natija beradi — o'zgarish faqat
    -- kelajakdagi xatoni oldindan yopadi.
    (select count(distinct t.route_id) from trip t
      where t.driver_id = d.id and t.status = 'COMPLETED')         as completed_trips,
    (select count(*) from driver_completed_trip dct
      where dct.driver_id = d.id)                                  as completed_trips_logged,
    (select count(*) from speed_violation sv
      where sv.driver_id = d.id
        and sv.occurred_at >= %s::date - make_interval(days => %s))  as recent_speed_violations,
    (select count(*) from incident inc
      where inc.driver_id = d.id
        and inc.occurred_at >= %s::date - make_interval(days => %s)) as recent_incidents,
    (select count(*) from vehicle_accident va
      where va.driver_id = d.id
        and va.occurred_at >= %s::date - make_interval(days => %s))  as recent_accidents
from driver d
left join lateral (
    select m.status, m.shift_date, m.alcohol_promille from medical_inspection m
    where m.driver_id = d.id and m.shift_date <= %s::date
    order by m.shift_date desc, m.inspected_at desc limit 1
) mi on true
left join lateral (
    select s.shift_type, s.status, s.planned_start_at, s.planned_end_at, s.planned_hours
    from driver_shift s
    where s.driver_id = d.id and s.shift_date = %s::date
    order by s.updated_at desc limit 1
) sh on true
where to_jsonb(d)->>'deleted_at' is null
order by d.full_name
limit %s
"""


def fetch_drivers(
    *,
    on_date: str,
    window_from: str | None = None,
    window_to: str | None = None,
    history_days: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Nomzod haydovchilar — hamma mezon uchun kerakli ustunlar bilan.

    Tibbiy ko'rik OXIRGISI olinadi (`shift_date <= on_date`), faqat
    bugungisi emas. Sababi: "bugun ko'rikdan o'tmagan" va "umuman ko'rikdan
    o'tmagan" — bular boshqa-boshqa holatlar, va ularni farqlash uchun
    oxirgi ko'rik sanasi kerak. Kesish qarori `rules.py` da.

    Jazo/hodisa jadvallari (`speed_violation`, `incident`,
    `vehicle_accident`) 22.08.2026 da bo'sh edi — so'rov baribir yoziladi,
    chunki ma'lumot kelganda kod o'zgarmasdan ishlashi kerak.
    """
    return _select(
        DRIVERS_SQL,
        (
            list(ACTIVE_TRIP_STATUSES),
            window_from, window_to, window_from, window_to,
            list(OPEN_WAYBILL_STATUSES),
            on_date, history_days,
            on_date, history_days,
            on_date, history_days,
            on_date,
            on_date,
            limit,
        ),
    )


# ------------------------------------------------------- Biriktirilgan juftlik


def fetch_assigned_pairs() -> set[tuple[str, str]]:
    """Mashinaga oldindan biriktirilgan haydovchilar — (vehicle_id, driver_id).

    UCH MANBA BOR va ular to'liq mos kelmaydi (22.08.2026 o'lchovi):
        driver_assigned_vehicles              133 yozuv
        vehicle_assigned_drivers              128 yozuv (128 tasi mos)
        transport_vehicle.assigned_driver_id   84 yozuv

    Uchalasining BIRLASHMASI olinadi. Bu ustama ball uchun, kesish uchun
    emas — noto'g'ri biriktirish natijani buzmaydi, faqat teng ballda
    tartibni o'zgartiradi, shuning uchun kengroq olish xavfsiz.
    """
    rows = _select(
        """
        select vehicle_id::text as vehicle_id, driver_id::text as driver_id
          from vehicle_assigned_drivers
         where vehicle_id is not null and driver_id is not null
        union
        select vehicle_id::text, driver_id::text
          from driver_assigned_vehicles
         where vehicle_id is not null and driver_id is not null
        union
        select id::text, assigned_driver_id::text
          from transport_vehicle
         where assigned_driver_id is not null
        """
    )
    return {(r["vehicle_id"], r["driver_id"]) for r in rows}
