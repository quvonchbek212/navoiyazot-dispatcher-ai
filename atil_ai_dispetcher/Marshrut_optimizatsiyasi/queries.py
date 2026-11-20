"""Bazadan rejalashtirish uchun ma'lumot o'qish — FAQAT SELECT, parametrli.

BAZAGA ZARAR YETMASLIGI uch qatlam bilan kafolatlangan (oil_detection va
vehicle_selection dagi kabi):
  1. bu faylda bitta ham yozuv amali yo'q — faqat `select`;
  2. ulanish `default_transaction_read_only=on` bilan ochiladi;
  3. `.env` dagi baza foydalanuvchisida faqat SELECT huquqi bor.

Sanalar va id'lar FOYDALANUVCHIDAN keladi, shuning uchun ular matnga
yopishtirilmaydi — psycopg2 parametrlari (`%s`) ishlatiladi.

BANDLIK BAYROQDAN OLINMAYDI. `transport_vehicle.current_status` bazada
yangilanmayotgani vehicle_selection modulida aniqlangan edi (aktiv
reysdagi 10 mashinaning 10 tasi ham hali `ACTIVE`). Shuning uchun bu
yerda ham bandlik HODISA jadvallaridan olinadi: `trip` (aktiv holatlar)
va `waybill` (ochiq holatlar) birlashmasi. Band mashinani bo'sh deb
ko'rsatib rejaga qo'yish — bo'shini o'tkazib yuborishdan qimmatroq xato.

KALIBROVKA SO'ROVLARI shu faylda: yo'l koeffitsienti, o'rtacha tezlik va
xizmat vaqti bazadan O'LCHANADI, o'ylab topilmaydi. Hisob-kitobning o'zi
`calibration.py` da — bu yerda faqat xom qatorlar olinadi.
"""

from __future__ import annotations

import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

# `db.connect_db_for_server` paket ichida yassi nom bilan import qiladi
# (`from config import ...`), shuning uchun `atil_chatbot` sys.path da
# bo'lishi shart. main.py buni allaqachon qiladi; bu yerdagi takror shu
# modulni alohida ham ishlata olish uchun.
_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

import psycopg2  # noqa: E402

from db.connect_db_for_server import read_only_cursor  # noqa: E402

logger = logging.getLogger(__name__)

#: Reys tugamagan hisoblanadigan holatlar — mashina band.
ACTIVE_TRIP_STATUSES = (
    "PLANNED", "ASSIGNED", "STARTED", "ARRIVED_AT_POINT", "LOADED", "UNLOADED",
)

#: Yo'l varaqasi ochiq — mashina yo'lda.
OPEN_WAYBILL_STATUSES = ("ISSUED", "IN_USE")

#: Mashina yo'lga chiqa olmaydigan holatlar.
BLOCKED_VEHICLE_STATUSES = ("IN_MAINTENANCE", "BLOCKED", "DECOMMISSIONED")

#: Modul o'qiydigan jadvallar — `data_quality.row_counts` da shular chiqadi.
SOURCE_TABLES = (
    "transport_request",
    "transport_request_point",
    "reference_data",
    "shipment",
    "transport_vehicle",
    "driver",
    "driver_shift",
    "route",
    "route_point",
    "trip",
    "trip_event",
    "waybill",
    "vehicle_telemetry_state",
    "dock",
    "dock_slot",
    "hazard_profile",
    "tariff",
)


class PlanningDataError(RuntimeError):
    """Bazadan o'qib bo'lmadi — router buni 503 ga aylantiradi."""


def _select(
    sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    try:
        with read_only_cursor() as cur:
            # Lug'at berilsa `%(nom)s`, ketma-ketlik berilsa `%s` ishlaydi.
            # Snapshot so'rovida o'nga yaqin parametr bor va ularni tartib
            # bo'yicha sanash xato manbai bo'lardi.
            cur.execute(sql, params if isinstance(params, Mapping) else tuple(params or ()))
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as exc:
        message = (getattr(exc, "pgerror", None) or str(exc)).strip().splitlines()[0]
        logger.warning("Rejalashtirish so'rovi bajarilmadi: %s", message[:300])
        raise PlanningDataError(message[:300]) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bazaga ulanishda kutilmagan xato")
        raise PlanningDataError(f"{type(exc).__name__}: {exc}"[:300]) from exc


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


SNAPSHOT_SQL = """
select
    -- ---------------------------------------------------------- Arizalar
    (select count(*) from transport_request)                                as rows_transport_request,
    (select count(*) from transport_request
      where status = any(%(statuses)s))                                     as ok_request_status,
    (select count(*) from transport_request
      where origin_latitude is not null and origin_longitude is not null
        and destination_latitude is not null
        and destination_longitude is not null)                              as ok_request_coords,
    (select count(*) from transport_request where cargo_weight_kg > 0)      as ok_request_weight,

    (select count(*) from transport_request_point)                          as rows_transport_request_point,
    (select count(*) from transport_request_point
      where latitude is not null and longitude is not null)                 as ok_point_coords,

    -- ----------------------------------------------------- Manzil katalogi
    (select count(*) from reference_data)                                   as rows_reference_data,
    (select count(*) from reference_data
      where catalog_type = 'LOCATIONS' and active
        and latitude is not null and longitude is not null)                 as ok_location_catalog,
    (select count(*) from reference_data
      where catalog_type = 'BRANCHES' and active
        and latitude is not null and longitude is not null)                 as ok_branch_catalog,

    -- --------------------------------------------------------- Mashinalar
    (select count(*) from transport_vehicle)                                as rows_transport_vehicle,
    (select count(*) from transport_vehicle
      where current_status <> all (%(blocked)s))                            as ok_vehicle_status,
    (select count(*) from transport_vehicle where payload_capacity_kg > 0)  as ok_vehicle_capacity,
    (select count(*) from transport_vehicle where branch_id is not null)    as ok_vehicle_branch,

    (select count(*) from vehicle_telemetry_state)                          as rows_vehicle_telemetry_state,
    (select count(*) from vehicle_telemetry_state
      where last_latitude is not null and last_longitude is not null)       as ok_vehicle_position,

    (select count(*) from driver)                                           as rows_driver,
    (select count(*) from driver_shift)                                     as rows_driver_shift,
    (select count(*) from driver_shift
      where planned_start_at is not null and planned_end_at is not null)    as ok_driver_shift,

    -- ------------------------------------------------------------ Bandlik
    (select count(*) from trip)                                             as rows_trip,
    (select count(*) from trip
      where status = any(%(active_trips)s)
        and scheduled_departure_at is not null
        and scheduled_arrival_at is not null)                               as ok_trip_schedule,
    (select count(*) from waybill)                                          as rows_waybill,
    (select count(*) from waybill
      where status = any(%(open_waybills)s)
        and planned_departure_at is not null
        and planned_return_at is not null)                                  as ok_waybill_schedule,

    -- --------------------------------------------------------- Kalibrovka
    -- Shartlar `fetch_speed_samples` / `fetch_road_factor_samples` /
    -- `fetch_service_time_samples` bilan AYNAN bir xil: bu yerdagi son
    -- "o'lchovga yaroqli qator" degani. Yakuniy fizik filtr
    -- (`calibration._clean`) undan keyin ishlaydi, ya'ni haqiqiy o'lchov
    -- soni shu sondan kichik bo'lishi mumkin.
    (select count(*) from trip
      where status = 'COMPLETED'
        and actual_departure_at is not null and actual_arrival_at is not null
        and actual_arrival_at > actual_departure_at
        and actual_distance_km > 0
        and actual_departure_at >= (now() - make_interval(days => %(days)s))) as ok_trip_speed,
    (select count(*) from route)                                            as rows_route,
    (select count(*) from route_point)                                      as rows_route_point,
    (select count(*) from route_point
      where distance_from_previous_km > 0
        and drive_duration_from_previous_minutes > 0)                       as ok_route_point_speed,
    (select count(*) from route_point p
      join lateral (
          select r2.latitude, r2.longitude
          from route_point r2
          where r2.route_id = p.route_id
            and r2.sequence_number < p.sequence_number
          order by r2.sequence_number desc
          limit 1
      ) prev on true
      where p.distance_from_previous_km > 0
        and p.latitude is not null and p.longitude is not null
        and prev.latitude is not null and prev.longitude is not null)       as ok_road_factor_pairs,

    (select count(*) from trip_event)                                       as rows_trip_event,
    (with ev as (
        select
            e.trip_id, e.event_type, e.event_time,
            lag(e.event_time) over (partition by e.trip_id order by e.event_time) as prev_time,
            lag(e.event_type) over (partition by e.trip_id order by e.event_time) as prev_type
        from trip_event e
        where e.event_type in ('TRIP_ARRIVED_AT_POINT', 'TRIP_LOADED', 'TRIP_UNLOADED')
          and e.event_time >= (now() - make_interval(days => %(days)s))
     )
     select count(*) from ev
      where prev_type = 'TRIP_ARRIVED_AT_POINT'
        and event_type in ('TRIP_LOADED', 'TRIP_UNLOADED')
        and event_time > prev_time)                                         as ok_service_pairs,

    -- --------------------------------------------------------- Xavfli yuk
    (select count(*) from shipment)                                         as rows_shipment,
    (select count(*) from shipment where hazard_profile_id is not null)     as ok_shipment_hazard,
    (select count(*) from hazard_profile)                                   as rows_hazard_profile,

    -- --------------------------------------------------------------- Dock
    (select count(*) from dock)                                             as rows_dock,
    (select count(*) from dock_slot)                                        as rows_dock_slot,
    (select count(*) from dock_slot where status = 'AVAILABLE')             as ok_dock_slot_available,

    (select count(*) from tariff)                                           as rows_tariff
"""


def data_snapshot(
    *,
    statuses: Sequence[str] = (),
    calibration_days: int | None = None,
) -> dict[str, int]:
    """Bazaning rejalashtirishga tayyorligi — BITTA so'rovda.

    Ikki xil son qaytadi:

        `rows_<jadval>`   jadvaldagi jami qator
        `ok_<narsa>`      rejalashtirishga YAROQLI qator: kerakli ustunlari
                          to'lgan, holati mos

    NIMA UCHUN `count(*)`, `pg_stat_user_tables` EMAS. Ilgari bu yerda
    `n_live_tup` o'qilardi — u yengil, lekin bu bazada YOLG'ON: statistika
    hech qachon yig'ilmagan (`last_analyze` ham, `last_autoanalyze` ham
    NULL), shuning uchun `transport_request` da 140 qator turganda javobda
    0 ko'rinardi. `data_quality` ning butun vazifasi "manba bo'shmi yoki
    reja chiqmadimi" ni ajratish edi va u shu vazifasini teskari bajarardi.

    Aniq son bu yerda qimmat emas: butun sxemada 2000 dan kam qator bor va
    hammasi BITTA so'rovda, bitta borib-kelishda olinadi.

    `ok_*` shartlari `fetch_*` so'rovlaridagi shartlarning AYNAN o'zi —
    aks holda "ma'lumot bor" deb ko'rsatib, uni o'lchovda ishlatmagan
    bo'lardik.
    """
    rows = _select(
        SNAPSHOT_SQL,
        {
            "statuses": list(statuses or []),
            "blocked": list(BLOCKED_VEHICLE_STATUSES),
            "active_trips": list(ACTIVE_TRIP_STATUSES),
            "open_waybills": list(OPEN_WAYBILL_STATUSES),
            "days": int(calibration_days if calibration_days is not None else 365),
        },
    )
    return {key: int(value or 0) for key, value in (rows[0] if rows else {}).items()}


def row_counts(
    snapshot: dict[str, int], tables: Sequence[str] = SOURCE_TABLES
) -> dict[str, int]:
    """`data_quality.row_counts` — snapshot'dagi `rows_*` lardan yig'iladi.

    Alohida so'rov qilinmaydi: sonlar `data_snapshot()` da allaqachon
    o'qilgan.
    """
    return {name: int(snapshot.get(f"rows_{name}", 0)) for name in tables}


# ------------------------------------------------------------------ Arizalar


REQUESTS_SQL = """
select
    r.id::text                       as request_id,
    r.request_number,
    r.request_type,
    r.status,
    r.priority,
    r.required_transport_type,
    r.cargo_description,
    r.cargo_weight_kg,
    r.cargo_volume_m3,
    r.cargo_places,
    r.special_requirements,
    r.origin_location,
    r.origin_location_id::text       as origin_location_id,
    r.origin_latitude,
    r.origin_longitude,
    r.destination_location,
    r.destination_location_id::text  as destination_location_id,
    r.destination_latitude,
    r.destination_longitude,
    coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at) as planned_departure_at,
    coalesce((nullif(to_jsonb(r)->>'planning_end_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_arrival_at) as planned_arrival_at,
    r.department_name,
    r.from_warehouse_name,
    r.to_warehouse_name,
    r.binding_vehicle_id::text       as binding_vehicle_id,
    r.binding_driver_id::text        as binding_driver_id,
    r.binding_route_id::text         as binding_route_id,

    -- WMS jo'natmasi: arizada bo'sh qolgan maydonlarni SHU TO'LDIRADI.
    -- Og'irlik ikki xil birlikda yozilishi mumkin (kg yoki tonna).
    s.id::text                       as shipment_id,
    s.cargo_weight_kg                as shipment_weight_kg,
    s.weight_tons                    as shipment_weight_tons,
    s.cargo_volume_m3                as shipment_volume_m3,
    s.ready_at                       as shipment_ready_at,
    s.requested_delivery_at          as shipment_requested_delivery_at,
    s.scheduled_pickup_at            as shipment_scheduled_pickup_at,
    s.scheduled_delivery_at          as shipment_scheduled_delivery_at,

    -- Xavfli yuk: ariza -> jo'natma -> xavf profili. Arizaning o'zida
    -- xavflilik ustuni yo'q, shuning uchun yagona avtomatik yo'l shu.
    coalesce(s.un_number, h.un_number)    as un_number,
    coalesce(s.hazard_class, h.hazard_class) as hazard_class,
    h.requires_special_tank          as requires_special_tank,
    h.requires_adr                   as requires_adr,
    h.official_name                  as hazard_name
from transport_request r
left join shipment s on s.id = r.wms_shipment_id
left join hazard_profile h on h.id = s.hazard_profile_id
where (%s::boolean is false or r.status = any(%s))
  and (%s::boolean is false or r.id = any(%s::uuid[]))
  and (%s::date is null
       or coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at) is null
       or coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at)::date <= %s::date)
order by
    case r.priority
        when 'CRITICAL' then 0 when 'URGENT' then 1
        when 'HIGH' then 2 else 3 end,
    coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at) nulls last,
    r.created_at
limit %s
"""


def fetch_requests(
    *,
    statuses: Sequence[str],
    request_ids: Sequence[str] | None,
    on_date: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Rejalashtirishni kutayotgan arizalar.

    `request_ids` berilsa holat filtri O'CHADI: dispetcher aniq arizani
    ko'rsatgan bo'lsa uning holati bizga emas, unga tegishli.

    Sana filtri "shu kungacha" — kechagi rejalashtirilmagan ariza bugungi
    rejaga tushishi kerak, aks holda u abadiy osilib qoladi.
    """
    ids = [str(x) for x in (request_ids or [])]
    use_ids = bool(ids)
    use_statuses = bool(statuses) and not use_ids
    return _select(
        REQUESTS_SQL,
        (
            use_statuses, list(statuses or []),
            use_ids, ids,
            on_date, on_date,
            int(limit),
        ),
    )


REQUEST_POINTS_SQL = """
select
    p.transport_request_id::text as request_id,
    p.sequence_number,
    p.point_type,
    p.location_id::text          as location_id,
    p.location_name,
    p.address,
    p.latitude,
    p.longitude,
    coalesce((nullif(to_jsonb(p)->>'planning_end_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),p.planned_arrival_at) as planned_arrival_at,
    coalesce((nullif(to_jsonb(p)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),p.planned_departure_at) as planned_departure_at,
    p.distance_from_previous_km,
    p.drive_duration_from_previous_minutes
from transport_request_point p
where p.transport_request_id = any(%s::uuid[])
order by p.transport_request_id, p.sequence_number
"""


def fetch_request_points(request_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Arizaning o'z nuqtalari — `transport_request` dagi manzildan aniqroq.

    `transport_request_point` da koordinata va vaqt oynasi bor. Bo'sh
    bo'lsa (25.08.2026 da 0 qator) arizaning o'z `origin_*`/`destination_*`
    ustunlariga qaytiladi.
    """
    if not request_ids:
        return []
    return _select(REQUEST_POINTS_SQL, ([str(x) for x in request_ids],))


# ---------------------------------------------------------------- Mashinalar


VEHICLES_SQL = """
select
    v.id::text                  as vehicle_id,
    v.plate_number,
    v.brand,
    v.model,
    v.transport_type,
    v.category,
    v.current_status,
    coalesce(v.payload_capacity_kg,nullif(to_jsonb(v)->>'cargo_capacity_tons','')::numeric*1000) as payload_capacity_kg,
    v.volume_m3,
    coalesce(v.seat_count,nullif(to_jsonb(v)->>'passenger_capacity','')::integer) as seat_count,
    v.branch_id::text           as branch_id,
    v.department_id::text       as department_id,
    v.assigned_driver_id::text  as assigned_driver_id,

    d.full_name                 as driver_name,

    -- Mashina hozir qayerda. Telematika bo'sh bo'lsa null bo'ladi va
    -- chiqish nuqtasi sifatida garaj (depot) ishlatiladi.
    ts.last_latitude            as last_latitude,
    ts.last_longitude           as last_longitude,
    ts.last_event_at            as last_event_at,

    -- Haydovchi smenasi: reys oynasi shundan olinadi.
    sh.planned_start_at         as shift_start_at,
    sh.planned_end_at           as shift_end_at,
    sh.planned_hours            as shift_hours,
    sh.shift_type               as shift_type,

    -- Bandlik: hodisa jadvallaridan, bayroqdan emas.
    --
    -- VAQT BO'YICHA KESILADI, "aktiv reysi bor" degani bilan emas.
    -- Ertalab 11:00 da reysini tugatadigan mashina tushdan keyingi
    -- marshrutga yaroqli. "Aktiv reysi bori band" desak, park yarim
    -- kunga bekor turgan bo'lib ko'rinardi va reja qashshoq chiqardi.
    --
    -- Reysning vaqti NOMA'LUM bo'lsa BAND deb hisoblanadi: bo'sh
    -- ekanini isbotlab bo'lmasa, band deyish xavfsiz tomon.
    (select t.id::text from trip t
      where t.vehicle_id = v.id and t.status = any(%s)
        and (%s::timestamp is null or %s::timestamp is null
             or t.scheduled_departure_at is null or t.scheduled_arrival_at is null
             or (t.scheduled_departure_at, t.scheduled_arrival_at)
                 overlaps (%s::timestamp, %s::timestamp))
      order by t.scheduled_departure_at limit 1)            as busy_trip_id,
    (select w.waybill_number from waybill w
      where w.vehicle_id = v.id and w.status = any(%s)
        and (%s::timestamp is null or %s::timestamp is null
             or w.planned_departure_at is null or w.planned_return_at is null
             or (w.planned_departure_at, w.planned_return_at)
                 overlaps (%s::timestamp, %s::timestamp))
      order by w.issue_date desc limit 1)                   as open_waybill_number,

    -- Bloklovchi ochiq remont bormi (vehicle_selection dagi qoida).
    (select count(*) from vehicle_repair vr
      where vr.vehicle_id = v.id and coalesce(vr.blocks_release, false)
        and coalesce(vr.status, '') <> all (array['CLOSED','COMPLETED','CANCELLED',
                                                  'ARM_CLOSED','REJECTED','REPAIRED'])
    )                                                       as blocking_repairs
from transport_vehicle v
left join driver d on d.id = v.assigned_driver_id
left join vehicle_telemetry_state ts on ts.vehicle_id = v.id
left join lateral (
    select s.* from driver_shift s
    where s.driver_id = v.assigned_driver_id
      and s.shift_date = %s::date
      and s.status <> 'CANCELLED'
    order by s.planned_start_at nulls last
    limit 1
) sh on true
where (%s::boolean is false or v.transport_type = any(%s))
  and (%s::boolean is false or v.id = any(%s::uuid[]))
  and v.current_status <> all (%s)
order by v.payload_capacity_kg desc nulls last, v.plate_number
limit %s
"""


def fetch_vehicles(
    *,
    on_date: str,
    transport_types: Sequence[str] | None,
    vehicle_ids: Sequence[str] | None,
    limit: int,
    window_from: str | None = None,
    window_to: str | None = None,
) -> list[dict[str, Any]]:
    """Rejalashtirishga tayyor mashinalar.

    `transport_types` — arizalar talab qilgan turlar. Butun parkni
    o'qishning ma'nosi yo'q: `TANKER` so'ralganda `BUS` larni tortish
    faqat vaqt sarflaydi.

    `window_from`/`window_to` — reja oynasi. Bandlik SHU OYNA bilan
    kesishishiga qarab aniqlanadi: kunning boshqa qismida band mashina
    bu rejaga yaroqli. Oyna berilmasa har qanday aktiv reys band deb
    hisoblanadi (eski, ehtiyotkor xulq).

    Bandlik bu yerda KESILMAYDI, faqat belgilanadi (`busy_trip_id`,
    `open_waybill_number`) — kesish qarori `optimizer.py` da, chunki
    "band" ni javobda ko'rsatish kerak.
    """
    types = [str(t) for t in (transport_types or []) if t]
    ids = [str(v) for v in (vehicle_ids or [])]
    return _select(
        VEHICLES_SQL,
        (
            list(ACTIVE_TRIP_STATUSES),
            window_from, window_to, window_from, window_to,
            list(OPEN_WAYBILL_STATUSES),
            window_from, window_to, window_from, window_to,
            on_date,
            bool(types), types,
            bool(ids), ids,
            list(BLOCKED_VEHICLE_STATUSES),
            int(limit),
        ),
    )


# ------------------------------------------------------------------ Manzil


LOCATION_SQL = """
select location_id, location_name, latitude, longitude, source from (
    -- 1. ASOSIY MANBA: manzil katalogi. `reference_data` da manzil
    --    ham `id`, ham `location_id` bo'yicha yozilishi mumkin.
    select
        coalesce(rd.location_id, rd.id)::text as location_id,
        coalesce(rd.name, rd.short_name, rd.address) as location_name,
        rd.latitude,
        rd.longitude,
        0 as priority,
        1 as sequence_number,
        'reference_data' as source
    from reference_data rd
    where rd.catalog_type = 'LOCATIONS'
      and rd.active
      and (rd.id = %s::uuid or rd.location_id = %s::uuid)

    union all

    -- 2. Marshrutlarda amalda ishlatilgan nuqtalar.
    select
        p.location_id::text,
        p.location_name,
        p.latitude,
        p.longitude,
        1,
        p.sequence_number,
        'route_point'
    from route_point p
    where p.location_id = %s::uuid

    union all

    select
        q.location_id::text,
        q.location_name,
        q.latitude,
        q.longitude,
        2,
        q.sequence_number,
        'transport_request_point'
    from transport_request_point q
    where q.location_id = %s::uuid
) src
order by (latitude is not null) desc, priority, sequence_number
limit 1
"""


def fetch_location(location_id: str) -> dict[str, Any] | None:
    """Manzilni id bo'yicha yechadi — nomi va koordinatasi.

    UCH MANBA, ANIQ TARTIBDA:

      1. `reference_data` (`catalog_type='LOCATIONS'`) — ATIL ning
         RASMIY manzil katalogi. Unda `latitude`, `longitude`, `address`
         ustunlari bor, ya'ni sxema aynan shu ish uchun qilingan.
      2. `route_point` — marshrutlarda amalda ishlatilgan nuqtalar.
      3. `transport_request_point` — arizaning o'z nuqtalari.

    Koordinatasi bori har doim ustun: katalogda yozuv bor-u koordinatasi
    yo'q bo'lsa, marshrutdagi koordinatali nusxasi olinadi.

    NIMA UCHUN UCHALASI: 25.08.2026 da katalog bo'sh edi
    (`catalog_type='LOCATIONS'` -> 0 qator) va marshrutlar `route_point`
    dagi id'lar bilan ishlayotgan edi. Katalog to'ldirilganda modul
    O'ZI birinchi manbaga o'tadi — kodni o'zgartirish kerak emas. Manba
    javobda `source` bo'lib qaytadi, ya'ni koordinata qayerdan
    kelgani ko'rinib turadi.
    """
    rows = _select(LOCATION_SQL, (location_id, location_id, location_id, location_id))
    return rows[0] if rows else None


BRANCH_DEPOT_SQL = """
select
    coalesce(rd.branch_id, rd.id)::text as branch_id,
    coalesce(rd.name, rd.short_name)    as name,
    rd.address,
    rd.latitude,
    rd.longitude
from reference_data rd
where rd.catalog_type = 'BRANCHES'
  and rd.active
  and rd.latitude is not null
  and rd.longitude is not null
"""


def fetch_branch_depots() -> dict[str, dict[str, Any]]:
    """Filiallarning koordinatasi — mashinaning GARAJI shu.

    NIMA UCHUN BU KERAK: mashinaning turgan joyi `vehicle_telemetry_state`
    dan olinadi, u esa bo'sh bo'lishi mumkin (25.08.2026 da 0 qator).
    Unda mashina o'z FILIALIDAN chiqadi deb hisoblanadi —
    `transport_vehicle.branch_id` -> `reference_data` (BRANCHES).

    Bu so'rovdagi `depot_latitude` parametridan YAXSHIROQ: park bir necha
    filialga bo'lingan bo'lsa, har bir mashina o'z garajidan chiqadi,
    hammasi bitta nuqtadan emas. Parametr esa faqat ZAXIRA bo'lib qoladi.

    Katalog bo'sh bo'lsa bo'sh lug'at qaytadi va chaqiruvchi parametrga
    tushadi — bu ham javobda ochiq yoziladi.
    """
    return {
        row["branch_id"]: row
        for row in _select(BRANCH_DEPOT_SQL)
        if row.get("branch_id")
    }


# ------------------------------------------------------------- Xavfli yuk


# Xavfli yuk `REQUESTS_SQL` ichida `shipment` -> `hazard_profile` zanjiri
# bilan avtomatik olinadi. Alohida "UN raqamini bering" degan parametr
# yo'q: xavflilik SO'ROVGA emas, AYRIM ARIZAGA tegishli xususiyat va
# uni odam qo'lda kiritishi xato manbai bo'lardi.


DOCK_SQL = """
select
    ds.id::text          as slot_id,
    ds.name              as slot_name,
    ds.status,
    ds.location_id::text as location_id
from dock_slot ds
where (%s::boolean is false or ds.location_id = any(%s::uuid[]))
"""


def fetch_dock_slots(location_ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """Yuklash joylaridagi dock slotlari.

    Bu QATTIQ CHEKLOV EMAS, OGOHLANTIRISH. `dock_slot` da ish vaqti ham,
    xizmat davomiyligi ham yo'q — faqat `status`. Ya'ni "bir vaqtda
    nechta mashina sig'adi" degan savolga baza javob bermaydi. Modul
    slotlar sonini o'qiydi va bir joyga bir vaqtda kelayotgan mashina
    slotlardan ko'p bo'lsa marshrutga OGOHLANTIRISH yozadi.
    """
    ids = [str(x) for x in (location_ids or [])]
    return _select(DOCK_SQL, (bool(ids), ids))


# ---------------------------------------------------- Kalibrovka (xom qator)


ROAD_FACTOR_SQL = """
select
    p.distance_from_previous_km as distance_km,
    prev.latitude               as from_lat,
    prev.longitude              as from_lon,
    p.latitude                  as to_lat,
    p.longitude                 as to_lon
from route_point p
join lateral (
    select r2.latitude, r2.longitude
    from route_point r2
    where r2.route_id = p.route_id
      and r2.sequence_number < p.sequence_number
    order by r2.sequence_number desc
    limit 1
) prev on true
where p.distance_from_previous_km > 0
  and p.latitude is not null and p.longitude is not null
  and prev.latitude is not null and prev.longitude is not null
limit %s
"""


def fetch_road_factor_samples(limit: int = 5000) -> list[dict[str, Any]]:
    """Yo'l koeffitsientini o'lchash uchun xom qatorlar.

    Har bir juft ketma-ket nuqta uchun BAZADAGI yo'l masofasi va o'sha
    ikki koordinata orasidagi TO'G'RI CHIZIQ olinadi. Ularning nisbati —
    "to'g'ri chiziqni yo'lga aylantiruvchi" koeffitsient.

    Shu tarzda "1.3" degan raqam o'ylab topilmaydi: u ATIL ning o'z
    yo'llaridan chiqadi va yangi marshrutlar qo'shilgani sari aniqlashadi.
    """
    return _select(ROAD_FACTOR_SQL, (int(limit),))


TRIP_SPEED_SQL = """
select
    t.actual_distance_km as distance_km,
    extract(epoch from (t.actual_arrival_at - t.actual_departure_at)) / 60.0 as minutes
from trip t
where t.status = 'COMPLETED'
  and t.actual_departure_at is not null
  and t.actual_arrival_at is not null
  and t.actual_arrival_at > t.actual_departure_at
  and t.actual_distance_km > 0
  and t.actual_departure_at >= (now() - make_interval(days => %s))
limit %s
"""

ROUTE_POINT_SPEED_SQL = """
select
    p.distance_from_previous_km as distance_km,
    p.drive_duration_from_previous_minutes::float as minutes
from route_point p
where p.distance_from_previous_km > 0
  and p.drive_duration_from_previous_minutes > 0
limit %s
"""


def fetch_speed_samples(days: int, limit: int = 5000) -> dict[str, list[dict[str, Any]]]:
    """O'rtacha tezlikni o'lchash uchun xom qatorlar — ikki manbadan.

    `trip` — HAQIQIY reyslar (jo'nash/yetib borish vaqti va bosib
    o'tilgan masofa). Eng ishonchli manba, chunki unda kutish ham,
    tirbandlik ham bor.

    `route_point` — REJA raqamlari (masofa va yo'l daqiqasi). Reys tarixi
    yetmasa shu ishlatiladi va javobda `speed_source` `route_point`
    bo'lib ko'rinadi — dispetcher raqam qayerdan kelganini biladi.
    """
    return {
        "trip": _select(TRIP_SPEED_SQL, (int(days), int(limit))),
        "route_point": _select(ROUTE_POINT_SPEED_SQL, (int(limit),)),
    }


SERVICE_TIME_SQL = """
with ev as (
    select
        e.trip_id,
        e.event_type,
        e.event_time,
        lag(e.event_time) over (partition by e.trip_id order by e.event_time) as prev_time,
        lag(e.event_type) over (partition by e.trip_id order by e.event_time) as prev_type
    from trip_event e
    where e.event_type in ('TRIP_ARRIVED_AT_POINT', 'TRIP_LOADED', 'TRIP_UNLOADED')
      and e.event_time >= (now() - make_interval(days => %s))
)
select extract(epoch from (event_time - prev_time)) / 60.0 as minutes
from ev
where prev_type = 'TRIP_ARRIVED_AT_POINT'
  and event_type in ('TRIP_LOADED', 'TRIP_UNLOADED')
  and event_time > prev_time
limit %s
"""


def fetch_service_time_samples(days: int, limit: int = 5000) -> list[dict[str, Any]]:
    """Nuqtadagi xizmat vaqtini o'lchash uchun xom qatorlar.

    "Yetib bordi" hodisasidan "yukladi"/"tushirdi" hodisasigacha o'tgan
    vaqt — bu haqiqiy yuklash/tushirish davomiyligi. `trip_event` da bu
    hodisalar 25.08.2026 da bor (ARRIVED_AT_POINT 13, LOADED 12,
    UNLOADED 12), lekin bir reys ichida ketma-ketligi yetarli emas.
    Ma'lumot ko'paygani sari o'lchov aniqlashadi.
    """
    return _select(SERVICE_TIME_SQL, (int(days), int(limit)))


# NARX HISOBI HOZIRCHA YO'Q. `tariff` jadvalida bitta qator bor
# (25.08.2026) va `fuel_norm` bo'sh, ya'ni "bu reja necha so'm turadi"
# degan savolga baza javob bermaydi. Narxni km ga ko'paytirib chiqarish
# mumkin edi, lekin u O'YLAB TOPILGAN raqam bo'lardi.
#
# `tariff` (pricing_model = PER_KM / PER_TON_KM / PER_TRIP) va
# `fuel_norm` (liters_per100km) to'lganda bu yerga narx so'rovi
# qo'shiladi va `summary` ga `estimated_cost` chiqadi. O'shanda maqsad
# funksiyasini ham masofa emas, PUL qilib qo'yish mumkin bo'ladi.
