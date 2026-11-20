"""Qism almashtirish vaqtini kuzatuvchi agent.

Hisobni `parts_control.passport` ning O'ZI qiladi — agent SQL yozmaydi va
oraliqlarni takrorlamaydi. Xabarga faqat "vaqti o'tgan" va "vaqti
yaqinlashgan" qismlar chiqadi; holati noma'lum qism xabar emas (u
pasportda "tarix yo'q" deb turadi).

Kalitda oxirgi almashtirish sanasi bor: qism almashtirilib, keyin yana
vaqti kelsa — bu YANGI hodisa va qayta xabar qilinadi.
"""

from __future__ import annotations

from typing import Any

from atil_ai_dispetcher.atil_agent.agents.watcher import ListWatcher, short
from atil_ai_dispetcher.atil_agent.base import Cycle
from atil_ai_dispetcher.atil_agent.texts import by_lang, spec
from parts_control import passport, rules
from parts_control import texts as pc_texts
from vehicle_reference import components as cat


class ServiceDueAgent(ListWatcher):
    name = "service"
    kind = "parts_service"
    title = "qism almashtirish vaqti"
    list_key = "list.service"
    action_url = "/parts-control/passport"
    endpoint = "GET /parts-control/passport"
    primary_source = "vehicle_part"
    group_field = "status"

    def fetch(self, cycle: Cycle) -> dict[str, Any]:
        fleet = passport.load_fleet()
        items: list[dict[str, Any]] = []
        for vehicle in fleet.vehicles:
            result = passport.vehicle_states(vehicle, fleet, today=cycle.now.date())
            for state in result["states"]:
                if state["status"] not in (passport.OVERDUE, passport.DUE_SOON):
                    continue
                last = state.get("last_replaced")
                items.append({
                    "vehicle_id": vehicle["vehicle_id"],
                    "plate_number": vehicle.get("plate_number"),
                    "vehicle": rules.vehicle_name(vehicle.get("brand"), vehicle.get("model")),
                    "component": state["key"],
                    "status": state["status"],
                    "used_pct": state.get("used_pct"),
                    "last_day": str(last.day) if last and last.day else "",
                })
        return {"items": items, "data_quality": {"notes": []}}

    def key(self, item: dict[str, Any]) -> str:
        return f"{item['vehicle_id']}:{item['component']}:{item['status']}:{item['last_day']}"

    def line_spec(self, item: dict[str, Any]) -> dict[str, Any]:
        component = cat.COMPONENTS.get(item["component"])
        name = by_lang({lang: component.name(lang) if component else item["component"]
                        for lang in pc_texts.LANGS})
        status = by_lang({lang: pc_texts.t(lang, f"status.{item['status']}")
                          for lang in pc_texts.LANGS})
        return spec(
            "line.service",
            plate=item.get("plate_number") or short(item.get("vehicle_id")),
            vehicle=item.get("vehicle") or "—",
            component=name,
            status=status,
            pct=f"{item.get('used_pct') or 0:.0f}",
        )

    def entity(self, items: list[dict[str, Any]]) -> dict[str, str]:
        if len({i["vehicle_id"] for i in items}) != 1:
            return {"entity_type": "vehicle"}
        return {
            "entity_type": "vehicle",
            "entity_id": str(items[0]["vehicle_id"]),
            "entity_number": str(items[0].get("plate_number") or ""),
        }
