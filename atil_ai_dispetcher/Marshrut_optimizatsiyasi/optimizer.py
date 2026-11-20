"""Orkestratsiya — bazadan o'qish, rejalashtirish, javob yig'ish.

BU FAYLDA ALGORITM YO'Q. Algoritm `solver.py` da, o'lchovlar
`calibration.py` da, SQL `queries.py` da. Bu yerda faqat ularni bir-biriga
ulash va javobni yig'ish. Shu bo'linish tufayli algoritmni almashtirish
(masalan OR-Tools ga o'tish) qolgan kodga tegmaydi.

BITTA KIRISH NUQTASI — `plan()`. U so'rovga qarab ikki yo'ldan birini
tanlaydi:

    stops berilmagan  -> plan_from_database()  arizalar `transport_request` dan
    stops berilgan    -> plan_manual()         bazaga umuman murojaat yo'q

Ikkala yo'l ham BIR XIL javob qaytaradi va bir xil solver'ni chaqiradi —
farq faqat ma'lumot qayerdan kelishida. Shuning uchun ular alohida
funksiya: bittasiga qo'shib yuborilsa ichi `if source == ...` bilan
to'lib ketardi.

VAQT OYNASI QANDAY O'QILADI (`transport_request`):
    planned_departure_at  -> YUKLASH oynasining BOSHI ("yuk shu vaqtdan
                             tayyor", undan oldin borishning ma'nosi yo'q)
    planned_arrival_at    -> TUSHIRISH oynasining OXIRI ("shu vaqtgacha
                             yetkazilsin")
Bu o'qish `transport_request_point` bo'lganda o'sha jadvalning o'z
`planned_arrival_at`/`planned_departure_at` ustunlari bilan almashtiriladi —
u yerda oyna nuqta darajasida aniqroq.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, time as dtime
from typing import Any, Sequence

from atil_ai_dispetcher.Marshrut_optimizatsiyasi import (
    calibration, config, geo, queries, readiness, solver, texts,
)
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.texts import priority_name, t, transport_name
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.solver import (
    Options,
    Order,
    Stop,
    Vehicle,
    naive,
)

logger = logging.getLogger(__name__)


class NothingToPlan(LookupError):
    """Rejalashtiradigan ariza topilmadi — router buni 404 ga aylantiradi.

    Xato MATNI bilan cheklanmaydi: `report` da bazaning tayyorlik holati
    ham keladi (`row_counts`, `requirements`). Sabab — aynan shu holatda
    "nega ariza yo'q" degan savol tug'iladi va javob "`transport_request`
    da 140 qator bor, lekin APPROVED holatida bittasi ham yo'q" bo'lishi
    kerak, quruq "topilmadi" emas.
    """

    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.report = report or {}


#: Yuklash nuqtasi hisoblanadigan nuqta turlari (`*_point.point_type`).
PICKUP_POINT_TYPES = ("ORIGIN", "LOADING")
#: Tushirish nuqtasi hisoblanadigan turlar.
DELIVERY_POINT_TYPES = ("DESTINATION", "UNLOADING")

# --------------------------------------------------------------- Yordamchi


def _f(value: Any) -> float | None:
    return queries.to_float(value)


def _type_code(value: str | None) -> str | None:
    """Transport turini KODGA keltiradi.

    Javobda tur NOM bo'lib chiqadi ("samosval"), shuning uchun
    foydalanuvchi o'sha nomni so'rovga qaytarib yozadi. Kod ham, nom ham
    (uch tilda) qabul qilinadi — aks holda so'rov jimgina bo'sh natija
    qaytarardi. Solishtirish esa doim KOD bo'yicha ketadi.
    """
    from atil_ai_dispetcher.vehicle_selection.labels import code_of

    return code_of("transport_type", value)


def _plan_reference(on_date: date | None, orders: list[Order]) -> datetime:
    """Reja qaysi paytdan boshlanadi.

    Smenasi ko'rsatilmagan mashina uchun boshlanish nuqtasi kerak.
    Tartib: eng erta vaqt oynasi -> berilgan sananing boshi -> hozir.
    O'YLAB TOPILGAN "ertalab soat 8" YO'Q.
    """
    windows = [
        w for order in orders
        for w in (order.pickup.window_from, order.delivery.window_from)
        if w is not None
    ]
    if windows:
        return min(windows)
    if on_date:
        return datetime.combine(on_date, dtime.min)
    return datetime.now().replace(second=0, microsecond=0)


def _service_minutes(cal: calibration.Calibration, override: float | None) -> float:
    if override is not None:
        return float(override)
    return float(cal.service_minutes or 0.0)


# ------------------------------------------------- Bazadan ariza -> Order


def _request_orders(
    rows: list[dict[str, Any]],
    points: dict[str, list[dict[str, Any]]],
    cal: calibration.Calibration,
    notes: list[str],
    lang: str = texts.DEFAULT_LANG,
) -> list[Order]:
    """`transport_request` qatorlarini `Order` ga aylantiradi.

    Koordinatasi topilmagan ariza SHU YERDA tashlanmaydi — u ham `Order`
    bo'ladi, faqat `node` si `None` bo'lib qoladi va solver uni
    `NO_COORDINATES` sababi bilan qaytaradi. Shunda javobda "48 ta
    arizadan 48 tasi koordinatasiz" degan aniq manzara ko'rinadi.
    """
    orders: list[Order] = []
    service = _service_minutes(cal, None)

    for row in rows:
        request_id = row["request_id"]
        own_points = points.get(request_id) or []

        pickup = _point_of(own_points, PICKUP_POINT_TYPES)
        delivery = _point_of(own_points, DELIVERY_POINT_TYPES)

        origin_lat = _f((pickup or {}).get("latitude")) or _f(row.get("origin_latitude"))
        origin_lon = _f((pickup or {}).get("longitude")) or _f(row.get("origin_longitude"))
        dest_lat = _f((delivery or {}).get("latitude")) or _f(row.get("destination_latitude"))
        dest_lon = _f((delivery or {}).get("longitude")) or _f(row.get("destination_longitude"))

        origin_name = (
            (pickup or {}).get("location_name")
            or row.get("origin_location")
            or row.get("from_warehouse_name")
        )
        dest_name = (
            (delivery or {}).get("location_name")
            or row.get("destination_location")
            or row.get("to_warehouse_name")
        )

        # OG'IRLIK UCH MANBADAN. Arizada bo'sh bo'lsa WMS jo'natmasidan
        # olinadi — u yerda tonna ko'rinishida ham yozilishi mumkin.
        # Hech qayerda bo'lmasa `None` qoladi: nol DEB HISOBLANMAYDI,
        # aks holda 20 tonnalik yuk "bo'sh" bo'lib har mashinaga sig'ardi.
        weight = _f(row.get("cargo_weight_kg")) or _f(row.get("shipment_weight_kg"))
        if weight is None:
            tons = _f(row.get("shipment_weight_tons"))
            weight = tons * 1000.0 if tons else None
        volume = _f(row.get("cargo_volume_m3")) or _f(row.get("shipment_volume_m3"))

        # VAQT OYNASI ham shu tartibda: nuqtaning o'zi -> ariza -> jo'natma.
        # `shipment.ready_at` "yuk tayyor bo'ladigan vaqt", ya'ni yuklash
        # oynasining boshi — arizadagi rejadan aniqroq.
        pickup_from = (
            naive((pickup or {}).get("planned_departure_at"))
            or naive(row.get("planned_departure_at"))
            or naive(row.get("shipment_ready_at"))
            or naive(row.get("shipment_scheduled_pickup_at"))
        )
        pickup_to = naive((pickup or {}).get("planned_arrival_at")) if pickup else None
        delivery_to = (
            naive((delivery or {}).get("planned_arrival_at"))
            or naive(row.get("planned_arrival_at"))
            or naive(row.get("shipment_requested_delivery_at"))
            or naive(row.get("shipment_scheduled_delivery_at"))
        )

        orders.append(
            Order(
                id=request_id,
                number=row.get("request_number"),
                priority=(row.get("priority") or "NORMAL"),
                required_transport_type=row.get("required_transport_type"),
                weight_kg=weight,
                volume_m3=volume,
                origin_name=origin_name,
                destination_name=dest_name,
                # Dispetcher qo'lda biriktirgan bo'lsa optimizator uni
                # buzmaydi — ariza faqat o'sha mashinaga qo'yiladi.
                locked_vehicle_id=row.get("binding_vehicle_id"),
                # Xavflilik `shipment` -> `hazard_profile` dan avtomatik.
                requires_tank=bool(row.get("requires_special_tank")),
                requires_adr=bool(row.get("requires_adr")),
                un_number=row.get("un_number"),
                pickup=Stop(
                    kind="PICKUP",
                    order_id=request_id,
                    node=None,
                    name=origin_name,
                    location_id=(pickup or {}).get("location_id")
                    or row.get("origin_location_id"),
                    latitude=origin_lat,
                    longitude=origin_lon,
                    demand_kg=weight or 0.0,
                    demand_m3=volume or 0.0,
                    window_from=pickup_from,
                    window_to=pickup_to,
                    service_minutes=service,
                ),
                delivery=Stop(
                    kind="DELIVERY",
                    order_id=request_id,
                    node=None,
                    name=dest_name,
                    location_id=(delivery or {}).get("location_id")
                    or row.get("destination_location_id"),
                    latitude=dest_lat,
                    longitude=dest_lon,
                    demand_kg=-(weight or 0.0),
                    demand_m3=-(volume or 0.0),
                    window_from=None,
                    window_to=delivery_to,
                    service_minutes=service,
                ),
            )
        )

    locked = sum(1 for o in orders if o.locked_vehicle_id)
    if locked:
        notes.append(t(lang, "note.locked", count=locked))

    tank = sum(1 for o in orders if o.requires_tank)
    if tank:
        notes.append(t(
            lang, "note.tank", count=tank,
            types=", ".join(
                transport_name(code, lang) or code
                for code in solver.TANK_TRANSPORT_TYPES
            ),
        ))

    adr = sum(1 for o in orders if o.requires_adr)
    if adr:
        notes.append(t(lang, "note.adr", count=adr))

    missing_weight = sum(1 for o in orders if o.weight_kg is None)
    if missing_weight:
        notes.append(t(lang, "note.missing_weight", count=missing_weight))
    return orders


def _point_of(points: list[dict[str, Any]], kinds: Sequence[str]) -> dict[str, Any] | None:
    for point in points:
        if (point.get("point_type") or "") in kinds:
            return point
    return None


def _resolve_missing_coordinates(
    orders: list[Order], notes: list[str], lang: str = texts.DEFAULT_LANG
) -> None:
    """Koordinatasi yo'q nuqtalarni `location_id` orqali yechishga urinadi.

    Manzil katalogi bo'sh, lekin bir xil manzil boshqa marshrutda
    koordinata bilan uchragan bo'lishi mumkin (`route_point`). Ya'ni
    "koordinata yo'q" degan xulosaga darrov kelinmaydi.
    """
    cache: dict[str, dict[str, Any] | None] = {}
    resolved = 0

    for order in orders:
        for stop in (order.pickup, order.delivery):
            if stop.latitude is not None and stop.longitude is not None:
                continue
            if not stop.location_id:
                continue
            if stop.location_id not in cache:
                try:
                    cache[stop.location_id] = queries.fetch_location(stop.location_id)
                except queries.PlanningDataError:
                    cache[stop.location_id] = None
            found = cache[stop.location_id]
            if not found:
                continue
            latitude = _f(found.get("latitude"))
            longitude = _f(found.get("longitude"))
            if latitude is not None and longitude is not None:
                stop.latitude = latitude
                stop.longitude = longitude
                stop.name = stop.name or found.get("location_name")
                resolved += 1

    if resolved:
        notes.append(t(lang, "note.coords_resolved", count=resolved))


# ----------------------------------------------- Bazadan mashina -> Vehicle


def _vehicles_from_rows(
    rows: list[dict[str, Any]],
    *,
    depot: tuple[float | None, float | None, str | None],
    branch_depots: dict[str, dict[str, Any]],
    plan_start: datetime,
    notes: list[str],
    lang: str = texts.DEFAULT_LANG,
) -> tuple[list[Vehicle], dict[str, int]]:
    """Bo'sh mashinalarni `Vehicle` ga aylantiradi.

    KESISH SHU YERDA: band mashina (reja oynasiga to'g'ri keladigan aktiv
    reys yoki ochiq yo'l varaqasi) va bloklovchi remontdagi mashina
    rejaga umuman kirmaydi. Nechtasi nima sababdan chiqib qolgani
    `data_quality.notes` da yoziladi — mashinalar jimgina yo'qolmaydi.

    XAVFLI YUK BU YERDA TEKSHIRILMAYDI. Ilgari tekshirilardi va bu xato
    edi: xavfli yuk BUTUN so'rovga emas, AYRIM arizaga tegishli. Bir
    kunda ham xavfli, ham oddiy yuk bo'lsa, sisternasiz mashinalarni
    butunlay chiqarib tashlash oddiy arizalarni ham mashinasiz
    qoldirardi. Endi bu `solver.compatible()` da ariza darajasida.

    CHIQISH NUQTASI UCH MANBADAN, aniqdan taxminiyga qarab:
        1. `vehicle_telemetry_state` — mashina HOZIR qayerda (eng aniq)
        2. `reference_data` (BRANCHES) — mashinaning O'Z FILIALI garaji
        3. so'rovdagi `depot_latitude/longitude` — umumiy zaxira
    """
    depot_lat, depot_lon, depot_name = depot
    vehicles: list[Vehicle] = []
    dropped = {"busy": 0, "repair": 0, "no_position": 0}
    start_sources = {"gps": 0, "branch": 0, "param": 0}

    for row in rows:
        if row.get("busy_trip_id") or row.get("open_waybill_number"):
            dropped["busy"] += 1
            continue
        if int(row.get("blocking_repairs") or 0) > 0:
            dropped["repair"] += 1
            continue

        latitude = _f(row.get("last_latitude"))
        longitude = _f(row.get("last_longitude"))
        start_name = t(lang, "misc.last_gps")
        if latitude is not None and longitude is not None:
            start_sources["gps"] += 1
        else:
            branch = branch_depots.get(row.get("branch_id") or "")
            if branch:
                latitude = _f(branch.get("latitude"))
                longitude = _f(branch.get("longitude"))
                start_name = (branch.get("name") or branch.get("address")
                              or t(lang, "misc.branch_depot"))
                start_sources["branch"] += 1
            else:
                latitude, longitude, start_name = depot_lat, depot_lon, depot_name
                if latitude is not None:
                    start_sources["param"] += 1
        if latitude is None or longitude is None:
            dropped["no_position"] += 1
            continue

        shift_from = naive(row.get("shift_start_at")) or plan_start
        shift_to = naive(row.get("shift_end_at"))
        shift_hours = _f(row.get("shift_hours"))

        vehicles.append(
            Vehicle(
                id=row["vehicle_id"],
                start_node=None,
                plate_number=row.get("plate_number"),
                brand=row.get("brand"),
                model=row.get("model"),
                transport_type=row.get("transport_type"),
                capacity_kg=_f(row.get("payload_capacity_kg")) or None,
                capacity_m3=_f(row.get("volume_m3")) or None,
                start_name=start_name,
                start_latitude=latitude,
                start_longitude=longitude,
                shift_from=shift_from,
                shift_to=shift_to,
                max_duration_minutes=(shift_hours * 60.0) if shift_hours else None,
                driver_id=row.get("assigned_driver_id"),
                driver_name=row.get("driver_name"),
                return_to_start=True,
            )
        )

    if dropped["busy"]:
        notes.append(t(lang, "note.busy", count=dropped["busy"]))
    if dropped["repair"]:
        notes.append(t(lang, "note.repair", count=dropped["repair"]))
    if dropped["no_position"]:
        notes.append(t(lang, "note.no_position", count=dropped["no_position"]))
    if start_sources["param"] and not start_sources["branch"]:
        notes.append(t(lang, "note.param_depot", count=start_sources["param"]))
    if start_sources["gps"]:
        notes.append(t(lang, "note.gps", count=start_sources["gps"]))

    missing_capacity = sum(1 for v in vehicles if v.capacity_kg is None)
    if missing_capacity:
        notes.append(t(lang, "note.missing_capacity", count=missing_capacity))
    return vehicles, dropped


# ------------------------------------------------------------- Matritsa


def _attach_nodes(
    orders: list[Order], vehicles: list[Vehicle], cal: calibration.Calibration
) -> geo.Matrix:
    """Barcha nuqtalarni bitta matritsaga yig'adi va tugun raqamlarini biriktiradi."""
    matrix = geo.Matrix(
        road_factor=cal.road_factor or 1.0,
        speed_kph=cal.average_speed_kph,
    )
    for order in orders:
        order.pickup.node = matrix.node(order.pickup.latitude, order.pickup.longitude)
        order.delivery.node = matrix.node(order.delivery.latitude, order.delivery.longitude)
    for vehicle in vehicles:
        vehicle.start_node = matrix.node(vehicle.start_latitude, vehicle.start_longitude)
    matrix.build()

    if config.OSRM_URL:
        used = matrix.apply_osrm(
            config.OSRM_URL, config.OSRM_TIMEOUT, config.OSRM_MAX_POINTS
        )
        cal.distance_source = "osrm" if used else "haversine"
        cal.notes.extend(matrix.notes)
    return matrix


# --------------------------------------------------------------- Javob


def _route_out(
    vehicle: Vehicle,
    evaluation: solver.RouteEval,
    orders_by_id: dict[str, Order],
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    stops: list[dict[str, Any]] = [
        {
            "sequence": 0,
            "kind": "START",
            "name": vehicle.start_name,
            "latitude": vehicle.start_latitude,
            "longitude": vehicle.start_longitude,
            "departure_at": evaluation.starts_at,
        }
    ]

    numbers: list[str] = []
    for index, visit in enumerate(evaluation.visits, start=1):
        order = orders_by_id.get(visit.stop.order_id)
        if visit.stop.kind == "PICKUP" and order is not None:
            numbers.append(order.number or order.id)
        stops.append(
            {
                "sequence": index,
                "kind": visit.stop.kind,
                "request_id": visit.stop.order_id,
                "request_number": (order.number if order else None),
                "location_id": visit.stop.location_id,
                "name": visit.stop.name,
                "latitude": visit.stop.latitude,
                "longitude": visit.stop.longitude,
                "distance_from_previous_km": _round(visit.distance_km, 3),
                "travel_minutes_from_previous": _round(visit.travel_minutes, 1),
                "arrival_at": visit.arrival_at,
                "wait_minutes": _round(visit.wait_minutes, 1),
                "service_minutes": _round(visit.service_minutes, 1),
                "departure_at": visit.departure_at,
                "window_from": visit.stop.window_from,
                "window_to": visit.stop.window_to,
                "late_minutes": _round(visit.late_minutes, 1),
                "load_after_kg": _round(visit.load_after_kg, 2),
                "load_after_m3": _round(visit.load_after_m3, 3),
            }
        )

    if vehicle.return_to_start:
        stops.append(
            {
                "sequence": len(stops),
                "kind": "END",
                "name": vehicle.start_name,
                "latitude": vehicle.start_latitude,
                "longitude": vehicle.start_longitude,
                "arrival_at": evaluation.ends_at,
            }
        )

    utilization = None
    if vehicle.capacity_kg:
        utilization = round(evaluation.max_load_kg / vehicle.capacity_kg, 4)

    warnings: list[str] = []
    if evaluation.late_minutes:
        warnings.append(t(
            lang, "warn.late", minutes=f"{evaluation.late_minutes:.0f}"))
    if utilization is not None and utilization > 1.0:
        warnings.append(t(lang, "warn.over_capacity"))

    return {
        "vehicle_id": vehicle.id,
        "plate_number": vehicle.plate_number,
        "brand": vehicle.brand,
        "model": vehicle.model,
        # Kod emas, NOM: `transport_type` javobda tanlangan tilda
        # ko'rinadi (`AERIAL_PLATFORM` -> "havo platformasi").
        "transport_type": transport_name(vehicle.transport_type, lang),
        "driver_id": vehicle.driver_id,
        "driver_name": vehicle.driver_name,
        "requests": numbers,
        "stops": stops,
        "total_distance_km": _round(evaluation.distance_km, 3) or 0.0,
        "total_duration_minutes": _round(evaluation.total_minutes, 1),
        "driving_minutes": _round(evaluation.driving_minutes, 1),
        "waiting_minutes": _round(evaluation.waiting_minutes, 1),
        "service_minutes_total": _round(evaluation.service_minutes, 1),
        "late_minutes_total": _round(evaluation.late_minutes, 1),
        "max_load_kg": _round(evaluation.max_load_kg, 2),
        "capacity_kg": vehicle.capacity_kg,
        "capacity_utilization": utilization,
        "starts_at": evaluation.starts_at,
        "ends_at": evaluation.ends_at,
        "warnings": warnings,
        "explanation": "",
    }


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _unassigned_out(
    order: Order, code: str, lang: str = texts.DEFAULT_LANG
) -> dict[str, Any]:
    """Joylanmagan ariza — sababi va transport turi TANLANGAN TILDA.

    `reason_code` esa tarjima qilinmaydi: u mashina o'qiydigan qiymat va
    chaqiruvchi shunga qarab filtr qiladi.
    """
    return {
        "request_id": order.id,
        "request_number": order.number,
        "priority": priority_name(order.priority, lang),
        "required_transport_type": transport_name(
            order.required_transport_type, lang),
        "weight_kg": order.weight_kg,
        "origin_name": order.origin_name,
        "destination_name": order.destination_name,
        "reason_code": code,
        "reason": t(lang, f"reason.{code}") if f"reason.{code}" in texts.MESSAGES
                  else code,
    }


def _build_report(
    *,
    scope: dict[str, Any],
    cal: calibration.Calibration,
    orders: list[Order],
    vehicles: list[Vehicle],
    solution: solver.Solution,
    matrix: geo.Matrix,
    options: Options,
    counts: dict[str, int],
    notes: list[str],
    started: float,
    ready: bool = True,
    requirements: list[dict[str, Any]] | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    orders_by_id = {o.id: o for o in orders}
    by_vehicle = {v.id: v for v in vehicles}

    routes = [
        _route_out(by_vehicle[vehicle_id], evaluation, orders_by_id, lang)
        for vehicle_id, evaluation in solution.evaluations.items()
        if evaluation.visits
    ]
    routes.sort(key=lambda r: r["total_distance_km"], reverse=True)

    unassigned = [
        _unassigned_out(orders_by_id[order_id], code, lang)
        for order_id, code in solution.unassigned.items()
        if order_id in orders_by_id
    ]
    unassigned.sort(key=lambda u: (u["reason_code"], u["request_number"] or ""))

    reasons: dict[str, int] = {}
    for item in unassigned:
        reasons[item["reason_code"]] = reasons.get(item["reason_code"], 0) + 1

    total_km = sum(r["total_distance_km"] for r in routes)
    total_minutes = (
        sum(r["total_duration_minutes"] or 0.0 for r in routes) if cal.time_aware else None
    )
    total_late = (
        sum(r["late_minutes_total"] or 0.0 for r in routes) if cal.time_aware else None
    )

    assigned_orders = [o for o in orders if o.id not in solution.unassigned]
    baseline = solver.baseline_distance_km(assigned_orders, vehicles, matrix)
    saved = None
    saved_percent = None
    if baseline and baseline > 0:
        saved = baseline - total_km
        saved_percent = round(saved / baseline * 100.0, 1)

    summary = {
        "requests_considered": len(orders),
        "requests_assigned": len(assigned_orders),
        "requests_unassigned": len(unassigned),
        "vehicles_considered": len(vehicles),
        "vehicles_used": len(routes),
        "total_distance_km": round(total_km, 3),
        "total_duration_minutes": _round(total_minutes, 1),
        "total_late_minutes": _round(total_late, 1),
        "objective": options.objective,
        "objective_value": _round(solution.cost, 3),
        "baseline_distance_km": _round(baseline, 3),
        "saved_distance_km": _round(saved, 3),
        "saved_percent": saved_percent,
        "unassigned_reasons": reasons,
        "improvement_rounds": solution.rounds,
        "time_budget_hit": solution.time_budget_hit,
    }

    if solution.time_budget_hit:
        notes.append(t(
            lang, "note.time_budget", seconds=config.TIME_BUDGET_SECONDS))
    if matrix.size == 0:
        notes.append(t(lang, "note.empty_matrix"))

    # Bloklovchi talab bajarilmagan bo'lsa buni izohlarning BOSHIDA aytamiz:
    # javobni to'liq o'qimagan odam ham nima to'ldirilishi kerakligini
    # ko'rsin. Batafsili `data_quality.requirements` da.
    blocking = [r for r in (requirements or []) if r["blocking"] and not r["ready"]]
    if blocking:
        notes.insert(0, t(lang, "note.not_ready", items="; ".join(
            f"{item['title']} ("
            + t(lang, "misc.or").join(
                source["table"] for source in item["sources"])
            + ")"
            for item in blocking
        )))

    return {
        "generated_at": datetime.now(),
        "scope": scope,
        "calibration": cal.as_dict(),
        "summary": summary,
        "analysis": {"text": "", "routes_considered": 0},
        "routes": routes,
        "unassigned": unassigned,
        "data_quality": {
            "ready": ready,
            "row_counts": counts,
            "requirements": requirements or [],
            "notes": notes,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


# --------------------------------------------------- Yagona kirish nuqtasi


def plan(request: dict[str, Any]) -> dict[str, Any]:
    """Reja tuzadi — `models.PlanRequest` dan kelgan so'rov bo'yicha.

    Rejimni `stops` belgilaydi, alohida bayroq yo'q: nuqtalar berilgan
    bo'lsa demak foydalanuvchi ularni o'zi bermoqchi, bazadan o'qishning
    ma'nosi yo'q. Bitta endpoint, ikki xil ish — chaqiruvchi tomonda
    tanlash kerak emas.
    """
    if request.get("stops"):
        return plan_manual(request)

    return plan_from_database(
        lang=texts.normalize(request.get("lang")),
        on_date=request.get("on_date"),
        request_ids=request.get("request_ids"),
        depot_latitude=request.get("depot_latitude"),
        depot_longitude=request.get("depot_longitude"),
        window_from=request.get("window_from"),
        window_to=request.get("window_to"),
        objective=request.get("objective"),
        respect_time_windows=bool(request.get("respect_time_windows", True)),
        average_speed_kph=request.get("average_speed_kph"),
    )


# ------------------------------------------------------- 1-yo'l: bazadan


def plan_from_database(
    *,
    lang: str = texts.DEFAULT_LANG,
    on_date: date | None = None,
    statuses: Sequence[str] | None = None,
    request_ids: Sequence[str] | None = None,
    vehicle_ids: Sequence[str] | None = None,
    depot_location_id: str | None = None,
    depot_latitude: float | None = None,
    depot_longitude: float | None = None,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
    objective: str | None = None,
    respect_time_windows: bool = True,
    respect_capacity: bool = True,
    average_speed_kph: float | None = None,
    road_factor: float | None = None,
    service_minutes: float | None = None,
) -> dict[str, Any]:
    """Bazadagi arizalar bo'yicha reja tuzadi.

    `window_from`/`window_to` — reja oynasi. Bandlik shu oyna bilan
    kesishishiga qarab aniqlanadi, ya'ni tushdan keyingi rejaga
    ertalabki reysini tugatgan mashina ham kiradi. Berilmasa oyna
    `on_date` ning butun kuni bo'ladi.
    """
    started = time.perf_counter()
    notes: list[str] = []
    day = on_date or date.today()
    status_list = list(statuses or config.DEFAULT_REQUEST_STATUSES)

    # Oyna berilmasa — butun kun. Bu TAXMIN emas, sananing ta'rifi.
    win_from = naive(window_from) or datetime.combine(day, dtime.min)
    win_to = naive(window_to) or datetime.combine(day, dtime.max)

    cal = calibration.calibrate(
        road_factor_override=road_factor,
        speed_override=average_speed_kph,
        service_override=service_minutes,
        lang=lang,
    )

    # Bazaning tayyorlik holati — BITTA so'rov. Arizalarni o'qishdan OLDIN
    # olinadi: ariza topilmay 404 qaytganda ham "qaysi jadval to'ldirilsin"
    # degan javob berilishi kerak.
    snapshot = queries.data_snapshot(
        statuses=status_list, calibration_days=config.CALIBRATION_DAYS)
    is_ready, requirements = readiness.build(
        snapshot, cal,
        depot_given=depot_latitude is not None and depot_longitude is not None,
        statuses=status_list,
        lang=lang,
    )

    request_rows = queries.fetch_requests(
        statuses=status_list,
        request_ids=request_ids,
        on_date=day.isoformat(),
        limit=config.MAX_REQUESTS,
    )
    if not request_rows:
        raise NothingToPlan(
            t(lang, "error.nothing_to_plan",
              date=day.isoformat(),
              statuses=", ".join(status_list) or t(lang, "misc.all")),
            {
                "ready": is_ready,
                "row_counts": queries.row_counts(snapshot),
                "requirements": requirements,
            },
        )
    if len(request_rows) >= config.MAX_REQUESTS:
        notes.append(t(lang, "note.max_requests", limit=config.MAX_REQUESTS))

    point_rows = queries.fetch_request_points([r["request_id"] for r in request_rows])
    points: dict[str, list[dict[str, Any]]] = {}
    for row in point_rows:
        points.setdefault(row["request_id"], []).append(row)

    orders = _request_orders(request_rows, points, cal, notes, lang)
    _resolve_missing_coordinates(orders, notes, lang)

    # ---------------------------------------------------------------- Garaj
    depot_name = None
    if depot_location_id and (depot_latitude is None or depot_longitude is None):
        found = queries.fetch_location(depot_location_id)
        if found:
            depot_latitude = _f(found.get("latitude"))
            depot_longitude = _f(found.get("longitude"))
            depot_name = found.get("location_name")
        else:
            notes.append(t(
                lang, "note.depot_not_found", location_id=depot_location_id))
    depot_name = depot_name or (
        t(lang, "misc.depot") if depot_latitude is not None else None)

    plan_start = _plan_reference(day, orders)

    # Transport turi filtri: xavfli yuk bo'lsa sisternalar ham kerak,
    # aks holda ular `required_transport_type` ro'yxatiga tushmay qolardi
    # va xavfli ariza mashinasiz qolardi.
    types = {o.required_transport_type for o in orders if o.required_transport_type}
    if any(o.requires_tank for o in orders):
        types.update(solver.TANK_TRANSPORT_TYPES)

    vehicle_rows = queries.fetch_vehicles(
        on_date=day.isoformat(),
        transport_types=sorted(types),
        vehicle_ids=vehicle_ids,
        limit=config.MAX_VEHICLES,
        window_from=win_from.isoformat(),
        window_to=win_to.isoformat(),
    )
    if len(vehicle_rows) >= config.MAX_VEHICLES:
        # Arizalar uchun shunday qilingan; mashinalar jimgina qirqilib
        # ketishi "park kichik ekan" degan noto'g'ri xulosaga olib borardi.
        notes.append(t(lang, "note.max_vehicles", limit=config.MAX_VEHICLES))

    branch_depots = queries.fetch_branch_depots()
    vehicles, _dropped = _vehicles_from_rows(
        vehicle_rows,
        depot=(depot_latitude, depot_longitude, depot_name),
        branch_depots=branch_depots,
        plan_start=plan_start,
        notes=notes,
        lang=lang,
    )

    matrix = _attach_nodes(orders, vehicles, cal)
    options = _options(
        objective, cal, plan_start, respect_time_windows, respect_capacity, lang)
    solution = solver.solve(orders, vehicles, matrix, options)

    _dock_warnings(solution, vehicles, notes, lang)

    counts = queries.row_counts(snapshot)
    scope = {
        "source": "database",
        "on_date": day,
        "statuses": status_list,
        "request_ids": [str(x) for x in (request_ids or [])],
        "depot_location_id": depot_location_id,
        "depot_name": depot_name,
        "depot_latitude": depot_latitude,
        "depot_longitude": depot_longitude,
        "window_from": win_from,
        "window_to": win_to,
        "respect_time_windows": respect_time_windows,
        "respect_capacity": respect_capacity,
        "hazard_summary": {
            "hazardous_requests": sum(1 for o in orders if o.un_number),
            "tank_required": sum(1 for o in orders if o.requires_tank),
            "adr_required": sum(1 for o in orders if o.requires_adr),
        },
        "locked_requests": sum(1 for o in orders if o.locked_vehicle_id),
    }

    return _build_report(
        scope=scope, cal=cal, orders=orders, vehicles=vehicles,
        solution=solution, matrix=matrix, options=options,
        counts=counts, notes=notes, started=started,
        ready=is_ready, requirements=requirements, lang=lang,
    )


def _options(
    objective: str | None,
    cal: calibration.Calibration,
    plan_start: datetime,
    respect_time_windows: bool,
    respect_capacity: bool,
    lang: str = texts.DEFAULT_LANG,
) -> Options:
    """So'rov va kalibrovkadan solver sozlamalarini yig'adi.

    Tezlik noma'lum bo'lsa maqsad AVTOMATIK `distance` ga tushadi:
    "duration" ni so'rab, vaqt hisoblanmasa, javob yolg'on bo'lardi.
    """
    chosen = (objective or config.DEFAULT_OBJECTIVE).lower()
    if chosen not in config.OBJECTIVES:
        chosen = config.DEFAULT_OBJECTIVE

    if not cal.time_aware and chosen != "distance":
        cal.notes.append(t(lang, "cal.objective_fallback", objective=chosen))
        chosen = "distance"

    return Options(
        objective=chosen,
        respect_time_windows=respect_time_windows and cal.time_aware,
        respect_capacity=respect_capacity,
        time_aware=cal.time_aware,
        speed_kph=cal.average_speed_kph,
        plan_start=plan_start,
    )


def _dock_warnings(
    solution: solver.Solution,
    vehicles: list[Vehicle],
    notes: list[str],
    lang: str = texts.DEFAULT_LANG,
) -> None:
    """Yuklash joyidagi slotlar yetadimi — QATTIQ CHEKLOV EMAS, ogohlantirish.

    `dock_slot` da ish vaqti ham, xizmat davomiyligi ham yo'q, ya'ni
    "bir vaqtda nechta mashina sig'adi" degan savolga baza javob
    bermaydi. Shuning uchun bu yerda faqat slotlar bor-yo'qligi
    tekshiriladi va yo'q bo'lsa aytiladi.
    """
    location_ids = {
        stop.location_id
        for sequence in solution.routes.values()
        for stop in sequence
        if stop.location_id
    }
    if not location_ids:
        return
    try:
        slots = queries.fetch_dock_slots(sorted(location_ids))
    except queries.PlanningDataError:
        return
    if not slots:
        notes.append(t(lang, "note.dock_missing"))
        return
    available = sum(1 for s in slots if (s.get("status") or "") == "AVAILABLE")
    used = len([e for e in solution.evaluations.values() if e.visits])
    if available and used > available:
        notes.append(t(lang, "note.dock_queue", used=used, available=available))


# -------------------------------------------------------- 2-yo'l: qo'lda


def plan_manual(payload: dict[str, Any]) -> dict[str, Any]:
    """So'rovda berilgan nuqta va mashinalar bo'yicha reja tuzadi.

    BAZAGA UMUMAN MUROJAAT QILINMAYDI (kalibrovka ham). Shuning uchun
    bu yo'l baza bo'sh bo'lganda ham, baza yotganda ham ishlaydi —
    modulni sinash va tashqi tizimdan kelgan ma'lumot bilan
    rejalashtirish uchun.
    """
    started = time.perf_counter()
    lang = texts.normalize(payload.get("lang"))
    notes: list[str] = [t(lang, "note.manual")]

    cal = calibration.calibrate(
        road_factor_override=payload.get("road_factor"),
        speed_override=payload.get("average_speed_kph"),
        service_override=None,
        read_database=False,
        lang=lang,
    )

    orders: list[Order] = []
    for item in payload["stops"]:
        weight = item.get("weight_kg")
        volume = item.get("volume_m3")
        service = float(item.get("service_minutes") or cal.service_minutes or 0.0)
        orders.append(
            Order(
                id=str(item["id"]),
                number=item.get("number") or str(item["id"]),
                priority=(item.get("priority") or "NORMAL"),
                required_transport_type=_type_code(
                    item.get("required_transport_type")),
                weight_kg=weight,
                volume_m3=volume,
                origin_name=item.get("pickup_name"),
                destination_name=item.get("dropoff_name"),
                pickup=Stop(
                    kind="PICKUP", order_id=str(item["id"]), node=None,
                    name=item.get("pickup_name"),
                    latitude=item["pickup_latitude"], longitude=item["pickup_longitude"],
                    demand_kg=weight or 0.0, demand_m3=volume or 0.0,
                    window_from=naive(item.get("pickup_from")),
                    window_to=naive(item.get("pickup_to")),
                    service_minutes=service,
                ),
                delivery=Stop(
                    kind="DELIVERY", order_id=str(item["id"]), node=None,
                    name=item.get("dropoff_name"),
                    latitude=item["dropoff_latitude"], longitude=item["dropoff_longitude"],
                    demand_kg=-(weight or 0.0), demand_m3=-(volume or 0.0),
                    window_from=naive(item.get("dropoff_from")),
                    window_to=naive(item.get("dropoff_to")),
                    service_minutes=service,
                ),
            )
        )

    plan_start = _plan_reference(None, orders)

    vehicles = [
        Vehicle(
            id=str(item["id"]),
            start_node=None,
            plate_number=item.get("plate_number"),
            transport_type=_type_code(item.get("transport_type")),
            capacity_kg=item.get("capacity_kg"),
            capacity_m3=item.get("capacity_m3"),
            start_name=item.get("start_name") or t(lang, "misc.start_point"),
            start_latitude=item["start_latitude"],
            start_longitude=item["start_longitude"],
            shift_from=naive(item.get("shift_from")) or plan_start,
            shift_to=naive(item.get("shift_to")),
            max_duration_minutes=item.get("max_duration_minutes"),
            driver_id=item.get("driver_id"),
            driver_name=item.get("driver_name"),
            return_to_start=bool(item.get("return_to_start", True)),
        )
        for item in payload["vehicles"]
    ]

    matrix = _attach_nodes(orders, vehicles, cal)
    options = _options(
        payload.get("objective"), cal, plan_start,
        bool(payload.get("respect_time_windows", True)),
        bool(payload.get("respect_capacity", True)),
        lang,
    )
    solution = solver.solve(orders, vehicles, matrix, options)

    scope = {
        "source": "manual",
        "on_date": plan_start.date(),
        "statuses": [],
        "request_ids": [o.id for o in orders],
        "depot_location_id": None,
        "depot_name": None,
        "depot_latitude": None,
        "depot_longitude": None,
        "window_from": None,
        "window_to": None,
        "respect_time_windows": options.respect_time_windows,
        "respect_capacity": options.respect_capacity,
        "hazard_summary": {},
        "locked_requests": 0,
    }

    return _build_report(
        scope=scope, cal=cal, orders=orders, vehicles=vehicles,
        solution=solution, matrix=matrix, options=options,
        counts={}, notes=notes, started=started, lang=lang,
    )
