"""Rejani odam tiliga o'girish — shablon va LLM tahlili.

VAZIFA BO'LINISHI:
  * REJA TUZISH — `solver.py`, sof arifmetika. LLM u yerga aralashmaydi.
    "Nega bu ariza shu mashinaga tushdi" degan savolga hisobdan chiqqan
    javob kerak, taxmindan emas: bir xil so'rovga bir xil reja chiqishi
    shart, aks holda dispetcher natijaga ishonmaydi.
  * TUSHUNTIRISH — shu fayl. Rejani BIR BUTUN ko'rib chiqish, e'tiborni
    xavfli joyga qaratish va tavsiya berish — LLM yaxshi bajaradigan ish.

LLM ISHLAMASA JAVOB HAM YO'Q. Umumiy tahlil shablon bilan
to'ldirilmaydi: LLM javob bermasa `AnalysisUnavailable` ko'tariladi va
endpoint 503 qaytaradi. Marshrutning O'ZIDAGI qisqa izoh
(`route.explanation`) esa boshqa narsa — u faktlarni sanaydi va LLM ga
bog'liq emas.

LLM GA RAQAM HISOBLATILMAYDI. Promptga faqat TAYYOR raqamlar boradi va
"yangi raqam o'ylab topma" deb qat'iy aytiladi. Hisoblanmagan narsalar
(vaqt noma'lum bo'lsa) ham ochiq yuboriladi — LLM "hammasi vaqtida
yetib boradi" deb yozib yubormasligi uchun.
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

from atil_ai_dispetcher.Marshrut_optimizatsiyasi import config, texts
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.texts import t

logger = logging.getLogger(__name__)


class AnalysisUnavailable(RuntimeError):
    """LLM tahlil yozib bera olmadi — router buni 503 ga aylantiradi.

    NIMA UCHUN XATO, SHABLON EMAS. Ilgari LLM ishlamasa tahlil shablon
    matni bilan to'ldirilardi va javob 200 bo'lib qaytardi. Bu loyihada
    tahlilning O'ZI mahsulot: shablon matni "AI tahlil qildi" degan
    taassurot berardi, aslida esa hech qanday tahlil bo'lmasdi.

    Endi javob YO to'liq (LLM tahlili bilan), YO umuman yo'q. Frontend
    503 ni ko'rib "xatolik yuz berdi, keyinroq urinib ko'ring" deydi va
    foydalanuvchi qayta so'raydi.

    Hisobotning QOLGAN hamma qismi (ballar, marshrut, topilmalar) baribir
    arifmetikadan chiqadi va u yo'qolmaydi — shunchaki bu javobda
    yuborilmaydi.
    """


# PROMPT QISQA — bu tezlik uchun. Javob 4.6-9.9 token/s yoziladi, ya'ni
# har bir ortiqcha jumla 5-10 soniya. To'rt jumla dispetcherga kerak
# bo'lgan hamma narsani qoplaydi: reja qanday, foyda qancha, xavf qayerda,
# nima tekshirilmagan.
PROMPT = """Sen transport dispetcheriga yordam beradigan yordamchisan.

Quyida ALLAQACHON TUZILGAN marshrut rejasi berilgan. Sen rejani qayta
tuzmaysan va raqamlarni qayta hisoblamaysan.

{language_rule}

Vazifang: 4 ta qisqa jumla yoz — YUQORIDA KO'RSATILGAN TILDA.
1-jumla: reja qisqacha — nechta mashina, nechta ariza, jami masofa.
2-jumla: eng yuklangan marshrut qaysi mashinada va nima uchun shunday.
3-jumla: xavf yoki muammo — joylanmagan arizalar, kechikish, to'lgan sig'im.
4-jumla: "tekshirilmagan" ro'yxati bo'sh bo'lmasa — nima TEKSHIRILMAGANINI ayt.

QAT'IY QOIDALAR:
- Mashinani "1-mashina" deb emas, DAVLAT RAQAMI bilan ata.
- Faqat berilgan raqamlardan foydalan. Yangi raqam O'YLAB TOPMA.
- Tekshirilmagan narsa haqida "muammo yo'q" yoki "hammasi joyida" DEMA.
- Sarlavha va ro'yxat belgisi yozma — faqat to'rt jumlaning o'zini yoz.

MA'LUMOT (JSON):
{facts}

TAHLIL:"""


# --------------------------------------------------------- Shablon (asos)


def template_route_explanation(
    route: dict[str, Any], lang: str = texts.DEFAULT_LANG
) -> str:
    """Bitta marshrut uchun LLM'siz qisqa izoh.

    Bu ZAXIRA emas, ASOS: LLM o'chirilgan bo'lsa ham har bir qator
    mazmunli bo'lishi kerak.
    """
    plate = route.get("plate_number") or route.get("vehicle_id", "")[:8]
    stops = [s for s in (route.get("stops") or []) if s.get("kind") in ("PICKUP", "DELIVERY")]
    parts = [t(
        lang, "route.head",
        plate=plate,
        requests=len(route.get("requests") or []),
        stops=len(stops),
        km=f"{route.get('total_distance_km', 0):.1f}",
    )]

    minutes = route.get("total_duration_minutes")
    if minutes is not None:
        parts.append(t(lang, "route.hours", hours=f"{minutes / 60:.1f}"))

    utilization = route.get("capacity_utilization")
    if utilization is not None:
        parts.append(t(lang, "route.utilization", percent=f"{utilization:.0%}"))
    elif route.get("capacity_kg") is None:
        parts.append(t(lang, "route.capacity_unknown"))

    late = route.get("late_minutes_total")
    if late:
        parts.append(t(lang, "route.late", minutes=f"{late:.0f}"))

    return ", ".join(parts)


def fill_templates(report: dict[str, Any], lang: str = texts.DEFAULT_LANG) -> None:
    """Har bir MARSHRUTGA qisqa izoh yozadi.

    Umumiy tahlil (`analysis`) bu yerda to'ldirilmaydi — uni faqat LLM
    yozadi. Marshrut izohi esa boshqa narsa: u faktlarni sanaydi
    ("3 ta ariza, 210 km") va LLM ga bog'liq emas.
    """
    for route in report.get("routes") or []:
        route["explanation"] = template_route_explanation(route, lang)


# ------------------------------------------------------------- LLM tahlili


def _facts_for_llm(report: dict[str, Any], limit: int) -> dict[str, Any]:
    """LLM ga faqat qaror uchun kerakli maydonlar yuboriladi.

    Butun hisobotni yuborish prompt'ni kattalashtiradi va javobni
    sekinlashtiradi. Har bir to'xtashning koordinatasi va vaqti tahlil
    uchun kerak emas — marshrut darajasidagi yig'indi yetarli.
    """
    summary = report.get("summary") or {}
    calibration = report.get("calibration") or {}
    routes = (report.get("routes") or [])[:limit]
    unassigned = report.get("unassigned") or []

    tekshirilmagan: list[str] = []
    if not calibration.get("time_aware"):
        tekshirilmagan.append("vaqt oynasi va smena (tezlik noma'lum)")
    if calibration.get("service_minutes") is None:
        tekshirilmagan.append("yuklash/tushirish vaqti (o'lchov yo'q)")
    if calibration.get("distance_source") == "haversine":
        tekshirilmagan.append("haqiqiy yo'l masofasi (to'g'ri chiziq ishlatildi)")

    return {
        "reja": {
            "mashina_ishlatildi": summary.get("vehicles_used"),
            "mashina_mavjud": summary.get("vehicles_considered"),
            "ariza_joylandi": summary.get("requests_assigned"),
            "ariza_joylanmadi": summary.get("requests_unassigned"),
            "jami_km": summary.get("total_distance_km"),
            "jami_daqiqa": summary.get("total_duration_minutes"),
            "optimizatsiyasiz_km": summary.get("baseline_distance_km"),
            "tejaldi_foiz": summary.get("saved_percent"),
            "kechikish_daqiqa": summary.get("total_late_minutes"),
        },
        "marshrutlar": [
            {
                "mashina": r.get("plate_number") or r.get("vehicle_id"),
                "haydovchi": r.get("driver_name"),
                "ariza_soni": len(r.get("requests") or []),
                "km": r.get("total_distance_km"),
                "daqiqa": r.get("total_duration_minutes"),
                "sigim_ulushi": r.get("capacity_utilization"),
                "kechikish_daqiqa": r.get("late_minutes_total"),
                "ogohlantirish": r.get("warnings"),
            }
            for r in routes
        ],
        "joylanmagan": [
            {
                "ariza": u.get("request_number"),
                "sabab": u.get("reason"),
                "muhimlik": u.get("priority"),
            }
            for u in unassigned[:limit]
        ],
        "tekshirilmagan": tekshirilmagan,
    }


async def analyze(
    report: dict[str, Any],
    *,
    limit: int | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> None:
    """Rejani LLM bilan tahlil qiladi va `report` ga yozadi (joyida).

    BITTA chaqiruv qilinadi (har marshrutga alohida emas): tahlilning
    ma'nosi rejani BIR BUTUN ko'rishda.
    """
    top = limit if limit is not None else config.LLM_ANALYZE_LIMIT
    if not (report.get("routes") or report.get("unassigned")):
        return

    # Kech import: Ollama o'chiq bo'lsa ham modul yuklansin.
    from config import DEFAULT_NUM_CTX  # chatbot config (atil_chatbot/config.py)
    from ollama_client import ask_llm

    # Til ko'rsatmasi chatbotnikidan olinadi — bitta joyda yozilgan
    # qoida ikki xizmatda bir xil ishlaydi.
    prompt = PROMPT.format(
        language_rule=texts.llm_instruction(lang),
        facts=json.dumps(
            _facts_for_llm(report, top), ensure_ascii=False, indent=2, default=str
        ),
    )
    try:
        text = await ask_llm(
            prompt,
            {
                "options": {
                    "temperature": 0.2,
                    # Javob to'rt jumla — undan ortig'ini kutish bekorga vaqt.
                    "num_predict": 200,
                    # NUM_CTX CHATBOTNIKI BILAN BIR XIL BO'LISHI SHART.
                    # Ollama modelni kontekst o'lchami bilan birga yuklaydi:
                    # boshqa `num_ctx` so'ralsa uni QAYTA YUKLAYDI (o'lchovda
                    # 30-33 s farq). Fon isitgichi modelni aynan chatbot
                    # sozlamasi bilan issiq ushlaydi.
                    "num_ctx": DEFAULT_NUM_CTX,
                },
                "think": False,
            },
        )
    except Exception as exc:  # noqa: BLE001 — tahlil yo'q = javob yo'q
        logger.warning("LLM tahlili olinmadi: %s", str(exc)[:160])
        raise AnalysisUnavailable(t(lang, "error.analysis")) from exc

    cleaned = (text or "").strip()
    if not cleaned:
        logger.warning("LLM bo'sh javob qaytardi")
        raise AnalysisUnavailable(t(lang, "error.analysis"))

    report["analysis"] = {
        "text": cleaned,
        "routes_considered": min(top, len(report.get("routes") or [])),
    }
