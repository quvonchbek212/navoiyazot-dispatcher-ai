"""Marshrut optimizatsiyasi sozlamalari.

MEYOR O'YLAB TOPILMAYDI. Bu modulda "o'rtacha tezlik 40 km/soat", "yuklash
20 daqiqa", "yo'l koeffitsienti 1.3" degan raqamlar QATTIQ YOZILMAGAN.
Ularning hammasi bazadan O'LCHANADI (`calibration.py`):

    yo'l koeffitsienti  <- route_point.distance_from_previous_km / haversine
    o'rtacha tezlik     <- trip (actual_distance_km / haqiqiy davomiylik)
                           va route_point (masofa / drive_duration)
    xizmat vaqti        <- trip_event (ARRIVED_AT_POINT -> LOADED/UNLOADED)

Bazada o'lchash uchun ma'lumot yetmasa qiymat NOMA'LUM bo'lib qoladi
(`None`), NOLGA aylanmaydi. Noma'lum tezlik = vaqt hisoblanmaydi = vaqt
oynasi tekshirilmaydi, va bu javobning `data_quality.notes` ida OCHIQ
yoziladi. Pastdagi `RO_FALLBACK_*` lar sukut bo'yicha "noma'lum" (0) —
dispetcher xohlasa `.env` da yoki so'rov parametrida o'zi beradi.

25.08.2026 holatiga bazada: route_point 114 qator (masofasi bor — 14 ta,
davomiyligi bor — 50 ta), tugagan reys 33 ta, telematics_event 0 ta.
Ya'ni kalibrovka bugun ishlamaydi, ma'lumot to'planishi bilan o'zi
ishlay boshlaydi — kod o'zgarmaydi.
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


def _text(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# ------------------------------------------------------------------ Maqsad
#: Nimani minimallashtiramiz.
#:   distance — jami masofa (km)
#:   duration — jami vaqt (yo'l + kutish + xizmat, daqiqa)
#:   balanced — ikkalasining yig'indisi
#: Vaqt faqat TEZLIK MA'LUM bo'lganda hisoblanadi; noma'lum bo'lsa modul
#: o'zi `distance` ga o'tadi va buni javobda yozadi.
OBJECTIVES = ("distance", "duration", "balanced")
DEFAULT_OBJECTIVE = _text("RO_OBJECTIVE", "balanced")
if DEFAULT_OBJECTIVE not in OBJECTIVES:
    DEFAULT_OBJECTIVE = "balanced"

#: `balanced` da masofa va vaqtning nisbati. Teng — chunki qaysi biri
#: qimmatroq ekanini bazadagi hech narsa aytmaydi (`tariff` da 1 qator bor).
#: Yoqilg'i va tarif to'ldirilganda bu yerda emas, `.env` da o'zgartiriladi.
BALANCE_DISTANCE = _float("RO_BALANCE_DISTANCE", 0.5)
BALANCE_DURATION = _float("RO_BALANCE_DURATION", 0.5)

#: Vaqt oynasidan kechikishning narxi: 1 daqiqa kechikish necha daqiqa
#: yo'lga teng. Bu MODEL parametri, meyor emas — va u faqat
#: `respect_time_windows=false` da ishlaydi (aks holda kechikish umuman
#: mumkin emas, variant rad etiladi).
LATENESS_PENALTY = _float("RO_LATENESS_PENALTY", 1.0)

#: Yangi mashina ochishning qo'shimcha narxi (daqiqada). 0 — mashina soni
#: alohida jazolanmaydi, lekin u BARIBIR kamayadi: yangi mashina ochish
#: garajdan borib-kelish vaqtini qo'shadi, ya'ni qimmatga tushadi.
#: Real qiymat (mashina kunlik xarajati) bazada yo'q, shuning uchun
#: o'ylab topilmadi.
VEHICLE_FIXED_MINUTES = _float("RO_VEHICLE_FIXED_MINUTES", 0.0)

# ------------------------------------------------------------- Kalibrovka
#: Kalibrovka uchun necha kun orqaga qaraladi.
CALIBRATION_DAYS = _int("RO_CALIBRATION_DAYS", 365)

#: Kalibrovka ishonchli deb qabul qilinadigan eng kam o'lchov soni.
#: Bu anomaliya chegarasi emas — STATISTIK himoya: 2 ta o'lchovdan
#: chiqarilgan "o'rtacha tezlik" tasodifiy son bo'ladi. Yetmasa qiymat
#: noma'lum qoladi va javobda shunday yoziladi.
MIN_CALIBRATION_SAMPLES = _int("RO_MIN_CALIBRATION_SAMPLES", 10)

#: Kalibrovka ishlamaganda ishlatiladigan zaxira qiymatlar.
#: SUKUT BO'YICHA 0 = NOMA'LUM. Nol "tezlik nol" degani emas — "o'lchov
#: yo'q" degani; modul u holda vaqtga tegishli hamma narsani o'tkazib
#: yuboradi va buni javobda yozadi.
FALLBACK_ROAD_FACTOR = _float("RO_FALLBACK_ROAD_FACTOR", 0.0)
FALLBACK_SPEED_KPH = _float("RO_FALLBACK_SPEED_KPH", 0.0)
FALLBACK_SERVICE_MINUTES = _float("RO_FALLBACK_SERVICE_MINUTES", 0.0)

# --------------------------------------------------------- Masofa manbai
#: OSRM (yoki mos keluvchi) yo'l xizmatining `table` endpointi.
#: Berilsa HAQIQIY yo'l masofasi olinadi; berilmasa to'g'ri chiziq
#: (haversine) x kalibrlangan yo'l koeffitsienti ishlatiladi.
#: Masalan: http://osrm:5000
OSRM_URL = _text("RO_OSRM_URL")
OSRM_TIMEOUT = _float("RO_OSRM_TIMEOUT", 10.0)

#: OSRM bitta so'rovda ko'tara oladigan eng ko'p nuqta. Undan oshsa
#: to'g'ri chiziqqa qaytiladi (matritsani bo'lib yuborish OSRM ni
#: cho'ktirmaslik uchun qilinmaydi).
OSRM_MAX_POINTS = _int("RO_OSRM_MAX_POINTS", 100)

# ------------------------------------------------------------ Cheklovlar
#: Bitta rejalashtirishga kiradigan eng ko'p ariza va mashina.
#: Bu tanlash chegarasi emas — bazani va CPU ni himoya qiladi.
#: Chegaraga yetilsa `data_quality.notes` da ochiq yoziladi.
MAX_REQUESTS = _int("RO_MAX_REQUESTS", 200)
MAX_VEHICLES = _int("RO_MAX_VEHICLES", 100)

#: Optimizatsiyaga ajratilgan vaqt. Yaxshilash sikli shu vaqt tugaganda
#: to'xtaydi va O'SHA PAYTDAGI eng yaxshi yechim qaytadi — javob hech
#: qachon osilib qolmaydi.
TIME_BUDGET_SECONDS = _float("RO_TIME_BUDGET_SECONDS", 5.0)

#: Yaxshilash sikllarining eng ko'p soni (vaqt byudjetidan qat'i nazar).
MAX_IMPROVE_ROUNDS = _int("RO_MAX_IMPROVE_ROUNDS", 30)

#: Arizani joylashtirishda bitta nuqta uchun ko'rib chiqiladigan eng ko'p
#: o'rin. Marshrutga nuqta qo'yish variantlari soni marshrut uzunligiga
#: KVADRATIK bog'liq: 50 to'xtashli marshrutda 1250 ta variant, har biri
#: to'liq baholanadi. O'lchov (25.08.2026, 50 ariza x 15 mashina):
#:     qisqartirishsiz -> 5 s byudjet tugadi, 50 tadan 42 tasi joylandi
#:     8 ta o'rin      -> 0.6 s, hammasi joylandi
#: Uzoq o'rin hech qachon eng arzon bo'lmaydi (u yerga borib qaytish
#: kerak), shuning uchun ularni saralab tashlash natijani deyarli
#: o'zgartirmaydi. 0 qilinsa qisqartirish o'chadi.
INSERTION_CANDIDATES = _int("RO_INSERTION_CANDIDATES", 8)

#: Bazadan olinadigan arizalarning sukut bo'yicha holatlari — ya'ni
#: "rejalashtirishni kutayotganlar". `ASSIGNED` va `IN_PROGRESS` kirmaydi:
#: ular allaqachon mashinaga berilgan.
DEFAULT_REQUEST_STATUSES = tuple(
    s.strip() for s in _text(
        "RO_REQUEST_STATUSES", "APPROVED,READY_FOR_PLANNING"
    ).split(",") if s.strip()
)

#: Ariza muhimligi tartibi — `transport_request.priority` dagi qiymatlar.
#: Bu ball emas, JOYLASHTIRISH TARTIBI: muhimroq ariza avval joylanadi,
#: chunki oxirida joylanganiga o'rin qolmasligi mumkin.
PRIORITY_ORDER = {"CRITICAL": 0, "URGENT": 1, "HIGH": 2, "NORMAL": 3}

# ----------------------------------------------------------- LLM tahlili
# Rejani ARIFMETIKA quradi, LLM esa uni TUSHUNTIRADI: nima uchun shu
# guruhlash, qayerda xavf bor, dispetcher nimaga e'tibor bersin.
# LLM rejaga TEGMAYDI — bir xil so'rovga bir xil reja chiqaveradi.
#
# TAHLIL DOIM YOZILADI, o'chirgich yo'q. Ilgari `analyze=false` va
# `RO_LLM_ANALYZE=false` bilan uni bekor qilish mumkin edi; ikkalasi ham
# olib tashlandi. LLM javob bermasa endpoint 503 qaytaradi — shablonga
# tushilmaydi.

#: Tahlilga nechta marshrut yuboriladi. Prompt qancha uzun bo'lsa javob
#: shuncha sekin (o'lchovda 4.6-9.9 token/s).
LLM_ANALYZE_LIMIT = _int("RO_LLM_ANALYZE_LIMIT", 3)
