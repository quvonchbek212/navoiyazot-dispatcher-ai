"""Yo'nalishdan og'gan mashinalarni kuzatuvchi agent."""

from __future__ import annotations

from typing import Any

from atil_ai_dispetcher.atil_agent import config
from atil_ai_dispetcher.atil_agent.texts import spec
from atil_ai_dispetcher.atil_agent.agents.watcher import ListWatcher, short
from atil_ai_dispetcher.atil_agent.base import Cycle
from atil_ai_dispetcher.dispatcher_assistant import service as da_service


class DeviationAgent(ListWatcher):
    name = "deviation"
    kind = "deviations"
    title = "yo'nalishdan og'gan mashinalar"
    list_key = "list.deviation"
    action_url = "/dispatcher/deviations"
    endpoint = "GET /dispatcher/deviations"
    #: Telematika holati bo'lmasa og'ish umuman aniqlanmaydi. 03.09.2026
    #: da bu jadval bo'sh, ya'ni bu agent bugun KO'R.
    primary_source = "vehicle_telemetry_state"

    def fetch(self, cycle: Cycle) -> dict[str, Any]:
        return da_service.deviations(now=cycle.now, limit=config.SCAN_LIMIT)

    def key(self, item: dict[str, Any]) -> str:
        """Mashina + marshrut.

        Og'ish tugab, keyin BOSHQA marshrutda qaytarilsa — bu boshqa
        hodisa.
        """
        return f"{item.get('vehicle_id')}:{item.get('route_id') or '-'}"

    def line_spec(self, item: dict[str, Any]) -> dict[str, Any]:
        who = item.get("plate_number") or short(item.get("vehicle_id"))
        metr = item.get("distance_from_route_meters")
        # `None` — "og'ish yo'q" EMAS, "masofa o'lchanmadi".
        masofa = (
            spec("deviation.unmeasured") if metr is None
            else spec("deviation.off_route", km=f"{metr / 1000:.1f}")
        )
        qoshimcha = []
        if item.get("driver_name"):
            qoshimcha.append(str(item["driver_name"]))
        if item.get("route_number"):
            qoshimcha.append(spec("deviation.route", number=item["route_number"]))
        return spec(
            "line.deviation",
            who=who,
            distance=masofa,
            # Marshrut raqami ham tarjima qilinadigan bo'lak, shuning
            # uchun u alohida kalit orqali qo'shiladi.
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
