"""Xabarni yetkazish — notification (website), log, webhook.

UCH QOIDA:

  1. NOTIFICATION VA LOG HAR DOIM ISHLAYDI va ularni o'chirib bo'lmaydi.
     Har bir hodisa agent xotirasiga yoziladi va `GET /agent/notifications`
     da turadi — ATIL website'ning notification qismi shu yerdan o'qiydi.
     Log esa serverda qoladi.

  2. TASHQARIGA CHIQADIGAN KANAL SUKUT BO'YICHA JIM. Webhook faqat
     `.env` da manzil yozilgandagina yoqiladi (n8n, ERP). Kod
     o'rnatilishining o'zi hech kimga xabar yubormasligi kerak.

  3. YETKAZISH XATOSI AGENTNI TO'XTATMAYDI. Webhook yiqilsa kuzatuv
     davom etadi; xato hodisaning `delivery` maydonida yozib qo'yiladi.
     Xatoni yashirmaymiz, lekin uning ustiga butun kuzatuvni qurmaymiz
     ham.

NIMA UCHUN WEBSITE BIZDAN O'QIYDI, BIZ UNGA YOZMAYMIZ. ATIL bazasida
`notification` jadvali bor va website o'sha jadvalni ko'rsatadi. Lekin
bizda unga YOZISH huquqi yo'q: ulanish READ ONLY va foydalanuvchida
faqat SELECT. Shuning uchun xabar bizning tomonda turadi va website uni
so'rab oladi.

SHUNGA QARAMAY MAYDON NOMLARI O'SHA JADVALDAN OLINGAN — `severity`,
`dedupe_key`, `entity_type`, `entity_id`, `entity_number`, `action_url`.
Sabab: ertaga ATIL backend bizdan o'qib, o'z `notification` jadvaliga
yozmoqchi bo'lsa, moslashtirish kerak bo'lmasin.

`kind` esa ATAYLAB o'sha jadvalning qiymatlaridan olinmagan. U yerdagi
`CHECK` ro'yxatida agent hodisalariga mos qiymat yo'q ("yo'nalishdan
og'ish", "reja tayyor" kabi), va bor qiymatlardan birini zo'rlab tanlash
website'da NOTO'G'RI belgi ko'rsatardi. Bizning `kind` — o'z nomimiz;
kerak bo'lsa moslashtirishni ATIL tomoni ochiq qiladi.

MATN ODDIY — MARKUP YO'Q. Xabar HTML ham, Markdown ham emas: davlat
raqami, ism va manzilda `<`, `_`, `*`, `[` uchraydi va ularni bezak deb
talqin qiladigan har qanday kanal xabarni buzardi. Website matnni o'zi
xohlagancha ko'rsatadi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from atil_ai_dispetcher.atil_agent import config

logger = logging.getLogger(__name__)

#: Xabarning og'irligi. Qiymatlar ATIL `notification.severity` dan.
#:
#: `CRITICAL` ATAYLAB ISHLATILMAYDI: 03.09.2026 da bazada 1192 ta `INFO`
#: va 654 ta `WARNING` bor, `CRITICAL` esa BIRORTA HAM yo'q. Ya'ni ATIL
#: uni amalda ishlatmaydi va agent o'zicha eng baland darajani kiritsa,
#: website'da hech kim kutmagan yangi holat paydo bo'lardi.
INFO = "INFO"
WARNING = "WARNING"


@dataclass
class Message:
    """Bitta hodisa — hamma kanal uchun bitta manba."""

    agent: str
    kind: str
    title: str
    #: `INFO` yoki `WARNING`. Bu MEYOR EMAS va ma'lumotdan hisoblanmaydi:
    #: hodisa TURIGA biriktirilgan yorliq, chaqiruvchi joyda ko'rinib
    #: turadi. "Necha soatdan keyin WARNING bo'ladi" degan qoida yo'q.
    severity: str = INFO
    text: str = ""
    lines: list[str] = field(default_factory=list)
    extra_count: int = 0
    hint: str = ""
    #: Takrorni tanish uchun — ATIL `notification.dedupe_key`. Agentning
    #: o'z xotirasi (`state.py`) takrorni allaqachon to'xtatadi; bu
    #: qabul qiluvchi tomon uchun IKKINCHI himoya.
    dedupe_key: str = ""
    #: Hodisa qaysi obyekt haqida. Bitta qatorli hodisada to'ldiriladi;
    #: ko'p qatorlida `entity_type` qoladi, `entity_id` esa bo'sh —
    #: chunki "uchta reys" bitta id ga sig'maydi.
    entity_type: str = ""
    entity_id: str = ""
    entity_number: str = ""
    #: Website'da "batafsil" tugmasi qayerga olib borsin.
    action_url: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def body(self) -> str:
        """Sarlavhasiz matn — website sarlavhani alohida ko'rsatadi."""
        parts: list[str] = []
        if self.text:
            parts.append(self.text)
        if self.lines:
            parts.append("\n".join(f"• {line}" for line in self.lines))
        if self.extra_count > 0:
            parts.append(f"...yana {self.extra_count} ta")
        if self.hint:
            parts.append(self.hint)
        return "\n\n".join(parts)

    def render(self) -> str:
        """Sarlavha bilan birga — log va webhook uchun."""
        body = self.body()
        return f"[ATIL AI] {self.title}\n\n{body}" if body else f"[ATIL AI] {self.title}"

    def as_notification(self) -> dict[str, Any]:
        """Website o'qiydigan shakl.

        Maydon nomlari ATIL `notification` jadvalidagidek — ertaga
        backend bizdan o'qib o'ziga yozmoqchi bo'lsa moslashtirish
        kerak bo'lmasin.
        """
        return {
            "severity": self.severity,
            "title": self.title,
            "body": self.body(),
            "dedupe_key": self.dedupe_key,
            "entity_type": self.entity_type or None,
            "entity_id": self.entity_id or None,
            "entity_number": self.entity_number or None,
            "action_url": self.action_url or None,
        }


# --------------------------------------------------------------------- Log


def _to_log(message: Message) -> dict[str, Any]:
    logger.info("AGENT %s/%s — %s", message.agent, message.kind, message.render())
    return {"channel": "log", "status": "ok"}


# ----------------------------------------------------------------- Webhook


async def _to_webhook(message: Message) -> dict[str, Any]:
    if not config.WEBHOOK_URL:
        return {"channel": "webhook", "status": "skipped", "detail": "manzil sozlanmagan"}
    body = {
        "agent": message.agent,
        "kind": message.kind,
        "message": message.render(),
        **message.as_notification(),
        **message.payload,
    }
    try:
        async with httpx.AsyncClient(timeout=config.WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(config.WEBHOOK_URL, json=body)
        if response.status_code >= 400:
            return {
                "channel": "webhook",
                "status": "error",
                "detail": f"HTTP {response.status_code}: {response.text[:160]}",
            }
        return {"channel": "webhook", "status": "ok", "detail": f"HTTP {response.status_code}"}
    except Exception as exc:  # noqa: BLE001 — yetkazish xatosi kuzatuvni to'xtatmaydi
        logger.warning("Webhook yuborilmadi: %s", str(exc)[:200])
        return {
            "channel": "webhook",
            "status": "error",
            "detail": f"{type(exc).__name__}: {exc}"[:200],
        }


# ------------------------------------------------------------------ Umumiy


async def deliver(message: Message) -> list[dict[str, Any]]:
    """Xabarni sozlangan TASHQI kanallarga yuboradi.

    `notification` kanali bu yerda YO'Q va bu ataylab: u YUBORILMAYDI,
    SAQLANADI. Hodisa xotiraga yozilgandan KEYIN chaqiruvchi
    (`watch._emit` / `backlog._emit`) uni `delivery` ga qo'shadi — ya'ni
    "ok" so'zi haqiqatan yozilgandan keyin paydo bo'ladi, oldin emas.

    Kanallar KETMA-KET chaqiriladi. Parallel bo'lsa tezroq bo'lardi,
    lekin bu yerda tezlik muhim emas: agent fon oqimida ishlaydi va
    hech kim javob kutib turmaydi.
    """
    return [_to_log(message), await _to_webhook(message)]


async def handoff(payload: dict[str, Any]) -> dict[str, Any]:
    """Tasdiqlangan taklifni tashqi tizimga uzatadi.

    NIMA UCHUN ALOHIDA MANZIL: bu hodisa xabari emas, HARAKAT.
    Kuzatuv xabarlari website notification qismiga boradi; rejani esa
    ATIL API yoki ERP qabul qilib BAJARISHI kerak.

    Manzil sozlanmagan bo'lsa `skipped` qaytadi va router javobda
    OCHIQ yozadi: qaror qayd etildi, lekin hech qayerga BAJARILISHGA
    yuborilmadi. "Tasdiqlandi" so'zi "bajarildi" degani emas.
    """
    if not config.APPROVAL_WEBHOOK_URL:
        return {"status": "skipped", "detail": "AGENT_APPROVAL_WEBHOOK_URL sozlanmagan"}
    try:
        async with httpx.AsyncClient(timeout=config.WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(config.APPROVAL_WEBHOOK_URL, json=payload)
        if response.status_code >= 400:
            return {
                "status": "error",
                "detail": f"HTTP {response.status_code}: {response.text[:160]}",
            }
        return {"status": "ok", "detail": f"HTTP {response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tasdiq uzatilmadi: %s", str(exc)[:200])
        return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"[:200]}


def configured() -> dict[str, bool]:
    """Qaysi kanal yoqilgan — `/agent/status` uchun.

    `notification` va `log` har doim `true`: birinchisi website o'qiydigan
    yagona manba, ikkinchisi esa tashqi kanal yiqilganda ham hodisa
    yo'qolmasligi uchun.
    """
    return {
        "notification": True,
        "log": True,
        "webhook": bool(config.WEBHOOK_URL),
        "approval_webhook": bool(config.APPROVAL_WEBHOOK_URL),
    }
