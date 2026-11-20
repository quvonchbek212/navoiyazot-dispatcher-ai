"""Ro'yxatni bir xatboshi xulosaga aylantirish — shablon va LLM.

VAZIFA BO'LINISHI:
  * ANIQLASH — `service.py` va `queries.py`, sof solishtirish. LLM u
    yerga aralashmaydi: "nechta reys kechikkan" degan savolga hisobdan
    chiqqan javob kerak.
  * XULOSALASH — shu fayl. 50 qatorli ro'yxatdan "nima eng shoshilinch"
    degan bir xatboshi chiqarish — LLM yaxshi bajaradigan ish.

NIMA UCHUN BITTA XATBOSHI: dispetcher ekranida to'rtta bo'lim bor.
Har biriga uzun matn yozilsa, o'qishga vaqt ketadi va ro'yxatning
o'ziga qaramaydi. Xulosa ro'yxatni ALMASHTIRMAYDI, unga yo'l ko'rsatadi.

LLM ISHLAMASA XIZMAT TO'XTAMAYDI: xulosa avval shablon bilan yoziladi,
LLM javob bersa ustidan almashtiriladi.

LLM GA RAQAM HISOBLATILMAYDI — promptga faqat tayyor sonlar boradi.
"Tekshirilmadi" ro'yxati ham yuboriladi, LLM "muammo yo'q" deb yozib
yubormasligi uchun.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from atil_ai_dispetcher.dispatcher_assistant import config, texts
from atil_ai_dispetcher.dispatcher_assistant.texts import t

logger = logging.getLogger(__name__)

#: Har bir ro'yxat nima haqidaligi — promptga shu matn qo'yiladi.
KIND_LABEL = {
    "delayed": "kechikayotgan reyslar",
    "deviations": "yo'nalishdan og'gan mashinalar",
    "idle": "bekor turgan mashinalar",
    "documents": "muddati tugayotgan hujjatlar",
}

# PROMPT QISQA — javob 4.6-9.9 token/s yoziladi, ya'ni har ortiqcha
# jumla 5-10 soniya. Dispetcherga uch jumla yetadi: nima bo'lyapti,
# nimadan boshlash kerak, nima tekshirilmagan.
PROMPT = """Sen transport dispetcheriga yordam beradigan yordamchisan.

Quyida "{label}" ro'yxati va ALLAQACHON HISOBLANGAN sonlari berilgan.
Sen ularni qayta hisoblamaysan.

Vazifang: 3 ta qisqa o'zbekcha jumla yoz.
1-jumla: umumiy manzara — nechta va qanchalik og'ir.
2-jumla: birinchi navbatda nima qilish kerak, KIM yoki QAYSI MASHINA
         bilan — davlat raqami yoki ism bilan ata.
3-jumla: "tekshirilmagan" bo'sh bo'lmasa — nima TEKSHIRILMAGANINI ayt.
         Bo'sh bo'lsa bu jumlani yozma.

{language_rule}

QAT'IY QOIDALAR:
- Faqat berilgan raqamlardan foydalan. Yangi raqam O'YLAB TOPMA.
- Ro'yxat bo'sh bo'lsa "muammo yo'q" DEMA — manba bo'sh bo'lishi mumkin.
- Sarlavha va ro'yxat belgisi yozma — faqat jumlalarning o'zini yoz.

MA'LUMOT (JSON):
{facts}

XULOSA:"""


# --------------------------------------------------------- Shablon (asos)


def template_analysis(
    report: dict[str, Any], kind: str, lang: str = texts.DEFAULT_LANG
) -> str:
    """LLM'siz xulosa — faktlarni gapga bog'laydi.

    Bu ZAXIRA emas, ASOS: LLM o'chirilgan bo'lsa ham javob mazmunli
    bo'lishi kerak.
    """
    summary = report.get("summary") or {}
    notes = report.get("data_quality", {}).get("notes") or []
    label = t(lang, f"kind.{kind}")
    total = summary.get("total") or 0

    if not total:
        # Izoh endi uch tilda yozilishi mumkin, shuning uchun kalit
        # so'z ham uch tilda qidiriladi (`texts.is_unchecked`).
        blocking = [n for n in notes if texts.is_unchecked(n)]
        if blocking:
            # Izohning birinchi qismi — manba nomi; qolgani takrorlanmaydi.
            manba = blocking[0].split("—")[0].strip().rstrip(".")
            return t(lang, "analysis.blocked", source=manba, label=label)
        return t(lang, "analysis.nothing", label=label)

    if kind == "documents":
        # "412 ta muddati tugayotgan hujjat" degan gap YOLG'ON bo'lardi:
        # `days` berilmasa ro'yxatga 2036-yilgacha amal qiladigan
        # guvohnoma ham kiradi. Shuning uchun bu yerda muddati
        # O'TGANLAR soni oldinga chiqariladi.
        expired = summary.get("expired") or 0
        if expired:
            lines = [t(lang, "analysis.expired", count=expired)]
        else:
            lines = [t(lang, "analysis.no_expired")]
        lines.append(t(lang, "analysis.documents_total", count=total))
    else:
        lines = [t(lang, "analysis.found", count=total, label=label)]

    if summary.get("worst"):
        lines.append(t(lang, "analysis.worst", worst=summary["worst"]))

    by_kind = {k: v for k, v in (summary.get("by_kind") or {}).items()
               if not k.startswith("_")}
    if len(by_kind) > 1:
        parts = ", ".join(f"{k}: {v}" for k, v in by_kind.items())
        lines.append(t(lang, "analysis.by_kind", parts=parts))

    unchecked = [n for n in notes if texts.is_unchecked(n)]
    if unchecked:
        lines.append(t(lang, "analysis.attention", note=unchecked[0]))

    return " ".join(lines)


def fill_template(
    report: dict[str, Any], kind: str, lang: str = texts.DEFAULT_LANG
) -> None:
    report["analysis"] = {
        "text": template_analysis(report, kind, lang),
        "source": "template",
        "items_considered": len(report.get("items") or []),
    }


# ------------------------------------------------------------- LLM xulosasi


def _facts(report: dict[str, Any], kind: str, limit: int) -> dict[str, Any]:
    """LLM ga faqat qaror uchun kerakli maydonlar yuboriladi.

    Butun ro'yxatni yuborish prompt'ni kattalashtiradi va javobni
    sekinlashtiradi. Koordinata, id va texnik maydonlar xulosa uchun
    kerak emas.
    """
    summary = report.get("summary") or {}
    items = (report.get("items") or [])[:limit]
    notes = report.get("data_quality", {}).get("notes") or []

    if kind == "delayed":
        rows = [
            {
                "reys": i.get("trip_number"),
                "turi": "jo'namagan" if i.get("kind") == "NOT_DEPARTED" else "yo'lda",
                "kechikish_soat": round((i.get("delay_minutes") or 0) / 60, 1),
                "mashina": i.get("plate_number"),
                "haydovchi": i.get("driver_name"),
                "manzil": i.get("destination"),
            }
            for i in items
        ]
    elif kind == "deviations":
        rows = [
            {
                "mashina": i.get("plate_number"),
                "haydovchi": i.get("driver_name"),
                "yoldan_metr": i.get("distance_from_route_meters"),
                "chegara_metr": i.get("threshold_meters"),
                "tezlik": i.get("speed_kph"),
                "marshrut": i.get("route_number"),
            }
            for i in items
        ]
    elif kind == "idle":
        rows = [
            {
                "mashina": i.get("plate_number"),
                "haydovchi": i.get("driver_name"),
                "turgan_soat": round((i.get("stopped_minutes") or 0) / 60, 1),
                "dvigatel_ishlayapti": i.get("engine_on"),
                "gps_dan_beri_daqiqa": i.get("minutes_since_last_event"),
            }
            for i in items
        ]
    else:
        rows = [
            {
                "kim": i.get("subject_name"),
                "hujjat": i.get("document_type"),
                "tugaydi": str(i.get("valid_until")),
                "qolgan_kun": i.get("days_left"),
                "muddati_otgan": i.get("expired"),
            }
            for i in items
        ]

    return {
        "jami": summary.get("total"),
        "korsatilgan": summary.get("returned"),
        "eng_ogiri": summary.get("worst"),
        "taqsimot": {k: v for k, v in (summary.get("by_kind") or {}).items()
                     if not k.startswith("_")},
        "royxat": rows,
        "tekshirilmagan": [n for n in notes if "TEKSHIRILMADI" in n],
    }


async def analyze(
    report: dict[str, Any],
    kind: str,
    *,
    limit: int | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> None:
    """Ro'yxatni LLM bilan xulosalaydi va `report` ga yozadi (joyida)."""
    top = limit if limit is not None else config.LLM_ANALYZE_LIMIT

    # BO'SH RO'YXATGA LLM CHAQIRILMAYDI. Sabab amalda ko'rildi: bo'sh
    # ro'yxat berilganda model "bekor turgan mashinalar yo'q" deb yozdi —
    # ya'ni aynan taqiqlangan xulosani chiqardi. Bo'sh holat uchun
    # shablon matni ANIQROQ ("manba bo'sh, tekshirilmadi") va bepul:
    # javob 8-10 soniyaga tezlashadi.
    if not (report.get("items") or []):
        return

    # Kech import: Ollama o'chiq bo'lsa ham modul yuklansin.
    from config import DEFAULT_NUM_CTX  # chatbot config (atil_chatbot/config.py)
    from ollama_client import ask_llm

    # Til ko'rsatmasi chatbotnikidan — bitta qoida to'rt xizmatda bir xil.
    prompt = PROMPT.format(
        language_rule=texts.llm_instruction(lang),
        label=t(lang, f"kind.{kind}"),
        facts=json.dumps(_facts(report, kind, top), ensure_ascii=False,
                         indent=2, default=str),
    )
    try:
        text = await ask_llm(
            prompt,
            {
                "options": {
                    "temperature": 0.2,
                    # Javob uch jumla — undan ortig'ini kutish bekorga vaqt.
                    "num_predict": 160,
                    # NUM_CTX CHATBOTNIKI BILAN BIR XIL BO'LISHI SHART:
                    # boshqa qiymat so'ralsa Ollama modelni QAYTA yuklaydi
                    # (o'lchovda 30 s gacha farq). Fon isitgichi modelni
                    # aynan chatbot sozlamasi bilan issiq ushlaydi.
                    "num_ctx": DEFAULT_NUM_CTX,
                },
                "think": False,
            },
        )
    except Exception as exc:  # noqa: BLE001 — xulosa yo'qligi xizmatni to'xtatmaydi
        logger.warning(
            "LLM xulosasi olinmadi (%s) — shablon qoldi", str(exc)[:160]
        )
        return

    cleaned = (text or "").strip()
    if cleaned:
        report["analysis"] = {
            "text": cleaned,
            "source": "llm",
            "items_considered": min(top, len(report.get("items") or [])),
        }
    else:
        logger.warning("LLM bo'sh javob qaytardi — shablon xulosasi qoldi")
