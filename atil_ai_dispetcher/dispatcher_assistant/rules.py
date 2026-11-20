"""Hisob-kitob — sof funksiyalar, bazasiz sinaladi.

Bu yerda ikkita ish bor: yo'ldan chetlanish masofasini o'lchash va
telematikaning `route_points_json` maydonini o'qish.

CHETLANISH MASOFASI NIMA UCHUN KERAK: `deviation_active` bayrog'i
"og'gan" deydi, lekin QANCHA og'ganini aytmaydi. Dispetcher uchun 200
metr bilan 15 kilometr butunlay boshqa vaziyat. Masofa hisoblansa
ro'yxatni og'irligi bo'yicha saralash mumkin.

NUQTADAN CHIZIQQACHA, NUQTADAN NUQTAGACHA EMAS. Marshrut — bu nuqtalar
emas, ular orasidagi KESMALAR. Mashina ikki nuqta o'rtasida ketayotgan
bo'lsa, eng yaqin nuqtagacha bo'lgan masofa katta chiqadi va mashina
yo'ldan chiqib ketgandek ko'rinadi. Shuning uchun har bir kesmagacha
bo'lgan masofa hisoblanadi va eng kichigi olinadi.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

# Haversine boshqa modulda allaqachon bor va bu SOF funksiya — uchinchi
# nusxa yaratishdan ko'ra o'shani chaqirgan ma'qul.
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.geo import haversine_km  # noqa: E402

#: `route_points_json` da koordinata qanday nomlanishi mumkinligi.
#: Jadval hozir bo'sh (0 qator), ya'ni format AMALDA KO'RILMAGAN.
#: Shuning uchun bir nechta keng tarqalgan nom qabul qilinadi va
#: hech biri to'g'ri kelmasa masofa `null` bo'ladi — taxmin qilinmaydi.
_LAT_KEYS = ("lat", "latitude", "y")
_LON_KEYS = ("lon", "lng", "long", "longitude", "x")


def parse_route_points(raw: Any) -> list[tuple[float, float]]:
    """`route_points_json` ni koordinatalar ro'yxatiga aylantiradi.

    Uch xil ko'rinish qabul qilinadi:

        [{"lat": 40.1, "lon": 65.3}, ...]
        [[40.1, 65.3], ...]
        {"points": [...]}

    Tanib bo'lmasa BO'SH ro'yxat qaytadi va chaqiruvchi masofani
    `null` qoldiradi. Formatni taxmin qilib noto'g'ri masofa
    ko'rsatishdan ko'ra, "hisoblanmadi" deyish to'g'riroq.
    """
    if not raw:
        return []
    data = raw
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("route_points_json o'qilmadi — masofa hisoblanmaydi")
            return []

    if isinstance(data, dict):
        for key in ("points", "route_points", "coordinates", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return []

    if not isinstance(data, list):
        return []

    points: list[tuple[float, float]] = []
    for item in data:
        pair = _coerce_point(item)
        if pair is not None:
            points.append(pair)
    return points


def _coerce_point(item: Any) -> tuple[float, float] | None:
    if isinstance(item, dict):
        latitude = _first_number(item, _LAT_KEYS)
        longitude = _first_number(item, _LON_KEYS)
        if latitude is None or longitude is None:
            return None
        return latitude, longitude
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        try:
            return float(item[0]), float(item[1])
        except (TypeError, ValueError):
            return None
    return None


def _first_number(source: dict[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        if key in source:
            try:
                return float(source[key])
            except (TypeError, ValueError):
                return None
    return None


def point_to_segment_km(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Nuqtadan kesmagacha bo'lgan eng qisqa masofa, km.

    Kichik masofalarda yer sharini tekislik deb hisoblash yetarli:
    marshrutdagi ikki nuqta orasi odatda o'nlab kilometr, chetlanish esa
    yuzlab metr. Shu masshtabda xato bir metrdan kam.

    Uzunlik daraja emas, KILOMETRDA o'lchanadi: uzunlik daraja kenglikka
    qarab siqiladi (`cos(lat)`), aks holda sharq-g'arb yo'nalishdagi
    masofa 1.3 barobar kattaroq chiqardi.
    """
    lat_km = 111.32                       # 1 daraja kenglik ~ 111.32 km
    lon_km = 111.32 * math.cos(math.radians(point[0]))

    px, py = point[1] * lon_km, point[0] * lat_km
    ax, ay = start[1] * lon_km, start[0] * lat_km
    bx, by = end[1] * lon_km, end[0] * lat_km

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)

    # Nuqtaning kesmaga proyeksiyasi; [0, 1] oralig'iga qisiladi, ya'ni
    # kesmadan tashqariga chiqmaydi.
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_from_route_meters(
    latitude: float | None,
    longitude: float | None,
    points: Sequence[tuple[float, float]],
) -> float | None:
    """Mashinadan rejadagi yo'lgacha bo'lgan eng qisqa masofa, metr.

    Nuqta yoki marshrut bo'lmasa `None` — NOL EMAS. Nol "yo'lda ketyapti"
    degan ma'noni berardi, aslida esa "o'lchab bo'lmadi".
    """
    if latitude is None or longitude is None or len(points) == 0:
        return None
    point = (float(latitude), float(longitude))

    if len(points) == 1:
        return haversine_km(point[0], point[1], points[0][0], points[0][1]) * 1000.0

    best = min(
        point_to_segment_km(point, points[i], points[i + 1])
        for i in range(len(points) - 1)
    )
    return best * 1000.0


def minutes_between(later: Any, earlier: Any) -> float | None:
    """Ikki vaqt orasidagi daqiqa. Biri yo'q bo'lsa `None`."""
    if later is None or earlier is None:
        return None
    try:
        a = later.replace(tzinfo=None) if getattr(later, "tzinfo", None) else later
        b = earlier.replace(tzinfo=None) if getattr(earlier, "tzinfo", None) else earlier
        return (a - b).total_seconds() / 60.0
    except (AttributeError, TypeError):
        return None


def worst_label(items: Iterable[dict[str, Any]], key: str, template: str) -> str | None:
    """Ro'yxatdagi eng og'ir qatorni qisqa matnga aylantiradi.

    Ro'yxat allaqachon saralangan, shuning uchun birinchi qator olinadi —
    qayta saralanmaydi.
    """
    for item in items:
        value = item.get(key)
        if value is None:
            continue
        try:
            return template.format(**item)
        except (KeyError, IndexError, ValueError):
            return None
    return None
