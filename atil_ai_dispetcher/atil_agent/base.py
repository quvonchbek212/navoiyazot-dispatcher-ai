"""Agentlarning umumiy shartnomasi — `Finding`, `Cycle`, `Agent`.

UCH QATLAM:

    boshqaruv     `orchestrator.py`  kimni qachon ishga tushirish
    bajaruvchi    `agents/*.py`      har biri BITTA vazifa
    javob beruvchi `responder.py`    natijalardan xabar quradi

BU FAYL O'RTADAGI SHARTNOMA. Bajaruvchi agent xabar YUBORMAYDI va
kanallarni bilmaydi — u faqat `Finding` qaytaradi. Yuborishni javob
beruvchi hal qiladi. Shu bo'linish tufayli yangi kuzatuv qo'shish uchun
`agents/` ga bitta fayl yoziladi va boshqa hech narsaga tegilmaydi.

`commit` — ENG NOZIK JOY, va u aynan shu bo'linish tufayli kerak bo'ldi.

Agent nimani ko'rganini eslab qolishi kerak, aks holda ertaga o'sha
hodisani qayta xabar qiladi. Lekin eslab qolish XABAR YOZILGANDAN KEYIN
bo'lishi shart: jarayon oradagi paytda o'lsa, hodisa qayta xabar
qilingani — butunlay yo'qolganidan yaxshiroq (`state.py` dagi "kamida
bir marta" izohi).

Ilgari agent xabarni o'zi yozardi va tartibni o'zi ushlab turardi. Endi
xabarni javob beruvchi yozadi, ya'ni agent "meni eslab qol" degan
harakatni KEYINGA qoldirishi kerak. `Finding.commit` shu — boshqaruv
uni xabar yozilgandan keyin chaqiradi. Chaqirilmasa hech narsa
saqlanmaydi va hodisa keyingi yurishda qaytadi.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from atil_ai_dispetcher.atil_agent import channels, texts

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    """Bitta agent topgan bitta o'zgarish.

    Bu XABAR EMAS — xabarga aylanishi javob beruvchi qo'lida. Agent
    faqat "men nimani topdim" deydi va matnni tayyor holda beradi
    (`title`, `lines`), model esa ustiga o'z jumlasini qo'shadi.

    `event_type`:
      `baseline`      birinchi ishga tushish — hozirgi holat yozib olindi
      `new`           ro'yxatda yangi qator paydo bo'ldi
      `new_requests`  navbatga yangi ariza tushdi
      `overdue`       ariza rejadagi jo'nash vaqtini o'tkazib yubordi
      `proposal`      reja tayyor, tasdiqlash kutilmoqda
      `blocked`       reja tuzib bo'lmadi — sabab ko'rsatilgan
      `blind`         manba bo'sh, tekshiruvning O'ZI bo'lmayapti
      `recovered`     tekshiruv tiklandi
    """

    agent: str
    kind: str
    event_type: str
    severity: str = channels.INFO
    title: str = ""
    text: str = ""
    lines: list[str] = field(default_factory=list)
    extra_count: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    count: int = 0
    dedupe_key: str = ""
    entity_type: str = ""
    entity_id: str = ""
    entity_number: str = ""
    action_url: str = ""
    hint: str = ""
    #: Matnni model yozdimi (`llm`) yoki kod (`template`).
    source: str = "template"
    payload: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------- Til uchun kalitlar
    #
    # Agent xabarni SIKL paytida tuzadi, o'qish esa keyinroq va boshqa
    # tilda bo'lishi mumkin. Shuning uchun matnning yonida uni QAYTA
    # QURADIGAN kalit ham saqlanadi (`texts.spec`). Tayyor `title`/`text`
    # sukut tilda quriladi — kanallar (Telegram) va log o'sha zahoti
    # matnni oladi.
    title_spec: dict[str, Any] | None = None
    text_spec: dict[str, Any] | None = None
    #: Model yozgan matn — har til uchun alohida (`{"uz": ..., "ru": ...}`).
    #: Kalit bilan qurib bo'lmaydigan yagona qism shu.
    text_lang: dict[str, str] = field(default_factory=dict)
    line_specs: list[dict[str, Any]] = field(default_factory=list)
    hint_spec: dict[str, Any] | None = None
    #: Xabar YOZILGANDAN keyin chaqiriladi (fayl boshidagi izoh).
    commit: Callable[[], None] | None = None

    #: Javob beruvchi qaysi hodisani birinchi qo'yishini hal qilishi
    #: uchun. Bu MUHIMLIK CHEGARASI EMAS — hodisa TURIGA biriktirilgan
    #: tartib. "Tekshiruv umuman ishlamayapti" har doim "3 ta yangi
    #: kechikish" dan oldin turadi, chunki birinchisi ikkinchisini
    #: ko'rinmas qilib qo'yadi.
    ORDER = {
        "blind": 0,
        "proposal": 1,
        "blocked": 2,
        "overdue": 3,
        "new": 4,
        "new_requests": 5,
        "recovered": 6,
        "baseline": 7,
    }

    def __post_init__(self) -> None:
        """Spetsifikatsiya berilgan bo'lsa sukut tildagi matnni quradi.

        Shu tufayli qolgan kod (`build_message`, kanallar, log) hech
        narsa bilmasdan ishlayveradi — u tayyor `title`/`text` ni oladi.
        """
        lang = texts.DEFAULT_LANG
        if self.title_spec and not self.title:
            self.title = texts.render(self.title_spec, lang)
        if self.text_lang and not self.text:
            self.text = self.text_lang.get(lang) or ""
        if self.text_spec and not self.text:
            self.text = texts.render(self.text_spec, lang)
        if self.line_specs and not self.lines:
            self.lines = texts.render_all(self.line_specs, lang)
        if self.hint_spec and not self.hint:
            self.hint = texts.render(self.hint_spec, lang)

    def specs(self) -> dict[str, Any]:
        """Saqlanadigan kalitlar — javob beruvchi shuni hodisaga yozadi."""
        return {
            "title": self.title_spec or texts.literal(self.title),
            "text": (
                texts.by_lang(self.text_lang) if self.text_lang
                else self.text_spec or texts.literal(self.text)
            ),
            "lines": self.line_specs or [texts.literal(x) for x in self.lines],
            "hint": self.hint_spec or texts.literal(self.hint),
        }

    @property
    def rank(self) -> int:
        return self.ORDER.get(self.event_type, 9)

    def do_commit(self) -> None:
        """Xotiraga yozadi. Xato bo'lsa yutilmaydi, LOGGA yoziladi.

        Bu yerda xato bo'lishi jiddiy: hodisa xabar qilingan, lekin
        "ko'rilgan" deb belgilanmagan — ya'ni u keyingi yurishda qayta
        keladi. Bu takror, yo'qotish emas, shuning uchun agentni
        to'xtatmaymiz; lekin jimgina ham qoldirmaymiz.
        """
        if self.commit is None:
            return
        try:
            self.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Agent xotirasi saqlanmadi (%s/%s) — bu hodisa qayta xabar qilinadi: %s",
                self.agent, self.kind, exc,
            )


@dataclass
class Cycle:
    """Bitta yurishning umumiy konteksti.

    NIMA UCHUN AGENTGA UZATILADI, HAR BIRI O'ZI OLMAYDI: `sources`
    (qaysi jadval bo'sh) BITTA so'rovda olinadi. Har agent o'zi so'rasa,
    `vehicle_telemetry_state` bitta yurishda ikki marta so'ralardi —
    og'ish uchun bir marta, bekor turish uchun yana bir marta.
    """

    now: datetime
    notify: bool = True
    #: `queries.has_rows` natijasi. BO'SH LUG'AT — "bilmadim", "hammasi
    #: bo'sh" EMAS. Farqi `Agent.is_blind` da.
    sources: dict[str, bool] = field(default_factory=dict)
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    async def once(self, key: str, loader: Callable[[], Any]) -> Any:
        """Bir yurishda BIR MARTA hisoblanadigan qiymat.

        Navbat ro'yxati ikkita agentga kerak: biri yangi arizani xabar
        qiladi, ikkinchisi ular uchun reja tuzadi. Har biri o'zi so'rasa
        bir xil so'rov bitta yurishda ikki marta ketardi.

        LEKIN AGENTLAR BIR-BIRIGA BOG'LIQ EMAS: ikkalasi ham shu
        funksiyani chaqiradi va kim birinchi kelsa o'sha yuklaydi. Ya'ni
        rejalashtiruvchi navbat agentisiz ham mustaqil ishlaydi —
        boshqaruv ularni alohida-alohida ishga tushira oladi.
        """
        if key not in self._cache:
            from fastapi.concurrency import run_in_threadpool

            self._cache[key] = await run_in_threadpool(loader)
        return self._cache[key]


class Agent(ABC):
    """Bitta vazifani bajaradigan agent.

    Yangi kuzatuv qo'shish uchun shu sinfdan meros olinadi va
    `agents/__init__.py` dagi ro'yxatga qo'shiladi. Boshqa hech qayerga
    tegilmaydi — na boshqaruvga, na javob beruvchiga, na routerga.
    """

    #: Ichki nom — holat fayli va `/agent/run?agent=` uchun.
    name: str = ""
    #: Kuzatiladigan ro'yxat nomi (holat kaliti).
    kind: str = ""
    #: O'zbekcha nom — xabarda ko'rinadi.
    title: str = ""
    #: Website'da "batafsil" qayerga olib borsin.
    action_url: str = ""
    #: To'liq ro'yxat qaysi endpointda.
    endpoint: str = ""
    #: Bu vazifa QAYSI jadvalsiz umuman ma'nosiz. `None` — bunday
    #: bog'liqlik yo'q (masalan reja tuzuvchi bir nechta jadvalga
    #: tayanadi va tayyorlikni o'zi hisoblaydi).
    primary_source: str | None = None
    #: Guruh — `/agent/run?agent=watch` bilan moslik uchun.
    group: str = ""

    @property
    @abstractmethod
    def interval_seconds(self) -> int:
        """Necha soniyada bir tekshirilsin.

        BU MEYOR EMAS, YANGILANISH TEZLIGI — bazaga tushadigan yuk
        haqidagi qaror. Sabab `config.py` da.
        """

    @abstractmethod
    async def run(self, cycle: Cycle) -> list[Finding]:
        """Vazifani bajaradi va topilganini qaytaradi.

        XABAR YUBORMAYDI va kanallarni bilmaydi. Xotiraga yozishni ham
        o'zi qilmaydi — buni `Finding.commit` orqali keyinga qoldiradi.
        """

    def is_blind(self, cycle: Cycle) -> bool:
        """Tekshiruvning O'ZI bo'lmayaptimi.

        Asosiy manba jadval bo'sh bo'lsa ro'yxat ham bo'sh qaytadi va bu
        "muammo yo'q" degani EMAS.

        MANBA NOMA'LUM BO'LSA KO'R DEB HISOBLANMAYDI: "bilmadim" ni
        "bo'sh" ga aylantirish — aynan shu modul ogohlantirib turgan
        xato. So'rov bajarilmagan bo'lsa `sources` bo'sh qoladi va bu
        yerda `False` qaytadi.
        """
        table = self.primary_source
        if not table or table not in cycle.sources:
            return False
        return not cycle.sources[table]

    def __repr__(self) -> str:  # pragma: no cover — faqat log uchun
        return f"<{type(self).__name__} {self.name}>"
