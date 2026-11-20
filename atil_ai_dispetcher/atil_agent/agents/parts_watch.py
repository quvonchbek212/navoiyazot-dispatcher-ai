"""Ehtiyot qism shubhalarini kuzatuvchi agent.

Hisobni `parts_control` ning O'ZI qiladi. Xabarga faqat qism SO'ROVLARI
chiqadi (mos kelmaydigan, hisobsiz, erta almashtirilgan) — o'rnatilgan
qismlarning holati (resursi tugagan) har kuni o'zgarmaydi va xabar
bo'roniga aylanardi; u `/parts-control/scan` da.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from atil_ai_dispetcher.atil_agent import config
from atil_ai_dispetcher.atil_agent.agents.watcher import ListWatcher, short
from atil_ai_dispetcher.atil_agent.base import Cycle
from atil_ai_dispetcher.atil_agent.texts import by_lang, spec
from parts_control import rules as pc_rules
from parts_control import service as pc_service
from parts_control import texts as pc_texts

_ALERT_KINDS = ("MISMATCH", "CONTROL", "EARLY")


def _serious(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in item.get("flags") or [] if f.get("kind") in _ALERT_KINDS]


class PartsControlAgent(ListWatcher):
    name = "parts"
    kind = "parts_control"
    title = "ehtiyot qism shubhalari"
    list_key = "list.parts"
    action_url = "/parts-control/scan"
    endpoint = "GET /parts-control/scan"
    primary_source = "repair_order_part_request"
    group_field = "kind"

    def fetch(self, cycle: Cycle) -> dict[str, Any]:
        today = cycle.now.date()
        report = pc_service.scan(
            date_from=today - timedelta(days=config.PARTS_WINDOW_DAYS), date_to=today,
            limit=config.SCAN_LIMIT,
        )
        items = []
        for item in report.get("requests") or []:
            serious = _serious(item)
            if serious:
                items.append({**item, "kind": serious[0]["kind"]})
        report["items"] = items
        return report

    def key(self, item: dict[str, Any]) -> str:
        codes = sorted({f["code"] for f in _serious(item)})
        return f"{item.get('request_id')}:{','.join(codes)}"

    def line_spec(self, item: dict[str, Any]) -> dict[str, Any]:
        early = next((f for f in _serious(item)
                      if f["code"] == "EARLY_REPLACEMENT" and f.get("data")), None)
        if early:
            # Xulosa raqamlari bilan: "oldingisi resursining atigi 8% ini ishlatgan
            # (4 760 / 60 000 km, yana 55 240 km yurishi kerak edi) — tekshiring".
            d = early["data"]

            def amount(value: float) -> dict[str, Any]:
                v = (pc_rules.fmt(round(value, 1)) if d["by"] == "months"
                     else f"{value:,.0f}".replace(",", " "))
                return by_lang({lang: pc_texts.t(lang, f"unit.{d['by']}", v=v)
                                for lang in pc_texts.LANGS})

            return spec(
                "line.parts_early",
                plate=item.get("plate_number") or short(item.get("vehicle_id")),
                vehicle=item.get("vehicle") or "—",
                item=(item.get("item_name") or "—")[:60],
                pct=pc_rules.fmt(d["pct"]), used=amount(d["used"]), life=amount(d["life"]),
                left=amount(max(0.0, d["left"])),
            )
        what = [by_lang({lang: pc_texts.t(lang, f"flag.{f['code']}") for lang in pc_texts.LANGS})
                for f in _serious(item)[:2]]
        return spec(
            "line.parts",
            plate=item.get("plate_number") or short(item.get("vehicle_id")),
            vehicle=item.get("vehicle") or "—",
            item=(item.get("item_name") or "—")[:60],
            what=what,
        )

    def entity(self, items: list[dict[str, Any]]) -> dict[str, str]:
        if len(items) != 1:
            return {"entity_type": "repair_order"}
        return {
            "entity_type": "repair_order",
            "entity_id": str(items[0].get("repair_order_id") or ""),
        }
