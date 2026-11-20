"""Masofa va vaqt matritsasi.

IKKI MANBA, BITTA INTERFEYS:

  1. OSRM (`RO_OSRM_URL` berilgan bo'lsa) — HAQIQIY yo'l masofasi va
     haqiqiy yo'l vaqti. Eng to'g'ri variant.
  2. Haversine x yo'l koeffitsienti — to'g'ri chiziqdagi masofa
     bazadan O'LCHANGAN koeffitsientga ko'paytiriladi
     (`calibration.road_factor`).

OSRM ishlamay qolsa (o'chiq, sekin, xato qaytardi) modul TO'XTAMAYDI —
haversine ga qaytadi va buni `notes` da ochiq yozadi. Yo'l xizmatining
uzilishi rejalashtirishni to'xtatmasligi kerak.

NIMA UCHUN MATRITSA OLDINDAN QURILADI: optimizatsiya davomida bir juft
nuqta orasidagi masofa minglab marta so'raladi (joylashtirish, ko'chirish,
almashtirish). Har safar qayta hisoblash — bekorga ketgan vaqt.

KOORDINATASIZ NUQTA — XATO EMAS, NOMA'LUM. Masofasi `None` bo'ladi va
bunday nuqtali ariza rejaga tushmaydi: `unassigned` da `NO_COORDINATES`
sababi bilan qaytadi. "Koordinatasi yo'q" ni "masofa nol" deb hisoblash
butun rejani buzadi.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki nuqta orasidagi to'g'ri chiziqli masofa, km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class Matrix:
    """Nuqtalar orasidagi masofa (km) va yo'l vaqti (daqiqa).

    Nuqtalar KOORDINATA bo'yicha birlashtiriladi: bir xil joyga borgan
    ikki ariza matritsada bitta tugun bo'ladi. Bu matritsani kichraytiradi
    va "o'ziga o'zi 0 km" degan to'g'ri natijani beradi.
    """

    def __init__(
        self,
        *,
        road_factor: float,
        speed_kph: float | None,
        source: str = "haversine",
    ) -> None:
        self.road_factor = road_factor
        self.speed_kph = speed_kph if speed_kph and speed_kph > 0 else None
        self.source = source
        self.notes: list[str] = []
        self._index: dict[tuple[float, float], int] = {}
        self._points: list[tuple[float, float]] = []
        self._km: list[list[float]] = []
        self._minutes: list[list[float]] | None = None

    # ------------------------------------------------------------- Qurish

    def node(self, lat: float | None, lon: float | None) -> int | None:
        """Koordinatani tugun raqamiga aylantiradi. Koordinata yo'q -> `None`."""
        if lat is None or lon is None:
            return None
        key = (round(float(lat), 6), round(float(lon), 6))
        if key not in self._index:
            self._index[key] = len(self._points)
            self._points.append(key)
        return self._index[key]

    def build(self) -> None:
        """Matritsani to'ldiradi. Barcha tugunlar qo'shilgandan keyin chaqiriladi."""
        n = len(self._points)
        self._km = [[0.0] * n for _ in range(n)]
        for i in range(n):
            lat1, lon1 = self._points[i]
            for j in range(i + 1, n):
                lat2, lon2 = self._points[j]
                km = haversine_km(lat1, lon1, lat2, lon2) * self.road_factor
                self._km[i][j] = km
                self._km[j][i] = km

    def apply_osrm(self, base_url: str, timeout: float, max_points: int) -> bool:
        """Matritsani OSRM dan olingan haqiqiy yo'l qiymatlari bilan almashtiradi.

        Muvaffaqiyatli bo'lsa `True`. Har qanday muammoda `False` — chaqiruvchi
        haversine matritsasi bilan davom etadi.
        """
        n = len(self._points)
        if n < 2:
            return False
        if n > max_points:
            self.notes.append(
                f"OSRM ishlatilmadi: {n} ta nuqta, chegara {max_points} "
                f"(`RO_OSRM_MAX_POINTS`) — to'g'ri chiziqqa qaytildi"
            )
            return False

        # Kech import: OSRM ishlatilmasa httpx umuman kerak emas.
        import httpx

        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in self._points)
        url = f"{base_url.rstrip('/')}/table/v1/driving/{coords}"
        try:
            response = httpx.get(
                url,
                params={"annotations": "distance,duration"},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 — yo'l xizmati rejani to'xtatmaydi
            logger.warning("OSRM javob bermadi (%s) — haversine ishlatiladi", str(exc)[:160])
            self.notes.append(
                f"OSRM javob bermadi ({type(exc).__name__}) — masofa to'g'ri chiziq bo'yicha"
            )
            return False

        distances = data.get("distances")
        durations = data.get("durations")
        if not distances or len(distances) != n:
            self.notes.append("OSRM matritsasi to'liq emas — to'g'ri chiziq ishlatildi")
            return False

        self._km = [
            [(float(v) / 1000.0 if v is not None else 0.0) for v in row]
            for row in distances
        ]
        if durations and len(durations) == n:
            self._minutes = [
                [(float(v) / 60.0 if v is not None else 0.0) for v in row]
                for row in durations
            ]
        self.source = "osrm"
        return True

    # ------------------------------------------------------------- O'qish

    def km(self, a: int | None, b: int | None) -> float | None:
        if a is None or b is None:
            return None
        return self._km[a][b]

    def minutes(self, a: int | None, b: int | None) -> float | None:
        """Yo'l vaqti. Tezlik ham, OSRM ham yo'q bo'lsa `None` (nol emas)."""
        if a is None or b is None:
            return None
        if self._minutes is not None:
            return self._minutes[a][b]
        if self.speed_kph is None:
            return None
        return self._km[a][b] / self.speed_kph * 60.0

    @property
    def time_aware(self) -> bool:
        """Vaqt hisoblanadimi — vaqt oynasi tekshiruvi shunga bog'liq."""
        return self._minutes is not None or self.speed_kph is not None

    @property
    def size(self) -> int:
        return len(self._points)


def build_matrix(
    coordinates: Iterable[Sequence[Any]],
    *,
    road_factor: float,
    speed_kph: float | None,
    osrm_url: str = "",
    osrm_timeout: float = 10.0,
    osrm_max_points: int = 100,
) -> tuple[Matrix, dict[tuple[float, float], int]]:
    """Koordinatalar ro'yxatidan tayyor matritsa quradi.

    `coordinates` — `(lat, lon)` juftliklari; `None` lar e'tiborsiz qoldiriladi.
    """
    matrix = Matrix(road_factor=road_factor, speed_kph=speed_kph)
    for pair in coordinates:
        if not pair:
            continue
        matrix.node(pair[0], pair[1])
    matrix.build()
    if osrm_url:
        matrix.apply_osrm(osrm_url, osrm_timeout, osrm_max_points)
    return matrix, dict(matrix._index)  # noqa: SLF001 — o'z sinfimiz
