"""Model parametrlarini BAZADAN o'lchash.

Bu fayl modulning eng muhim g'oyasi. Marshrut optimizatsiyasi uch raqamga
tayanadi va odatda ular kodga qattiq yozib qo'yiladi:

    yo'l koeffitsienti  "to'g'ri chiziqni 1.3 ga ko'paytiramiz"
    o'rtacha tezlik     "shaharlararo 60 km/soat deb olamiz"
    xizmat vaqti        "yuklash 30 daqiqa"

Bu uchala raqam ham TAXMIN bo'lardi va reja shu taxmin ustiga qurilardi.
Shuning uchun ular bu yerda ATIL ning O'Z ma'lumotidan o'lchanadi:

    yo'l koeffitsienti  route_point: bazadagi yo'l masofasi / haversine
    o'rtacha tezlik     trip: haqiqiy masofa / haqiqiy davomiylik
                        (yetmasa route_point ning reja raqamlari)
    xizmat vaqti        trip_event: "yetib bordi" -> "yukladi/tushirdi"

O'LCHOV YETMASA QIYMAT NOMA'LUM BO'LADI. Nolga aylanmaydi, taxminga ham
aylanmaydi. Noma'lum tezlik butun vaqt hisobini o'chiradi va bu javobda
`calibration.time_aware=false` bo'lib ko'rinadi.

MEDIANA, O'RTACHA EMAS. Bitta xato yozuv (masofa 5000 km, davomiyligi 3
daqiqa) o'rtachani buzadi, medianani deyarli buzmaydi. Logistika
ma'lumotida bunday yozuvlar doim bo'ladi.
"""

from __future__ import annotations

import logging
from statistics import median
from typing import Any, Iterable

from atil_ai_dispetcher.Marshrut_optimizatsiyasi import config, queries, texts
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.texts import t
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.geo import haversine_km

logger = logging.getLogger(__name__)

#: Ishonchsiz o'lchovlar shu oraliqdan tashqarida bo'lsa tashlanadi.
#: Bu ANOMALIYA CHEGARASI EMAS — fizik imkoniyat chegarasi: yo'l to'g'ri
#: chiziqdan qisqa bo'la olmaydi (koeffitsient < 1) va 5 barobardan uzun
#: yo'l koordinata xatosini bildiradi.
_ROAD_FACTOR_RANGE = (1.0, 5.0)

#: Tezlik: 1 km/soat dan sekin ham, 120 km/soat dan tez ham yuk mashinasi
#: yurmaydi — bunday qator vaqt ustunidagi xatodan kelib chiqadi.
_SPEED_RANGE = (1.0, 120.0)

#: Xizmat vaqti: 0 dan katta va bir sutkadan kam bo'lishi kerak.
_SERVICE_RANGE = (0.0, 1440.0)


class Calibration:
    """O'lchangan parametrlar va ular qayerdan olingani.

    Har bir qiymat yonida MANBASI va O'LCHOV SONI turadi — javobda
    shundayligicha ko'rinadi, ya'ni raqamning kelib chiqishini
    dispetcher ham, dasturchi ham tekshira oladi.
    """

    def __init__(self) -> None:
        self.road_factor: float | None = None
        self.road_factor_source: str = "unknown"
        self.road_factor_samples: int = 0

        self.average_speed_kph: float | None = None
        self.speed_source: str = "unknown"
        self.speed_samples: int = 0

        self.service_minutes: float | None = None
        self.service_source: str = "unknown"
        self.service_samples: int = 0

        self.distance_source: str = "haversine"
        self.notes: list[str] = []

    @property
    def time_aware(self) -> bool:
        """Vaqtni hisoblash mumkinmi.

        Tezlik noma'lum bo'lsa `False`: bunda vaqt oynasi, smena chegarasi
        va xizmat vaqti TEKSHIRILMAYDI, reja faqat masofa bo'yicha
        quriladi. Bu holat javobda ochiq yoziladi.
        """
        return bool(self.average_speed_kph and self.average_speed_kph > 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "road_factor": _round(self.road_factor, 3),
            "road_factor_source": self.road_factor_source,
            "road_factor_samples": self.road_factor_samples,
            "average_speed_kph": _round(self.average_speed_kph, 1),
            "speed_source": self.speed_source,
            "speed_samples": self.speed_samples,
            "service_minutes": _round(self.service_minutes, 1),
            "service_source": self.service_source,
            "service_samples": self.service_samples,
            "distance_source": self.distance_source,
            "time_aware": self.time_aware,
            "notes": self.notes,
        }


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _clean(values: Iterable[float], low: float, high: float) -> list[float]:
    return [v for v in values if v is not None and low <= v <= high]


# --------------------------------------------------------- Alohida o'lchovlar


def measure_road_factor(rows: list[dict[str, Any]]) -> tuple[float | None, int]:
    """Bazadagi yo'l masofasini to'g'ri chiziqqa nisbatan o'lchaydi."""
    ratios: list[float] = []
    for row in rows:
        distance = queries.to_float(row.get("distance_km"))
        straight = _straight_km(row)
        if not distance or not straight or straight <= 0:
            continue
        ratios.append(distance / straight)

    ratios = _clean(ratios, *_ROAD_FACTOR_RANGE)
    if len(ratios) < config.MIN_CALIBRATION_SAMPLES:
        return None, len(ratios)
    return float(median(ratios)), len(ratios)


def _straight_km(row: dict[str, Any]) -> float | None:
    lat1 = queries.to_float(row.get("from_lat"))
    lon1 = queries.to_float(row.get("from_lon"))
    lat2 = queries.to_float(row.get("to_lat"))
    lon2 = queries.to_float(row.get("to_lon"))
    if None in (lat1, lon1, lat2, lon2):
        return None
    return haversine_km(lat1, lon1, lat2, lon2)


def measure_speed(samples: dict[str, list[dict[str, Any]]]) -> tuple[float | None, str, int]:
    """O'rtacha YO'L tezligini o'lchaydi.

    TARTIB: `route_point` BIRINCHI. Uning
    `drive_duration_from_previous_minutes` ustuni nomiga ko'ra YO'L
    vaqti, ya'ni bizga aynan shu kerak.

    `trip` esa ikkinchi va u BOSHQA NARSANI o'lchaydi:
    `actual_arrival_at - actual_departure_at` reysning TO'LIQ vaqti —
    jo'nash, nuqtada ish, qaytish. Modul nuqtadagi xizmat vaqtini
    ALOHIDA qo'shgani uchun bu manbadan olingan tezlik o'sha vaqtni ikki
    marta hisoblaydi va reja pessimistik chiqadi. (05.09.2026 o'lchovi:
    mediana 25 km / 240 daqiqa = 6.2 km/soat — bu yo'l tezligi emas.)

    Shuning uchun `trip` butunlay olib tashlanmadi, lekin ZAXIRAGA
    tushirildi va ishlatilganda javobda izoh yoziladi.
    """
    for source in ("route_point", "trip"):
        speeds: list[float] = []
        for row in samples.get(source) or []:
            distance = queries.to_float(row.get("distance_km"))
            minutes = queries.to_float(row.get("minutes"))
            if not distance or not minutes or minutes <= 0:
                continue
            speeds.append(distance / (minutes / 60.0))
        speeds = _clean(speeds, *_SPEED_RANGE)
        if len(speeds) >= config.MIN_CALIBRATION_SAMPLES:
            return float(median(speeds)), source, len(speeds)

    # Yetarli o'lchov topilmadi — nechta bo'lgani baribir aytiladi.
    counted = sum(len(rows) for rows in samples.values())
    return None, "unknown", counted


def measure_service_minutes(rows: list[dict[str, Any]]) -> tuple[float | None, int]:
    """Nuqtadagi yuklash/tushirish vaqtini o'lchaydi."""
    minutes = _clean(
        (queries.to_float(r.get("minutes")) for r in rows), *_SERVICE_RANGE
    )
    if len(minutes) < config.MIN_CALIBRATION_SAMPLES:
        return None, len(minutes)
    return float(median(minutes)), len(minutes)


# ------------------------------------------------------------------- Yig'ish


def calibrate(
    *,
    road_factor_override: float | None = None,
    speed_override: float | None = None,
    service_override: float | None = None,
    read_database: bool = True,
    lang: str = texts.DEFAULT_LANG,
) -> Calibration:
    """Uch parametrni yig'adi: so'rov -> baza -> `.env` -> noma'lum.

    TARTIB MUHIM. So'rovda berilgan qiymat eng ustun (dispetcher aniq
    biladi), keyin bazadan o'lchangan, keyin `.env` dagi zaxira. Hech
    biri bo'lmasa qiymat NOMA'LUM bo'lib qoladi — bu ham to'g'ri javob,
    "taxminan 60" dan yaxshiroq.
    """
    cal = Calibration()

    # --------------------------------------------------------- Yo'l koeffitsienti
    if road_factor_override and road_factor_override > 0:
        cal.road_factor = float(road_factor_override)
        cal.road_factor_source = "request"
    elif read_database:
        try:
            rows = queries.fetch_road_factor_samples()
            value, count = measure_road_factor(rows)
            cal.road_factor_samples = count
            if value is not None:
                cal.road_factor = value
                cal.road_factor_source = "route_point"
            else:
                cal.notes.append(t(
                    lang, "cal.road_not_measured",
                    count=count, need=config.MIN_CALIBRATION_SAMPLES))
        except queries.PlanningDataError as exc:
            cal.notes.append(t(lang, "cal.road_error", error=exc))

    if cal.road_factor is None:
        if config.FALLBACK_ROAD_FACTOR > 0:
            cal.road_factor = config.FALLBACK_ROAD_FACTOR
            cal.road_factor_source = "env"
        else:
            # 1.0 — TAXMIN EMAS, ochiq kelishuv: masofa to'g'ri chiziq
            # bo'yicha o'lchanadi. Haqiqiy yo'l undan UZUN, ya'ni reja
            # optimistik. Buni yashirmaymiz.
            cal.road_factor = 1.0
            cal.road_factor_source = "straight_line"
            cal.notes.append(t(lang, "cal.straight_line"))

    # ------------------------------------------------------------------ Tezlik
    if speed_override and speed_override > 0:
        cal.average_speed_kph = float(speed_override)
        cal.speed_source = "request"
    elif read_database:
        try:
            samples = queries.fetch_speed_samples(config.CALIBRATION_DAYS)
            value, source, count = measure_speed(samples)
            cal.speed_samples = count
            if value is not None:
                cal.average_speed_kph = value
                cal.speed_source = source
                if source == "trip":
                    # Manba reysning to'liq vaqtini o'lchaydi — buni
                    # aytmaslik javobni yolg'on qilib qo'yardi.
                    cal.notes.append(t(lang, "cal.speed_from_trip"))
            else:
                cal.notes.append(t(
                    lang, "cal.speed_not_measured",
                    count=count, need=config.MIN_CALIBRATION_SAMPLES))
        except queries.PlanningDataError as exc:
            cal.notes.append(t(lang, "cal.speed_error", error=exc))

    if cal.average_speed_kph is None and config.FALLBACK_SPEED_KPH > 0:
        cal.average_speed_kph = config.FALLBACK_SPEED_KPH
        cal.speed_source = "env"

    if cal.average_speed_kph is None:
        cal.notes.append(t(lang, "cal.speed_unknown"))

    # -------------------------------------------------------------- Xizmat vaqti
    if service_override is not None and service_override >= 0:
        cal.service_minutes = float(service_override)
        cal.service_source = "request"
    elif read_database:
        try:
            rows = queries.fetch_service_time_samples(config.CALIBRATION_DAYS)
            value, count = measure_service_minutes(rows)
            cal.service_samples = count
            if value is not None:
                cal.service_minutes = value
                cal.service_source = "trip_event"
            else:
                cal.notes.append(t(
                    lang, "cal.service_not_measured",
                    count=count, need=config.MIN_CALIBRATION_SAMPLES))
        except queries.PlanningDataError as exc:
            cal.notes.append(t(lang, "cal.service_error", error=exc))

    if cal.service_minutes is None and config.FALLBACK_SERVICE_MINUTES > 0:
        cal.service_minutes = config.FALLBACK_SERVICE_MINUTES
        cal.service_source = "env"

    if cal.service_minutes is None and cal.time_aware:
        cal.notes.append(t(lang, "cal.service_optimistic"))

    return cal
