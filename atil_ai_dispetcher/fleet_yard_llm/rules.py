"""Bazasiz geofence hisoblash. Signal oralig'i yo'q bo'lsa holat noma'lum."""

from __future__ import annotations

from collections import defaultdict
from bisect import bisect_left
from datetime import datetime
from typing import Any

from atil_ai_dispetcher.Marshrut_optimizatsiyasi.geo import haversine_km
from atil_ai_dispetcher.fleet_yard_llm import config
from atil_ai_dispetcher.fleet_yard_llm.models import EvaluateRequest, GPSPoint


def local_time(value: datetime) -> datetime:
    """Zonasiz DB timestamp'lar ATIL lokal vaqti sifatida talqin qilinadi."""
    if value.tzinfo is None or value.utcoffset() is None:
        return config.TZ.localize(value)
    return value.astimezone(config.TZ)


def evaluate(request: EvaluateRequest) -> dict[str, Any]:
    start, end = local_time(request.from_at), local_time(request.to_at)
    policy, zone = request.policy, request.zone
    quality: dict[str, Any] = {
        "status": "OK", "notes": [], "input_points": len(request.points),
        "used_points": 0, "rejected_points": 0, "duplicate_points": 0,
        "conflicting_timestamps": 0, "signal_gaps": 0, "truncated": False,
    }
    groups: dict[datetime, list[GPSPoint]] = defaultdict(list)
    for point in request.points:
        timestamp = local_time(point.timestamp)
        if not point.valid or not start <= timestamp <= end:
            quality["rejected_points"] += 1
            continue
        groups[timestamp].append(point)

    # Bir vaqtda qarama-qarshi koordinata yoki sensor qiymati bo'lsa
    # nuqta tanlab olinmaydi. Qayta yuborilgan aynan bir xil nuqta bitta.
    points: list[tuple[datetime, GPSPoint, str | None]] = []
    for timestamp, duplicates in sorted(groups.items()):
        signatures = {
            (p.latitude, p.longitude, p.speed_kph, p.engine_on) for p in duplicates
        }
        if len(signatures) > 1:
            quality["conflicting_timestamps"] += 1
            quality["rejected_points"] += len(duplicates)
            continue
        quality["duplicate_points"] += len(duplicates) - 1
        point = duplicates[0]
        meters = haversine_km(
            point.latitude, point.longitude, zone.latitude, zone.longitude
        ) * 1000
        side = (
            "INSIDE" if meters <= zone.radius_meters - policy.hysteresis_meters
            else "OUTSIDE" if meters >= zone.radius_meters + policy.hysteresis_meters
            else None
        )
        points.append((timestamp, point, side))
    quality["used_points"] = len(points)

    events: list[dict[str, Any]] = []
    visits: list[dict[str, Any]] = []
    stable: str | None = None
    pending: str | None = None
    pending_since: datetime | None = None
    pending_count = 0
    previous: datetime | None = None
    last_stable_at: datetime | None = None
    active_visit: dict[str, Any] | None = None
    untrusted = getattr(request, "untrusted_timestamps", ())

    def close_visit(at: datetime, reason: str) -> None:
        nonlocal active_visit
        if active_visit is not None:
            active_visit["observed_until"] = at
            active_visit["end_reason"] = reason
            active_visit["right_censored"] = reason != "EXIT"
            if reason == "EXIT":
                active_visit["exited_at"] = at
                if active_visit["entered_at"] is not None:
                    active_visit["duration_minutes"] = round(
                        (at - active_visit["entered_at"]).total_seconds() / 60, 2
                    )
            visits.append(active_visit)
            active_visit = None

    for timestamp, point, side in points:
        barrier = bisect_left(untrusted, previous) if previous is not None else len(untrusted)
        uncertain = barrier < len(untrusted) and untrusted[barrier] <= timestamp
        gap = previous is not None and (timestamp - previous).total_seconds() > policy.max_gap_seconds
        if previous is not None and (gap or uncertain):
            quality["signal_gaps"] += int(gap)
            close_visit(previous, "UNTRUSTED_GPS" if uncertain else "SIGNAL_GAP")
            stable, pending, pending_since, pending_count = None, None, None, 0
            last_stable_at = None
        previous = timestamp
        if side is None:
            # Chegara ichidagi noaniq nuqta tasdiqlash ketma-ketligini buzadi.
            pending, pending_since, pending_count = None, None, 0
            continue
        if side == stable:
            last_stable_at = timestamp
            pending, pending_since, pending_count = None, None, 0
            continue
        if pending != side:
            pending, pending_since, pending_count = side, timestamp, 1
        else:
            pending_count += 1
        assert pending_since is not None
        if pending_count < policy.confirmation_points:
            continue
        if (timestamp - pending_since).total_seconds() < policy.confirmation_seconds:
            continue

        known_transition = stable is not None
        if known_transition:
            events.append({
                "kind": "ENTER" if side == "INSIDE" else "EXIT",
                "occurred_at": pending_since, "confirmed_at": timestamp,
                "previous_observed_at": last_stable_at,
            })
        if side == "INSIDE":
            active_visit = {
                "entered_at": pending_since if known_transition else None,
                "exited_at": None, "observed_from": pending_since,
                "observed_until": timestamp, "left_censored": not known_transition,
                "right_censored": True, "end_reason": "WINDOW_END",
                "duration_minutes": None, "observed_inside_minutes": 0.0,
                "speed_observed_minutes": 0.0, "engine_observed_minutes": 0.0,
                "observed_stopped_minutes": None, "engine_on_stopped_minutes": None,
            }
        else:
            close_visit(pending_since, "EXIT")
        stable, last_stable_at = side, timestamp
        pending, pending_since, pending_count = None, None, 0

    if previous is not None:
        close_visit(previous, "WINDOW_END")

    # Faqat ketma-ket ichki nuqtalar orasidagi kuzatilgan vaqt yig'iladi.
    # Oxirgi signal -> hozir va signal uzilishi bu yig'indiga kirmaydi.
    visit_index = 0
    for left, right in zip(points, points[1:]):
        a, pa, side_a = left
        b, pb, side_b = right
        while visit_index < len(visits) and visits[visit_index]["observed_until"] < b:
            visit_index += 1
        if visit_index == len(visits):
            break
        visit = visits[visit_index]
        seconds = (b - a).total_seconds()
        if (
            a < visit["observed_from"] or b > visit["observed_until"]
            or seconds > policy.max_gap_seconds
            or side_a != "INSIDE" or side_b != "INSIDE"
        ):
            continue
        visit["observed_inside_minutes"] += seconds / 60
        if pa.speed_kph is not None and pb.speed_kph is not None:
            visit["speed_observed_minutes"] += seconds / 60
            if visit["observed_stopped_minutes"] is None:
                visit["observed_stopped_minutes"] = 0.0
            stopped = max(pa.speed_kph, pb.speed_kph) <= policy.stationary_speed_kph
            if stopped:
                visit["observed_stopped_minutes"] += seconds / 60
                if pa.engine_on is not None and pb.engine_on is not None:
                    visit["engine_observed_minutes"] += seconds / 60
                    if visit["engine_on_stopped_minutes"] is None:
                        visit["engine_on_stopped_minutes"] = 0.0
                    if pa.engine_on and pb.engine_on:
                        visit["engine_on_stopped_minutes"] += seconds / 60

    for visit in visits:
        for name in ("observed_inside_minutes", "speed_observed_minutes", "engine_observed_minutes", "observed_stopped_minutes", "engine_on_stopped_minutes"):
            if visit[name] is not None:
                visit[name] = round(visit[name], 2)

    last_signal = previous
    if last_signal is None or (end - last_signal).total_seconds() > policy.max_gap_seconds:
        state = "NO_SIGNAL"
    elif stable is None or pending is not None:
        state = "UNKNOWN"
    else:
        state = stable
    if not points:
        quality["status"] = "NO_DATA"
        quality["notes"].append("Davrda yaroqli GPS nuqtasi yo'q; keldi-ketdi tekshirilmadi.")
    else:
        if (points[0][0] - start).total_seconds() > policy.max_gap_seconds:
            quality["notes"].append("Davr boshida GPS kuzatuvi yetishmaydi.")
        if state == "NO_SIGNAL":
            quality["notes"].append("Davr oxirida GPS signali eskirgan; joriy joylashuv noma'lum.")
        if quality["signal_gaps"]:
            quality["notes"].append("Signal uzilgan oraliqlar garajda turgan vaqtga qo'shilmadi.")
        if quality["rejected_points"] or quality["duplicate_points"]:
            quality["notes"].append("Yaroqsiz, ziddiyatli yoki takroriy nuqtalar hisobdan ajratildi.")
        if state == "UNKNOWN":
            quality["notes"].append("Holatni tasdiqlash uchun ketma-ket GPS nuqtalari yetarli emas.")
        if quality["notes"]:
            quality["status"] = "PARTIAL"

    summary = {
        "entries": sum(e["kind"] == "ENTER" for e in events),
        "exits": sum(e["kind"] == "EXIT" for e in events),
        "visits": len(visits),
        "observed_inside_minutes": round(sum(v["observed_inside_minutes"] for v in visits), 2),
        "censored_visits": sum(v["left_censored"] or v["right_censored"] for v in visits),
    }
    return {
        "generated_at": datetime.now(config.TZ), "vehicle_id": str(request.vehicle_id),
        "source": "supplied", "from_at": start, "to_at": end,
        "zone": zone.model_dump(), "policy": policy.model_dump(),
        "state_at_window_end": state, "last_signal_at": last_signal,
        "summary": summary, "events": events, "visits": visits,
        "data_quality": quality,
    }
