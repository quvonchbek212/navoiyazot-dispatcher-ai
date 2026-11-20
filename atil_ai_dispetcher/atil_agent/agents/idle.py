"""Bekor turgan mashinalarni kuzatuvchi agent."""

from __future__ import annotations

from typing import Any

from atil_ai_dispetcher.atil_agent import config
from atil_ai_dispetcher.atil_agent.texts import spec
from atil_ai_dispetcher.atil_agent.agents.watcher import ListWatcher, short
from atil_ai_dispetcher.atil_agent.base import Cycle
from atil_ai_dispetcher.dispatcher_assistant import service as da_service


class IdleAgent(ListWatcher):
    name = "idle"
    kind = "idle"
    title = "bekor turgan mashinalar"
    list_key = "list.idle"
    action_url = "/dispatcher/idle"
    endpoint = "GET /dispatcher/idle"
    primary_source = "vehicle_telemetry_state"

    def fetch(self, cycle: Cycle) -> dict[str, Any]:
        return da_service.idle(now=cycle.now, limit=config.SCAN_LIMIT)

    def key(self, item: dict[str, Any]) -> str:
        """Mashina + TO'XTASH BOSHLANGAN PAYT.

        Bir to'xtash bir marta xabar qilinadi; yangi to'xtash — yangi
        kalit. `stopped_since` telematikadan keladi va bitta to'xtash
        davomida o'zgarmaydi, shuning uchun mashina 5 soat turganda ham
        xabar bitta bo'ladi.
        """
        return f"{item.get('vehicle_id')}:{item.get('stopped_since') or '-'}"

    def line_spec(self, item: dict[str, Any]) -> dict[str, Any]:
        who = item.get("plate_number") or short(item.get("vehicle_id"))
        daqiqa = item.get("stopped_minutes")
        davomiylik = (
            spec("idle.unknown") if daqiqa is None
            else spec("idle.standing", hours=f"{daqiqa / 60:.1f}")
        )
        qoshimcha = []
        if item.get("engine_on"):
            # Dvigatel ishlab turib to'xtagan mashina yoqilg'ini behuda
            # yoqadi — bu alohida aytilishi kerak.
            qoshimcha.append(spec("idle.engine_on"))
        if item.get("driver_name"):
            qoshimcha.append(str(item["driver_name"]))
        return spec(
            "line.idle",
            who=who,
            duration=davomiylik,
            # Bo'laklarning bir qismi kalit, bir qismi ma'lumot —
            # ikkalasi ham `render` orqali o'tadi.
            tail=qoshimcha,
        )

    def entity(self, items: list[dict[str, Any]]) -> dict[str, str]:
        if len(items) != 1:
            return {"entity_type": "vehicle"}
        return {
            "entity_type": "vehicle",
            "entity_id": str(items[0].get("vehicle_id") or ""),
            "entity_number": str(items[0].get("plate_number") or ""),
        }
