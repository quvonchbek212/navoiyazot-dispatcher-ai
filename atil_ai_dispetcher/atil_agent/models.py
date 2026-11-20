"""Javob sxemasi — Swagger shu modellardan chiziladi.

QOIDA BOSHQA MODULLARDAGI BILAN BIR XIL: `null` — NOL EMAS.
`overdue_minutes: null` "kechikmagan" degani emas, "rejadagi jo'nash
vaqti ko'rsatilmagan" degani. Ikkalasini aralashtirish arizani
navbatning oxiriga tashlab yuborardi.

IKKINCHI QOIDA SHU MODULGA XOS: TASDIQLASH — BAJARISH EMAS. ATIL
bazasiga yozish huquqi yo'q, shuning uchun `APPROVED` holati "reja
bazaga yozildi" degani emas. `Decision.handoff` aynan shuni ko'rsatadi:
qaror tashqi tizimga uzatildimi yoki faqat qayd etildimi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

#: Xabarning og'irligi — ATIL `notification.severity` dagi qiymatlar.
#:
#: `CRITICAL` ATAYLAB YO'Q: 03.09.2026 da bazada 1192 ta `INFO` va 654
#: ta `WARNING` bor, `CRITICAL` esa birorta ham yo'q. Agent o'zicha eng
#: baland darajani kiritsa, website'da hech kim kutmagan holat paydo
#: bo'lardi. Sabab `channels.py` da ham yozilgan.
Severity = Literal["INFO", "WARNING"]
INFO = "INFO"


# ------------------------------------------------------------------- Holat


class OrchestratorState(BaseModel):
    """Boshqaruv agentining holati."""

    enabled: bool = Field(..., description="`.env` bo'yicha yoqilganmi")
    running: bool = Field(..., description="Fon halqasi hozir ishlayaptimi")
    next_run_at: datetime | None = None
    runs: int = 0
    last_run_at: datetime | None = None
    last_ok_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    consecutive_errors: int = 0
    last_elapsed_seconds: float | None = None


class WorkerState(BaseModel):
    """Bitta bajaruvchi agentning holati."""

    title: str = Field("", description="Vazifasi — o'zbekcha nomi")
    group: str = Field("", description="`watch` yoki `backlog`")
    enabled: bool = Field(
        True,
        description="Fon halqasi buni o'zi ishga tushiradimi. `false` bo'lsa ham "
                    "`POST /agent/run` bilan qo'lda chaqirish mumkin",
    )
    kind: str = Field("", description="Holat fayli va `/agent/events` dagi kalit")
    interval_seconds: int = Field(
        0, description="Necha soniyada bir tekshiriladi. MEYOR EMAS, yangilanish tezligi")
    primary_source: str | None = Field(
        None, description="Bu vazifa qaysi jadvalsiz umuman ma'nosiz")
    blind: bool | None = Field(
        None,
        description="Manba bo'sh, ya'ni tekshiruvning O'ZI bo'lmayapti. `null` — hali "
                    "aniqlanmagan (bo'sh EMAS degani emas)",
    )
    watched: int = Field(0, description="Nechta qator eslab qolingan")
    last_run_at: datetime | None = None


class Decision(BaseModel):
    """Boshqaruv agentining oxirgi qarori."""

    source: str = Field("template", description="`llm` — model hal qildi; `template` — sukut tartibi")
    reason: str = ""
    order: list[str] = Field(default_factory=list, description="Qaysi tartibda ishga tushirildi")
    also_run: list[str] = Field(
        default_factory=list, description="Muddati kelmagan, lekin model qo'shgan vazifalar")
    restored: list[str] = Field(
        default_factory=list,
        description="Model tushirib qoldirgan, lekin QAYTARILGAN vazifalar. Muddati kelgan "
                    "tekshiruv o'tkazib yuborilmaydi — sabab `orchestrator.py` da",
    )


class AgentStatus(BaseModel):
    scheduler_enabled: bool = Field(
        ..., description="`AGENT_ENABLED`. O'chiq bo'lsa agentlar faqat qo'lda ishlaydi")
    running: bool = Field(False, description="Boshqaruv halqasi ishlayaptimi")
    next_run_at: datetime | None = None
    last_decision: Decision | None = Field(
        None, description="Boshqaruv agent oxirgi marta nimani qanday tartibda ishga tushirgan")
    orchestrator: OrchestratorState
    agents: dict[str, WorkerState] = Field(
        default_factory=dict, description="Bajaruvchi agentlar — har biri bitta vazifa")
    channels: dict[str, bool] = Field(
        default_factory=dict,
        description="Qaysi kanal sozlangan. `notification` va `log` har doim yoqiq",
    )
    llm_enabled: bool = Field(
        True, description="Model uch qatlamda ishlatiladimi. O'chiq bo'lsa agent SHABLON bilan ishlaydi")
    documents_days: int | None = Field(
        None,
        description="Hujjat uchun oldindan ogohlantirish oynasi. `null` — oyna yo'q, "
                    "faqat MUDDATI O'TGANI xabar qilinadi",
    )
    state_path: str
    unread_notifications: int = Field(
        0, description="`GET /agent/notifications?unread=true` da nechta xabar turibdi")


# ----------------------------------------------------------------- Hodisa


class Delivery(BaseModel):
    channel: str
    status: Literal["ok", "error", "skipped"]
    detail: str | None = None


class Event(BaseModel):
    """Agent yuborgan bitta xabar.

    `event_type`:
      `baseline`      birinchi ishga tushish — hozirgi holat yozib olindi
      `new`           ro'yxatda yangi qator paydo bo'ldi
      `new_requests`  navbatga yangi ariza tushdi
      `overdue`       ariza rejadagi jo'nash vaqtini o'tkazib yubordi
      `proposal`      reja tayyor, tasdiqlash kutilmoqda
      `blocked`       reja tuzib bo'lmadi — sabab ko'rsatilgan
      `blind`         manba bo'sh, tekshiruvning O'ZI bo'lmayapti
      `recovered`     tekshiruv tiklandi
      `cycle`         bitta yurishda bir nechta topilma bo'ldi —
                      ular `findings` da alohida ko'rinadi
    """

    id: str
    created_at: datetime
    agent: str
    kind: str
    event_type: str = ""
    title: str
    text: str = ""
    message: str = Field("", description="Kanalga ketgan matnning to'liq nusxasi")
    count: int = 0
    severity: Severity = INFO
    read_at: datetime | None = None
    source: str = Field(
        "template", description="Matnni model yozdimi (`llm`) yoki kod (`template`)")
    delivery: list[Delivery] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(
        default_factory=list, description="Shu yurishda topilgan o'zgarishlar, har biri alohida")


class Notification(BaseModel):
    """ATIL website'ning notification qismi o'qiydigan shakl.

    MAYDON NOMLARI ATIL `notification` JADVALIDAN OLINGAN va bu ataylab:
    bugun website bizdan JSON bo'lib o'qiydi, ertaga backend shu javobni
    o'z jadvaliga yozmoqchi bo'lsa moslashtirish kerak bo'lmasin.

    BITTA FARQ BOR VA UNI BILIB QO'YISH KERAK. `kind` — bizning O'Z
    nomimiz (`delayed`, `route_plan`, ...), ATIL jadvalidagi `CHECK`
    ro'yxatidan emas. U yerda agent hodisalariga mos qiymat yo'q va
    boridan birini zo'rlab tanlash website'da noto'g'ri belgi
    ko'rsatardi. Yozmoqchi bo'lgan tomon moslashtirishni O'ZI, ochiq
    qiladi.

    IKKINCHI FARQ: bitta notification KO'P QATOR haqida bo'lishi mumkin
    ("3 ta yangi kechikkan reys"). Shuning uchun `entity_id` faqat
    qator BITTA bo'lganda to'ldiriladi, to'liq ro'yxat esa `items` da
    turadi. Aks holda uchta reysdan ikkitasi jimgina yo'qolardi.
    """

    id: str
    created_at: datetime
    read_at: datetime | None = Field(
        None, description="`null` — o'qilmagan. Belgilash: `POST /agent/notifications/{id}/read`")
    severity: Severity = Field(
        INFO, description="ATIL `notification.severity`. `CRITICAL` ishlatilmaydi")
    title: str
    body: str = Field("", description="Sarlavhasiz matn — ro'yxat va izoh")
    agent: str = Field(
        ..., description="Xabarni kim yubordi. Bir nechta topilma birlashtirilsa "
                         "`orchestrator`", examples=["orchestrator"])
    kind: str = Field(
        ..., description="`cycle` — bir nechta topilma birlashtirilgan. Bitta bo'lsa: "
                         "`delayed`, `deviations`, `idle`, `documents`, `backlog_queue`, "
                         "`backlog_plan`, `route_plan`")
    event_type: str = Field("", description="`baseline`, `new`, `overdue`, `proposal`, ...")
    count: int = Field(0, description="Nechta qator haqida")
    dedupe_key: str = Field(
        "", description="Takrorni tanish uchun — ATIL `notification.dedupe_key`")
    entity_type: str | None = None
    entity_id: str | None = Field(
        None, description="Faqat qator BITTA bo'lganda to'ldiriladi")
    entity_number: str | None = None
    action_url: str | None = Field(None, description="\"Batafsil\" tugmasi qayerga olib borsin")
    items: list[dict[str, Any]] = Field(
        default_factory=list, description="Xabardagi qatorlar (`AGENT_MAX_ITEMS_IN_MESSAGE` tagacha)")
    source: str = Field(
        "template",
        description="Matnni model yozdimi (`llm`) yoki kod (`template`). Model bir hafta "
                    "yiqilib yotgan bo'lsa ham buni shu yerdan bilib olasiz",
    )
    findings: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Bitta yurishda bir nechta o'zgarish topilsa, ular BITTA xabarga "
                    "yig'iladi va shu yerda alohida-alohida turadi. Har birining o'z "
                    "`action_url` i saqlanadi — reja taklifining tasdiqlash havolasi "
                    "ayniqsa yo'qolmasligi kerak",
    )


class MarkReadResponse(BaseModel):
    marked: list[str] = Field(
        default_factory=list, description="Haqiqatan o'qilgan deb belgilanganlari")
    already_read: list[str] = Field(
        default_factory=list,
        description="Allaqachon o'qilgan edi — `read_at` O'ZGARMAYDI, birinchi "
                    "ko'rilgan payt saqlanib qoladi",
    )
    not_found: list[str] = Field(
        default_factory=list,
        description="Bunday xabar yo'q. Tarix `AGENT_EVENT_HISTORY` ta yozuv bilan "
                    "chegaralangan — eskisi siqib chiqarilgan bo'lishi mumkin",
    )
    unread: int = Field(0, description="Belgilashdan keyin nechta o'qilmagan qoldi")


# ------------------------------------------------------------------ Navbat


class QueuedRequest(BaseModel):
    """Rejalashtirishni kutayotgan bitta ariza."""

    request_id: str
    request_number: str | None = None
    status: str | None = None
    priority: str | None = None
    required_transport_type: str | None = None
    waybill_category: str | None = None
    department: str | None = None
    origin: str | None = None
    destination: str | None = None
    purpose: str | None = None
    initiator: str | None = None
    created_at: datetime | None = None
    planned_departure_at: datetime | None = None
    waiting_hours: float | None = Field(
        None, description="Ariza kelganidan beri o'tgan vaqt")
    overdue_minutes: float | None = Field(
        None,
        description="Rejadagi jo'nash vaqtidan qancha o'tgani. `null` — jo'nash "
                    "vaqti ko'rsatilmagan (kechikmagan DEGANI EMAS)",
    )


class QueueSummary(BaseModel):
    total: int = 0
    returned: int = 0
    overdue: int = Field(0, description="Jo'nash vaqti o'tib ketganlar soni")
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_transport_type: dict[str, int] = Field(default_factory=dict)
    oldest: str | None = None


class DataQuality(BaseModel):
    row_counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class Scope(BaseModel):
    checked_at: datetime
    filters: dict[str, Any] = Field(default_factory=dict)


class QueueReport(BaseModel):
    generated_at: datetime
    scope: Scope
    summary: QueueSummary
    items: list[QueuedRequest] = Field(default_factory=list)
    data_quality: DataQuality
    elapsed_seconds: float = 0.0


# ------------------------------------------------------------------ Taklif


class ProposedRoute(BaseModel):
    vehicle_id: str | None = None
    plate_number: str | None = None
    transport_type: str | None = None
    driver_id: str | None = None
    driver_name: str | None = None
    request_numbers: list[str] = Field(default_factory=list)
    request_ids: list[str] = Field(
        default_factory=list,
        description="Bajaruvchi tizim uchun — raqam emas, aynan id",
    )
    stops: int = 0
    total_distance_km: float | None = None
    total_duration_minutes: float | None = None
    capacity_utilization: float | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    explanation: str = ""


class ProposalPlan(BaseModel):
    summary: dict[str, Any] = Field(default_factory=dict)
    routes: list[ProposedRoute] = Field(default_factory=list)
    unassigned: list[dict[str, Any]] = Field(default_factory=list)
    analysis: str = Field("", description="LLM izohi. Bo'sh bo'lsa model javob bermagan")
    calibration: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    """Odam tasdiqlashi kerak bo'lgan reja.

    `status`:
      `PENDING`     qaror kutilmoqda
      `APPROVED`    tasdiqlangan — pastdagi `handoff` ga qarang
      `REJECTED`    rad etilgan
      `SUPERSEDED`  yangi reja tuzildi, bu eskirdi
    """

    id: str
    kind: str
    agent: str
    title: str
    status: Literal["PENDING", "APPROVED", "REJECTED", "SUPERSEDED"]
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    note: str | None = None
    analysis_available: bool = Field(
        True, description="LLM izoh yozib bera oldimi. `false` bo'lsa reja o'zi to'liq")
    summary: dict[str, Any] = Field(default_factory=dict)
    plan: ProposalPlan = Field(default_factory=ProposalPlan)
    handoff: dict[str, Any] | None = Field(
        None,
        description="Tasdiq tashqi tizimga uzatildimi. `skipped` — uzatilmadi, "
                    "ya'ni qaror QAYD ETILDI, lekin BAJARILMADI",
    )


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    decided_by: str = Field(
        ..., min_length=2,
        description="Kim qaror qildi. MAJBURIY: tasdiq egasiz qolmasligi kerak",
        examples=["Dispetcher: To'rayeva I."],
    )
    note: str | None = Field(None, description="Izoh — ayniqsa rad etilganda")


class DecisionResponse(BaseModel):
    proposal: Proposal
    handoff: dict[str, Any] = Field(
        default_factory=dict,
        description="`status`: ok — tashqi tizimga uzatildi; skipped — manzil "
                    "sozlanmagan; error — uzatib bo'lmadi",
    )
    warning: str | None = Field(
        None,
        description="Tasdiq hech qayerga uzatilmagan bo'lsa shu yerda ochiq yoziladi",
    )


# ------------------------------------------------------- Qo'lda ishga tushirish


class RunResponse(BaseModel):
    """Bitta yurish natijasi.

    Har bajaruvchi agent `results` da alohida qatorga ega. Topilmalar
    esa BITTA xabarga yig'iladi — `notification_id` o'shani ko'rsatadi.
    `null` bo'lsa hech narsa o'zgarmagan va bu NORMAL holat: agent
    ro'yxatni emas, o'zgarishni xabar qiladi.
    """

    agent: str = Field("orchestrator", description="Yurishni kim boshqardi")
    checked_at: datetime | None = None
    decision: Decision | None = Field(
        None, description="Boshqaruv agent qaysi tartibni tanladi va nega")
    results: list[dict[str, Any]] = Field(
        default_factory=list, description="Har bajaruvchi agent alohida")
    findings: int = Field(0, description="Jami nechta o'zgarish topildi")
    notification_id: str | None = Field(
        None, description="Yozilgan xabar id si. `null` — o'zgarish bo'lmadi")
    errors: list[str] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
