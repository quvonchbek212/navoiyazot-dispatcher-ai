"""Tanlash sozlamalari.

OG'IRLIKLAR TENG QILIB QO'YILGAN — bu ataylab shunday. Qaysi mezon qanchalik
muhimligini bazadagi hech narsa aytmaydi, shuning uchun "sig'im 30%, masofa
25%" degan raqamlarni o'ylab topish o'rniga hammasi teng olindi. Real
og'irliklar ish tajribasidan chiqadi va `.env` dan sozlanadi — kod
o'zgarmaydi.

MUHIM: og'irlik NOL EMAS. Ma'lumoti yo'q mezon `null` bo'ladi va og'irliklar
qolgan mezonlar ustida qayta taqsimlanadi (`ranker.py`). Ya'ni sig'imi
noma'lum mashina "sig'imi yomon" deb baholanmaydi.
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


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


# ------------------------------------------------------------------ Mezonlar
#: Olti mezon. Kalitlar `rules.py` dagi nomlar bilan bir xil.
CRITERIA = ("capacity", "distance", "documents", "shift", "skill", "technical")

#: O'zbekcha nomlari — javobda va LLM promptida ishlatiladi.
CRITERION_LABEL = {
    "capacity": "Sig'im",
    "distance": "Masofa",
    "documents": "Hujjat",
    "shift": "Smena",
    "skill": "Malaka",
    "technical": "Texnik holat",
}

#: Har bir mezon og'irligi. Sukut bo'yicha teng (1/6 ≈ 0.1667).
#: `.env` da VS_WEIGHT_CAPACITY=0.30 ko'rinishida o'zgartiriladi.
WEIGHTS = {
    name: _float(f"VS_WEIGHT_{name.upper()}", 1.0 / len(CRITERIA))
    for name in CRITERIA
}

#: Mashinaga oldindan biriktirilgan haydovchi juftligiga qo'shiladigan ustama.
#: Bu MEZON EMAS — bazada allaqachon mavjud bo'lgan ish tartibi
#: (`vehicle_assigned_drivers`). Teng ballda biriktirilgan juftlik oldinga
#: chiqadi, xolos. Nolga qo'yilsa butunlay hisobga olinmaydi.
ASSIGNED_PAIR_BONUS = _float("VS_ASSIGNED_PAIR_BONUS", 0.05)

# ------------------------------------------------------------ Resurs himoyasi
#: Bitta so'rovda bazadan o'qiladigan eng ko'p mashina/haydovchi.
#: Bu tanlash chegarasi emas — bazani va xotirani himoya qiladi.
#: Chegaraga yetilsa javobning `data_quality.notes` ida ochiq yoziladi.
MAX_VEHICLES = _int("VS_MAX_VEHICLES", 2000)
MAX_DRIVERS = _int("VS_MAX_DRIVERS", 2000)

#: Javobda qaytadigan juftliklar soni (so'rovdagi `limit` bilan bekor qilinadi).
DEFAULT_LIMIT = _int("VS_DEFAULT_LIMIT", 10)
MAX_LIMIT = _int("VS_MAX_LIMIT", 100)

#: Baholanadigan eng ko'p juftlik. Juftliklar soni mashina x haydovchi
#: bo'lgani uchun ko'payib ketishi mumkin; chegaraga yetilsa nomzodlar
#: o'z ballari bo'yicha qisqartiriladi va bu `data_quality.notes` da
#: OCHIQ yoziladi — natija jimgina qirqilib qolmaydi.
MAX_PAIRS = _int("VS_MAX_PAIRS", 20000)

#: Haydovchi xavfsizlik tarixi shuncha kun orqaga qaraladi
#: (`speed_violation`, `incident`, `vehicle_accident`).
#: Bu anomaliya chegarasi emas — "yaqin o'tmish" oynasi.
HISTORY_DAYS = _int("VS_HISTORY_DAYS", 365)

# ----------------------------------------------------------------- LLM tahlili
# Reytingni ARIFMETIKA quradi, LLM esa yuqori variantlarni TAHLIL qiladi:
# taqqoslaydi, xavfni ko'rsatadi, tavsiya beradi. Ballarga tegmaydi —
# shuning uchun bir xil so'rovga bir xil tartib chiqaveradi.
#
# TAHLIL DOIM YOZILADI, o'chirgich yo'q. Ilgari `?analyze=false` va
# `VS_LLM_ANALYZE=false` bilan uni bekor qilish mumkin edi; ikkalasi ham
# olib tashlandi, chunki javob har doim izoh bilan to'liq kelishi kerak.
# NARXI: bitta chaqiruv, chatbotda o'lchanganda 14-67 s (model qayta
# yuklansa). LLM javob bermasa SHABLONGA TUSHILMAYDI — endpoint 503
# qaytaradi va frontend "keyinroq urinib ko'ring" deydi.

#: Tahlilga nechta yuqori variant yuboriladi. Ro'yxat ball bo'yicha
#: saralangani uchun birinchilar — dispetcher aslida tanlaydiganlari.
#: 5 emas, 3: prompt qancha uzun bo'lsa LLM shuncha uzun javob yozadi,
#: javob esa 4.6-9.9 token/s tezlikda chiqadi.
LLM_ANALYZE_LIMIT = _int("VS_LLM_ANALYZE_LIMIT", 3)
