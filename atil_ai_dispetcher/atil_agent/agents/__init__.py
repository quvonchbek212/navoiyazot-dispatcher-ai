"""Bajaruvchi agentlar ro'yxati.

YANGI KUZATUV QO'SHISH: `agents/` ga bitta fayl yoziladi va uning
sinfi shu ro'yxatga qo'shiladi. Boshqa hech qayerga tegilmaydi — na
boshqaruvga, na javob beruvchiga, na routerga, na `.env` ga.

TARTIB — SUKUT BO'YICHA. Boshqaruv agent uni o'zgartirishi mumkin
(`orchestrator.py`), lekin model javob bermasa aynan shu tartib
ishlatiladi. Bu yerda tartib ATAYLAB shunday: telematika (og'ish, bekor
turish) kechikishdan keyin turadi, chunki 03.09.2026 da telematika
jadvali bo'sh va u har yurishda "ko'r" holatni qaytaradi.
"""

from __future__ import annotations

from atil_ai_dispetcher.atil_agent.agents.delayed import DelayedAgent
from atil_ai_dispetcher.atil_agent.agents.deviation import DeviationAgent
from atil_ai_dispetcher.atil_agent.agents.document import DocumentAgent
from atil_ai_dispetcher.atil_agent.agents.idle import IdleAgent
from atil_ai_dispetcher.atil_agent.agents.parts_watch import PartsControlAgent
from atil_ai_dispetcher.atil_agent.agents.planner import PlannerAgent
from atil_ai_dispetcher.atil_agent.agents.queue_agent import QueueAgent
from atil_ai_dispetcher.atil_agent.agents.service_watch import ServiceDueAgent
from atil_ai_dispetcher.atil_agent.base import Agent

#: Jarayondagi yagona nusxalar — agentlar holatsiz, ular xotirani
#: `state.py` da saqlaydi.
REGISTRY: tuple[Agent, ...] = (
    DelayedAgent(),
    DeviationAgent(),
    IdleAgent(),
    DocumentAgent(),
    PartsControlAgent(),
    ServiceDueAgent(),
    QueueAgent(),
    PlannerAgent(),
)

BY_NAME: dict[str, Agent] = {a.name: a for a in REGISTRY}

#: `/agent/run?agent=watch` bilan moslik uchun: eski ikkita "agent"
#: endi GURUH nomi.
GROUPS: dict[str, tuple[str, ...]] = {
    "watch": tuple(a.name for a in REGISTRY if a.group == "watch"),
    "backlog": tuple(a.name for a in REGISTRY if a.group == "backlog"),
}


def enabled() -> tuple[Agent, ...]:
    """FON HALQASI ishga tushiradigan agentlar.

    `.env` dagi guruh bayroqlari (`AGENT_WATCH_ENABLED`,
    `AGENT_BACKLOG_ENABLED`) shu yerda qo'llanadi.

    QO'LDA ISHGA TUSHIRISH BUNGA BOG'LIQ EMAS: `POST /agent/run` o'chiq
    guruhni ham chaqira oladi. Bayroq "fonda o'zi ishlasinmi" degan
    savolga tegishli, "umuman ishlaydimi" degan savolga emas — aks holda
    o'chirilgan guruhni sinab ko'rishning iloji qolmasdi.
    """
    from atil_ai_dispetcher.atil_agent import config

    yoqilgan = {
        "watch": config.WATCH_ENABLED,
        "backlog": config.BACKLOG_ENABLED,
    }
    return tuple(a for a in REGISTRY if yoqilgan.get(a.group, True))


def resolve(target: str) -> tuple[Agent, ...]:
    """Nom yoki guruh bo'yicha agentlarni topadi.

    `all` — hammasi. Noma'lum nom `ValueError` beradi: jimgina bo'sh
    ro'yxat qaytarish "ishladi, lekin hech narsa topilmadi" degan
    yolg'on taassurot berardi.
    """
    if target == "all":
        return REGISTRY
    if target in GROUPS:
        return tuple(BY_NAME[n] for n in GROUPS[target])
    if target in BY_NAME:
        return (BY_NAME[target],)
    raise ValueError(
        f"Noma'lum agent: {target}. Mavjud: {', '.join(BY_NAME)} "
        f"yoki guruh: {', '.join(GROUPS)}, yoki `all`"
    )


__all__ = ["REGISTRY", "BY_NAME", "GROUPS", "resolve"]
