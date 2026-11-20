"""Dispetcher yordamchisi sozlamalari.

MEYOR O'YLAB TOPILMAYDI — bu modulda ayniqsa muhim, chunki "kechikish"
va "uzoq to'xtash" degan tushunchalar meyorga o'xshab ko'rinadi. Aslida
ularning hech biri kodda qattiq yozilmagan:

    kechikish      rejadagi vaqt bilan HOZIRGI vaqtni solishtirish —
                   `scheduled_arrival_at < now()`. Bu solishtirish,
                   chegara emas.
    yo'ldan og'ish `vehicle_telemetry_state.deviation_threshold_meters`
                   BAZADAN olinadi. Telematika xizmati o'zi belgilaydi.
    bekor turish   "uzoq" degan chegara YO'Q. Ro'yxat davomiylik
                   bo'yicha saralanadi, eng uzog'i tepada. Kesish
                   kerak bo'lsa chaqiruvchi `min_minutes` beradi.
    hujjat muddati muddat o'tganmi yoki yo'qmi — sananing o'zi.
                   "30 kun qolgani xavfli" degan raqam yo'q; oyna
                   so'rovda `days` bilan beriladi.

Ya'ni bu modulda faqat CHEGARALAR EMAS, RESURS chegaralari bor:
nechta qator o'qiladi va nechtasi qaytadi.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ------------------------------------------------------------ Resurs chegarasi
#: Javobda qaytadigan qatorlar soni (so'rovdagi `limit` bekor qiladi).
DEFAULT_LIMIT = _int("DA_DEFAULT_LIMIT", 50)
MAX_LIMIT = _int("DA_MAX_LIMIT", 500)

#: Bitta so'rovda bazadan o'qiladigan eng ko'p qator. Bu tanlash
#: chegarasi emas — bazani himoya qiladi. Chegaraga yetilsa javobning
#: `data_quality.notes` ida ochiq yoziladi.
MAX_ROWS = _int("DA_MAX_ROWS", 5000)

# ----------------------------------------------------------------- Holatlar
#: Reys hali tugamagan hisoblanadigan holatlar — kechikish shularda
#: qaraladi. COMPLETED, CANCELLED va INTERRUPTED kirmaydi: ular tugagan.
ACTIVE_TRIP_STATUSES = (
    "PLANNED", "ASSIGNED", "STARTED", "ARRIVED_AT_POINT", "LOADED", "UNLOADED",
)

#: Yo'l varaqasi ochiq hisoblanadigan holatlar.
OPEN_WAYBILL_STATUSES = ("ISSUED", "IN_USE")

# ----------------------------------------------------------------- LLM
#: Ro'yxatni ARIFMETIKA quradi, LLM esa uni bir xatboshi qilib
#: xulosalaydi: nima eng shoshilinch, nimaga e'tibor berish kerak.
#: Ro'yxatga TEGMAYDI.
LLM_ANALYZE = _flag("DA_LLM_ANALYZE", True)

#: Tahlilga nechta yuqori qator yuboriladi. Ro'yxat allaqachon
#: saralangani uchun birinchilar — eng muhimlari.
LLM_ANALYZE_LIMIT = _int("DA_LLM_ANALYZE_LIMIT", 10)
