"""LLM uchun anonim, tekshiriladigan faktlar va mumkin bo'lgan tavsiyalar."""

from __future__ import annotations

from typing import Any

from atil_ai_dispetcher.fleet_yard_llm.ai_models import EvidenceFact


SAFEGUARDS = [
    "GPS signali yo'qligi transport ishlamayotganini isbotlamaydi.",
    "Sabablar ehtimol sifatida beriladi; ularni mas'ul xodim tekshiradi.",
    "Sotish yoki balansdan chiqarish uchun xarajat, qiymat, mavsumiylik va zaxira ehtiyoji alohida baholanadi.",
    "AI tavsiya beradi; transport holatini o'zgartirish yoki sotish amalini bajarmaydi.",
]


def _fact(fid: str, metric: str, value: Any, source: str) -> dict[str, Any]:
    return EvidenceFact(id=fid, metric=metric, value=value, source=source).model_dump()


def packets(report: dict[str, Any], kind: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary = report["summary"]
    common = [
        _fact("S.kind", "Hisobot doirasi", "FLEET_UTILIZATION" if kind == "utilization" else "GPS_SINGLE_VEHICLE", "request"),
        _fact("S.from_at", "Tahlil davri boshi", report["from_at"], "request"),
        _fact("S.to_at", "Tahlil davri oxiri; hozirgi holat emas", report["to_at"], "request"),
        _fact("S.quality", "Ma'lumot sifati holati", report["data_quality"]["status"], "data_quality"),
        _fact("S.truncated", "Natija qator limiti bilan kesilganmi", report["data_quality"].get("truncated", False), "data_quality"),
        _fact("S.quality_notes", "Hisobning muhim cheklovlari", report["data_quality"].get("notes", []), "data_quality"),
    ]
    if kind == "utilization":
        common.extend([
            _fact("S.total", "Tekshirilgan transportlar soni", summary["total"], "transport_vehicle"),
            _fact("S.days", "Tahlil oynasi, kun", report["days"], "request"),
            _fact("S.statuses", "Butun tanlangan flot bo'yicha qayd holatlari", summary["by_status"], "trip+waybill+transport_vehicle+vehicle_repair"),
            _fact("S.returned", "Ushbu sahifadagi transportlar soni", len(report["items"]), "pagination"),
        ])
        items = report["items"]
    else:
        common.extend([
            _fact("S.entries", "Tasdiqlangan kirishlar", summary["entries"], report["source"]),
            _fact("S.exits", "Tasdiqlangan chiqishlar", summary["exits"], report["source"]),
            _fact("S.garage_minutes", "Garaj ichida kuzatilgan daqiqalar", summary["observed_inside_minutes"], report["source"]),
        ])
        items = [{"vehicle_id": report["vehicle_id"], "plate_number": report.get("plate_number"), "review_status": "GPS_OBSERVATION"}]

    result = []
    for index, item in enumerate(items, start=1):
        alias = f"V{index}"
        facts = []

        def add(key: str, label: str, value: Any, source: str):
            facts.append(_fact(f"{alias}.{key}", label, value, source))

        causes = {"INSUFFICIENT_EVIDENCE"}
        actions = {"VERIFY_RECORDS", "MONITOR"}
        missing = []
        add("status", "Hisoblangan qayd holati", item["review_status"], "calculated")
        if kind == "utilization":
            quality = item.get("record_quality") or {}
            add("record_quality", "Chiqarib tashlangan hujjatlar va o'lchov xatolari", quality, "trip+waybill")
            add("work", "Birlashtirilgan ish yozuvlari soni", item["work_count"], "trip+waybill")
            add("km", "Davr hujjatlaridagi jami o'lchangan masofa, km", item["distance_km"], "trip+waybill")
            add("hours", "Davr hujjatlaridagi motosaat", item["engine_hours"], "trip+waybill")
            add("active_days", "Ish sanasi qayd etilgan kunlar", item.get("recorded_activity_days"), "trip+waybill")
            add("history_days", "Bazaga qo'shilgandan keyingi kuzatuv oynasi, kun", item.get("history_days_in_window"), "transport_vehicle.created_at")
            add("usage", "O'lchash rejimi", item["usage_mode"], "transport_vehicle")
            add("ownership", "Egalik turi", item["ownership_type"], "transport_vehicle")
            add("latest_work", "Davrdagi oxirgi qayd etilgan ish", item["latest_recorded_work_at"], "trip+waybill")
            gps = item.get("gps_context") or {}
            add("gps_mapping", "GPS bog'lanishi tasdiqlanganmi", gps.get("mapping_verified"), "vehicle_gps")
            add("gps_last", "Tayyor telematika holatidagi oxirgi signal", gps.get("last_signal_at"), "vehicle_telemetry_state")
            repairs = [{key: value for key, value in r.items() if key != "repair_id"} for r in item.get("repair_context", [])]
            add("repairs", "Davr oxirida ochiq ta'mirlar", repairs, "vehicle_repair")
            peer = item.get("peer_comparison") or {}
            add("peers", "Shu filial, tur, marka, model va o'lchash rejimidagi boshqa transportlar", peer, "transport_vehicle+trip+waybill")
            demand = item.get("demand_context") or {}
            add("demand", "Shu transport turi bo'yicha tasdiqlangan talablar, barcha filiallar", demand, "transport_request")
            if item["work_count"] == 0 or quality.get("excluded_work_records") or quality.get("measurement_notes"):
                causes.add("DATA_RECORDING_GAP")
                actions.add("REVIEW_DEMAND")
            if item["review_status"] == "NEW_VEHICLE" or (item.get("history_days_in_window") is not None and item["history_days_in_window"] < report["days"]):
                causes.add("SHORT_HISTORY")
                actions.add("BUILD_HISTORY")
            if item["review_status"] == "IN_REPAIR" or repairs:
                causes.add("REPAIR_IN_PROGRESS")
                actions.add("CHECK_REPAIR")
            if item["review_status"] == "RESERVED_OR_BLOCKED":
                causes.add("RESERVE_OR_BLOCK")
                actions.add("REVIEW_RESERVE")
            if peer.get("comparable") and peer.get("below_peer_median") and item["review_status"] in ("WORK_RECORDED", "NO_RECORDED_WORK"):
                causes.add("ALLOCATION_IMBALANCE")
                actions.add("REVIEW_ALLOCATION")
            if demand.get("request_count") == 0:
                causes.add("NO_RECORDED_DEMAND")
                actions.add("REVIEW_DEMAND")
            if gps.get("mapping_verified") is False:
                causes.add("GPS_MAPPING_UNVERIFIED")
                actions.add("CHECK_GPS")
            elif gps.get("mapping_verified") is True and gps.get("last_signal_at") is None:
                causes.add("GPS_NOT_REPORTING")
                actions.add("CHECK_GPS")
            if quality.get("excluded_work_records"):
                missing.append("Sana xatolari tuzatilgan reys/yo'l varaqalari")
            if item["ownership_type"] == "RENTED":
                actions.add("REVIEW_RENTAL_COSTS")
            if item["distance_km"] is None and item["usage_mode"] in ("KM", "KM_AND_MOTOSOAT"):
                missing.append("To'liq va mos keladigan masofa o'lchovi")
            if item["engine_hours"] is None and item["usage_mode"] in ("MOTOSOAT", "KM_AND_MOTOSOAT"):
                missing.append("To'liq va mos keladigan motosaat o'lchovi")
            if not peer.get("comparable"):
                missing.append("Yetarli va taqqoslanadigan guruhdosh transportlar")
            if demand.get("request_count") is None:
                missing.append("Tasdiqlangan transport talabi ma'lumotlari")
            if not gps.get("history_coverage_verified"):
                missing.append("Butun davrni qamragan GPS tarixi")
            missing.extend(["Transportga tegishli saqlash/ta'mir xarajatlari va aktiv qiymati", "Mavsumiy ish va zaxira texnika siyosati"])
        else:
            add("entries", "Tasdiqlangan kirishlar", summary["entries"], report["source"])
            add("exits", "Tasdiqlangan chiqishlar", summary["exits"], report["source"])
            add("garage_minutes", "Garaj ichida kuzatilgan daqiqalar", summary["observed_inside_minutes"], report["source"])
            add("observation_source", "Nuqtalar manbasi; supplied bo'lsa so'rov namunasi", report["source"], "request")
            add("state", "Davr oxiridagi GPS holati", report["state_at_window_end"], report["source"])
            add("last_signal", "Davrdagi oxirgi GPS nuqtasi", report.get("last_signal_at"), report["source"])
            add("gaps", "Signal uzilgan oraliqlar soni", report["data_quality"]["signal_gaps"], "data_quality")
            add("points", "Hisobga olingan GPS nuqtalari", report["data_quality"]["used_points"], "data_quality")
            add("censored", "Chegarasi to'liq kuzatilmagan tashriflar", summary["censored_visits"], report["source"])
            engine = [v["engine_on_stopped_minutes"] for v in report["visits"] if v.get("engine_on_stopped_minutes") is not None]
            add("engine_idle", "Dvigatel yoqilgan holatda kuzatilgan to'xtash, daqiqa", round(sum(engine), 2) if engine else None, report["source"])
            if report["state_at_window_end"] in ("NO_SIGNAL", "UNKNOWN"):
                causes.add("GPS_NOT_REPORTING")
                actions.add("CHECK_GPS")
            if engine and sum(engine) > 0:
                causes.add("ENGINE_ON_STATIONARY")
                actions.add("REDUCE_ENGINE_IDLE")
            missing = ["Garajda turishning operatsion sababi va dispetcher topshirig'i", "Transportning reys/ta'mir tarixi"]
            if report["data_quality"]["status"] != "OK":
                missing.append("Uzluksiz va yaroqli GPS kuzatuvi")

        result.append({
            "alias": alias, "vehicle_id": item["vehicle_id"], "plate_number": item.get("plate_number"),
            "kind": kind,
            "review_status": item["review_status"], "facts": facts,
            "allowed_causes": sorted(causes), "allowed_actions": sorted(actions),
            "missing_evidence": missing,
        })
    return result, common
