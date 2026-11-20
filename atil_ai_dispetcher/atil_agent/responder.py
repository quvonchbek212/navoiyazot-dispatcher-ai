"""Javob beruvchi agent — topilmalardan BITTA xabar quradi.

NIMA UCHUN BITTA. Bajaruvchi agentlar bir yurishda bir nechta topilma
qaytarishi mumkin: 3 ta yangi kechikish, 2 ta muddati o'tgan hujjat,
tayyor reja. Ilgari bularning har biri alohida xabar bo'lardi va
dispetcher bir daqiqada uchta bildirishnoma olardi. Endi ular bitta
xabarga yig'iladi: bitta yurish — bitta xabar.

TARTIB TASODIFIY EMAS. `Finding.rank` bo'yicha saralanadi va eng tepada
"tekshiruv umuman ishlamayapti" turadi. Sabab: ko'r holat qolgan
hammasini ma'nosiz qiladi — telematika o'chgan bo'lsa "og'ish yo'q"
degan xabar yolg'on bo'ladi. Bu MUHIMLIK CHEGARASI EMAS, hodisa turiga
biriktirilgan tartib.

MODEL NIMA QILADI VA NIMA QILMAYDI:

  qiladi     topilmalarni bog'lab, dispetcher NIMADAN boshlashi
             kerakligini bitta jumlada aytadi
  qilmaydi   sonlarni o'zgartirmaydi, qatorlarni qayta yozmaydi,
             topilmani tashlab yubormaydi

Oxirgisi eng muhimi va u KOD BILAN kafolatlanadi, ishonch bilan emas:
ro'yxatni javob beruvchining o'zi quradi, model faqat birinchi
xatboshini yozadi. Model "bu unchalik muhim emas" deb bir topilmani
tushirib qoldira olmaydi, chunki uning qo'lida ro'yxat yo'q.

MODEL YIQILSA XABAR BARIBIR KETADI — shablon bilan. `source` maydonida
matnni kim yozgani ochiq turadi.
"""

from __future__ import annotations

import logging
from typing import Any

from atil_ai_dispetcher.atil_agent import brain, channels, config, state, texts
from atil_ai_dispetcher.atil_agent.base import Cycle, Finding

logger = logging.getLogger(__name__)

PROMPT = """Sen ATIL avtopark dispetcherining yordamchisisan.

Fon kuzatuvi hozirgina tugadi. Quyida SHU YURISHDA topilgan
o'zgarishlar berilgan — ular allaqachon ro'yxat bo'lib xabarga
yozilgan.

{language_rule}

Topilmalar:
{facts}

JSON qaytar, boshqa hech narsa yozma:
{{"title": "xabar sarlavhasi, 60 belgigacha — YUQORIDA KO'RSATILGAN TILDA",
  "summary": "1-2 jumla: dispetcher NIMADAN boshlashi kerak — O'SHA TILDA"}}

QAT'IY QOIDALAR:
- Faktlardagi sonlarni O'ZGARTIRMA va yangi son O'YLAB TOPMA.
- Topilmalarni ro'yxat qilib qayta yozma — ular xabarda allaqachon bor.
- "Kritik", "shoshilinch", "muhim" kabi baho berma: bu tizimda
  muhimlik chegarasi YO'Q va uni sen o'ylab topa olmaysan.
- Agar topilmalar orasida "TEKSHIRILMAYAPTI" bo'lsa, avval SHUNI ayt:
  bo'sh ro'yxat "muammo yo'q" degani emas.
"""


def _title(findings: list[Finding], lang: str) -> str:
    """Shablon sarlavha — model javob bermaganda ishlatiladi."""
    if len(findings) == 1:
        return texts.render(findings[0].specs()["title"], lang)
    return texts.t(lang, "responder.title", count=len(findings))


def _summary(findings: list[Finding], lang: str) -> str:
    """Shablon xatboshi."""
    bosh = findings[0]
    sarlavha = texts.render(bosh.specs()["title"], lang)
    qolgan = len(findings) - 1
    if qolgan <= 0:
        return texts.render(bosh.specs()["text"], lang) or sarlavha
    return texts.t(lang, "responder.more", title=sarlavha, count=qolgan)


def severity_of(findings: list[Finding]) -> str:
    """Xabarning og'irligi — topilmalarning eng balandi.

    `WARNING` `INFO` dan ustun. Uchinchi daraja yo'q: ATIL bazasida
    `CRITICAL` birorta ham ishlatilmagan (1192 `INFO`, 654 `WARNING`),
    ya'ni uni agent kiritsa website'da hech kim kutmagan holat paydo
    bo'lardi.
    """
    return channels.WARNING if any(f.severity == channels.WARNING for f in findings) else channels.INFO


def _action_url(findings: list[Finding]) -> str:
    """Website'dagi "batafsil" tugmasi qayerga olib borsin.

    Eng yuqori tartibdagi topilmaniki. Qolganlarining havolasi
    `findings[]` ichida saqlanadi, ya'ni hech biri yo'qolmaydi.
    """
    return findings[0].action_url if findings else ""


def _entity(findings: list[Finding]) -> dict[str, Any]:
    """Obyekt faqat topilma BITTA bo'lganda ko'rsatiladi.

    Ikkita topilmani bitta obyektga bog'lash ikkinchisini jimgina
    yo'qotardi.
    """
    if len(findings) != 1:
        return {"entity_type": findings[0].entity_type if findings else None}
    f = findings[0]
    return {
        "entity_type": f.entity_type or None,
        "entity_id": f.entity_id or None,
        "entity_number": f.entity_number or None,
    }


def build_message(findings: list[Finding], *, title: str, summary: str) -> channels.Message:
    """Topilmalardan xabar matnini quradi.

    RO'YXATNI SHU YER QURADI, MODEL EMAS — fayl boshidagi izohga qarang.
    """
    lines: list[str] = []
    extra = 0
    for f in findings:
        if len(findings) > 1:
            lines.append(f"{f.title}:" if f.lines else f.title)
        lines.extend(f"  {line}" if len(findings) > 1 else line for line in f.lines)
        extra += f.extra_count

    hints = [f.hint for f in findings if f.hint]
    return channels.Message(
        agent="orchestrator",
        kind="cycle" if len(findings) > 1 else findings[0].kind,
        severity=severity_of(findings),
        title=title,
        text=summary,
        lines=lines,
        extra_count=extra,
        hint="\n".join(dict.fromkeys(hints)),
        dedupe_key="+".join(f.dedupe_key for f in findings if f.dedupe_key)[:240],
        action_url=_action_url(findings),
        **{k: (v or "") for k, v in _entity(findings).items()},
    )


async def respond(findings: list[Finding], cycle: Cycle) -> dict[str, Any] | None:
    """Topilmalardan xabar yozadi va yetkazadi.

    TARTIB: AVVAL SAQLASH, KEYIN YUBORISH, OXIRIDA XOTIRA.

      1. hodisa yoziladi — shu bilan u website uchun tayyor
      2. tashqi kanallarga yuboriladi (webhook)
      3. `Finding.commit` chaqiriladi — agentlar "ko'rdim" deb belgilaydi

    3-qadam OXIRIDA turishi shart. Jarayon 1 va 3 orasida o'lsa hodisa
    qayta xabar qilinadi; teskarisi bo'lsa BUTUNLAY yo'qolardi, va
    yo'qolgan ogohlantirish takrorlangandan xavfliroq.
    """
    if not findings:
        return None

    ordered = sorted(findings, key=lambda f: (f.rank, f.agent))
    titles, summaries, source = await _compose(ordered)
    # Kanallarga (Telegram, log) sukut tildagi matn ketadi; javobda esa
    # uchala til ham saqlanadi va o'qish paytida tanlanadi.
    message = build_message(
        ordered,
        title=titles[texts.DEFAULT_LANG],
        summary=summaries[texts.DEFAULT_LANG],
    )

    store = state.store()
    event = store.record_event(
        {
            "agent": "orchestrator",
            "kind": message.kind,
            "event_type": ordered[0].event_type if len(ordered) == 1 else "cycle",
            "title": message.title,
            "text": message.text,
            # Til uchun: sarlavha va xulosa model yozgani uchun uchala
            # tilda saqlanadi, qolgan matn esa KALIT bo'lib saqlanadi va
            # o'qish paytida quriladi (`router.py`).
            "title_by_lang": titles,
            "text_by_lang": summaries,
            "line_specs": [
                spec for f in ordered for spec in f.specs()["lines"]
            ],
            "hint_specs": [
                f.specs()["hint"] for f in ordered if f.hint
            ],
            "message": message.render(),
            "count": sum(f.count for f in ordered),
            "source": source,
            **message.as_notification(),
            "delivery": [],
            "items": [i for f in ordered for i in f.items][: config.MAX_ITEMS_IN_MESSAGE],
            # HAR TOPILMA ALOHIDA KO'RINADI. Xabar bitta bo'lsa ham
            # website ularni ajratib ko'rsata olishi kerak, va har
            # birining o'z havolasi saqlanib qolishi kerak — reja
            # taklifining tasdiqlash havolasi ayniqsa.
            "findings": [
                {
                    "agent": f.agent,
                    "kind": f.kind,
                    "event_type": f.event_type,
                    "severity": f.severity,
                    "title": f.title,
                    "title_spec": f.specs()["title"],
                    "count": f.count,
                    "action_url": f.action_url or None,
                    "dedupe_key": f.dedupe_key,
                    "entity_type": f.entity_type or None,
                    "entity_id": f.entity_id or None,
                    "entity_number": f.entity_number or None,
                    "source": f.source,
                }
                for f in ordered
            ],
        }
    )

    delivery = [{"channel": "notification", "status": "ok", "detail": "GET /agent/notifications"}]
    if cycle.notify:
        delivery += await channels.deliver(message)
    else:
        # Sinov xabari website'da o'qilmagan bo'lib osilib qolmasin.
        store.mark_read([event["id"]])
        delivery[0]["detail"] = "notify=false — yozildi, lekin darhol o'qilgan deb belgilandi"
        delivery.append({"channel": "-", "status": "skipped", "detail": "notify=false"})
    store.set_delivery(event["id"], delivery)
    event["delivery"] = delivery

    # Xabar yozildi — endi agentlar "ko'rdim" deb belgilashi mumkin.
    for f in ordered:
        f.do_commit()
    return event


async def _compose(
    findings: list[Finding],
) -> tuple[dict[str, str], dict[str, str], str]:
    """Sarlavha va birinchi xatboshi — HAR TIL UCHUN.

    Model matnini keyin tarjima qilib bo'lmaydi, shuning uchun u shu
    yerda uchala tilda yoziladi (`texts.py` boshidagi izoh).
    """
    if len(findings) == 1 and (findings[0].text_lang or findings[0].text):
        # Bitta topilma — bajaruvchi agent o'z jumlasini allaqachon
        # yozgan (yoki model yozgan). Uni qayta yozdirish ikkinchi LLM
        # chaqiruvi va hech qanday yangi ma'lumot bermasdi.
        bitta = findings[0]
        sarlavhalar = {
            til: texts.render(bitta.specs()["title"], til) for til in texts.LANGS
        }
        # Model yozgan matn tayyor tilda keladi; shablon matn esa
        # KALITDAN quriladi — aks holda sarlavha tarjima bo'lib, tanasi
        # o'zbekcha qolib ketardi.
        matnlar = (
            dict(bitta.text_lang) if bitta.text_lang
            else {
                til: texts.render(bitta.specs()["text"], til) for til in texts.LANGS
            }
        )
        return sarlavhalar, matnlar, bitta.source

    sarlavhalar: dict[str, str] = {}
    matnlar: dict[str, str] = {}
    source = "template"
    for til in texts.LANGS:
        shablon_title, shablon_summary = _title(findings, til), _summary(findings, til)
        natija, bu_source = await brain.think(
            PROMPT.format(
                language_rule=texts.llm_instruction(til),
                facts=brain.facts(
                    [
                        {
                            "vazifa": f.agent,
                            "hodisa": f.event_type,
                            "sarlavha": texts.render(f.specs()["title"], til),
                            "qatorlar_soni": f.count,
                            "namuna": texts.render_all(f.specs()["lines"], til)[:3],
                        }
                        for f in findings
                    ]
                ),
            ),
            role="responder",
            fallback=(shablon_title, shablon_summary),
            parse=lambda data: (
                str(data["title"]).strip()[:60] or shablon_title,
                str(data["summary"]).strip() or shablon_summary,
            ),
        )
        sarlavhalar[til], matnlar[til] = natija
        if bu_source == "llm":
            source = bu_source
    return sarlavhalar, matnlar, source
