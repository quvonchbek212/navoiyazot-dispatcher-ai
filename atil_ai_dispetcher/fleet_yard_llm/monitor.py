"""Evidence-based fleet monitoring. No missing interval is counted as idle."""

from collections import Counter, defaultdict
from bisect import bisect_left
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from atil_ai_dispetcher.Marshrut_optimizatsiyasi.geo import haversine_km
from atil_ai_dispetcher.fleet_yard_llm import config, queries, rules, service
from atil_ai_dispetcher.fleet_yard_llm.models import GPSPoint
from atil_ai_dispetcher.fleet_yard_llm.monitor_models import MonitorRequest

STATUSES = (
    "GARAGE_STOPPED", "GARAGE_MOVING", "ROAD_MOVING", "ROAD_SLOW", "ROAD_STOPPED",
    "SIGNAL_LOST", "NO_GPS_DATA", "GPS_MAPPING_UNVERIFIED", "LOCATION_ONLY", "UNKNOWN",
)
MOVING = {"GARAGE_MOVING", "ROAD_MOVING", "ROAD_SLOW"}
HISTORY_PRIORITY = {"telematics_event": 0, "gps_archive_point": 1, "position_log": 2}


def _side(point, request):
    distance = haversine_km(point.latitude, point.longitude, request.garage.latitude, request.garage.longitude) * 1000
    if distance <= request.garage.radius_meters - request.policy.hysteresis_meters:
        return "INSIDE"
    if distance >= request.garage.radius_meters + request.policy.hysteresis_meters:
        return "OUTSIDE"
    return "BOUNDARY"


def prepare_points(groups, telemetry, start, end):
    """Merge compatible duplicates. Disagreeing sources are never silently selected."""
    by_time = defaultdict(list)
    rejected = 0
    untrusted = set()
    source_counts = Counter()
    for source, rows in groups.items():
        for row in rows:
            copies = row.get("_copies", 1)
            point = service._point(row, source)
            if point is None or not point.valid or not start <= rules.local_time(point.timestamp) <= end:
                rejected += copies
                at = row.get("timestamp")
                if isinstance(at, datetime) and start <= rules.local_time(at) <= end:
                    untrusted.add(rules.local_time(at))
                continue
            by_time[rules.local_time(point.timestamp)].append((source, point, copies))
            source_counts[source] += copies
    latest_history = max(by_time, default=None)
    snapshot = None
    if telemetry:
        snapshot = service._point({k: v for k, v in telemetry.items() if k != "vehicle_id"}, "telematics_event")
    # An isolated state snapshot can show freshness, but never supplies the missing history.
    if snapshot and snapshot.valid and rules.local_time(snapshot.timestamp) <= end and (
        latest_history is None or snapshot.timestamp > latest_history
    ):
        by_time[rules.local_time(snapshot.timestamp)].append(("vehicle_telemetry_state", snapshot, 1))
        source_counts["vehicle_telemetry_state"] += 1
    points, duplicates, conflicts = [], 0, 0
    last_conflict = None
    for at, candidates in sorted(by_time.items()):
        coords = {(p.latitude, p.longitude) for _, p, _ in candidates}
        speeds = {p.speed_kph for _, p, _ in candidates if p.speed_kph is not None}
        engines = {p.engine_on for _, p, _ in candidates if p.engine_on is not None}
        weight = sum(copies for _, _, copies in candidates)
        if len(coords) > 1 or len(speeds) > 1 or len(engines) > 1:
            conflicts += 1
            rejected += weight
            last_conflict = at
            untrusted.add(at)
            continue
        source, point, _ = min(candidates, key=lambda x: HISTORY_PRIORITY.get(x[0], 3))
        speed_point = next((p for _, p, _ in sorted(candidates, key=lambda x: HISTORY_PRIORITY.get(x[0], 3)) if p.speed_kph is not None), point)
        points.append(point.model_copy(update={"timestamp": at, "speed_kph": next(iter(speeds), None), "engine_on": next(iter(engines), None), "speed_basis": speed_point.speed_basis}))
        duplicates += weight - 1
    accepted, impossible, latest_rejected = [], 0, last_conflict
    for point in points:
        if accepted:
            previous = accepted[-1]
            seconds = (point.timestamp - previous.timestamp).total_seconds()
            km = haversine_km(previous.latitude, previous.longitude, point.latitude, point.longitude)
            if km / seconds * 3600 > 400:
                impossible += 1
                rejected += 1
                untrusted.add(point.timestamp)
                latest_rejected = max(latest_rejected or point.timestamp, point.timestamp)
                continue
        accepted.append(point)
    latest_rejected = max(untrusted, default=latest_rejected)
    return accepted, {"rejected_points": rejected, "duplicate_points": duplicates,
                    "conflicting_timestamps": conflicts, "source_points": dict(source_counts),
                    "kinematically_rejected_points": impossible,
                    "latest_point_untrusted": bool(latest_rejected and (not accepted or latest_rejected > accepted[-1].timestamp)),
                    "untrusted_timestamps": sorted(untrusted)}


def interval_kind(left, right, request):
    dt = (right.timestamp - left.timestamp).total_seconds()
    if dt > request.policy.max_gap_seconds:
        return "SIGNAL_GAP"
    distance = haversine_km(left.latitude, left.longitude, right.latitude, right.longitude) * 1000
    if distance / dt * 3.6 > 400:
        return "SENSOR_CONFLICT"
    a, b = _side(left, request), _side(right, request)
    if a != b or a == "BOUNDARY":
        return "TRANSITION"
    speeds = left.speed_kph, right.speed_kph
    if any(v is None for v in speeds):
        return "LOCATION_ONLY"
    if max(speeds) <= request.policy.stationary_speed_kph:
        if distance > request.policy.stationary_radius_meters:
            # The vehicle may have moved and stopped between the two fixes.
            # This disproves continuous standing, not necessarily the sensors.
            return "POSITION_CHANGED_BETWEEN_STOPS"
        return "GARAGE_STOPPED" if a == "INSIDE" else "ROAD_STOPPED"
    if min(speeds) > request.policy.stationary_speed_kph:
        if a == "INSIDE":
            return "GARAGE_MOVING"
        return "ROAD_SLOW" if max(speeds) <= request.policy.slow_speed_kph else "ROAD_MOVING"
    return "TRANSITION"


def _intervals(points, request, untrusted=()):
    def kind(a, b):
        index = bisect_left(untrusted, a.timestamp)
        if index < len(untrusted) and untrusted[index] <= b.timestamp:
            return "SENSOR_CONFLICT"
        return interval_kind(a, b, request)
    return [{"from_at": a.timestamp, "to_at": b.timestamp,
             "seconds": (b.timestamp - a.timestamp).total_seconds(),
             "kind": kind(a, b)} for a, b in zip(points, points[1:])]


def _episodes(intervals):
    result = []
    for row in intervals:
        if row["kind"] not in {"GARAGE_STOPPED", "ROAD_STOPPED", "ROAD_SLOW", "SIGNAL_GAP"}:
            continue
        if result and result[-1]["kind"] == row["kind"] and result[-1]["to_at"] == row["from_at"]:
            result[-1]["to_at"] = row["to_at"]
            result[-1]["observed_minutes"] += row["seconds"] / 60
        else:
            result.append({"kind": row["kind"], "from_at": row["from_at"], "to_at": row["to_at"],
                           "observed_minutes": row["seconds"] / 60})
    for row in result:
        row["observed_seconds"] = round(row["observed_minutes"] * 60, 6)
        row["observed_minutes"] = round(row["observed_minutes"], 2)
    return result


def _yard(points, vid, request, start, end, untrusted=()):
    # All fields here already passed MonitorRequest/GPSPoint validation. The pure
    # geofence engine is reused without the old manual-sample 31-day resource cap.
    return rules.evaluate(SimpleNamespace(vehicle_id=vid, from_at=start, to_at=end,
        points=[p for p in points if start <= p.timestamp <= end], zone=request.garage, policy=request.policy,
        untrusted_timestamps=untrusted))


def _current(points, yard, request, end, mapping, truncated, intervals):
    last = points[-1] if points else None
    age = max(0, (end - last.timestamp).total_seconds()) if last else None
    current = {"status": "UNKNOWN", "last_signal_at": last.timestamp if last else None,
               "signal_age_seconds": round(age, 1) if age is not None else None,
               "latitude": last.latitude if last else None, "longitude": last.longitude if last else None,
               "speed_kph": last.speed_kph if last else None, "engine_on": last.engine_on if last else None,
               "speed_basis": last.speed_basis if last and last.speed_kph is not None else "UNAVAILABLE",
               "road_context_verified": False,
               "garage_idle_observed_minutes": None, "road_stop_observed_minutes": None,
               "slow_movement_observed_minutes": None}
    if truncated:
        return current
    if mapping is not True:
        current["status"] = "GPS_MAPPING_UNVERIFIED"
    elif last is None:
        current["status"] = "NO_GPS_DATA"
    elif age > request.policy.signal_timeout_seconds:
        current["status"] = "SIGNAL_LOST"
    elif yard["state_at_window_end"] in ("INSIDE", "OUTSIDE") and not (
        intervals and intervals[-1]["kind"] in ("SENSOR_CONFLICT", "POSITION_CHANGED_BETWEEN_STOPS")
    ):
        if last.speed_kph is None:
            current["status"] = "LOCATION_ONLY"
        elif yard["state_at_window_end"] == "INSIDE":
            current["status"] = "GARAGE_STOPPED" if last.speed_kph <= request.policy.stationary_speed_kph else "GARAGE_MOVING"
        elif last.speed_kph <= request.policy.stationary_speed_kph:
            current["status"] = "ROAD_STOPPED"
        elif last.speed_kph <= request.policy.slow_speed_kph:
            current["status"] = "ROAD_SLOW"
        else:
            current["status"] = "ROAD_MOVING"
    return current


def _period(points, intervals, work, days, end, request):
    start = end - timedelta(days=days)
    selected = [p for p in points if start <= p.timestamp <= end]
    totals = Counter()
    gaps = 0
    # Clip boundary-spanning observations to the requested window.
    for row in intervals:
        seconds = (min(end, row["to_at"]) - max(start, row["from_at"])).total_seconds()
        if seconds <= 0:
            continue
        if row["kind"] == "SIGNAL_GAP":
            gaps += 1
        elif row["kind"] != "SENSOR_CONFLICT":
            totals[row["kind"]] += seconds
    moving = sum(totals[k] for k in MOVING)
    classifiable = sum(totals[k] for k in MOVING | {"GARAGE_STOPPED", "ROAD_STOPPED"})
    return {"days": days, "from_at": start, "to_at": end, "gps_points": len(selected),
        "observation_status": "PARTIAL" if selected else "NO_DATA",
        "movement_observed": moving > 0 if classifiable else None,
        "garage_stationary_observed": totals["GARAGE_STOPPED"] > 0 if classifiable else None,
        "garage_only_observed": bool(totals["GARAGE_STOPPED"]) and all(_side(p, request) == "INSIDE" for p in selected) if classifiable else None,
        "moving_observed_minutes": round(moving / 60, 2) if classifiable else None,
        "garage_stopped_observed_minutes": round(totals["GARAGE_STOPPED"] / 60, 2) if classifiable else None,
        "road_stopped_observed_minutes": round(totals["ROAD_STOPPED"] / 60, 2) if classifiable else None,
        "slow_moving_observed_minutes": round(totals["ROAD_SLOW"] / 60, 2) if classifiable else None,
        "signal_gap_count": gaps,
        "interval_coverage_percent": round(sum(totals.values()) / (days * 86400) * 100, 4),
        "coverage_verified": False,
        "work_count": work["work_count"], "distance_km": work["distance_km"], "engine_hours": work["engine_hours"],
        "work_status": work["review_status"], "record_quality": work.get("record_quality", {}),
        "notes": work.get("notes", [])}


def _identity(vehicle):
    return {"vehicle_id": vehicle["id"], "plate_number": vehicle.get("plate_number"),
            "brand": vehicle["brand"], "model": vehicle["model"]}


def build_report(data: dict[str, Any], request: MonitorRequest, *, end: datetime) -> dict[str, Any]:
    end = rules.local_time(end)
    start = end - timedelta(days=request.days)
    windows = [d for d in (1, 7, 15, 30, 60) if d <= request.days]
    work_reports = {d: service.build_utilization(data["work"], days=d, to_at=end, limit=config.MAX_VEHICLES) for d in windows}
    work_by_window = {d: {i["vehicle_id"]: i for i in r["items"]} for d, r in work_reports.items()}
    vehicles, alerts = [], []
    detail_limit = config.MONITOR_DETAIL_LIMIT
    for vehicle in data["work"]["vehicles"]:
        vid = vehicle["id"]
        identity = _identity(vehicle)
        points, quality = prepare_points(data["history"].get(vid, {}), data.get("telemetry", {}).get(vid), start, end)
        untrusted = quality.pop("untrusted_timestamps")
        intervals = _intervals(points, request, untrusted)
        episodes = _episodes(intervals)
        yard = _yard(points, vid, request, start, end, untrusted)
        truncated = vid in data.get("truncated_vehicle_ids", set())
        current = _current(points, yard, request, end,
            data["work"].get("gps_rows", {}).get(vid, {}).get("mapping_verified"),
            truncated or quality["latest_point_untrusted"], intervals)

        def alert(code, message, *, severity="warning", at=None, active=True, **details):
            alerts.append({**identity, "code": code, "severity": severity, "message": message,
                           "occurred_at": at or end, "active": active, **details})

        if current["status"] == "SIGNAL_LOST":
            alert("GPS_SIGNAL_LOST", "Oxirgi GPS nuqtasidan keyin belgilangan muddatda signal kuzatilmadi; joylashuv noma'lum.",
                  last_signal_at=current["last_signal_at"], signal_age_seconds=current["signal_age_seconds"])
        elif current["status"] == "NO_GPS_DATA":
            alert("GPS_DATA_MISSING", "GPS bog'langan, lekin yaroqli nuqta topilmadi. Signal uzilganini isbotlash uchun oldingi signal kerak.")
        elif current["status"] == "GPS_MAPPING_UNVERIFIED":
            alert("GPS_MAPPING_UNVERIFIED", "Hisobot vaqtida transportning GPS bog'lanishi tasdiqlanmagan.", severity="info")
        if truncated:
            alert("GPS_DATA_TRUNCATED", "GPS qator limiti sabab tarix to'liq emas; joriy holat noma'lum.")
        if quality["conflicting_timestamps"]:
            alert("GPS_TIMESTAMP_CONFLICT", "Bir vaqtda turli GPS qiymatlari kelgan; bu nuqtalar va ularni kesib o'tuvchi oraliqlar hisobdan chiqarildi.",
                  active=False, count=quality["conflicting_timestamps"])
        for ep in episodes:
            active = bool(points and ep["to_at"] == points[-1].timestamp and current["status"] == ep["kind"])
            ep["ongoing"] = active
            if active:
                name = {"GARAGE_STOPPED": "garage_idle_observed_minutes", "ROAD_STOPPED": "road_stop_observed_minutes", "ROAD_SLOW": "slow_movement_observed_minutes"}.get(ep["kind"])
                if name:
                    current[name] = ep["observed_minutes"]
            if ep["kind"] == "ROAD_STOPPED" and ep["observed_seconds"] >= request.policy.long_stop_minutes * 60:
                alert("LONG_ROAD_STOP", "Garajdan tashqarida uzoq to'xtash kuzatilgan; to'xtash sababini dispetcher bilan tekshiring.",
                      at=ep["to_at"], active=active, from_at=ep["from_at"], to_at=ep["to_at"], observed_minutes=ep["observed_minutes"])
            if ep["kind"] == "ROAD_SLOW" and ep["observed_seconds"] >= request.policy.slow_duration_minutes * 60:
                alert("POSSIBLE_CONGESTION", "Davomli sekin yurish kuzatilgan. Tirbandlik ehtimoli bor, ammo yo'l sharoiti va topshiriq bilan tekshirilmagan.",
                      at=ep["to_at"], active=active, hypothesis=True, from_at=ep["from_at"], to_at=ep["to_at"], observed_minutes=ep["observed_minutes"])
            if ep["kind"] == "SIGNAL_GAP":
                alert("GPS_HISTORY_GAP", "Ketma-ket GPS nuqtalari orasida signal kuzatilmagan oraliq bor. Bu vaqt turish hisobiga qo'shilmagan.",
                      at=ep["to_at"], active=False, from_at=ep["from_at"], to_at=ep["to_at"], gap_minutes=ep["observed_minutes"])
        conflicts = sum(i["kind"] == "SENSOR_CONFLICT" for i in intervals) + quality["kinematically_rejected_points"]
        if conflicts:
            alert("GPS_SENSOR_CONFLICT", "Koordinata harakati va sensor o'lchovlari mos emas; ziddiyatli oraliqlar turish hisobiga qo'shilmadi.", active=False, count=conflicts)
        changes = sum(i["kind"] == "POSITION_CHANGED_BETWEEN_STOPS" for i in intervals)
        if changes:
            alert("POSITION_CHANGED_BETWEEN_STOPS", "Nuqtalarda tezlik past, lekin koordinatalar siljigan. Transport oraliqda yurib qayta to'xtagan bo'lishi mumkin; bu vaqt uzluksiz turish deb hisoblanmadi.", active=False, count=changes)
        quality.update({"status": "NO_DATA" if not points else "PARTIAL", "used_points": len(points),
            "truncated": truncated, "sensor_conflict_intervals": conflicts, "history_coverage_verified": False,
            "speed_available_points": sum(p.speed_kph is not None for p in points),
            "speed_bases": dict(Counter(p.speed_basis for p in points if p.speed_kph is not None)),
            "first_signal_at": points[0].timestamp if points else None,
            "last_signal_at": points[-1].timestamp if points else None,
            "notes": yard["data_quality"]["notes"] + (["Qator limiti sabab tarix to'liq emas."] if truncated else [])})
        if points and not quality["speed_available_points"]:
            quality["notes"].append("Tezlik km/soat birligida mavjud emas; harakat/to'xtash tezlikdan baholanmadi.")
        periods = [_period(points, intervals, work_by_window[d][vid], d, end, request) for d in windows]
        observations = [f"Davrda {yard['summary']['entries']} kirish va {yard['summary']['exits']} chiqish GPS orqali tasdiqlangan."] if points else ["Yaroqli GPS nuqtasi topilmadi; garajda turgan yoki harakatlangan degan hukm chiqarilmaydi."]
        if periods[-1]["work_count"]:
            observations.append(f"Davr hujjatlarida {periods[-1]['work_count']} ta birlashtirilgan ish qayd etilgan; bu GPS orqali joylashuv tasdig'i emas.")
        vehicles.append({**identity, "current": current, "garage": {
            "entries": yard["summary"]["entries"], "exits": yard["summary"]["exits"],
            "observed_inside_minutes": yard["summary"]["observed_inside_minutes"],
            "events": yard["events"][-detail_limit:], "visits": yard["visits"][-detail_limit:],
            "detail_truncated": len(yard["events"]) > detail_limit or len(yard["visits"]) > detail_limit},
            "periods": periods, "episodes": episodes[-detail_limit:],
            "episodes_truncated": len(episodes) > detail_limit,
            "data_quality": quality, "observations": observations, "observations_source": "calculated"})

    by_status = {s: sum(v["current"]["status"] == s for v in vehicles) for s in STATUSES}
    known = sum(by_status[s] for s in MOVING | {"GARAGE_STOPPED", "ROAD_STOPPED"})
    periods = []
    for index, days in enumerate(windows):
        pairs = [(v, v["periods"][index]) for v in vehicles]
        observed = sum(p["movement_observed"] is not None for _, p in pairs)
        def identities(condition):
            return [{k: v[k] for k in ("vehicle_id", "plate_number", "brand", "model")} for v, p in pairs if condition(p)]
        moving = identities(lambda p: p["movement_observed"] is True)
        garage = identities(lambda p: p["garage_stationary_observed"] is True)
        garage_only = identities(lambda p: p["garage_only_observed"] is True)
        work = identities(lambda p: p["work_count"] > 0)
        periods.append({"days": days, "from_at": end - timedelta(days=days), "to_at": end,
            "gps_classifiable_vehicles": observed, "moving_observed_count": len(moving) if observed else None,
            "garage_stopped_observed_count": len(garage) if observed else None,
            "moving_vehicles": moving, "garage_stopped_vehicles": garage, "garage_only_observed_vehicles": garage_only,
            "work_recorded_count": len(work), "work_recorded_vehicles": work,
            "interpretation": "GPS faqat kuzatilgan oraliqlarni ko'rsatadi. Faqat garajda kuzatilganlik butun davr garajda turganini isbotlamaydi.",
            "work_data_quality": work_reports[days]["data_quality"]})
    alerts.sort(key=lambda a: (not a["active"], -a["occurred_at"].timestamp(), a["plate_number"] or ""))
    summary = {"total_vehicles": len(vehicles), "by_status": by_status,
        "garage_stopped_count": by_status["GARAGE_STOPPED"] if known else None,
        "moving_count": sum(by_status[s] for s in MOVING) if known else None,
        "road_stopped_count": by_status["ROAD_STOPPED"] if known else None,
        "slow_moving_count": by_status["ROAD_SLOW"] if known else None,
        "unknown_count": len(vehicles) - known,
        "signal_lost_count": by_status["SIGNAL_LOST"],
        "active_long_stop_count": sum(a["code"] == "LONG_ROAD_STOP" and a["active"] for a in alerts),
        "active_possible_congestion_count": sum(a["code"] == "POSSIBLE_CONGESTION" and a["active"] for a in alerts),
        "counts_are_lower_bounds": known < len(vehicles),
        "alerts_total": len(alerts), "alerts_by_code": dict(Counter(a["code"] for a in alerts)),
        "active_alerts_by_code": dict(Counter(a["code"] for a in alerts if a["active"])),
        "alerts_truncated": len(alerts) > 5000,
        "count_semantics": "GPS bilan tasdiqlangan holatlar sanaladi. Noma'lum transportlar to'xtagan yoki harakatdagi soniga qo'shilmaydi; umuman tasdiq bo'lmasa son null."}
    quality = {"status": "NO_DATA" if not any(v["data_quality"]["used_points"] for v in vehicles) else "PARTIAL",
        "gps_sources": data["sources"], "gps_truncated": data.get("gps_truncated", False),
        "fleet_scope_truncated": data.get("scope_truncated", False),
        "work_truncated": data["work"]["truncated"],
        "gps_read_complete": getattr(data["history"], "complete", not data.get("gps_truncated", False)),
        "gps_rows_read": getattr(data["history"], "rows_read", sum(sum(v["data_quality"]["source_points"].values()) for v in vehicles)),
        "gps_unique_rows_read": getattr(data["history"], "distinct_rows_read", None),
        "speed_units_by_provider": config.ARCHIVE_SPEED_UNITS,
        "thresholds_are_configurable_pilot_values": True,
        "notes": ["GPS nuqtalari orasidagi davomiyliklar kuzatuvdan baholanadi; signal bo'shliqlari turishga qo'shilmaydi.",
                  "Qayd etilmagan ish transport ishlamaganini anglatmaydi.",
                  "Sekin yurish tirbandlikni isbotlamaydi; hodisa ehtimol sifatida qaytariladi.",
                  "Garajdan tashqaridagi nuqta xarita bilan yo'lga moslanmagan; u boshqa maydon yoki to'xtash joyi ham bo'lishi mumkin.",
                  "Ogohlantirishlar shu so'rov javobida qaytadi; tashqi xabar yoki fon jo'natmasi yo'q."]}
    return {"generated_at": datetime.now(config.TZ), "as_of": end, "from_at": start, "days": request.days,
        "garage": request.garage.model_dump(), "plate_number": request.plate_number,
        "policy": request.policy.model_dump(), "summary": summary, "periods": periods,
        "vehicles": vehicles, "alerts": alerts[:5000], "data_quality": quality, "analysis": {}}


def report(request: MonitorRequest, *, now: datetime | None = None, cancelled=None):
    current_time = rules.local_time(now or datetime.now(config.TZ))
    end = rules.local_time(request.as_of or current_time)
    if end > current_time:
        raise ValueError("as_of kelajakda bo'lishi mumkin emas")
    data = queries.monitor_data(from_at=end - timedelta(days=request.days), to_at=end, plate_number=request.plate_number)
    if hasattr(data["history"], "cancelled"):
        data["history"].cancelled = cancelled
    try:
        return build_report(data, request, end=end)
    finally:
        close = getattr(data["history"], "close", None)
        if close:
            close()
