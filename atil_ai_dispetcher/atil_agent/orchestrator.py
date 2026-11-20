"""Boshqaruv agent — kimni qachon ishga tushirishni hal qiladi.

BUTUN MODULNING MA'NOSI SHU FAYLDA. Qolgan hamma narsa (chatbot, OCR,
dispetcher, marshrut) so'ralganda javob beradi; bu yerda esa hech kim
so'ramasa ham ishlaydigan oqim bor.

BIR YURISH:

    1. muddati kelgan agentlarni topadi          (deterministik)
    2. modeldan tartib va qo'shimcha so'raydi     (LLM)
    3. agentlarni ketma-ket ishga tushiradi
    4. topilmalarni javob beruvchiga uzatadi      (LLM xabar yozadi)

MODEL NIMANI HAL QILADI:
  * agentlarning TARTIBI — qaysi biri birinchi tekshirilsin
  * QO'SHIMCHA yurish — muddati kelmagan agentni ham chaqirish
    (masalan kechikish ko'payib ketgan bo'lsa navbatni ham ko'rish)

MODEL NIMANI HAL QILA OLMAYDI — VA BU ATAYLAB:

  MUDDATI KELGAN TEKSHIRUV BARIBIR ISHLAYDI. Model ro'yxatdan agentni
  o'chira olmaydi, faqat tartibni o'zgartiradi yoki ustiga qo'shadi.

  Sabab: bu modulning butun vazifasi — hech kim qaramaganda ham
  kuzatishni davom ettirish. Model "bugun hujjatlarni tekshirmasa ham
  bo'ladi" deb qaror qilsa, kuzatuv JIMGINA o'chib qolardi va buni hech
  kim sezmasdi, chunki agentning ishi tashqaridan "jim turish" ga
  o'xshaydi. Yo'qolgan ogohlantirish — bu tizimdagi eng xavfli xato.

  Model yiqilsa ham shu sababdan hech narsa o'zgarmaydi: tartib
  ro'yxatdagi sukut tartibi bo'ladi, xolos.

UCHTA QATTIQ QOIDA (ilgarigi rejadan o'zgarmagan):

  1. HALQA HECH QACHON O'LMAYDI. Bitta yurishdagi xato ushlanadi, yozib
     qo'yiladi va halqa keyingi urinishga o'tadi.

  2. USTMA-UST ISHLAMAYDI. `asyncio.Lock` bor: sekin ishlagan yurish
     keyingi vaqtga cho'zilib qolsa, ikkinchisi boshlanmaydi. Qo'lda
     ishga tushirish (`POST /agent/run`) ham SHU qulfni oladi.

  3. HAR AGENT O'Z VAQTIDA. Kechikish 15 daqiqada, hujjat muddati
     kuniga bir marta tekshiriladi (sabab: `config.py`).

`asyncio.sleep` o'rniga hodisani kutish ishlatiladi: server o'chganda
agent 15 daqiqa kutib turmasin, darhol chiqsin.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Sequence

from fastapi.concurrency import run_in_threadpool

from atil_ai_dispetcher.atil_agent import agents as registry
from atil_ai_dispetcher.atil_agent import brain, channels, config, queries, responder, state
from atil_ai_dispetcher.atil_agent.base import Agent, Cycle, Finding

logger = logging.getLogger(__name__)

AGENT = "orchestrator"

_task: asyncio.Task | None = None
_stop: asyncio.Event | None = None
_lock = asyncio.Lock()
#: Keyingi yurish vaqti — faqat ko'rsatish uchun (`/agent/status`).
#: Halqaning o'zi monotonik soatga tayanadi, chunki tizim soati
#: o'zgarsa (NTP, qish/yoz vaqti) rejalar sakrab ketardi.
_next_run: datetime | None = None
#: Har agentning keyingi muddati (monotonik).
_due: dict[str, float] = {}
#: Boshqaruvning oxirgi qarori — `/agent/status` da ko'rinadi.
_last_decision: dict[str, Any] = {}

PROMPT = """Sen ATIL avtopark kuzatuv tizimining boshqaruvchisisan.

Fon yurishi boshlanmoqda. Quyidagi vazifalarning muddati keldi va ular
BARIBIR bajariladi — sening ishing ularning TARTIBINI aytish va kerak
bo'lsa ustiga qo'shimcha vazifa qo'shish.

Muddati kelganlar (o'zgartirib bo'lmaydi):
{due}

Muddati kelmaganlar (xohlasang qo'shishing mumkin):
{idle}

Oxirgi holat:
{status}

JSON qaytar, boshqa hech narsa yozma:
{{"order": ["vazifa_nomi", ...],
  "also_run": ["vazifa_nomi", ...],
  "reason": "bir jumla: nega shunday tartib"}}

QOIDALAR:
- `order` ichida faqat muddati kelganlar bo'lsin, HAMMASI bo'lsin.
- `also_run` bo'sh bo'lishi mumkin va bu normal holat.
- Oxirgi yurishda xato bergan vazifani oldinroq qo'y.
- Ma'lumot manbasi bo'sh bo'lgan vazifani orqaroq qo'y — u baribir
  "tekshirib bo'lmadi" deb qaytadi.
"""


# ------------------------------------------------------------------ Qaror


async def decide(due: Sequence[Agent], idle: Sequence[Agent]) -> tuple[list[Agent], dict[str, Any]]:
    """Qaysi agentlar, qaysi tartibda ishlasin.

    DETERMINISTIK POL: `due` dagi hamma agent qaytadi, nima bo'lganda
    ham. Model faqat tartibni o'zgartiradi va `idle` dan qo'shimcha
    qo'shadi. Fayl boshidagi izohga qarang.
    """
    sukut = list(due)
    # BITTA VAZIFANI TARTIBLASH — ma'nosiz LLM chaqiruvi. `idle` bo'sh
    # bo'lsa qo'shimcha ham qo'sha olmaydi, ya'ni model hech narsa hal
    # qilmaydi va faqat 10 soniya yo'qotardi.
    if not sukut or not config.LLM_ENABLED or (len(sukut) < 2 and not idle):
        return sukut, {
            "source": "template",
            "reason": "sukut tartibi" if sukut else "muddati kelgan vazifa yo'q",
            "order": [a.name for a in sukut],
            "also_run": [],
            "restored": [],
        }

    store = state.store()
    natija, source = await brain.think(
        PROMPT.format(
            due=brain.facts([_describe(a, store) for a in due]),
            idle=brain.facts([_describe(a, store) for a in idle]),
            status=brain.facts(store.run_state(AGENT) or {"runs": 0}),
        ),
        role="orchestrator",
        fallback={"order": [a.name for a in sukut], "also_run": [], "reason": "sukut tartibi"},
        parse=_parse_decision,
    )

    nomlar = list(dict.fromkeys(natija.get("order") or []))
    tanlangan = [registry.BY_NAME[n] for n in nomlar if n in registry.BY_NAME]

    # POL: model tushirib qoldirgan agentlar QAYTARILADI. Model
    # ro'yxatni qisqartira olmasligi kerak, faqat qayta tartiblashi.
    tushib_qolgan = [a for a in sukut if a not in tanlangan]
    if tushib_qolgan:
        logger.info(
            "Boshqaruv %s ni tushirib qoldirdi — qaytarildi (muddati kelgan tekshiruv "
            "o'tkazib yuborilmaydi)",
            ", ".join(a.name for a in tushib_qolgan),
        )
    tanlangan = [a for a in tanlangan if a in sukut] + tushib_qolgan

    qoshimcha = [
        registry.BY_NAME[n]
        for n in dict.fromkeys(natija.get("also_run") or [])
        if n in registry.BY_NAME and registry.BY_NAME[n] in idle
    ]
    qaror = {
        "source": source,
        "reason": str(natija.get("reason") or "")[:200],
        "order": [a.name for a in tanlangan],
        "also_run": [a.name for a in qoshimcha],
        "restored": [a.name for a in tushib_qolgan],
    }
    return tanlangan + qoshimcha, qaror


def _parse_decision(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("obyekt kutilgan edi")
    return {
        "order": [str(x) for x in (data.get("order") or [])],
        "also_run": [str(x) for x in (data.get("also_run") or [])],
        "reason": data.get("reason"),
    }


def _describe(agent: Agent, store: state.Store) -> dict[str, Any]:
    holat = store.kind_state(agent.kind)
    return {
        "nomi": agent.name,
        "vazifa": agent.title,
        "manba_jadval": agent.primary_source,
        "manba_bosh": holat.get("blind"),
        "eslab_qolgan_qator": len(holat.get("seen") or {}),
        "oxirgi_yurish": holat.get("last_run_at"),
    }


# ------------------------------------------------------------------ Yurish


async def run_cycle(
    targets: Sequence[Agent],
    *,
    notify: bool = True,
    now: datetime | None = None,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bitta yurish: agentlarni chaqiradi, javob beruvchiga uzatadi.

    BITTA AGENTNING XATOSI QOLGANINI TO'XTATMAYDI. Bu eski qoida:
    telematika o'chganda hujjat kuzatuvi ishlayverishi kerak.
    """
    started = time.perf_counter()
    now = now or datetime.now()

    # MANBALAR BITTA SO'ROVDA, agentlardan oldin. Har agent o'zi
    # so'rasa, bir xil jadval (`vehicle_telemetry_state`) bitta yurishda
    # ikki marta so'ralardi.
    #
    # So'rov yiqilsa bo'sh lug'at qoladi va hech bir agent KO'R deb
    # belgilanmaydi — bu to'g'ri: bilmaganni "bo'sh" deb e'lon qilish
    # noto'g'ri xabar berardi.
    sources: dict[str, bool] = {}
    kerakli = sorted({a.primary_source for a in targets if a.primary_source})
    if kerakli:
        try:
            sources = await run_in_threadpool(functools.partial(queries.has_rows, kerakli))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Manba jadvallari tekshirilmadi: %s", str(exc)[:160])

    cycle = Cycle(now=now, notify=notify, sources=sources)
    findings: list[Finding] = []
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for agent in targets:
        agent_started = time.perf_counter()
        try:
            topilmalar = await agent.run(cycle)
        except Exception as exc:  # noqa: BLE001 — bittasi yiqilsa qolgani davom etadi
            logger.exception("Agent vazifani bajara olmadi: %s", agent.name)
            xato = f"{type(exc).__name__}: {exc}"[:200]
            errors.append(f"{agent.name}: {xato}")
            results.append({"agent": agent.name, "kind": agent.kind, "error": xato})
            continue
        findings.extend(topilmalar)
        results.append(
            {
                "agent": agent.name,
                "kind": agent.kind,
                "findings": [f.event_type for f in topilmalar],
                "count": sum(f.count for f in topilmalar),
                "blind": agent.is_blind(cycle),
                "elapsed_seconds": round(time.perf_counter() - agent_started, 3),
            }
        )

    event = await responder.respond(findings, cycle)

    # BITTA AGENT YIQILSA HAM YURISH SOG'LOM EMAS. `/agent/status` da
    # xato ko'rinishi kerak: jimgina "hammasi joyida" ko'rsatish aynan
    # shu modul ogohlantirib turgan xato.
    ok = not errors
    elapsed = time.perf_counter() - started
    state.store().record_run(
        AGENT, ok=ok, error="; ".join(errors) or None, elapsed=elapsed, now=now
    )
    return {
        "agent": AGENT,
        "checked_at": now,
        # QAROR PARAMETRDAN KELADI, modul o'zgaruvchisidan EMAS. Ilgari
        # bu yerda `_last_decision` o'qilardi va uni faqat fon halqasi
        # to'ldirardi — natijada `POST /agent/run` javobida qaror har
        # doim bo'sh chiqardi, go'yo boshqaruv qatlami umuman
        # ishlamagandek.
        "decision": decision
        or {
            "source": "manual",
            "reason": "boshqaruvsiz chaqirildi",
            # Kalitlar TO'LIQ bo'lishi shart: chaqiruvchi `decision["order"]`
            # ni bemalol o'qiy olishi kerak. Pydantic javobda sukut qiymat
            # qo'shadi, lekin xom lug'atni o'qiganlar `KeyError` olardi.
            "order": [a.name for a in targets],
            "also_run": [],
            "restored": [],
        },
        "results": results,
        "notification_id": (event or {}).get("id"),
        "findings": len(findings),
        "errors": errors,
        "elapsed_seconds": round(elapsed, 3),
    }


# ------------------------------------------------------------------ Halqa


async def _wait(seconds: float) -> bool:
    """Kutadi. `True` qaytsa — to'xtash so'raldi.

    `assert` ATAYLAB ISHLATILMAYDI: `python -O` da u olib tashlanadi va
    keyingi qatorda tushunarsiz xato chiqardi.
    """
    if _stop is None:
        return True
    try:
        await asyncio.wait_for(_stop.wait(), timeout=max(1.0, seconds))
        return True
    except asyncio.TimeoutError:
        return False


async def _loop() -> None:
    global _next_run, _last_decision
    # `.env` da o'chirilgan guruh fon halqasiga umuman kirmaydi.
    # Qo'lda (`POST /agent/run`) ular baribir chaqiriladi — sabab
    # `agents.enabled` izohida.
    ishlaydigan = registry.enabled()
    _due.update({a.name: 0.0 for a in ishlaydigan})  # 0 — hoziroq

    while not (_stop and _stop.is_set()):
        hozir = time.monotonic()
        due = [a for a in ishlaydigan if _due.get(a.name, 0.0) <= hozir]
        idle = [a for a in ishlaydigan if a not in due]

        if due:
            try:
                targets, _last_decision = await decide(due, idle)
                async with _lock:
                    natija = await run_cycle(targets, notify=True, decision=_last_decision)
                yiqilgan = {
                    row["agent"] for row in natija.get("results") or [] if row.get("error")
                }
            except Exception as exc:  # noqa: BLE001 — halqa o'lmasligi kerak
                logger.exception("Boshqaruv halqasida kutilmagan xato")
                state.store().record_run(
                    AGENT, ok=False, error=f"{type(exc).__name__}: {exc}"
                )
                targets, yiqilgan = due, {a.name for a in due}

            for agent in targets:
                # Xatodan keyin tezroq qaytamiz, lekin uzluksiz emas.
                seconds = (
                    config.RETRY_INTERVAL_SECONDS
                    if agent.name in yiqilgan
                    else agent.interval_seconds
                )
                _due[agent.name] = time.monotonic() + seconds

        keyingi = min(_due.values()) - time.monotonic() if _due else config.WATCH_INTERVAL_SECONDS
        _next_run = datetime.now() + timedelta(seconds=max(0.0, keyingi))
        if await _wait(keyingi):
            break


# ------------------------------------------------------------ Boshqarish


def start() -> list[str]:
    """Boshqaruv agentini ishga tushiradi. Qaysi agentlar yoqilganini qaytaradi."""
    global _stop
    if _task is not None and not _task.done():
        return [a.name for a in registry.enabled()]
    if not config.ENABLED:
        return []

    ishlaydigan = registry.enabled()
    if not ishlaydigan:
        logger.warning(
            "Agentlar yoqilgan, lekin hamma guruh o'chirilgan "
            "(AGENT_WATCH_ENABLED / AGENT_BACKLOG_ENABLED) — fon halqasi ishga tushmadi"
        )
        return []

    globals()["_stop"] = asyncio.Event()
    globals()["_task"] = asyncio.create_task(_loop(), name=AGENT)
    return [a.name for a in ishlaydigan]


async def stop(timeout: float = 10.0) -> None:
    """Halqani to'xtatadi va tugashini kutadi."""
    if _stop is not None:
        _stop.set()
    task = _task
    if task is None:
        return
    done, pending = await asyncio.wait([task], timeout=timeout)
    for t in pending:
        # Ishlab turgan yurish byudjetga ulgurmadi — uzamiz. Holat
        # fayli atomik yozilgani uchun ma'lumot buzilmaydi; eng yomoni
        # oxirgi hodisa qayta xabar qilinadi.
        t.cancel()
    globals()["_task"] = None


async def run_now(target: str, *, notify: bool = True, now: datetime | None = None) -> dict[str, Any]:
    """Qo'lda ishga tushirish — rejadagi halqa bilan BIR XIL qulf ostida.

    Qulfsiz bo'lsa `POST /agent/run` fon halqasi bilan bir vaqtda
    ishlab, bir hodisani ikki marta xabar qilardi.
    """
    targets = registry.resolve(target)
    async with _lock:
        # QO'LDA ISHGA TUSHIRISH HAM BOSHQARUV QATLAMIDAN O'TADI —
        # tartibni o'sha hal qiladi. `idle` ATAYLAB bo'sh: foydalanuvchi
        # qaysi vazifani so'raganini aniq aytdi va boshqaruv unga
        # so'ralmagan vazifani QO'SHMASLIGI kerak.
        tanlangan, qaror = await decide(targets, [])
        return await run_cycle(tanlangan, notify=notify, decision=qaror, now=now)


def status() -> dict[str, Any]:
    """`/agent/status` uchun — yoqilganmi, qachon ishladi, qachon ishlaydi."""
    store = state.store()
    ishlayapti = _task is not None and not _task.done()
    return {
        "scheduler_enabled": config.ENABLED,
        "running": ishlayapti,
        "next_run_at": _next_run,
        "last_decision": _last_decision or None,
        "orchestrator": {
            "enabled": config.ENABLED,
            "running": ishlayapti,
            "next_run_at": _next_run,
            **store.run_state(AGENT),
        },
        "agents": {
            a.name: {
                "title": a.title,
                "group": a.group,
                "enabled": a in registry.enabled(),
                "kind": a.kind,
                "interval_seconds": a.interval_seconds,
                "primary_source": a.primary_source,
                "blind": store.kind_state(a.kind).get("blind"),
                "watched": len(store.kind_state(a.kind).get("seen") or {}),
                "last_run_at": store.kind_state(a.kind).get("last_run_at"),
            }
            for a in registry.REGISTRY
        },
        "channels": channels.configured(),
        "llm_enabled": config.LLM_ENABLED,
        "documents_days": config.DOCUMENTS_DAYS,
        "state_path": str(config.STATE_PATH),
        "unread_notifications": store.unread_count(),
    }
