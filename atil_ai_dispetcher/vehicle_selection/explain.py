"""Natijani odam tiliga o'girish — shablon va LLM tahlili.

VAZIFA BO'LINISHI:
  * TANLASH — `rules.py` va `ranker.py`, sof arifmetika. LLM u yerga
    aralashmaydi, chunki "nega bu mashina birinchi" degan savolga
    hisobdan chiqqan javob kerak, taxmindan emas. Bir xil so'rovga bir
    xil tartib chiqishi shart.
  * TAHLIL — shu fayl. Yuqori juftliklarni BIRGALIKDA ko'rib chiqish,
    ularni taqqoslash, xavfni ko'rsatish va tavsiya berish — LLM yaxshi
    bajaradigan ish.

NIMA UCHUN JUFTLIKLAR BIRGALIKDA: har biriga alohida izoh yozish
"87 ball, chunki toifasi bor" degan quruq takrorga olib keladi. Dispetcherga
kerak bo'lgan narsa — QAYSI BIRINI TANLASH va NEGA, ya'ni variantlarni
bir-biri bilan solishtirish.

LLM ISHLAMASA JAVOB HAM YO'Q. Tahlil shablon bilan to'ldirilmaydi:
LLM javob bermasa `AnalysisUnavailable` ko'tariladi va endpoint 503
qaytaradi. Sababi — bu loyihada tahlilning o'zi mahsulot, shablon matni
esa "AI tahlil qildi" degan yolg'on taassurot berardi.

LLM GA RAQAM HISOBLATILMAYDI. Promptga faqat TAYYOR ballar va faktlar
boradi va "yangi raqam o'ylab topma" deb qat'iy aytiladi. Baholanmagan
mezonlar ham ochiq yuboriladi — LLM "sig'imi mos" deb yozib yubormasligi
uchun.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from atil_ai_dispetcher.vehicle_selection import config, labels, texts
from atil_ai_dispetcher.vehicle_selection.texts import t

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


# PROMPT QISQA — bu tezlik uchun.
#
# 22.08.2026 o'lchovi (gemma4:31b, ngrok orqali) javob yozish tezligi
# 4.6-9.9 token/s ekanini ko'rsatdi, ya'ni har bir ortiqcha jumla 5-10 soniya:
#     "4-8 jumla" so'ralganda -> 194 token -> 19-42 s
#     "3 jumla"   so'ralganda ->  68 token -> 13-15 s
# Uch jumla B-variantning uchala talabini ham qoplaydi: qaysi biri afzal,
# nimasi bilan farq qiladi, qaysi mezon tekshirilmagan.
PROMPT = """Sen transport dispetcheriga yordam beradigan yordamchisan.

Quyida bitta reys uchun mashina+haydovchi variantlari va ALLAQACHON
HISOBLANGAN ballari berilgan. Sen ballarni qayta hisoblamaysan.

{language_rule}

Vazifang: 3 ta qisqa jumla yoz — YUQORIDA KO'RSATILGAN TILDA.
1-jumla: qaysi variant afzal va NEGA — mezon nomi bilan.
2-jumla: keyingi variantdan farqi yoki qanday xavf bor (muddati
         yaqinlashayotgan hujjat, ochiq remont, tajribasi kam haydovchi).
3-jumla: "baholanmagan_mezonlar" bo'sh bo'lmasa — o'sha mezonlar
         TEKSHIRILMAGANINI ayt.

QAT'IY QOIDALAR:
- Variantni "1-variant" deb emas, MASHINA RAQAMI va HAYDOVCHI ismi bilan ata.
- Faqat berilgan raqamlardan foydalan. Yangi raqam O'YLAB TOPMA.
- Baholanmagan mezon haqida "mos keladi" yoki "yetarli" DEMA.
- Sarlavha va ro'yxat belgisi yozma — faqat uch jumlaning o'zini yoz.
- Ma'lumot ichida KOD uchrasa (holat kodi, jadval yoki ustun nomi —
  masalan ACTIVE, FIT, DUMP_TRUCK, driver_shift), uni javobga KO'CHIRMA:
  ma'nosini javob tilida ayt yoki o'sha joyni umuman tilga olma. Mashina
  raqami (85299EBA), haydovchi ismi va reys raqami — bular nom, ular
  o'zgarmaydi.

MA'LUMOT (JSON):
{facts}

TAHLIL:"""


# --------------------------------------------------------- Shablon (asos)


def template_explanation(
    pair: dict[str, Any], lang: str = texts.DEFAULT_LANG
) -> str:
    """Bitta juftlik uchun LLM'siz qisqa izoh.

    Bu ZAXIRA emas, ASOS: LLM o'chirilgan bo'lsa ham har bir qator
    mazmunli bo'lishi kerak.
    """
    vehicle = pair.get("vehicle") or {}
    driver = pair.get("driver") or {}
    head = " + ".join(
        part for part in (
            vehicle.get("plate_number") or vehicle.get("brand"),
            driver.get("full_name"),
        ) if part
    )

    if pair.get("blocked"):
        from atil_ai_dispetcher.vehicle_selection import rules
        reasons = "; ".join(
            rules.blocker_text(code, lang) for code in pair.get("blockers") or [])
        return (t(lang, "pair.blocked", head=head, reasons=reasons) if head
                else t(lang, "pair.blocked_short", reasons=reasons))

    strong: list[str] = []
    weak: list[str] = []
    for name in pair.get("criteria_used") or []:
        crit = pair["criteria"][name]
        label = t(lang, f"criterion.{name}")
        if crit.score is None:
            continue
        (strong if crit.score >= 0.5 else weak).append(f"{label} {crit.score:.0%}")

    parts = []
    if strong:
        parts.append(t(lang, "pair.strong", items=", ".join(strong)))
    if weak:
        parts.append(t(lang, "pair.weak", items=", ".join(weak)))
    if pair.get("assigned_pair"):
        parts.append(t(lang, "pair.assigned"))

    skipped = [
        t(lang, f"criterion.{name}")
        for name, crit in (pair.get("criteria") or {}).items()
        if crit.score is None
    ]
    if skipped:
        parts.append(t(lang, "pair.skipped", items=", ".join(skipped)))

    body = "; ".join(parts) if parts else t(lang, "pair.no_data")
    return f"{head} — {body}" if head else body

def _pair_title(pair: dict[str, Any]) -> str:
    vehicle = (pair.get("vehicle") or {}).get("plate_number") or "?"
    driver = (pair.get("driver") or {}).get("full_name") or "?"
    return f"{vehicle} + {driver}"


def _blocker_text(code: str) -> str:
    from atil_ai_dispetcher.vehicle_selection import rules
    return rules.blocker_text(code)


# ------------------------------------------------------------- LLM tahlili


#: `detail` matnlarida jadval nomi backtick ichida beriladi — masalan
#: "smena yozuvi yo'q (`driver_shift`)". Bu API'da FOYDALI (nima uchun
#: baholanmagani ko'rinadi), lekin LLM uni javobga ko'chirib qo'yardi va
#: o'zbekcha jumla ichida inglizcha jadval nomi paydo bo'lardi. Shuning
#: uchun promptga ketayotgan nusxadan olib tashlanadi; API javobidagi
#: `detail` esa TEGILMAYDI.
_TEXNIK_NOM_RE = re.compile(r"`[a-z_][a-z0-9_]*`")


def _sof(matn: str | None) -> str | None:
    """LLM ga yuboriladigan izohdan texnik nomlarni olib tashlaydi."""
    if not matn:
        return matn
    t = _TEXNIK_NOM_RE.sub("", matn)
    t = re.sub(r"\(\s*\)", "", t)      # nomdan keyin bo'sh qavs qolgan
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def _facts_for_llm(report: dict[str, Any], limit: int) -> dict[str, Any]:
    """LLM ga faqat qaror uchun kerakli maydonlar yuboriladi.

    Butun hisobotni yuborish prompt'ni kattalashtiradi va javobni
    sekinlashtiradi. `evidence` darajasidagi tafsilot tahlil uchun kerak
    emas — ball va mezon izohi yetarli.
    """
    demand = report.get("demand") or {}
    summary = report.get("summary") or {}
    pairs = [p for p in (report.get("pairs") or []) if not p.get("blocked")][:limit]

    return {
        "talab": {
            "transport_turi": labels.label(
                "transport_type", demand.get("required_transport_type")
            ),
            "haydovchi_toifasi": demand.get("required_driver_category"),
            "yuk_kg": demand.get("cargo_weight_kg"),
            "yuk_m3": demand.get("cargo_volume_m3"),
            "yolovchi": demand.get("passengers"),
            "reys_uzunligi_km": demand.get("total_distance_km"),
            "jonash": str(demand.get("window_from") or demand.get("on_date") or ""),
        },
        "bosh_resurslar": {
            "bosh_mashina": summary.get("vehicles_available"),
            "bosh_haydovchi": summary.get("drivers_available"),
            "kesilgan_juftlik": summary.get("pairs_blocked"),
        },
        "baholanmagan_mezonlar": {
            config.CRITERION_LABEL.get(name, name): _sof(reason)
            for name, reason in (summary.get("criteria_skipped") or {}).items()
        },
        "variantlar": [
            {
                "orin": p["rank"],
                "ball": p["score"],
                "mashina": (p.get("vehicle") or {}).get("plate_number"),
                "marka": " ".join(
                    x for x in (
                        (p.get("vehicle") or {}).get("brand"),
                        (p.get("vehicle") or {}).get("model"),
                    ) if x
                ),
                "haydovchi": (p.get("driver") or {}).get("full_name"),
                "toifalari": (p.get("driver") or {}).get("license_categories"),
                "biriktirilgan_juftlik": p.get("assigned_pair"),
                "mezonlar": {
                    config.CRITERION_LABEL.get(name, name): {
                        "ball": c.get("score"),
                        "izoh": _sof(c.get("detail")),
                    }
                    for name, c in (p.get("criteria") or {}).items()
                },
            }
            for p in pairs
        ],
    }


async def analyze(
    report: dict[str, Any],
    *,
    limit: int | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> None:
    """Yuqori variantlarni LLM bilan tahlil qiladi va `report` ga yozadi (joyida).

    HAMMASIGA emas, faqat birinchi `limit` tasiga: ro'yxat ball bo'yicha
    saralangani uchun birinchilar — dispetcher aslida tanlaydigan variantlar.
    Pastdagi 90 ta variantni tahlil qilish vaqtni behuda ketkazardi.

    BITTA chaqiruv qilinadi (har juftlikka alohida emas): tahlilning butun
    ma'nosi variantlarni BIR-BIRI BILAN solishtirishda.
    """
    top = limit if limit is not None else config.LLM_ANALYZE_LIMIT
    pairs = [p for p in (report.get("pairs") or []) if not p.get("blocked")]
    if not pairs:
        # Variant yo'q bo'lsa tahlil qiladigan narsaning o'zi yo'q. Bu LLM
        # nosozligi EMAS, shuning uchun xato ko'tarilmaydi: javob 200
        # bo'lib qaytadi, `analysis.text` bo'sh qoladi va sabab
        # `summary.blocker_counts` da turadi.
        return

    # Kech import: Ollama o'chiq bo'lsa ham modul yuklansin.
    from config import DEFAULT_NUM_CTX  # chatbot config (atil_chatbot/config.py)
    from ollama_client import ask_llm

    # Til ko'rsatmasi chatbotnikidan — bitta qoida ikki xizmatda bir xil.
    prompt = PROMPT.format(
        language_rule=texts.llm_instruction(lang),
        facts=json.dumps(
            _facts_for_llm(report, top), ensure_ascii=False, indent=2, default=str
        )
    )
    try:
        text = await ask_llm(
            prompt,
            {
                "options": {
                    "temperature": 0.2,
                    # Javob uch jumla — undan ortig'ini kutish bekorga vaqt.
                    "num_predict": 160,
                    # NUM_CTX CHATBOTNIKI BILAN BIR XIL BO'LISHI SHART.
                    # Ollama modelni kontekst o'lchami bilan birga yuklaydi:
                    # boshqa `num_ctx` so'ralsa uni QAYTA YUKLAYDI.
                    # 22.08.2026 o'lchovi:
                    #     num_ctx=8192  (chatbotnikidan farqli) -> yuklash 30-33 s
                    #     num_ctx=16384 (chatbotniki bilan bir) -> yuklash 0.5-0.8 s
                    # Fon isitgichi (`start_model_warmer`) modelni aynan
                    # chatbot sozlamasi bilan issiq ushlaydi, shuning uchun
                    # bu yerda ham o'shani so'rash kifoya — o'z isitgichimiz
                    # bilan kurashmaymiz.
                    "num_ctx": DEFAULT_NUM_CTX,
                },
                "think": False,
            },
        )
    except Exception as exc:  # noqa: BLE001 — tahlil yo'q = javob yo'q
        logger.warning("LLM tahlili olinmadi: %s", str(exc)[:160])
        raise AnalysisUnavailable("Tahlil olinmadi: LLM serveri javob bermadi. Keyinroq urinib ko'ring") from exc

    cleaned = (text or "").strip()
    if not cleaned:
        # Bo'sh javob ham javob emas — uni jimgina o'tkazib yuborish
        # foydalanuvchiga bo'sh tahlil ko'rsatardi.
        logger.warning("LLM bo'sh javob qaytardi")
        raise AnalysisUnavailable("Tahlil olinmadi: LLM serveri javob bermadi. Keyinroq urinib ko'ring")

    report["analysis"] = {
        "text": cleaned,
        "pairs_considered": min(top, len(pairs)),
    }
