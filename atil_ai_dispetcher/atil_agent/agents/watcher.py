"""Ro'yxat kuzatuvchilarining umumiy asosi.

TO'RTTA KUZATUVCHI (kechikish, og'ish, bekor turish, hujjat) BIR XIL
ISHNI QILADI:

    1. `dispatcher_assistant` dan ro'yxatni oladi
    2. har qatorga O'ZGARMAS kalit beradi
    3. oldingi holat bilan solishtiradi
    4. FAQAT YANGI paydo bo'lganini qaytaradi

Farqi atigi to'rt joyda: qaysi funksiyani chaqirish, kalit nimadan
tuziladi, qator qanday yoziladi va qaysi jadvalsiz ma'nosiz. Shuning
uchun mashina shu yerda, farq esa `delayed.py`, `deviation.py`,
`idle.py`, `document.py` da — har biri 40 qatordan oshmaydi.

NIMA UCHUN "O'ZGARISH", "RO'YXAT" EMAS. 03.09.2026 da bazada 73 ta
kechikkan reys va 412 ta hujjat bor. Har 15 daqiqada shu ro'yxatni
yuborish kuniga 96 ta bir xil xabar demakdir — bunday kanalni odam
birinchi kuni o'chirib tashlaydi va keyin HAQIQIY hodisani ham
ko'rmaydi.

AGENT MEYOR O'YLAB TOPMAYDI. "Muhim kechikish" degan chegara yo'q —
`dispatcher_assistant` dagi filtrlar sukut bo'yicha o'chiq va agent
ularni yoqmaydi. Hodisaning ta'rifi bitta: RO'YXATDA YANGI QATOR PAYDO
BO'LDI. Bu chegara emas, oldingi holat bilan solishtirish.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import logging
from typing import Any

from fastapi.concurrency import run_in_threadpool

from atil_ai_dispetcher.atil_agent import brain, channels, config, state, texts
from atil_ai_dispetcher.atil_agent.texts import literal, spec
from atil_ai_dispetcher.atil_agent.base import Agent, Cycle, Finding

logger = logging.getLogger(__name__)

PROMPT = """Sen ATIL avtopark dispetcherining yordamchisisan.

Quyida SHU TEKSHIRUVDA YANGI paydo bo'lgan qatorlar berilgan. Faqat
shular haqida yoz — bazadagi umumiy holat haqida emas.

Vazifa: {label}

{language_rule}

Faktlar:
{facts}

JSON qaytar, boshqa hech narsa yozma:
{{"summary": "1-2 jumla: dispetcher NIMADAN boshlashi kerak — YUQORIDA KO'RSATILGAN TILDA"}}

QAT'IY QOIDALAR:
- Faktlardagi sonlarni O'ZGARTIRMA va yangi son O'YLAB TOPMA.
- "Muhim", "kritik", "shoshilinch" kabi baho berma — chegara yo'q.
- Ro'yxatni qayta yozma, u xabarda allaqachon bor.
"""


def short(value: Any, size: int = 8) -> str:
    return str(value or "")[:size]


def fingerprint(keys: list[str]) -> str:
    """Kalitlar to'plamining qisqa belgisi — `dedupe_key` uchun.

    Kalitlarning o'zini yozib bo'lmaydi: ATIL `notification.dedupe_key`
    256 belgi, 73 ta reys id si esa undan uzun. Kriptografiya emas,
    takrorni tanish.
    """
    joined = "|".join(sorted(str(k) for k in keys))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


class ListWatcher(Agent):
    """Bitta ro'yxatni kuzatadigan agent."""

    group = "watch"
    #: Kuzatilayotgan ro'yxat nomining KALITI (`texts.py`). `title`
    #: o'rniga kalit turadi, chunki sarlavha uch tilda quriladi.
    list_key: str = ""
    #: Xulosada qatorlarni shu ustun bo'yicha guruhlash (`None` — kerak emas).
    group_field: str | None = None

    @property
    def interval_seconds(self) -> int:
        return config.WATCH_INTERVAL_SECONDS

    # ------------------------------------------------- Vorislar to'ldiradi

    def fetch(self, cycle: Cycle) -> dict[str, Any]:
        """Ro'yxatni `dispatcher_assistant` ning O'ZI bilan hisoblaydi.

        Agent SQL yozmaydi va hisob-kitobni takrorlamaydi. Aks holda bir
        xil savolga ikki xil javob beradigan ikkita kod paydo bo'lardi:
        panelda bir raqam, xabarda boshqasi.
        """
        raise NotImplementedError

    def key(self, item: dict[str, Any]) -> str:
        """Qatorning O'ZGARMAS belgisi — shu bo'yicha "yangimi" hal qilinadi."""
        raise NotImplementedError

    def line_spec(self, item: dict[str, Any]) -> dict[str, Any]:
        """Xabardagi bitta qator — KALIT ko'rinishida.

        Matn emas, kalit qaytariladi: qator o'qish paytida, tanlangan
        tilda quriladi.
        """
        raise NotImplementedError

    def list_name(self) -> dict[str, Any]:
        """Ro'yxat nomi — sarlavhaga qo'yiladigan ichki kalit."""
        return spec(self.list_key) if self.list_key else literal(self.title)

    def entity(self, items: list[dict[str, Any]]) -> dict[str, str]:
        """Hodisa qaysi obyekt haqida — ATIL `notification.entity_*` uchun."""
        return {}

    def alertable(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Qaysi qatorlar HODISA bo'la oladi.

        Sukut bo'yicha hammasi: kechikish, og'ish va bekor turish
        ro'yxatining o'zi allaqachon "hozir muammo bor" degan ma'noni
        bildiradi. Hujjat buni qayta belgilaydi.
        """
        return items

    # ------------------------------------------------------------ Mashina

    async def run(self, cycle: Cycle) -> list[Finding]:
        store = state.store()
        report = await run_in_threadpool(functools.partial(self.fetch, cycle))

        items = self.alertable(report.get("items") or [])
        keys = [self.key(item) for item in items]
        by_key = dict(zip(keys, items))
        diff = store.plan_diff(self.kind, keys)

        findings: list[Finding] = []

        # 1. Tekshiruvning O'ZI bo'lmayotgan bo'lsa — buni birinchi aytamiz.
        #
        # `previous is None` — bu ro'yxat hali hech qachon ko'rilmagan.
        # Bunda "tiklandi" deb yozib bo'lmaydi: hech narsa buzilmagan edi.
        previous = store.blind_state(self.kind)
        blind = self.is_blind(cycle)
        if blind and previous is not True:
            findings.append(self._blind_finding(report))
        elif previous is True and not blind:
            findings.append(self._recovered_finding(len(items)))

        # 2. Birinchi ishga tushish — bazaviy holat, qator-qator xabar YO'Q.
        if diff.baseline:
            findings.append(self._baseline_finding(report, items, blind))
        elif diff.has_news:
            new_items = [by_key[k] for k in diff.new_keys if k in by_key]
            findings.append(await self._news_finding(report, new_items, len(items), diff))

        # 3. HOLAT XABARDAN KEYIN saqlanadi — `commit` ni oxirgi
        #    topilmaga bog'laymiz. Topilma bo'lmasa ham saqlash kerak
        #    (ro'yxat o'zgargan bo'lishi mumkin), shuning uchun bo'sh
        #    holatda darhol yozamiz.
        def saqla() -> None:
            store.set_blind(self.kind, blind)
            store.commit_diff(diff, now=cycle.now)

        if findings:
            findings[-1].commit = saqla
        else:
            saqla()
        return findings

    # ----------------------------------------------------------- Topilmalar

    def _blind_finding(self, report: dict[str, Any]) -> Finding:
        return Finding(
            agent=self.name,
            kind=self.kind,
            event_type="blind",
            severity=channels.WARNING,
            title_spec=spec("watch.blind.title", list=self.list_name()),
            text_spec=spec("watch.blind.text", table=self.primary_source),
            line_specs=_gap_notes(report),
            hint_spec=spec("watch.blind.hint"),
            dedupe_key=f"{self.name}:blind",
            action_url=self.action_url,
        )

    def _recovered_finding(self, total: int) -> Finding:
        return Finding(
            agent=self.name,
            kind=self.kind,
            event_type="recovered",
            severity=channels.INFO,
            title_spec=spec("watch.recovered.title", list=self.list_name()),
            text_spec=spec("watch.recovered.text", table=self.primary_source),
            count=total,
            dedupe_key=f"{self.name}:recovered",
            action_url=self.action_url,
        )

    def _baseline_finding(
        self, report: dict[str, Any], items: list[dict[str, Any]], blind: bool
    ) -> Finding:
        return Finding(
            agent=self.name,
            kind=self.kind,
            event_type="baseline",
            # Bazaviy xabar HODISA EMAS, e'lon: "kuzatuv boshlandi".
            # Ro'yxatda 73 ta kechikkan reys bo'lsa ham, ularning hech
            # biri HOZIR sodir bo'lgani yo'q.
            severity=channels.INFO,
            title_spec=spec("watch.baseline.title", list=self.list_name()),
            text_spec=spec("watch.baseline.text", count=len(items)),
            # Tekshirilmay qolgan QISMLAR shu yerda bir marta aytiladi.
            # Har tekshiruvda takrorlansa shovqinga aylanardi, umuman
            # aytilmasa — ro'yxat o'zidan to'liqroq ko'rinardi.
            line_specs=[] if blind else _gap_notes(report),
            count=len(items),
            dedupe_key=f"{self.name}:baseline",
            action_url=self.action_url,
            hint_spec=spec("watch.hint.full_list", endpoint=self.endpoint),
        )

    async def _news_finding(
        self,
        report: dict[str, Any],
        new_items: list[dict[str, Any]],
        total_now: int,
        diff: Any,
    ) -> Finding:
        shown = new_items[: config.MAX_ITEMS_IN_MESSAGE]
        text_lang, source = await self._summary(report, new_items)
        return Finding(
            agent=self.name,
            kind=self.kind,
            event_type="new",
            # Uch ro'yxatning o'zi "hozir muammo bor" degani, hujjatda
            # esa muddat o'tib bo'lgan. Bu chegara emas, hodisa TURIGA
            # biriktirilgan yorliq.
            severity=channels.WARNING,
            title_spec=spec(
                "watch.new.title", count=len(new_items), list=self.list_name()),
            text_lang=text_lang,
            source=source,
            line_specs=[self.line_spec(item) for item in shown],
            extra_count=len(new_items) - len(shown),
            items=shown,
            count=len(new_items),
            dedupe_key=f"{self.name}:new:{fingerprint(diff.new_keys)}",
            action_url=self.action_url,
            hint=f"To'liq ro'yxat: {self.endpoint}",
            payload={"new_count": len(new_items), "total_now": total_now},
            **self.entity(new_items),
        )

    # ---------------------------------------------------------------- Miya

    async def _summary(
        self, report: dict[str, Any], new_items: list[dict[str, Any]]
    ) -> tuple[dict[str, str], str]:
        """Xabarning birinchi jumlasi.

        SHABLON ASOS, MODEL USTIGA YOZADI. Model o'chirilgan yoki javob
        bermagan bo'lsa xabar baribir to'liq ketadi — kuzatuvni model
        ushlab turmasligi kerak.

        MODELGA FAQAT YANGI QATORLAR KO'RSATILADI. To'liq ro'yxat
        berilsa model "73 ta reys kechikdi" deb yozardi — to'g'ri son,
        lekin XABARGA yolg'on: xabar 3 ta yangi hodisa haqida.
        """
        # HAR TIL UCHUN ALOHIDA CHAQIRUV. Model matnini keyin tarjima
        # qilib bo'lmaydi, xabar esa o'qish paytida istalgan tilda
        # so'ralishi mumkin. Agent fonda ishlagani uchun bu kechikish
        # foydalanuvchiga ko'rinmaydi.
        natija: dict[str, str] = {}
        source = "template"
        for til in texts.LANGS:
            shablon = self._template(new_items, til)
            prompt = PROMPT.format(
                label=texts.render(self.list_name(), til),
                language_rule=texts.llm_instruction(til),
                facts=brain.facts(
                    {
                        "yangi_qatorlar_soni": len(new_items),
                        "turlari": self._by_group(new_items),
                        "qatorlar": [
                            texts.render(self.line_spec(i), til)
                            for i in new_items[: config.LLM_FACT_LIMIT]
                        ],
                        "manba_izohlari": texts.render_all(_gap_notes(report), til),
                    }
                ),
            )
            matn, bu_source = await brain.think(
                prompt,
                role="agent",
                fallback=shablon,
                parse=lambda data: str(data["summary"]).strip() or shablon,
            )
            natija[til] = matn
            if bu_source == "llm":
                source = "llm"
        return natija, source

    def _template(self, new_items: list[dict[str, Any]], lang: str) -> str:
        eng = texts.render(self.line_spec(new_items[0]), lang) if new_items else ""
        return texts.t(
            lang, "watch.template",
            count=len(new_items),
            list=texts.render(self.list_name(), lang),
            top=texts.t(lang, "watch.template.top", line=eng) if eng else "",
        )

    def _by_group(self, items: list[dict[str, Any]]) -> dict[str, int]:
        if not self.group_field:
            return {}
        out: dict[str, int] = {}
        for item in items:
            key = str(item.get(self.group_field) or "OTHER")
            out[key] = out.get(key, 0) + 1
        return out


def _gap_notes(report: dict[str, Any]) -> list[str]:
    """Tekshirilmay qolgan QISM haqidagi izohlar.

    Bu "ko'r" holat emas: ro'yxat ishlayapti, lekin ba'zi manbalar bo'sh
    (masalan sug'urta jadvali). Shuning uchun bu izohlar har tekshiruvda
    emas, faqat BAZAVIY xabarda bir marta ko'rsatiladi.
    """
    from atil_ai_dispetcher.dispatcher_assistant import texts as da_texts

    dq = report.get("data_quality") or {}
    notes = dq.get("notes") or []
    # `dispatcher_assistant` izohlarni UCHALA TILDA birga qaytaradi
    # (`notes_by_lang`) — shuning uchun ular ham tarjima bo'lib
    # saqlanadi. Boshqa manbadan kelgan izoh bo'lsa xom matn qoladi.
    by_lang = dq.get("notes_by_lang") or {}
    out: list[dict[str, Any]] = []
    for index, note in enumerate(notes):
        if not da_texts.is_unchecked(note):
            continue
        if by_lang:
            out.append(texts.by_lang({
                til: (qatorlar[index] if index < len(qatorlar) else note)
                for til, qatorlar in by_lang.items()
            }))
        else:
            out.append(literal(note))
    return out


def deep_copy(value: Any) -> Any:  # pragma: no cover — qulaylik uchun
    return copy.deepcopy(value)
