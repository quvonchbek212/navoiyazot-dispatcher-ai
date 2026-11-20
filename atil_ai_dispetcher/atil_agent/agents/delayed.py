"""Kechikayotgan reyslarni kuzatuvchi agent."""

from __future__ import annotations

from typing import Any

from atil_ai_dispetcher.atil_agent import config
from atil_ai_dispetcher.atil_agent.texts import spec
from atil_ai_dispetcher.atil_agent.agents.watcher import ListWatcher, short
from atil_ai_dispetcher.atil_agent.base import Cycle
from atil_ai_dispetcher.dispatcher_assistant import service as da_service


class DelayedAgent(ListWatcher):
    name = "delayed"
    kind = "delayed"
    title = "kechikayotgan reyslar"
    list_key = "list.delayed"
    action_url = "/dispatcher/delayed"
    endpoint = "GET /dispatcher/delayed"
    primary_source = "trip"
    group_field = "kind"

    def fetch(self, cycle: Cycle) -> dict[str, Any]:
        return da_service.delayed(now=cycle.now, limit=config.SCAN_LIMIT)

    def key(self, item: dict[str, Any]) -> str:
        """Reys + KECHIKISH TURI.

        `NOT_DEPARTED` dan `LATE_EN_ROUTE` ga o'tish — YANGI vaziyat:
        birinchisida reysni hali to'xtatib bo'lardi, ikkinchisida yo'q.
        Shuning uchun bu o'tish qayta xabar qilinadi.
        """
        return f"{item.get('trip_id')}:{item.get('kind')}"

    def line_spec(self, item: dict[str, Any]) -> dict[str, Any]:
        who = item.get("plate_number") or short(item.get("vehicle_id"))
        soat = (item.get("delay_minutes") or 0) / 60
        turi = spec(
            "delay.not_departed" if item.get("kind") == "NOT_DEPARTED"
            else "delay.en_route"
        )
        # Ma'lumot bo'laklari (raqam, ism, manzil) tarjima qilinmaydi —
        # ular kalitga PARAMETR bo'lib kiradi.
        qoshimcha = [who]
        if item.get("driver_name"):
            qoshimcha.append(str(item["driver_name"]))
        if item.get("destination"):
            qoshimcha.append(str(item["destination"]))
        return spec(
            "line.delayed",
            trip=item.get("trip_number") or short(item.get("trip_id")),
            hours=f"{soat:.1f}",
            kind=turi,
            tail=qoshimcha,
        )

    def entity(self, items: list[dict[str, Any]]) -> dict[str, str]:
        # `entity_id` faqat qator BITTA bo'lganda: uchta reysga bitta id
        # yozish qolgan ikkitasini jimgina yo'qotardi.
        if len(items) != 1:
            return {"entity_type": "trip"}
        return {
            "entity_type": "trip",
            "entity_id": str(items[0].get("trip_id") or ""),
            "entity_number": str(items[0].get("trip_number") or ""),
        }
