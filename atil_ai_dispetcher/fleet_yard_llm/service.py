"""Manba qatorlarini geofence va flot hisobotiga aylantirish."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from statistics import median
from typing import Any

from pydantic import ValidationError

from atil_ai_dispetcher.fleet_yard_llm import config, queries, rules
from atil_ai_dispetcher.fleet_yard_llm.models import EvaluateRequest, GPSPoint, HistoryRequest


def _point(row: dict[str, Any], source: str) -> GPSPoint | None:
    try:
        row = dict(row)
        unit = row.pop("_speed_unit", None)
        provider = row.pop("_provider_connection", "")
        row.pop("_copies", None)
        if source == "gps_archive_point" and "payload" in row:
            data = json.loads(row["payload"]) if isinstance(row.get("payload"), str) else row.get("payload")
            # Faqat ochiq belgilangan koordinata kontrakti qabul qilinadi.
            if not isinstance(data, dict):
                return None
            unit = "kph" if data.get("speed_kph") is not None else config.ARCHIVE_SPEED_UNITS.get(str(provider).upper())
            row = {
                "timestamp": row["timestamp"], "latitude": data.get("latitude"),
                "longitude": data.get("longitude"), "valid": data.get("valid", True),
                "speed_kph": data.get("speed_kph") if data.get("speed_kph") is not None else (data.get("speed") if unit else None),
                "engine_on": data.get("engine_on"),
            }
        speed = row.get("speed_kph")
        if unit and speed is not None:
            factors = {"kph": 1, "knots": 1.852, "mph": 1.609344, "mps": 3.6}
            if unit not in factors or isinstance(speed, bool):
                row["speed_kph"] = None
            else:
                row["speed_kph"] = float(speed) * factors[unit]
                row["speed_basis"] = "REPORTED_KPH" if unit == "kph" else "CONVERTED_" + unit.upper()
        return GPSPoint.model_validate(row)
    except (ValidationError, ValueError, TypeError):
        return None


def visits(request: HistoryRequest, *, now: datetime | None = None) -> dict[str, Any]:
    if request.to_at > (now or datetime.now(config.TZ)):
        raise ValueError("to_at kelajakda bo'lishi mumkin emas")
    data = queries.history(
        vehicle_id=str(request.vehicle_id), from_at=request.from_at,
        to_at=request.to_at, source=request.source,
    )
    points = [point for row in data["rows"] if (point := _point(row, request.source)) is not None]
    report = rules.evaluate(EvaluateRequest(**request.model_dump(exclude={"source"}), points=points))
    report["source"] = request.source
    report["plate_number"] = data["vehicle"].get("plate_number")
    quality = report["data_quality"]
    rejected = len(data["rows"]) - len(points)
    quality["input_points"] += rejected
    quality["rejected_points"] += rejected
    if rejected:
        quality["notes"].append(f"Format yoki koordinata xatosi sabab {rejected} ta yozuv o'qilmadi.")
        if quality["status"] == "OK":
            quality["status"] = "PARTIAL"
    if request.source in ("position_log", "gps_archive_point"):
        quality["notes"].append("Provider speed birligi tasdiqlanmagan; faqat aniq speed_kph mavjud bo'lsa bekor turish hisoblanadi.")
    if data["truncated"]:
        quality["truncated"] = True
        quality["status"] = "PARTIAL"
        quality["notes"].append("GPS qator limiti oshdi; davrni qisqartiring. Davr oxiridagi holat noma'lum.")
        report["state_at_window_end"] = "UNKNOWN"
    return report


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def _delta(row: dict[str, Any], start: str, end: str) -> float | None:
    a, b = _number(row.get(start)), _number(row.get(end))
    return b - a if a is not None and b is not None and b >= a else None


def build_utilization(data: dict[str, Any], *, days: int, to_at: datetime, limit: int, offset: int = 0) -> dict[str, Any]:
    end = rules.local_time(to_at)
    start = end - timedelta(days=days)
    notes = [
        "GPS kuzatuvi to'liqligi tasdiqlanmagan; ish yozuvi yo'qligi transport ishlamaganini isbotlamaydi.",
        "Hisobotdagi butun reys masofasi uning jo'nash yoki qaytish vaqti davrga tushsa olinadi; kunlar bo'yicha taqsimlanmagan.",
    ]
    # Bitta trip va uning waybill'i faqat bir marta sanaladi.
    work: dict[tuple[str, str], dict[str, Any]] = {}
    invalid_records = 0
    invalid_reasons: Counter[str] = Counter()
    invalid_by_vehicle: dict[str, Counter[str]] = defaultdict(Counter)
    invalid_counts: Counter[str] = Counter()

    def times(row: dict[str, Any]) -> list[datetime]:
        nonlocal invalid_records
        raw = [rules.local_time(row[k]) for k in ("started_at", "ended_at") if row.get(k) is not None]
        reasons = []
        if any(t.year < 2000 for t in raw):
            reasons.append("SENTINEL_DATE")
        if any(t > end for t in raw):
            reasons.append("FUTURE_DATE")
        if len(raw) == 2 and raw[1] < raw[0]:
            reasons.append("RETURN_BEFORE_DEPARTURE")
        if reasons:
            invalid_records += 1
            invalid_counts[row["vehicle_id"]] += 1
            invalid_reasons.update(reasons)
            invalid_by_vehicle[row["vehicle_id"]].update(reasons)
            return []
        return [t for t in raw if start <= t < end]

    def record(row: dict[str, Any], key: str, stamps: list[datetime]) -> dict[str, Any]:
        entry = work.setdefault((row["vehicle_id"], key), {
            "at": max(stamps), "trip_km": None, "trip_hours": None,
            "waybill_km": [], "waybill_hours": [], "notes": [],
            "activity_dates": set(),
        })
        entry["at"] = max(entry["at"], max(stamps))
        entry["activity_dates"].update(t.date() for t in stamps)
        return entry

    for row in data["trips"]:
        if row.get("status") in ("CANCELLED", "INTERRUPTED"):
            continue
        stamps = times(row)
        if not stamps:
            continue
        entry = record(row, "trip:" + row["id"], stamps)
        # trip.actual_distance_km da 0 ko'pincha to'ldirilmagan default.
        km = _number(row.get("distance_km"))
        entry["trip_km"] = km if km and km > 0 else None
        hours = _number(row.get("engine_hours"))
        entry["trip_hours"] = hours if hours and hours > 0 else None
    for row in data["waybills"]:
        if row.get("status") not in ("IN_USE", "RETURNED", "CLOSED"):
            continue
        stamps = times(row)
        if not stamps:
            continue
        key = "trip:" + row["trip_id"] if row.get("trip_id") else "waybill:" + row["id"]
        entry = record(row, key, stamps)
        km = _delta(row, "odometer_start_km", "odometer_end_km")
        hour_values = [v for v in (
            _number(row.get("motohours_worked")),
            _delta(row, "pre_trip_motohours", "post_trip_motohours"),
            _delta(row, "moto_hours_start", "moto_hours_end"),
        ) if v is not None]
        hours = hour_values[0] if hour_values else None
        if hour_values and max(hour_values) - min(hour_values) > 0.001:
            hours = None
            entry["notes"].append("Yo'l varaqasida motosaat o'lchovlari bir-biriga mos emas.")
        entry["waybill_km"].append(km)
        entry["waybill_hours"].append(hours)
        if row.get("odometer_end_km") is not None and row.get("odometer_start_km") is not None and km is None:
            entry["notes"].append("Yo'l varaqasida spidometr farqi yaroqsiz.")

    by_vehicle: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (vehicle_id, _), entry in work.items():
        by_vehicle[vehicle_id].append(entry)

    def measure(entries: list[dict[str, Any]], name: str) -> float | None:
        values = []
        for entry in entries:
            documented = entry["waybill_" + name]
            if len(documented) == 1 and documented[0] is not None:
                value = documented[0]
            elif entry["trip_" + name] is not None:
                value = entry["trip_" + name]
            else:
                value = None
            if value is None:
                return None  # qisman summani jami deb chiqarmaymiz
            values.append(value)
        return round(sum(values), 3) if values else None

    repair_by_vehicle: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for repair in data.get("repair_rows", []):
        context = {
            "repair_id": repair["id"], "status": repair["status"],
            "component_category": repair.get("component_category"),
            "opened_at": rules.local_time(repair["opened_at"]),
            "days_open": round(max(0, (end - rules.local_time(repair["opened_at"])).total_seconds() / 86400), 2),
            "blocks_release": bool(repair.get("blocks_release")),
            "overdue_days": None,
        }
        if repair.get("estimated_completion_time"):
            context["overdue_days"] = round(max(0, (end - rules.local_time(repair["estimated_completion_time"])).total_seconds() / 86400), 2)
        repair_by_vehicle[repair["vehicle_id"]].append(context)
    items = []
    peer_keys = {}
    for vehicle in data["vehicles"]:
        entries = by_vehicle.get(vehicle["id"], [])
        item_notes = list(dict.fromkeys(n for e in entries for n in e["notes"]))
        excluded = invalid_counts[vehicle["id"]]
        if excluded:
            item_notes.append(f"Sana xatosi bor {excluded} ta hujjat hisobga olinmadi; hujjatlarni tekshiring.")
        if any(len(e["waybill_km"]) > 1 for e in entries):
            item_notes.append("Bitta reysga bir nechta varaqa bog'langan; takror sanamaslik uchun reys o'lchovi olinadi, u bo'lmasa jami noma'lum.")
        status = vehicle["current_status"]
        created = rules.local_time(vehicle["created_at"])
        commissioning = vehicle.get("commissioning_date")
        new = created >= start or (
            commissioning is not None
            and rules.local_time(datetime.combine(commissioning, time.min)) >= start
        )
        if status == "DECOMMISSIONED":
            review, recommendation = "DECOMMISSIONED", "ALREADY_DECOMMISSIONED"
        elif entries:
            review, recommendation = "WORK_RECORDED", "REVIEW_UTILIZATION"
            if vehicle["id"] in data["repair_ids"]:
                item_notes.append("Ochiq ta'mir bor; shu davrda ish ham qayd etilgan.")
        elif vehicle["id"] in data["repair_ids"] or status == "IN_MAINTENANCE":
            review, recommendation = "IN_REPAIR", "CHECK_REPAIR"
        elif new:
            review, recommendation = "NEW_VEHICLE", "BUILD_OBSERVATION_HISTORY"
        elif status in ("RESERVED", "BLOCKED"):
            review, recommendation = "RESERVED_OR_BLOCKED", "CHECK_RESERVE_OR_BLOCK_REASON"
        else:
            review, recommendation = "NO_RECORDED_WORK", "VERIFY_RECORDS_AND_DEMAND"
        if excluded and review == "NO_RECORDED_WORK":
            review, recommendation = "DATA_INCOMPLETE", "VERIFY_RECORDS_AND_DEMAND"
        if commissioning is None:
            item_notes.append("Foydalanishga topshirilgan sana yo'q.")
        if not (vehicle.get("plate_number") or "").strip():
            item_notes.append("Davlat raqami kiritilmagan; transport UUID orqali ajratildi.")
        if any(not (vehicle.get(key) or "").strip() or vehicle[key].strip() == "1" for key in ("brand", "model")):
            item_notes.append("Marka/model ma'lumoti to'liq emas yoki namuna qiymatga o'xshaydi; kartochkani tekshiring.")
        gps_row = data.get("gps_rows", {}).get(vehicle["id"], {})
        signal = gps_row.get("last_event_at")
        gps_context = {
            "mapping_verified": gps_row.get("mapping_verified"),
            "last_signal_at": rules.local_time(signal) if signal else None,
            "signal_age_minutes": round((end - rules.local_time(signal)).total_seconds() / 60, 1) if signal else None,
            "history_coverage_verified": False,
        }
        demand_available = data.get("demand_by_type") is not None and bool(vehicle.get("transport_type"))
        demand_row = (data.get("demand_by_type") or {}).get(vehicle.get("transport_type"), {})
        demand_context = {
            "source": "transport_request", "scope": "ALL_BRANCHES_SAME_TRANSPORT_TYPE",
            "request_count": int(demand_row.get("request_count", 0)) if demand_available else None,
            "unassigned_count": int(demand_row.get("unassigned_count", 0)) if demand_available else None,
        }
        peer_keys[vehicle["id"]] = (
            vehicle.get("branch_id"), vehicle.get("transport_type"),
            (vehicle["brand"] or "").strip().casefold(), (vehicle["model"] or "").strip().casefold(),
            vehicle["usage_mode"],
        )
        items.append({
            "vehicle_id": vehicle["id"], "plate_number": vehicle.get("plate_number"),
            "brand": vehicle["brand"], "model": vehicle["model"],
            "usage_mode": vehicle["usage_mode"], "ownership_type": vehicle["ownership_type"],
            "current_status": status, "review_status": review, "recommendation": recommendation,
            "work_count": len(entries), "distance_km": measure(entries, "km"),
            "engine_hours": measure(entries, "hours"),
            "latest_recorded_work_at": max((e["at"] for e in entries), default=None),
            "notes": item_notes,
            "transport_type": vehicle.get("transport_type"),
            "recorded_activity_days": len(set().union(*(e["activity_dates"] for e in entries))) if entries else 0,
            "history_days_in_window": round(min(days, max(0, (end - created).total_seconds() / 86400)), 2),
            "peer_comparison": {}, "gps_context": gps_context,
            "repair_context": repair_by_vehicle.get(vehicle["id"], []),
            "demand_context": demand_context,
            "record_quality": {
                "excluded_work_records": excluded,
                "exclusion_reasons": dict(invalid_by_vehicle[vehicle["id"]]),
                "work_count_is_lower_bound": bool(excluded or data["truncated"]),
                "measurement_notes": list(dict.fromkeys(n for e in entries for n in e["notes"])),
            },
        })
    if invalid_records:
        labels = {"SENTINEL_DATE": "sentinel sana", "FUTURE_DATE": "kelajak sanasi", "RETURN_BEFORE_DEPARTURE": "qaytish jo'nashdan oldin"}
        details = "; ".join(f"{labels[key]}: {count}" for key, count in invalid_reasons.items())
        notes.append(f"{invalid_records} ta hujjat sana xatosi sabab hisobga olinmadi ({details}). Bitta hujjatda bir nechta sabab bo'lishi mumkin.")
    if data["truncated"]:
        notes.append("Qator limiti oshdi; flot yoki davrni qisqartiring. Ishsiz transport xulosasi chiqarilmaydi.")
        for item in items:
            if item["review_status"] == "NO_RECORDED_WORK":
                item["review_status"], item["recommendation"] = "DATA_INCOMPLETE", "RETRY_SMALLER_SCOPE"
    for item in items:
        peers = [other for other in items
                 if other["vehicle_id"] != item["vehicle_id"]
                 and peer_keys[other["vehicle_id"]] == peer_keys[item["vehicle_id"]]
                 and other["history_days_in_window"] >= days
                 and not other["record_quality"]["excluded_work_records"]
                 and other["current_status"] in ("ACTIVE", "IN_OPERATION")
                 and other["vehicle_id"] not in data["repair_ids"]]
        comparable = (
            item["history_days_in_window"] >= days and len(peers) >= 2
            and bool(peer_keys[item["vehicle_id"]][0]) and bool(peer_keys[item["vehicle_id"]][1])
            and all(value and value != "1" for value in peer_keys[item["vehicle_id"]][2:4])
            and not item["record_quality"]["excluded_work_records"]
            and not data["truncated"]
        )
        peer_median = float(median(p["work_count"] for p in peers)) if comparable else None
        item["peer_comparison"] = {
            "scope": "SAME_BRANCH_TYPE_BRAND_MODEL_USAGE_MODE", "other_vehicles": len(peers),
            "comparable": comparable, "median_recorded_work_count": peer_median,
            "below_peer_median": item["work_count"] < peer_median if peer_median is not None else None,
        }
    distribution = dict(Counter(item["review_status"] for item in items))
    priority = {"NO_RECORDED_WORK": 0, "DATA_INCOMPLETE": 1, "IN_REPAIR": 2, "NEW_VEHICLE": 3}
    items.sort(key=lambda i: (priority.get(i["review_status"], 4), i["work_count"], i["plate_number"] or i["vehicle_id"]))
    return {
        "generated_at": datetime.now(config.TZ), "from_at": start, "to_at": end,
        "days": days, "summary": {
            "total": len(items), "returned": len(items[offset:offset + limit]), "by_status": distribution,
            "offset": offset, "has_more": offset + limit < len(items),
        },
        "items": items[offset:offset + limit],
        "data_quality": {
            "status": "PARTIAL", "notes": notes, "truncated": data["truncated"],
            "invalid_work_records": invalid_records,
            "invalid_work_records_by_reason": dict(invalid_reasons),
            "vehicles_with_invalid_work_records": len(invalid_counts),
            "measurement_coverage": {
                "vehicles_with_work": sum(bool(i["work_count"]) for i in items),
                "vehicles_with_complete_distance": sum(i["distance_km"] is not None for i in items),
                "vehicles_with_complete_engine_hours": sum(i["engine_hours"] is not None for i in items),
            },
        },
    }


def utilization(*, days: int, vehicle_id: str | None = None, limit: int = config.DEFAULT_LIMIT, offset: int = 0, now: datetime | None = None) -> dict[str, Any]:
    end = rules.local_time(now or datetime.now(config.TZ))
    data = queries.utilization(from_at=end - timedelta(days=days), to_at=end, vehicle_id=vehicle_id)
    return build_utilization(data, days=days, to_at=end, limit=limit, offset=offset)
