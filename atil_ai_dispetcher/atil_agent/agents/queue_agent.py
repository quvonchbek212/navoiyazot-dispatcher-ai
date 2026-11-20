"""Rejalashtirishni kutayotgan arizalarni kuzatuvchi agent.

MUAMMO O'YLAB TOPILMAGAN. 03.09.2026 da bazada rejalashtirishni
kutayotgan 33 ta ariza bor va ULARNING HAMMASI rejadagi jo'nash vaqtini
o'tkazib yuborgan. Eng eskisi — `001-00033`, jo'nashi 21-avgustga
rejalashtirilgan, ya'ni 13 kundan beri navbatda turibdi. Hech kim
so'ramaguncha bu ro'yxat hech qayerda ko'rinmaydi.

MEYOR YO'Q. "Necha soat kutgan ariza kech qolgan" degan raqam bu faylda
ham yo'q. Ikkita solishtirish bor: ariza qachon kelgan (`created_at`) va
rejadagi jo'nash vaqti o'tganmi (`planned_departure_at < hozir`).
Ikkinchisi — kechikishning bazadagi o'z ta'rifi, biz qo'shgan chegara
emas.
"""

from __future__ import annotations

import functools
import time
from datetime import datetime
from typing import Any

from atil_ai_dispetcher.atil_agent import brain, channels, config, queries, state, texts
from atil_ai_dispetcher.atil_agent.texts import spec
from atil_ai_dispetcher.atil_agent.agents.watcher import fingerprint
from atil_ai_dispetcher.atil_agent.base import Agent, Cycle, Finding
from atil_ai_dispetcher.dispatcher_assistant.queries import to_float
from atil_ai_dispetcher.Marshrut_optimizatsiyasi import config as ro_config

#: Navbat ro'yxatining `Cycle` dagi kaliti — rejalashtiruvchi ham shuni
#: ishlatadi, ya'ni so'rov bir yurishda bir marta ketadi.
QUEUE_KEY = "waiting_requests"

PROMPT = """Sen ATIL avtopark dispetcherining yordamchisisan.

Quyida rejalashtirishni kutayotgan arizalar orasidan SHU TEKSHIRUVDA
YANGI paydo bo'lganlari berilgan.

{language_rule}

Faktlar:
{facts}

JSON qaytar, boshqa hech narsa yozma:
{{"summary": "1-2 jumla: dispetcher nimadan boshlashi kerak — YUQORIDA KO'RSATILGAN TILDA"}}

QAT'IY QOIDALAR:
- Faktlardagi sonlarni O'ZGARTIRMA va yangi son O'YLAB TOPMA.
- "Kech qolgan", "shoshilinch" kabi baho berma — chegara yo'q.
- Ro'yxatni qayta yozma, u xabarda allaqachon bor.
"""


def sort_key(row: dict[str, Any]) -> tuple:
    """Navbat tartibi — uchta mezon, shu ketma-ketlikda.

    1. JO'NASH VAQTI O'TGANLAR oldinda, kechikkani ko'proq bo'lgani
       tepada. Bu bazadagi `planned_departure_at` ga tayanadi.
    2. Muhimlik — `atil_ai_dispetcher.Marshrut_optimizatsiyasi.config.PRIORITY_ORDER`.
       Tartib ATAYLAB o'sha yerdan olinadi: reja arizalarni shu
       ketma-ketlikda joylashtiradi va navbat boshqacha ko'rsatsa,
       dispetcher ikki xil "birinchi" ko'rardi.
    3. Eskisi oldinda.
    """
    overdue = to_float(row.get("overdue_minutes"))
    created = row.get("created_at")
    return (
        0 if overdue is not None else 1,
        -(overdue or 0.0),
        ro_config.PRIORITY_ORDER.get(str(row.get("priority") or "").upper(), 99),
        created.timestamp() if isinstance(created, datetime) else float("inf"),
    )


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def queue_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": row.get("request_id"),
        "request_number": row.get("request_number"),
        "status": row.get("status"),
        "priority": row.get("priority"),
        "required_transport_type": row.get("required_transport_type"),
        "waybill_category": row.get("waybill_category"),
        "department": row.get("department_name"),
        "origin": row.get("origin_location"),
        "destination": row.get("destination_location"),
        "purpose": row.get("purpose") or row.get("cargo_description"),
        "initiator": row.get("initiator_name"),
        "created_at": row.get("created_at"),
        "planned_departure_at": row.get("planned_departure_at"),
        "waiting_hours": _round(to_float(row.get("waiting_hours"))),
        "overdue_minutes": _round(to_float(row.get("overdue_minutes"))),
    }


def queue_line(item: dict[str, Any]) -> dict[str, Any]:
    """Xabardagi bitta ariza qatori — KALIT ko'rinishida."""
    qoshimcha: list[Any] = []
    yol = " -> ".join(x for x in (item.get("origin"), item.get("destination")) if x)
    if yol:
        qoshimcha.append(yol)
    soat = item.get("waiting_hours")
    if soat is not None:
        qoshimcha.append(
            spec("queue.waited_days", days=f"{soat / 24:.0f}") if soat >= 48
            else spec("queue.waited_hours", hours=f"{soat:.0f}")
        )
    kech = item.get("overdue_minutes")
    if kech is not None:
        qoshimcha.append(spec("queue.overdue_by", hours=f"{kech / 60:.0f}"))
    return spec(
        "queue.line",
        number=item.get("request_number") or str(item.get("request_id"))[:8],
        priority=item.get("priority") or "NORMAL",
        type=item.get("required_transport_type") or "—",
        tail=qoshimcha,
    )


async def load_queue(cycle: Cycle) -> list[dict[str, Any]]:
    """Navbat — muhimlik tartibida. Bir yurishda bir marta so'raladi."""
    rows = await cycle.once(
        QUEUE_KEY,
        functools.partial(
            queries.fetch_waiting,
            now=cycle.now,
            statuses=ro_config.DEFAULT_REQUEST_STATUSES,
            limit=ro_config.MAX_REQUESTS,
        ),
    )
    return sorted((queue_item(r) for r in rows), key=sort_key)


class QueueAgent(Agent):
    name = "queue"
    kind = "backlog_queue"
    title = "rejalashtirishni kutayotgan arizalar"
    action_url = "/agent/queue"
    endpoint = "GET /agent/queue"
    #: Ariza jadvalisiz navbatning o'zi yo'q.
    primary_source = "transport_request"
    group = "backlog"

    @property
    def interval_seconds(self) -> int:
        return config.BACKLOG_INTERVAL_SECONDS

    async def run(self, cycle: Cycle) -> list[Finding]:
        store = state.store()
        items = await load_queue(cycle)
        overdue = [i for i in items if i.get("overdue_minutes") is not None]

        # IKKI XIL KALIT, BITTA RO'YXATDA: ariza NAVBATGA TUSHGANI va
        # keyinchalik JO'NASH VAQTINI O'TKAZIB YUBORGANI — ikki ayrim
        # hodisa. Ikkinchisi birinchisidan keyin sodir bo'lishi mumkin,
        # shuning uchun alohida kalit kerak.
        keys = [f"req:{i['request_id']}" for i in items]
        keys += [f"late:{i['request_id']}" for i in overdue]
        diff = store.plan_diff(self.kind, keys)

        by_id = {i["request_id"]: i for i in items}
        yangi = [by_id[k[4:]] for k in diff.new_keys if k.startswith("req:") and k[4:] in by_id]
        kechikkan = [
            by_id[k[5:]] for k in diff.new_keys if k.startswith("late:") and k[5:] in by_id
        ]

        findings: list[Finding] = []
        if diff.baseline:
            findings.append(self._baseline(items, overdue))
        else:
            if yangi:
                findings.append(await self._new_requests(yangi, len(items)))
            if kechikkan:
                findings.append(self._overdue(kechikkan))

        def saqla() -> None:
            store.commit_diff(diff, now=cycle.now)

        if findings:
            findings[-1].commit = saqla
        else:
            saqla()
        return findings

    # ----------------------------------------------------------- Topilmalar

    def _baseline(self, items: list[dict], overdue: list[dict]) -> Finding:
        return Finding(
            agent=self.name,
            kind=self.kind,
            event_type="baseline",
            severity=channels.INFO,
            title_spec=spec("queue.baseline.title"),
            text_spec=spec(
                "queue.baseline.text", total=len(items), overdue=len(overdue)),
            line_specs=[
                queue_line(i) for i in items[: config.MAX_ITEMS_IN_MESSAGE]],
            extra_count=max(0, len(items) - config.MAX_ITEMS_IN_MESSAGE),
            count=len(items),
            dedupe_key=f"{self.name}:baseline",
            entity_type="transport_request",
            action_url=self.action_url,
            hint_spec=spec("queue.hint.full", endpoint=self.endpoint),
            payload={"overdue": len(overdue)},
        )

    async def _new_requests(self, yangi: list[dict], total: int) -> Finding:
        shown = yangi[: config.MAX_ITEMS_IN_MESSAGE]
        # Model matni uch tilda yoziladi — o'qish paytida tarjima qilib
        # bo'lmaydi (`texts.py` boshidagi izoh).
        matn: dict[str, str] = {}
        source = "template"
        for til in texts.LANGS:
            shablon = texts.t(til, "queue.new.text", total=total)
            javob, bu_source = await brain.think(
                PROMPT.format(
                    language_rule=texts.llm_instruction(til),
                    facts=brain.facts(
                        {
                            "yangi_ariza": len(yangi),
                            "navbatdagi_jami": total,
                            "qatorlar": [
                                texts.render(queue_line(i), til)
                                for i in yangi[: config.LLM_FACT_LIMIT]
                            ],
                        }
                    ),
                ),
                role="agent",
                fallback=shablon,
                parse=lambda data: str(data["summary"]).strip() or shablon,
            )
            matn[til] = javob
            if bu_source == "llm":
                source = "llm"
        return Finding(
            agent=self.name,
            kind=self.kind,
            event_type="new_requests",
            # Ariza navbatga TUSHDI — bu odatiy ish oqimi, buzilgan
            # narsa emas.
            severity=channels.INFO,
            title_spec=spec("queue.new.title", count=len(yangi)),
            text_lang=matn,
            source=source,
            line_specs=[queue_line(i) for i in shown],
            extra_count=len(yangi) - len(shown),
            items=shown,
            count=len(yangi),
            dedupe_key=f"{self.name}:new:{fingerprint([str(i['request_id']) for i in yangi])}",
            action_url=self.action_url,
            hint_spec=spec("queue.hint.full", endpoint=self.endpoint),
            **_entity(yangi),
        )

    def _overdue(self, kechikkan: list[dict]) -> Finding:
        shown = kechikkan[: config.MAX_ITEMS_IN_MESSAGE]
        return Finding(
            agent=self.name,
            kind=self.kind,
            event_type="overdue",
            # Jo'nash vaqti o'tib ketgan, ariza esa hali birorta
            # mashinaga berilmagan.
            severity=channels.WARNING,
            title_spec=spec("queue.overdue.title", count=len(kechikkan)),
            text_spec=spec("queue.overdue.text"),
            line_specs=[queue_line(i) for i in shown],
            extra_count=len(kechikkan) - len(shown),
            items=shown,
            count=len(kechikkan),
            dedupe_key=(
                f"{self.name}:overdue:"
                f"{fingerprint([str(i['request_id']) for i in kechikkan])}"
            ),
            action_url=self.action_url,
            hint_spec=spec("queue.hint.full", endpoint=self.endpoint),
            **_entity(kechikkan),
        )


def _entity(items: list[dict[str, Any]]) -> dict[str, str]:
    """`entity_id` faqat ariza BITTA bo'lganda to'ldiriladi."""
    if len(items) != 1:
        return {"entity_type": "transport_request"}
    return {
        "entity_type": "transport_request",
        "entity_id": str(items[0].get("request_id") or ""),
        "entity_number": str(items[0].get("request_number") or ""),
    }


# --------------------------------------------------------------- Hisobot


async def report(
    *,
    now: datetime | None = None,
    limit: int | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    """Navbatning o'zi — xabarsiz, hodisasiz (`GET /agent/queue`).

    Dispetcher panelga qo'yishi uchun kutayotgan arizalarning MUHIMLIK
    tartibidagi ro'yxati. Agent ishga tushishidan mustaqil: bu endpoint
    fon halqasi o'chirilgan bo'lsa ham ishlaydi.
    """
    started = time.perf_counter()
    now = now or datetime.now()
    # BITTA `Cycle` — navbat ham, qator sonlari ham bir marta so'raladi.
    cycle = Cycle(now=now)
    items = await load_queue(cycle)
    counts = await cycle.once(
        "counts", functools.partial(queries.table_counts, queries.SOURCE_TABLES)
    )

    notes: list[str] = []
    if len(items) >= ro_config.MAX_REQUESTS:
        notes.append(texts.t(lang, "queue.note.limit", limit=ro_config.MAX_REQUESTS))
    if not counts.get("transport_request"):
        notes.append(texts.t(lang, "queue.note.empty"))

    overdue = [i for i in items if i.get("overdue_minutes") is not None]
    return {
        "generated_at": datetime.now(),
        "scope": {
            "checked_at": now,
            "filters": {"statuses": list(ro_config.DEFAULT_REQUEST_STATUSES), "limit": limit},
        },
        "summary": {
            "total": len(items),
            "returned": len(items[:limit] if limit else items),
            "overdue": len(overdue),
            "by_priority": _count(items, "priority"),
            "by_transport_type": _count(items, "required_transport_type"),
            # `/agent/queue` SO'ROV paytida hisoblanadi, shuning uchun
            # bu yerda kalit emas, tayyor matn qaytadi.
            "oldest": texts.render(queue_line(items[0]), lang) if items else None,
        },
        "items": items[:limit] if limit else items,
        "data_quality": {"row_counts": counts, "notes": notes},
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _count(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        key = str(item.get(field) or "—")
        out[key] = out.get(key, 0) + 1
    return out
