"""Agent endpointlari — kuzatish, navbat, tasdiqlash.

Router `main.py` dagi yagona FastAPI ilovasiga ulanadi; butun ilova
HTTP Basic bilan yopiq (`security.py`).

BU ENDPOINTLAR AGENTNING O'ZI EMAS. Agent fon oqimida ishlaydi
(`scheduler.py`) va hech kim so'ramasa ham xabar beradi. Bu yerdagi
yo'llar unga QARASH va ARALASHISH uchun:

    GET  /agent/notifications                WEBSITE SHUNI O'QIYDI
    POST /agent/notifications/{id}/read      o'qilgan deb belgilash
    POST /agent/notifications/read           bir nechtasini yoki hammasini
    GET  /agent/status                       ishlayaptimi, qachon ishladi
    GET  /agent/queue                        kutayotgan arizalar navbati
    GET  /agent/events                       agent nima deganini ko'rish
    POST /agent/run                          kutmasdan hoziroq tekshirish
    GET  /agent/proposals                    tasdiq kutayotgan rejalar
    POST /agent/proposals/{id}/decision      tasdiqlash yoki rad etish
    DELETE /agent/state                      bazaviy holatni tozalash

XABAR WEBSITE'GA QANDAY BORADI. ATIL bazasida `notification` jadvali
bor, lekin bizda unga YOZISH huquqi yo'q (READ ONLY, faqat SELECT).
Shuning uchun agent hech qayerga yubormaydi — xabar `GET
/agent/notifications` da turadi va website uni SO'RAB OLADI. Javob
maydonlari o'sha jadvalning ustunlari bilan bir xil nomlangan, ya'ni
ertaga backend uni o'ziga ko'chirmoqchi bo'lsa moslashtirish kerak
bo'lmaydi.

TASDIQLASH — BAJARISH EMAS, va bu javobda ochiq yoziladi. ATIL
bazasiga yozish huquqi yo'q (`DB_READ_ONLY`, foydalanuvchida faqat
SELECT), shuning uchun tasdiqlangan reja bazaga TUSHMAYDI. U
`AGENT_APPROVAL_WEBHOOK_URL` ga uzatiladi; manzil sozlanmagan bo'lsa
javobda `warning` chiqadi. "Tasdiqlandi" so'zi ostida bajarilmagan ish
qolib ketishi — bu modulda bo'lishi mumkin bo'lgan eng xavfli xato.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Body, HTTPException, Query

from atil_ai_dispetcher.atil_agent import agents as registry
from atil_ai_dispetcher.atil_agent import channels, config, orchestrator, state, texts
from atil_ai_dispetcher.atil_agent.agents import queue_agent
from atil_ai_dispetcher.atil_agent.models import (
    AgentStatus,
    DecisionRequest,
    DecisionResponse,
    Event,
    MarkReadResponse,
    Notification,
    Proposal,
    QueueReport,
    RunResponse,
)
from atil_ai_dispetcher.atil_agent.queries import AgentDataError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["Agentlar"])


#: Swagger'da uchala endpointda bir xil ko'rinishi uchun.
LANG_QUERY = Query(
    "uz",
    description="**Javob tili.** Xabar sarlavhasi, matni, qatorlari va "
                "topilmalar nomi shu tilda quriladi.\n\n"
                "Agent xabarni SIKL paytida yozadi, o'qish esa keyinroq "
                "bo'ladi \u2014 shuning uchun matn emas, KALIT saqlanadi va "
                "javob shu yerda quriladi. Model yozgan xatboshi esa sikl "
                "paytida uchala tilda yozilgan.\n\n"
                "**Kodlar tarjima qilinmaydi**: `agent`, `kind`, "
                "`event_type`, `severity`, `entity_type`, `dedupe_key`, "
                "`action_url`.",
)


def _findings(row: dict, lang: str) -> list[dict]:
    """Topilmalar ro'yxati — sarlavhasi tanlangan tilda."""
    out = []
    for f in row.get("findings") or []:
        item = dict(f)
        if f.get("title_spec"):
            item["title"] = texts.render(f["title_spec"], lang)
        item.pop("title_spec", None)
        out.append(item)
    return out


def _notification(row: dict, lang: str = texts.DEFAULT_LANG) -> Notification:
    """Saqlangan hodisadan website o'qiydigan shakl.

    Hodisa va notification — BITTA yozuv, ikki xil ko'rinish. Alohida
    saqlansa ikkalasi bir-biridan uzilib qolardi: `/agent/events` da bor
    xabar website'da yo'q bo'lib chiqardi.

    MATN SHU YERDA QURILADI. Saqlangan yozuvda kalitlar turadi
    (`line_specs`) va model yozgan xatboshi uchala tilda
    (`title_by_lang`). Eski yozuvlarda ular yo'q — u holda saqlangan
    tayyor matn qaytadi va javob buzilmaydi.
    """
    lang = texts.normalize(lang)
    sarlavha = (row.get("title_by_lang") or {}).get(lang) or row.get("title") or ""
    matn = (row.get("text_by_lang") or {}).get(lang) or (
        row.get("body") or row.get("text") or "")
    return Notification(
        id=row["id"],
        created_at=row["created_at"],
        read_at=row.get("read_at"),
        severity=row.get("severity") or "INFO",
        title=sarlavha,
        body=matn,
        agent=row["agent"],
        kind=row.get("kind") or "",
        event_type=row.get("event_type") or "",
        count=row.get("count") or 0,
        dedupe_key=row.get("dedupe_key") or "",
        entity_type=row.get("entity_type"),
        entity_id=row.get("entity_id"),
        entity_number=row.get("entity_number"),
        action_url=row.get("action_url"),
        items=row.get("items") or [],
        source=row.get("source") or "template",
        findings=_findings(row, lang),
    )


# ============================================================ Notification


@router.get(
    "/notifications",
    response_model=list[Notification],
    summary="ATIL website notification qismi uchun — o'qilmagan xabarlar",
)
async def notifications(
    unread: bool = Query(
        True,
        description="Faqat o'qilmaganlari. `false` — tarix bilan birga "
                    "(o'qilganlari `read_at` bilan qaytadi).",
    ),
    since: str | None = Query(
        None,
        description="Shu paytdan KEYIN yaratilganlari (ISO: `2026-09-04T09:35:52`). "
                    "Website har safar hammasini emas, faqat yangisini so'rashi uchun.",
        examples=["2026-09-04T09:35:52"],
    ),
    agent: str | None = Query(
        None, description="Faqat shu agent yozgan xabarlar (odatda `orchestrator`)"),
    limit: int = Query(50, ge=1, le=200),
    lang: Literal["uz", "ru", "en"] = LANG_QUERY,
) -> list[Notification]:
    """Website shu yerdan o'qiydi. Eng yangisi birinchi.

    **NIMA UCHUN BIZ YUBORMAYMIZ, SIZ O'QIYSIZ.** ATIL bazasidagi
    `notification` jadvaliga yozish huquqimiz yo'q — ulanish `READ ONLY`
    va foydalanuvchida faqat `SELECT`. Shuning uchun xabar shu yerda
    turadi va yo'qolmaydi: tashqi kanal sozlanmagan yoki yiqilgan
    bo'lsa ham.

    **Maydon nomlari ATIL `notification` jadvalidan olingan** —
    `severity`, `dedupe_key`, `entity_type`, `entity_id`,
    `entity_number`, `action_url`. Backend bu javobni o'z jadvaliga
    ko'chirmoqchi bo'lsa moslashtirish kerak emas.

    **Bitta istisno — `kind`.** Bu bizning O'Z nomimiz (`delayed`,
    `route_plan`, ...), ATIL jadvalidagi `CHECK` ro'yxatidan emas: u
    yerda "yo'nalishdan og'ish" yoki "reja tayyor" uchun mos qiymat
    yo'q. Jadvalga yozmoqchi bo'lgan tomon moslashtirishni ochiq
    qilishi kerak.

    **Bitta xabar KO'P QATOR haqida bo'lishi mumkin** ("3 ta yangi
    kechikkan reys"). Shuning uchun `entity_id` faqat qator bitta
    bo'lganda to'ladi; to'liq ro'yxat `items` da, undan uzuni esa
    `action_url` dagi endpointda.

    **Agent RO'YXATNI emas, O'ZGARISHNI xabar qiladi.** Bazada 73 ta
    kechikkan reys turgan bo'lsa ham, bu yerga faqat YANGI paydo
    bo'lgani tushadi — aks holda kuniga 96 ta bir xil xabar kelardi.
    """
    rows = state.store().events(
        limit=limit, agent=agent, unread_only=unread, since=since
    )
    return [_notification(row, lang) for row in rows]


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MarkReadResponse,
    summary="Bitta xabarni o'qilgan deb belgilash",
    responses={404: {"description": "Bunday xabar yo'q"}},
)
async def mark_one_read(notification_id: str) -> MarkReadResponse:
    """Foydalanuvchi xabarni ochganda chaqiriladi.

    **Ikkinchi marta chaqirilsa `read_at` O'ZGARMAYDI** — birinchi
    ko'rilgan payt saqlanib qoladi. Aks holda ro'yxat har ochilganda
    vaqt surilib, "qachon ko'rilgan" degan savolga javob yo'qolardi.
    """
    store = state.store()
    mavjud = {e["id"] for e in store.events(limit=config.EVENT_HISTORY)}
    if notification_id not in mavjud:
        raise HTTPException(404, f"Xabar topilmadi: {notification_id}")
    marked = store.mark_read([notification_id])
    return MarkReadResponse(
        marked=marked,
        already_read=[] if marked else [notification_id],
        unread=store.unread_count(),
    )


@router.post(
    "/notifications/read",
    response_model=MarkReadResponse,
    summary="Bir nechtasini yoki hammasini o'qilgan deb belgilash",
)
async def mark_read(
    ids: list[str] | None = Body(
        None,
        description="Belgilanadigan xabarlar. Berilmasa — HAMMASI "
                    "(`agent` berilgan bo'lsa faqat o'shaniki).",
        examples=[["a3f1c2d4e5f6", "b7c8d9e0f1a2"]],
    ),
    agent: str | None = Query(
        None, description="`ids` berilmaganda: faqat shu agent yozgan xabarlar"),
) -> MarkReadResponse:
    """Website'dagi "hammasini o'qilgan deb belgilash" tugmasi uchun.

    `ids` berilsa faqat o'shalar; berilmasa o'qilmagan HAMMASI.
    Topilmagan id lar `not_found` da qaytadi va bu xato emas: tarix
    `AGENT_EVENT_HISTORY` ta yozuv bilan chegaralangan, eskisi siqib
    chiqarilgan bo'lishi mumkin.
    """
    store = state.store()
    if ids is None:
        marked = store.mark_all_read(agent=agent)
        return MarkReadResponse(marked=marked, unread=store.unread_count())

    mavjud = {e["id"] for e in store.events(limit=config.EVENT_HISTORY)}
    marked = store.mark_read(ids)
    return MarkReadResponse(
        marked=marked,
        already_read=[i for i in ids if i in mavjud and i not in marked],
        not_found=[i for i in ids if i not in mavjud],
        unread=store.unread_count(),
    )


# ==================================================================== Holat


@router.get("/status", response_model=AgentStatus, summary="Agentlar holati")
async def status() -> AgentStatus:
    """Agentlar yoqilganmi, oxirgi marta qachon ishlagan, keyingisi qachon.

    **`scheduler_enabled: false` bo'lsa fon oqimi umuman yo'q** —
    `.env` da `AGENT_ENABLED` o'chiq. Bunda endpointlar ishlayveradi
    va `POST /agent/run` bilan qo'lda tekshirish mumkin, lekin hech
    kim so'ramasa hech narsa bo'lmaydi.

    **`channels`** qaysi kanal sozlanganini ko'rsatadi. `log` har doim
    `true` va ularni o'chirib bo'lmaydi: `notification` — website
    o'qiydigan yagona manba, `log` esa tashqi kanal yiqilganda ham
    hodisa yo'qolmasligi uchun. `webhook` esa `.env` da manzil
    yozilmaguncha `false` — kod o'rnatilishining o'zi hech qayerga
    xabar yubormaydi.

    **`unread_notifications`** — website'da nechta o'qilmagan xabar
    turibdi.

    **`watched`** — har ro'yxatda nechta qator eslab qolingani. Agent
    RO'YXATNI emas, O'ZGARISHNI xabar qiladi; shu sonlar uning
    xotirasi.
    """
    return AgentStatus(**orchestrator.status())


@router.delete(
    "/state",
    summary="Bazaviy holatni tozalash — keyingi tekshiruv yangidan boshlaydi",
)
async def reset_state(
    kind: str | None = Query(
        None,
        description="Faqat bitta ro'yxat: `delayed`, `deviations`, `idle`, "
                    "`documents`, `backlog_queue`, `backlog_plan`, "
                    "`backlog_proposal`. Berilmasa hammasi.",
    ),
) -> dict[str, str]:
    """Agent nimani ko'rganini UNUTADI.

    **Nima bo'ladi:** keyingi tekshiruv "birinchi marta" deb hisoblanadi
    va bitta umumiy "kuzatuv boshlandi" xabari keladi — 400 ta alohida
    xabar EMAS (bazaviy holat mantig'i `state.py` da).

    **Qachon kerak:** xabarlar noto'g'ri holatda qotib qolgan bo'lsa
    yoki sinovdan keyin toza boshlash kerak bo'lsa.

    Bazaga TEGMAYDI — faqat agentning o'z holat fayli tozalanadi.
    """
    state.store().forget(kind)
    return {"status": "reset", "kind": kind or "hammasi"}


# ==================================================================== Navbat


@router.get(
    "/queue",
    response_model=QueueReport,
    summary="Rejalashtirishni kutayotgan arizalar — muhimlik tartibida",
    responses={503: {"description": "Bazaga ulanib bo'lmadi"}},
)
async def queue(
    limit: int | None = Query(
        None, ge=1, le=500,
        description="Nechta qator qaytsin. `summary.total` da chegaradan oldingi "
                    "to'liq son turadi. Berilmasa hammasi.",
    ),
    lang: Literal["uz", "ru", "en"] = LANG_QUERY,
) -> QueueReport:
    """Hali birorta mashinaga berilmagan arizalar.

    **Tartib — uchta mezon, shu ketma-ketlikda:**

    | # | Mezon | Manba |
    |---|---|---|
    | 1 | rejadagi jo'nash vaqti o'tganlar, kechikkani ko'p bo'lgani tepada | `planned_departure_at` |
    | 2 | muhimlik | `priority` (CRITICAL → URGENT → HIGH → NORMAL) |
    | 3 | eskisi oldinda | `created_at` |

    **"Kech qolgan ariza" degan meyor YO'Q.** `overdue_minutes` —
    rejadagi jo'nash vaqti bilan hozirgi vaqtning ayirmasi, ya'ni
    solishtirish. `null` bo'lsa jo'nash vaqti ko'rsatilmagan — bu
    "kechikmagan" degani EMAS.

    **Qaysi holatlar navbat hisoblanadi** `.env` dagi
    `RO_REQUEST_STATUSES` da (sukut: `APPROVED`, `READY_FOR_PLANNING`).
    `ASSIGNED` va `IN_PROGRESS` kirmaydi — ular allaqachon mashinaga
    berilgan.

    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY tranzaksiyada.
    """
    try:
        report = await queue_agent.report(limit=limit, lang=lang)
    except AgentDataError as exc:
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")
    return QueueReport(**report)


# =================================================================== Hodisa


@router.get(
    "/events",
    response_model=list[Event],
    summary="Agent yuborgan xabarlar",
)
async def events(
    limit: int = Query(50, ge=1, le=200),
    agent: str | None = Query(
        None, description="Faqat shu agent yozgan hodisalar (odatda `orchestrator`)"),
) -> list[Event]:
    """Oxirgi hodisalar — eng yangisi birinchi.

    Bu DIAGNOSTIKA uchun: website `GET /agent/notifications` ni
    o'qiydi, bu yerda esa o'sha yozuvlar yetkazish tafsiloti bilan
    ko'rinadi. Har hodisada `delivery` bor: `notification` har doim
    `ok` (yozuv saqlangan), `webhook` esa sozlangan bo'lsa natijasi
    bilan. Webhook yiqilsa buni SHU YERDAN bilinadi — kuzatuvning o'zi
    to'xtamaydi va xabar website'da baribir turadi.

    Tarix `AGENT_EVENT_HISTORY` ta yozuv bilan chegaralangan (sukut
    200) va holat faylida saqlanadi, ya'ni serverni qayta ishga
    tushirsangiz ham qoladi.
    """
    return [Event(**row) for row in state.store().events(limit=limit, agent=agent)]


@router.post(
    "/run",
    response_model=RunResponse,
    summary="Agentni kutmasdan hoziroq ishga tushirish",
    responses={503: {"description": "Bazaga ulanib bo'lmadi"}},
)
async def run(
    agent: str = Query(
        "all",
        description="Bitta vazifa (`delayed`, `deviation`, `idle`, `document`, `queue`, "
                    "`planner`), guruh (`watch`, `backlog`) yoki `all`.",
        examples=["all"],
    ),
    notify: bool = Query(
        True,
        description="Xabar yuborilsinmi. `false` — hodisa faqat qayd etiladi, "
                    "webhook ga chiqmaydi va DARHOL o'qilgan deb belgilanadi "
                    "(website'da o'qilmagan bo'lib osilib qolmasin). Sinash uchun.",
    ),
) -> RunResponse:
    """Fon halqasini kutmasdan bitta tekshiruv o'tkazadi.

    **Rejadagi halqa bilan bir xil qulf ostida ishlaydi** — ikkalasi
    bir vaqtda ishlab, bir hodisani ikki marta xabar qilmaydi. Halqa
    hozir ishlayotgan bo'lsa, bu so'rov uning tugashini kutadi.

    **`notify=false` sinash uchun.** Hodisa yozib qo'yiladi va
    `/agent/events` da ko'rinadi, lekin tashqariga chiqmaydi. DIQQAT:
    hodisa baribir "ko'rilgan" deb belgilanadi, ya'ni keyingi haqiqiy
    tekshiruvda u YANGI bo'lmaydi. Toza boshlash uchun
    `DELETE /agent/state`.

    Birinchi ishga tushirishda qator-qator xabar kelmaydi — bitta
    "kuzatuv boshlandi" xabari keladi.
    """
    try:
        result = await orchestrator.run_now(agent, notify=notify)
    except AgentDataError as exc:
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return RunResponse(**result)


# =================================================================== Taklif


@router.get(
    "/proposals",
    response_model=list[Proposal],
    summary="Tasdiq kutayotgan rejalar",
)
async def proposals(
    status_filter: Literal["PENDING", "APPROVED", "REJECTED", "SUPERSEDED"] | None = Query(
        None, alias="status", description="Berilmasa hammasi"),
    limit: int = Query(20, ge=1, le=50),
) -> list[Proposal]:
    """Agent tuzgan reja takliflari — eng yangisi birinchi.

    **Bir vaqtda faqat BITTA `PENDING` taklif bo'ladi.** Yangi reja
    tuzilganda eskisi `SUPERSEDED` ga o'tadi: ikkita kutayotgan reja
    bir xil arizalarni boshqacha taqsimlaydi va ikkalasini tasdiqlash
    bir-biriga zid ikki qaror bo'lardi.

    **Bugun taklif bo'lmasligi kutilgan holat.** Bazada arizalarning
    koordinatasi yo'q, shuning uchun optimizator hech narsani
    joylashtira olmaydi. Bunda taklif o'rniga `blocked` hodisasi
    chiqadi va u NIMA TO'LDIRILISHI kerakligini aytadi —
    `/agent/events` ga qarang.
    """
    return [
        Proposal(**row)
        for row in state.store().proposals(status=status_filter, limit=limit)
    ]


@router.get(
    "/proposals/{proposal_id}",
    response_model=Proposal,
    summary="Bitta taklif — to'liq reja bilan",
    responses={404: {"description": "Taklif topilmadi"}},
)
async def proposal(proposal_id: str) -> Proposal:
    """Rejaning to'liq mazmuni: qaysi mashina, qaysi arizalar, qancha km.

    `plan.unassigned` — rejaga TUSHMAGAN arizalar sababi bilan. Ular
    tasdiqlangandan keyin ham navbatda qoladi va agent ular haqida
    xabar berishda davom etadi.
    """
    row = state.store().proposal(proposal_id)
    if row is None:
        raise HTTPException(404, f"Taklif topilmadi: {proposal_id}")
    return Proposal(**row)


@router.post(
    "/proposals/{proposal_id}/decision",
    response_model=DecisionResponse,
    summary="Rejani tasdiqlash yoki rad etish",
    responses={
        404: {"description": "Taklif topilmadi"},
        409: {"description": "Taklif allaqachon hal qilingan yoki eskirgan"},
    },
)
async def decide(
    proposal_id: str,
    payload: DecisionRequest = Body(...),
) -> DecisionResponse:
    """Odam nazorati — agent 90% ishni qiladi, oxirgi qarorni odam qabul qiladi.

    **TASDIQLASH BAJARISH EMAS.** ATIL bazasiga yozish huquqi yo'q
    (`DB_READ_ONLY=true` va bazadagi foydalanuvchida faqat `SELECT`).
    Shuning uchun tasdiqlangan reja bazaga TUSHMAYDI. U
    `AGENT_APPROVAL_WEBHOOK_URL` ga (ATIL API, ERP yoki n8n) yuboriladi.

    | `handoff.status` | Ma'nosi |
    |---|---|
    | `ok` | reja bajaruvchi tizimga yetkazildi |
    | `skipped` | manzil sozlanmagan — qaror QAYD ETILDI, lekin hech qayerga ketmadi |
    | `error` | uzatib bo'lmadi — qaror qayd etilgan, qayta yuborish kerak |

    `skipped` va `error` da javobda `warning` chiqadi. Buni e'tiborsiz
    qoldirmang: "tasdiqlandi" deb yozilgan, aslida bajarilmagan reja —
    bu moduldagi eng xavfli holat.

    **`decided_by` majburiy.** Tasdiq egasiz qolmasligi kerak: keyin
    "kim ruxsat berdi" degan savolga javob bo'lishi shart.

    **Faqat `PENDING` taklif hal qilinadi.** Allaqachon hal qilingan
    yoki eskirgani `409` qaytaradi — bir qarorni ikki marta qabul
    qilib bo'lmaydi.
    """
    store = state.store()
    existing = store.proposal(proposal_id)
    if existing is None:
        raise HTTPException(404, f"Taklif topilmadi: {proposal_id}")

    new_status = "APPROVED" if payload.decision == "approve" else "REJECTED"
    updated = store.decide(
        proposal_id, status=new_status, decided_by=payload.decided_by, note=payload.note
    )
    if updated is None:
        raise HTTPException(
            409,
            f"Taklif holati `{existing.get('status')}` — faqat `PENDING` ni hal qilish mumkin",
        )

    handoff = {"status": "skipped", "detail": "rad etilgan reja uzatilmaydi"}
    if new_status == "APPROVED":
        handoff = await channels.handoff(
            {
                "type": "route_plan_approved",
                "proposal_id": proposal_id,
                "decided_by": payload.decided_by,
                "decided_at": updated.get("decided_at"),
                "note": payload.note,
                "summary": updated.get("summary"),
                "plan": updated.get("plan"),
            }
        )
        store.mark_handoff(proposal_id, handoff)
        updated["handoff"] = handoff

    warning = None
    if new_status == "APPROVED" and handoff.get("status") != "ok":
        warning = (
            "Reja TASDIQLANDI, lekin hech qayerga BAJARILISHGA yuborilmadi "
            f"({handoff.get('detail')}). ATIL bazasiga yozish huquqi yo'q — "
            "rejani dispetcher qo'lda kiritishi yoki "
            "`AGENT_APPROVAL_WEBHOOK_URL` sozlanishi kerak."
        )

    return DecisionResponse(
        proposal=Proposal(**updated), handoff=handoff, warning=warning
    )
