"""Parametrli SELECT so'rovlari; har bir sessiya READ ONLY."""

from __future__ import annotations

import logging
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from atil_ai_dispetcher.fleet_yard_llm import config
from atil_ai_dispetcher.fleet_yard_llm.monitor_history import StreamingHistory

_CHATBOT_DIR = str(Path(__file__).resolve().parents[2] / "atil_chatbot")
if _CHATBOT_DIR not in sys.path:
    sys.path.insert(0, _CHATBOT_DIR)

from db.connect_db_for_server import read_only_cursor  # noqa: E402

logger = logging.getLogger(__name__)


class YardDataError(RuntimeError):
    """Bazaga ulanish yoki sxema xatosi. HTTP qatlamida 503."""


class VehicleNotFound(LookupError):
    pass


class AmbiguousPlate(ValueError):
    pass


TABLES = (
    "transport_vehicle", "vehicle_gps", "telematics_event", "position_log",
    "gps_archive_point", "gps_archive_coverage", "vehicle_telemetry_state",
    "telematics_geozone", "gps_event_zone", "gps_event_policy", "gps_event_evaluation",
    "gps_ingest_event", "gps_ingest_receipt", "trip", "waybill", "vehicle_repair", "transport_request",
)


@contextmanager
def _cursor() -> Iterator[Any]:
    try:
        with read_only_cursor() as cur:
            # DB_READ_ONLY=false bo'lgan muhitda ham bu modul yozolmaydi.
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL TIME ZONE 'Asia/Tashkent'")
            yield cur
    except (VehicleNotFound, YardDataError):
        raise
    except Exception as exc:
        # Server manzili va credentiallar HTTP javobiga yoki logga chiqmaydi.
        logger.warning("Fleet yard DB o'qish xatosi: %s", type(exc).__name__)
        raise YardDataError("ATIL bazasidan o'qib bo'lmadi; ulanish va sxemani tekshiring.") from exc


def _schema(cur: Any) -> dict[str, set[str]]:
    cur.execute(
        """select table_name, column_name from information_schema.columns
           where table_schema = current_schema() and table_name = any(%s)""",
        (list(TABLES),),
    )
    result: dict[str, set[str]] = {}
    for row in cur.fetchall():
        result.setdefault(row["table_name"], set()).add(row["column_name"])
    return result


def _require(schema: dict[str, set[str]], table: str, columns: set[str]) -> None:
    missing = columns - schema.get(table, set())
    if missing:
        raise YardDataError(f"Sxema yoki SELECT huquqi yetishmaydi: {table} ({', '.join(sorted(missing))}).")


def readiness() -> dict[str, Any]:
    """Statistika taxmini o'rniga haqiqiy EXISTS va kichik reyestr COUNT'i."""
    with _cursor() as cur:
        schema = _schema(cur)
        sources = {}
        for table in TABLES:
            if table not in schema:
                sources[table] = {"available": False, "has_rows": None}
                continue
            cur.execute(sql.SQL("select exists(select 1 from {}) as present").format(sql.Identifier(table)))
            sources[table] = {"available": True, "has_rows": cur.fetchone()["present"]}
        _require(schema, "transport_vehicle", {"id"})
        _require(schema, "vehicle_gps", {"vehicle_id", "active", "verified_from", "unbound_at"})
        cur.execute("select count(*) as n from transport_vehicle")
        total = int(cur.fetchone()["n"])
        cur.execute("""select count(distinct vehicle_id) as n from vehicle_gps
                       where active and verified_from <= current_timestamp and unbound_at is null""")
        mapped = int(cur.fetchone()["n"])
    populated = [name for name in HISTORY_SQL if sources.get(name, {}).get("has_rows")]
    ready = bool(populated)
    notes = []
    if not ready:
        notes.append("GPS manbalarida nuqta yo'q; keldi-ketdi uchun GPS oqimini ulash kerak.")
    if not sources.get("gps_event_zone", {}).get("has_rows"):
        notes.append("Versiyalangan garaj geozonasi sozlanmagan; pilotda zone so'rov orqali beriladi.")
    return {
        "generated_at": datetime.now(config.TZ), "status": "HISTORY_AVAILABLE" if ready else "NOT_READY",
        "fleet_total": total, "verified_gps_vehicles": mapped,
        "populated_gps_sources": populated,
        "sources": sources, "notes": notes,
        "ai": {"enabled_by_default": True, "max_vehicles_per_page": config.AI_MAX_VEHICLES,
               "default_page_size": config.DEFAULT_LIMIT, "model_status": "CHECKED_WHEN_ANALYZING"},
    }


def zones() -> list[dict[str, Any]]:
    """Eski tizimdagi radiusli DEPOT zonalar; yangi JSON kontrakti taxmin qilinmaydi."""
    with _cursor() as cur:
        cur.execute("""select id::text, name, latitude, longitude, radius_meters
                       from telematics_geozone
                       where active and type = 'DEPOT'
                       order by name, id limit 1001""")
        return [dict(row) for row in cur.fetchall()]


HISTORY_SQL = {
    "telematics_event": """
        select e.timestamp, e.latitude, e.longitude, true as valid,
               e.speed_kph, e.engine_on
        from telematics_event e
        where e.vehicle_id = %s::uuid and e.timestamp >= %s and e.timestamp <= %s
          and exists (
              select 1 from vehicle_gps g
              where g.vehicle_id = e.vehicle_id and g.verified_from <= e.timestamp
                and (g.unbound_at is null or e.timestamp < g.unbound_at)
                and (e.binding_id is null or e.binding_id = g.id)
          )
        order by e.timestamp, e.id limit %s
    """,
    "position_log": """
        select p.fix_time as timestamp, p.latitude, p.longitude, p.valid,
               null::numeric as speed_kph, null::boolean as engine_on
        from position_log p
        where p.fix_time >= %s and p.fix_time <= %s
          and exists (
              select 1 from vehicle_gps g
              where g.vehicle_id = %s::uuid and g.device_id = p.device_id
                and g.verified_from <= p.fix_time
                and (g.unbound_at is null or p.fix_time < g.unbound_at)
                and not exists (
                    select 1 from vehicle_gps other
                    where other.device_id = p.device_id and other.id <> g.id
                      and other.verified_from <= p.fix_time
                      and (other.unbound_at is null or p.fix_time < other.unbound_at)
                )
          )
        order by p.fix_time, p.id limit %s
    """,
    "gps_archive_point": """
        select a.fix_time as timestamp, a.payload
        from gps_archive_point a
        join vehicle_gps g on g.id = a.binding_id and g.vehicle_id = a.vehicle_id
        where a.vehicle_id = %s::uuid and a.fix_time >= %s and a.fix_time <= %s
          and g.verified_from <= a.fix_time
          and (g.unbound_at is null or a.fix_time < g.unbound_at)
        order by a.fix_time, a.provider_point_id limit %s
    """,
}


def history(*, vehicle_id: str, from_at: datetime, to_at: datetime, source: str) -> dict[str, Any]:
    if source not in HISTORY_SQL:
        raise ValueError("Noma'lum GPS manbasi")
    with _cursor() as cur:
        schema = _schema(cur)
        _require(schema, "vehicle_gps", {"id", "vehicle_id", "verified_from", "unbound_at"})
        _require(schema, source, {
            "telematics_event": {"timestamp", "vehicle_id", "latitude", "longitude", "speed_kph", "engine_on", "binding_id"},
            "position_log": {"fix_time", "latitude", "longitude", "valid", "device_id"},
            "gps_archive_point": {"fix_time", "payload", "binding_id", "vehicle_id", "provider_point_id"},
        }[source])
        cur.execute("select id::text, plate_number from transport_vehicle where id = %s::uuid", (vehicle_id,))
        vehicle = cur.fetchone()
        if vehicle is None:
            raise VehicleNotFound(vehicle_id)
        if source == "position_log":
            _require(schema, "vehicle_gps", {"device_id"})
            params = (from_at, to_at, vehicle_id, config.MAX_POINTS + 1)
        else:
            params = (vehicle_id, from_at, to_at, config.MAX_POINTS + 1)
        cur.execute(HISTORY_SQL[source], params)
        rows = [dict(row) for row in cur.fetchall()]
    return {"vehicle": dict(vehicle), "rows": rows[:config.MAX_POINTS], "truncated": len(rows) > config.MAX_POINTS}


def _work_rows(cur: Any, statement: str, params: tuple[Any, ...], *, max_rows: int | None = None) -> list[dict[str, Any]]:
    """Natijani READ ONLY sessiyada 500 qatorli bo'laklarda o'qish.

    Server kursori katta natijani bitta execute javobida uzatmaydi.
    O'qish tugamay qolsa xato yuqoriga chiqadi; qisman hujjatlardan
    'ishlamagan mashina' xulosasi chiqarilmaydi.
    """
    rows: list[dict[str, Any]] = []
    maximum = config.MAX_WORK_ROWS if max_rows is None else max_rows
    with cur.connection.cursor(
        name="fy_work_" + uuid4().hex, cursor_factory=RealDictCursor,
    ) as stream:
        stream.execute(statement, params)
        while len(rows) < maximum + 1:
            batch = stream.fetchmany(min(500, maximum + 1 - len(rows)))
            if not batch:
                break
            rows.extend(dict(row) for row in batch)
    return rows


def utilization(*, from_at: datetime, to_at: datetime, vehicle_id: str | None = None, vehicle_ids: list[str] | None = None) -> dict[str, Any]:
    """Reys va varaqa alohida o'qiladi; trip_id bo'yicha birlashtirish Python'da."""
    with _cursor() as cur:
        cur.execute("""
            select id::text, plate_number, brand, model, current_status, usage_mode,
                   ownership_type, created_at, commissioning_date, transport_type,
                   branch_id::text
            from transport_vehicle
            where (%s::uuid is null or id = %s::uuid)
              and (%s::uuid[] is null or id = any(%s::uuid[]))
            order by id limit %s
        """, (vehicle_id, vehicle_id, vehicle_ids, vehicle_ids, config.MAX_VEHICLES + 1))
        vehicles = [dict(row) for row in cur.fetchall()]
        if vehicle_id and not vehicles:
            raise VehicleNotFound(vehicle_id)
        vehicle_truncated = len(vehicles) > config.MAX_VEHICLES
        vehicles = vehicles[:config.MAX_VEHICLES]
        ids = [v["id"] for v in vehicles]
        trips = _work_rows(cur, """
            select id::text, vehicle_id::text, status,
                   actual_departure_at at time zone 'Asia/Tashkent' as started_at,
                   actual_arrival_at at time zone 'Asia/Tashkent' as ended_at,
                   actual_distance_km as distance_km, actual_engine_hours as engine_hours
            from trip
            where vehicle_id = any(%s::uuid[])
              and status not in ('CANCELLED', 'INTERRUPTED')
              and (
                (actual_departure_at at time zone 'Asia/Tashkent' >= %s
                 and actual_departure_at at time zone 'Asia/Tashkent' < %s)
                or (actual_arrival_at at time zone 'Asia/Tashkent' >= %s
                    and actual_arrival_at at time zone 'Asia/Tashkent' < %s)
              )
            order by id limit %s
        """, (ids, from_at, to_at, from_at, to_at, config.MAX_WORK_ROWS + 1))
        waybills = _work_rows(cur, """
            select id::text, vehicle_id::text, trip_id::text, status,
                   actual_departure_at as started_at, actual_return_at as ended_at,
                   odometer_start_km, odometer_end_km, motohours_worked,
                   pre_trip_motohours, post_trip_motohours,
                   moto_hours_start, moto_hours_end
            from waybill
            where vehicle_id = any(%s::uuid[])
              and status in ('IN_USE', 'RETURNED', 'CLOSED')
              and ((actual_departure_at >= %s and actual_departure_at < %s)
                   or (actual_return_at >= %s and actual_return_at < %s))
            order by id limit %s
        """, (ids, from_at, to_at, from_at, to_at, config.MAX_WORK_ROWS + 1))
        cur.execute("""
            select id::text, vehicle_id::text, status, opened_at,
                   estimated_completion_time, component_category, blocks_release
            from vehicle_repair
            where vehicle_id = any(%s::uuid[])
              and opened_at < %s
              and (coalesce(repaired_at, completed_at) is null
                   or coalesce(repaired_at, completed_at) >= %s)
              and status not in ('CANCELLED', 'REJECTED')
        """, (ids, to_at, to_at))
        repair_rows = [dict(row) for row in cur.fetchall()]
        repair_ids = {row["vehicle_id"] for row in repair_rows}
        cur.execute("""
            select v.id::text as vehicle_id,
                   exists(select 1 from vehicle_gps g where g.vehicle_id = v.id
                          and g.active and g.verified_from <= %s
                          and (g.unbound_at is null or g.unbound_at > %s)) as mapping_verified,
                   ts.last_event_at
            from transport_vehicle v
            left join vehicle_telemetry_state ts on ts.vehicle_id = v.id
            where v.id = any(%s::uuid[])
        """, (to_at, to_at, ids))
        gps_rows = {row["vehicle_id"]: dict(row) for row in cur.fetchall()}
        cur.execute("""
            select required_transport_type, count(*) as request_count,
                   count(*) filter (where status in ('APPROVED','READY_FOR_PLANNING')) as unassigned_count
            from transport_request
            where created_at >= %s and created_at < %s
              and status in ('APPROVED','READY_FOR_PLANNING','ASSIGNED','IN_PROGRESS','COMPLETED')
            group by required_transport_type
        """, (from_at, to_at))
        demand = {row["required_transport_type"]: dict(row) for row in cur.fetchall()}
    return {
        "vehicles": vehicles, "trips": trips[:config.MAX_WORK_ROWS],
        "waybills": waybills[:config.MAX_WORK_ROWS], "repair_ids": repair_ids,
        "repair_rows": repair_rows, "gps_rows": gps_rows, "demand_by_type": demand,
        "truncated": vehicle_truncated or len(trips) > config.MAX_WORK_ROWS or len(waybills) > config.MAX_WORK_ROWS,
    }


def monitor_data(*, from_at: datetime, to_at: datetime, plate_number: str | None) -> dict[str, Any]:
    """Bounded batch reads. Plate selection never interpolates user input into SQL."""
    with _cursor() as cur:
        cur.execute("""
            select id::text from transport_vehicle
            where (%s::text is null or
              regexp_replace(upper(coalesce(plate_number, '')), '[^[:alnum:]]', '', 'g') =
              regexp_replace(upper(%s::text), '[^[:alnum:]]', '', 'g'))
              and created_at <= %s
            order by id limit %s
        """, (plate_number, plate_number, to_at, config.MAX_VEHICLES + 1))
        scope = [r["id"] for r in cur.fetchall()]
    if plate_number and not scope:
        raise VehicleNotFound(plate_number)
    if plate_number and len(scope) > 1:
        raise AmbiguousPlate("Bir xil raqam bir nechta transportda bor; avval reyestrdagi raqamni aniqlashtiring.")
    scope_truncated = len(scope) > config.MAX_VEHICLES
    scope = scope[:config.MAX_VEHICLES]
    work = utilization(from_at=from_at, to_at=to_at, vehicle_ids=scope)
    work["truncated"] |= scope_truncated
    # Use the actually loaded registry scope if it changed between reads.
    ids = [v["id"] for v in work["vehicles"]]
    sources = {}
    batch_sql = {
        "telematics_event": """
          select e.vehicle_id::text, e.timestamp, to_jsonb(e.latitude) as latitude,
                 to_jsonb(e.longitude) as longitude,'true'::jsonb as valid,
                 to_jsonb(e.speed_kph) as speed,'kph'::text as unit,to_jsonb(e.engine_on) as engine
          from telematics_event e
          where e.vehicle_id=any(%(ids)s::uuid[]) and e.timestamp>=%(from_at)s and e.timestamp<=%(to_at)s
            and exists(select 1 from vehicle_gps g where g.vehicle_id=e.vehicle_id
              and g.verified_from<=e.timestamp and (g.unbound_at is null or e.timestamp<g.unbound_at)
              and (e.binding_id is null or e.binding_id=g.id))""",
        "position_log": """
          select g.vehicle_id::text,p.fix_time as timestamp,to_jsonb(p.latitude) as latitude,
                 to_jsonb(p.longitude) as longitude,to_jsonb(p.valid) as valid,
                 null::jsonb as speed,null::text as unit,null::jsonb as engine
          from position_log p join vehicle_gps g on g.device_id=p.device_id
          where g.vehicle_id=any(%(ids)s::uuid[]) and p.fix_time>=%(from_at)s and p.fix_time<=%(to_at)s
            and g.verified_from<=p.fix_time and (g.unbound_at is null or p.fix_time<g.unbound_at)
            and not exists(select 1 from vehicle_gps other where other.device_id=p.device_id
              and other.id<>g.id and other.verified_from<=p.fix_time
              and (other.unbound_at is null or p.fix_time<other.unbound_at))""",
        "gps_archive_point": """
          select a.vehicle_id::text,a.fix_time as timestamp,
                 p.data->'latitude' as latitude,p.data->'longitude' as longitude,
                 coalesce(p.data->'valid','true'::jsonb) as valid,
                 coalesce(nullif(p.data->'speed_kph','null'::jsonb),p.data->'speed') as speed,
                 case when p.data->>'speed_kph' is not null then 'kph'
                   else %(units)s::jsonb->>upper(g.provider_connection) end as unit,
                 p.data->'engine_on' as engine
          from gps_archive_point a join vehicle_gps g on g.id=a.binding_id and g.vehicle_id=a.vehicle_id
          cross join lateral (select case when pg_input_is_valid(a.payload,'jsonb')
            then a.payload::jsonb else '{}'::jsonb end as data) p
          where a.vehicle_id=any(%(ids)s::uuid[]) and a.fix_time>=%(from_at)s and a.fix_time<=%(to_at)s
            and g.verified_from<=a.fix_time and (g.unbound_at is null or a.fix_time<g.unbound_at)""",
    }
    with _cursor() as cur:
        schema = _schema(cur)
        if ids:
            # `active` is today's flag. A historical binding that was unbound
            # later still belongs to the vehicle at the requested as_of time.
            cur.execute("""
                select v.id::text as vehicle_id,exists(select 1 from vehicle_gps g
                  where g.vehicle_id=v.id and g.verified_from<=%s
                    and (g.unbound_at is null or g.unbound_at>%s)
                    and (g.active or g.unbound_at is not null)) as mapping_verified
                from transport_vehicle v where v.id=any(%s::uuid[])
            """, (to_at, to_at, ids))
            for row in cur.fetchall():
                work["gps_rows"].setdefault(row["vehicle_id"], {}).update(mapping_verified=row["mapping_verified"])
        for source, statement in batch_sql.items():
            if source not in schema:
                sources[source] = {"available": False, "has_rows": None}
                continue
            cur.execute(sql.SQL("select exists(select 1 from {}) as present").format(sql.Identifier(source)))
            present = bool(cur.fetchone()["present"])
            sources[source] = {"available": True, "has_rows": present}
        telemetry = {}
        if "vehicle_telemetry_state" in schema and ids:
            cur.execute("""
                select t.vehicle_id::text,t.last_event_at as timestamp,
                       t.last_latitude as latitude,t.last_longitude as longitude,
                       t.last_speed_kph as speed_kph,t.last_engine_on as engine_on,true as valid
                from vehicle_telemetry_state t
                where t.vehicle_id=any(%s::uuid[]) and t.last_event_at<=%s
                  and exists(select 1 from vehicle_gps g where g.vehicle_id=t.vehicle_id
                    and g.verified_from<=t.last_event_at
                    and (g.unbound_at is null or t.last_event_at<g.unbound_at))
            """, (ids, to_at))
            telemetry = {r["vehicle_id"]: dict(r) for r in cur.fetchall()}
    statements = [(source, statement) for source, statement in batch_sql.items()
                  if ids and sources.get(source, {}).get("has_rows")]
    history = StreamingHistory(_monitor_packets(statements, {
        "ids": ids, "from_at": from_at, "to_at": to_at,
        "units": json.dumps(config.ARCHIVE_SPEED_UNITS), "packet_size": config.MONITOR_PACKET_POINTS}))
    return {"work": work, "history": history, "telemetry": telemetry,
            "sources": sources, "truncated_vehicle_ids": set(),
            "gps_truncated": False, "scope_truncated": scope_truncated}


def _monitor_packets(statements, params):
    """Read all matching fixes as compact packets; exact duplicates keep their weight.

    Named cursor, one DB connection, no LIMIT/OFFSET and no database writes.
    The sort and grouping happen in PostgreSQL; Python retains one vehicle.
    """
    if not statements:
        return
    ids = list(params.get("ids") or [])
    if not ids:
        return
    union = " UNION ALL ".join(
        "SELECT '" + source + "'::text as source,r.* FROM (" + statement + ") r"
        for source, statement in statements)
    statement = """WITH raw AS (""" + union + """), distinct_fixes AS (
        SELECT source,vehicle_id,timestamp,latitude,longitude,valid,speed,unit,engine,count(*) as copies
        FROM raw GROUP BY source,vehicle_id,timestamp,latitude,longitude,valid,speed,unit,engine
      ), numbered AS (
        SELECT *, (row_number() OVER(PARTITION BY vehicle_id,source ORDER BY timestamp)-1)/%(packet_size)s as packet
        FROM distinct_fixes
      ) SELECT vehicle_id,source,json_agg(json_build_array(
          (extract(epoch from timestamp)*1000000)::bigint,latitude,longitude,valid,speed,unit,engine,copies
        ) ORDER BY timestamp) as points
        FROM numbered GROUP BY vehicle_id,source,packet ORDER BY vehicle_id,source,packet"""
    chunk_size = 5
    for offset in range(0, len(ids), chunk_size):
        chunk_params = {**params, "ids": ids[offset:offset + chunk_size]}
        with _cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '90s'")
            with cur.connection.cursor(name="fy_monitor_" + uuid4().hex, cursor_factory=RealDictCursor) as stream:
                stream.execute(statement, chunk_params)
                while True:
                    packet = stream.fetchone()
                    if packet is None:
                        break
                    yield dict(packet)
