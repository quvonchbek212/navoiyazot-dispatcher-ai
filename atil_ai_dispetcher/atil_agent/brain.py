"""Agentlarning LLM bilan gaplashadigan YAGONA joyi.

NIMA UCHUN BITTA FAYL. Uch qatlamning uchalasi ham modeldan foydalanadi
(boshqaruv, bajaruvchi, javob beruvchi). Har biri o'zicha chaqirsa, uch
xil timeout, uch xil xato ishlovi va uch xil "model yiqilganda nima
bo'ladi" savoli paydo bo'lardi. Bu yerda javob bitta.

ENG MUHIM QOIDA: MODEL YIQILSA AGENT ISHLAYVERADI.

Bu qulaylik emas, modulning mavjudlik sharti. Agent 15 daqiqada bir
marta, hech kim qaramay turib ishlaydi. Model javob bermaganda tekshiruv
to'xtasa, kuzatuv JIMGINA o'chib qolardi — va uni hech kim sezmasdi,
chunki agentning ishi tashqaridan "jim turish" ga o'xshaydi. Shuning
uchun har chaqiruvda `fallback` majburiy: model javob bermasa kod o'zi
hisoblagan javob ishlatiladi.

IKKINCHI QOIDA: MODEL RAQAM QAYTARMAYDI.

Har uch qatlamda ham modeldan MATN va TARTIB so'raladi, SON emas.
Kechikish necha soat, nechta ariza navbatda, qaysi jadval bo'sh — bularni
SQL aytadi. Model shu sonlar ustiga jumla yozadi.

Sabab amaliy, falsafiy emas: `/dispatcher/delayed` va agent xabari BIR
XIL raqamni ko'rsatishi kerak. Model raqamni qayta hisoblasa, panelda bir
son, xabarda boshqasi chiqadi va dispetcher qaysi biriga ishonishni
bilmaydi. Buni bir marta ko'rgan odam ikkalasiga ham ishonmay qo'yadi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from atil_ai_dispetcher.atil_agent import config

_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Model javobining uzunligi. Uch qatlamning uchalasi ham qisqa javob
#: so'raydi — uzun javob kutish fon oqimini bo'sh ushlab turardi.
NUM_PREDICT = {"orchestrator": 200, "agent": 200, "responder": 320}


class BrainUnavailable(RuntimeError):
    """Model javob bermadi. Chaqiruvchi `fallback` ga o'tadi."""


def _now() -> float:
    return time.perf_counter()


async def _ask(prompt: str, *, role: str, temperature: float) -> str:
    """Modelga bitta savol. Xato bo'lsa `BrainUnavailable`."""
    # Kech import: model o'chiq bo'lsa ham modul yuklansin va agent
    # ishga tushsin. `atil_chatbot` ni import qilishning o'zi ulanish
    # ochmaydi, lekin bog'liqlikni shu yerda ushlab turamiz.
    try:
        from config import DEFAULT_NUM_CTX  # atil_chatbot/config.py
        from ollama_client import ask_llm
    except Exception as exc:  # noqa: BLE001
        raise BrainUnavailable(f"LLM klienti yuklanmadi: {exc}") from exc

    try:
        return await asyncio.wait_for(
            ask_llm(
                prompt,
                {
                    "options": {
                        "temperature": temperature,
                        "num_predict": NUM_PREDICT.get(role, 200),
                        # NUM_CTX CHATBOTNIKI BILAN BIR XIL BO'LISHI SHART:
                        # boshqa qiymat so'ralsa model QAYTA yuklanadi
                        # (o'lchovda 30 s gacha farq). Fon isitgichi modelni
                        # aynan chatbot sozlamasi bilan issiq ushlaydi.
                        "num_ctx": DEFAULT_NUM_CTX,
                    },
                    "think": False,
                },
            ),
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise BrainUnavailable(f"model {config.LLM_TIMEOUT_SECONDS} s ichida javob bermadi") from exc
    except Exception as exc:  # noqa: BLE001 — qaysi xato bo'lishidan qat'i nazar
        raise BrainUnavailable(f"{type(exc).__name__}: {exc}"[:200]) from exc


async def think(
    prompt: str,
    *,
    role: str,
    fallback: T,
    parse: Callable[[Any], T],
    temperature: float = 0.2,
) -> tuple[T, str]:
    """Modeldan JSON so'raydi. Qaytadi: (natija, manba).

    `manba` — `"llm"` yoki `"template"`. Bu ATAYLAB qaytariladi va
    javobda ko'rsatiladi: xabarni model yozganmi yoki kod yozganmi degan
    savolga foydalanuvchi javob topa olishi kerak. Yashirilsa, model bir
    hafta yiqilib yotgan bo'lsa ham hech kim bilmasdi.

    `parse` — model javobini kutilgan tipga aylantiradi. U XATO
    TASHLASHI MUMKIN va bu normal: model noto'g'ri shakl qaytarsa
    `fallback` ishlatiladi. Ya'ni modelning javobi HAR DOIM
    tekshiriladi, hech qachon ko'r-ko'rona ishlatilmaydi.
    """
    if not config.LLM_ENABLED:
        return fallback, "template"

    started = _now()
    try:
        raw = await _ask(prompt, role=role, temperature=temperature)
    except Exception as exc:  # noqa: BLE001 — QAYSI xato bo'lishidan qat'i nazar
        # `BrainUnavailable` emas, `Exception`: bu funksiya modelning
        # butun tizim uchun chidamlilik chegarasi. `_ask` ichida
        # kutilmagan xato chiqsa ham (klient kutubxonasi o'zgardi,
        # sozlama noto'g'ri) agent to'xtamasligi kerak — u shablonga
        # o'tadi va ishlashda davom etadi.
        logger.warning("Agent miyasi javob bermadi (%s): %s", role, str(exc)[:160])
        return fallback, "template"

    try:
        from core.ollama_json import extract_json  # atil_chatbot/core/

        return parse(extract_json(raw)), "llm"
    except Exception as exc:  # noqa: BLE001 — noto'g'ri shakl ham "javob yo'q"
        logger.warning(
            "Agent miyasi kutilmagan shakl qaytardi (%s, %.1f s): %s — javob: %s",
            role, _now() - started, str(exc)[:120], (raw or "")[:160],
        )
        return fallback, "template"


def facts(data: dict[str, Any], *, limit: int | None = None) -> str:
    """Modelga beriladigan faktlar — JSON matn bo'lib.

    Faqat SHU yerda tayyorlanadi, ya'ni model hech qachon xom bazadan
    kelgan qatorni to'g'ridan-to'g'ri ko'rmaydi: chaqiruvchi nimani
    ko'rsatishni o'zi tanlaydi.
    """
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)[: limit or 4000]
