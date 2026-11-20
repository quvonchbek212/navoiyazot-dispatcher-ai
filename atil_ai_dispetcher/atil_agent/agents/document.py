"""Hujjat muddatini kuzatuvchi agent.

BU AGENT QOLGAN UCHTASIDAN FARQ QILADI va farq muhim.

`/dispatcher/documents` oyna berilmasa HAMMA hujjatni qaytaradi
(03.09.2026 da 412 ta, ichida 2036-yilgacha amal qiladigani ham bor).
Ularning hammasini "hodisa" deb hisoblash mumkin emas. Shuning uchun bu
yerda hodisa — MUDDATI O'TISHI: `valid_until < bugun`. Bu chegara emas,
sana bilan solishtirish.

Oldindan ogohlantirish kerak bo'lsa `.env` da `AGENT_DOCUMENTS_DAYS`
beriladi. Sukut bo'yicha u BO'SH, chunki "necha kun qolgani xavfli"
degan raqamni baza aytmaydi va u kodda O'YLAB TOPILMAGAN.

DAVRIYLIGI HAM BOSHQACHA: hujjat muddati — SANA, u yarim tundan boshqa
paytda o'zgara olmaydi. Shuning uchun kuniga bir marta yetadi; 15
daqiqada tekshirish bir xil javobni 96 marta olib kelardi.
"""

from __future__ import annotations

from typing import Any

from atil_ai_dispetcher.atil_agent import config
from atil_ai_dispetcher.atil_agent.texts import spec
from atil_ai_dispetcher.atil_agent.agents.watcher import ListWatcher, short
from atil_ai_dispetcher.atil_agent.base import Cycle
from atil_ai_dispetcher.dispatcher_assistant import service as da_service


class DocumentAgent(ListWatcher):
    name = "document"
    kind = "documents"
    title = "muddati o'tgan hujjatlar"
    list_key = "list.document"
    action_url = "/dispatcher/documents"
    endpoint = "GET /dispatcher/documents"
    #: Guvohnoma va tibbiy sertifikat shu jadvaldan keladi. Bo'sh bo'lsa
    #: hujjat tekshiruvining o'zi yo'q.
    primary_source = "driver"
    group_field = "document_type"

    @property
    def interval_seconds(self) -> int:
        return config.DOCUMENTS_INTERVAL_SECONDS

    def fetch(self, cycle: Cycle) -> dict[str, Any]:
        return da_service.documents(
            today=cycle.now.date(), days=config.DOCUMENTS_DAYS, limit=config.SCAN_LIMIT
        )

    def alertable(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Muddati o'tganlar, va oyna berilgan bo'lsa unga tushganlar.

        `days_left is None` — muddat NOMA'LUM, "yaqin emas" degani emas:
        bunday qator oynaga tushmaydi, chunki uni solishtirib bo'lmaydi.
        """
        oyna = config.DOCUMENTS_DAYS
        result = []
        for item in items:
            if item.get("expired"):
                result.append(item)
            elif oyna is not None and item.get("days_left") is not None:
                if item["days_left"] <= oyna:
                    result.append(item)
        return result

    def key(self, item: dict[str, Any]) -> str:
        """Kim + hujjat turi + AMAL QILISH SANASI.

        Hujjat yangilansa sana o'zgaradi, eski kalit yo'qoladi va yangisi
        (endi muddati o'tmagan) hodisa bo'lmaydi.
        """
        return f"{item.get('subject_id')}:{item.get('document_type')}:{item.get('valid_until')}"

    def line_spec(self, item: dict[str, Any]) -> dict[str, Any]:
        kim = item.get("subject_name") or short(item.get("subject_id"))
        kunlar = item.get("days_left")
        if item.get("expired"):
            holat = (
                spec("document.expired_days", days=abs(kunlar))
                if kunlar is not None
                else spec("document.expired")
            )
        else:
            holat = (
                spec("document.expires_in", days=kunlar)
                if kunlar is not None
                else spec("document.unknown")
            )
        return spec(
            "line.document",
            who=kim,
            type=item.get("document_type"),
            state=holat,
        )

    def entity(self, items: list[dict[str, Any]]) -> dict[str, str]:
        # Hujjat haydovchiga ham, mashinaga ham tegishli bo'lishi mumkin —
        # turni qatorning O'ZI aytadi, biz taxmin qilmaymiz.
        tur = str((items[0].get("subject_type") if items else "") or "").lower()
        if len(items) != 1:
            return {"entity_type": tur}
        return {
            "entity_type": tur,
            "entity_id": str(items[0].get("subject_id") or ""),
            "entity_number": str(items[0].get("subject_name") or ""),
        }
