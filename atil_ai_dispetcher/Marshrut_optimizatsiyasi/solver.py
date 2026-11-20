"""VRP yadrosi — arizalarni mashinalarga taqsimlash va tartibga solish.

MASALA TURI: PDPTW (Pickup and Delivery Problem with Time Windows).
Klassik "omborchidan mijozlarga tarqatish" (CVRP) EMAS — ATIL da har bir
ariza A NUQTADAN B NUQTAGA yuk tashish, ya'ni har arizada IKKI to'xtash
bor va ular BITTA mashinada, YUKLASH AVVAL bo'lishi shart. Shuning uchun
Clarke-Wright kabi tarqatish algoritmlari bu yerga to'g'ri kelmaydi.

ALGORITM (ikki bosqich, ikkalasi ham determinlashgan):

  1. QURISH — eng arzon joylashtirish (cheapest insertion).
     Arizalar muhimlik va muddat bo'yicha tartiblanadi, so'ng har biri
     uchun "qaysi mashinaning qaysi ikki o'rniga qo'yilsa umumiy narx
     eng kam oshadi" degan savolga to'liq javob qidiriladi.

  2. YAXSHILASH — mahalliy qidiruv.
     `relocate` (arizani boshqa mashinaga/o'ringa ko'chirish) va
     `exchange` (ikki arizani almashtirish). Har bir yurish faqat
     narxni KAMAYTIRSA qabul qilinadi, shuning uchun jarayon monoton
     va cheksiz aylanmaydi.

NIMA UCHUN OR-TOOLS EMAS: serverga yangi og'ir bog'liqlik qo'shilmadi.
Modul faqat standart Python bilan ishlaydi. 200 ariza x 100 mashina
chegarasida (`RO_MAX_REQUESTS`, `RO_MAX_VEHICLES`) bu yechim vaqt
byudjetiga sig'adi. Hajm o'sib ketsa `_best_insertion` ni OR-Tools bilan
almashtirish yetarli — qolgan kod tegilmaydi.

DETERMINLASHGAN: tasodifiy son ishlatilmaydi. Bir xil kirishga har doim
bir xil reja chiqadi — dispetcher ikki marta so'rab ikki xil javob
olmaydi.

VAQT BYUDJETI: yaxshilash sikli `RO_TIME_BUDGET_SECONDS` tugaganda
to'xtaydi va o'sha paytdagi eng yaxshi yechim qaytadi. Yechim har doim
to'liq va yaroqli — byudjet faqat "yana yaxshilanishi mumkin edi"
degan ma'noni bildiradi va javobda `time_budget_hit` bilan ko'rsatiladi.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from atil_ai_dispetcher.Marshrut_optimizatsiyasi import config
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.geo import Matrix

logger = logging.getLogger(__name__)

# Joylanmaslik sabablari — `models.UnassignedRequest` dagi kodlar bilan bir xil.
NO_COORDINATES = "NO_COORDINATES"
NO_MATCHING_VEHICLE = "NO_MATCHING_VEHICLE"
CAPACITY = "CAPACITY"
TIME_WINDOW = "TIME_WINDOW"
SHIFT_LIMIT = "SHIFT_LIMIT"
HAZARD = "HAZARD"
BOUND_VEHICLE_UNAVAILABLE = "BOUND_VEHICLE_UNAVAILABLE"
NO_VEHICLE_LEFT = "NO_VEHICLE_LEFT"

#: Sabab qanchalik "aniq" ekani. Bir ariza bir necha mashinada bir necha
#: sababga urilsa, eng aniq sabab ko'rsatiladi: koordinata yo'qligi
#: "vaqt yetmadi" dan muhimroq xabar.
_REASON_RANK = {
    NO_COORDINATES: 0,
    BOUND_VEHICLE_UNAVAILABLE: 1,
    HAZARD: 2,
    NO_MATCHING_VEHICLE: 3,
    CAPACITY: 4,
    TIME_WINDOW: 5,
    SHIFT_LIMIT: 6,
    NO_VEHICLE_LEFT: 7,
}


#: Xavfli yuk maxsus sisternani talab qilsa faqat shu turlar yaraydi
#: (`hazard_profile.requires_special_tank`).
TANK_TRANSPORT_TYPES = ("TANKER", "WATER_TRUCK")


# ------------------------------------------------------------------ Kirish


@dataclass
class Stop:
    """Bitta to'xtash — yuklash yoki tushirish."""

    kind: str                      # PICKUP | DELIVERY
    order_id: str
    node: int | None               # matritsadagi tugun; None — koordinata yo'q
    name: str | None = None
    location_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    demand_kg: float = 0.0         # PICKUP da musbat, DELIVERY da manfiy
    demand_m3: float = 0.0
    window_from: datetime | None = None
    window_to: datetime | None = None
    service_minutes: float = 0.0


@dataclass
class Order:
    """Bitta ariza — yuklash va tushirish juftligi."""

    id: str
    pickup: Stop
    delivery: Stop
    number: str | None = None
    priority: str = "NORMAL"
    required_transport_type: str | None = None
    weight_kg: float | None = None
    volume_m3: float | None = None
    origin_name: str | None = None
    destination_name: str | None = None

    #: Dispetcher bazada allaqachon biriktirib qo'ygan mashina
    #: (`transport_request.binding_vehicle_id`). Berilgan bo'lsa ariza
    #: FAQAT shu mashinaga qo'yiladi — optimizator odamning qarorini
    #: bekor qilmaydi, faqat qolganini shu qaror atrofida quradi.
    locked_vehicle_id: str | None = None

    #: Xavfli yuk maxsus sisterna talab qiladimi. `shipment` ->
    #: `hazard_profile` zanjiridan avtomatik chiqadi.
    requires_tank: bool = False

    #: Xavfli yuk ADR talab qiladimi. Bu FAQAT ogohlantirish uchun:
    #: haydovchining ADR ruxsati bazada alohida ustun emas, shuning
    #: uchun cheklov sifatida qo'llab bo'lmaydi.
    requires_adr: bool = False
    un_number: str | None = None


@dataclass
class Vehicle:
    """Reja tuzilayotgan bitta mashina."""

    id: str
    start_node: int | None
    plate_number: str | None = None
    brand: str | None = None
    model: str | None = None
    transport_type: str | None = None
    capacity_kg: float | None = None
    capacity_m3: float | None = None
    start_name: str | None = None
    start_latitude: float | None = None
    start_longitude: float | None = None
    shift_from: datetime | None = None
    shift_to: datetime | None = None
    max_duration_minutes: float | None = None
    driver_id: str | None = None
    driver_name: str | None = None
    return_to_start: bool = True


@dataclass
class Options:
    """Optimizatsiya sozlamalari — so'rovdan va `.env` dan yig'iladi."""

    objective: str = "balanced"
    respect_time_windows: bool = True
    respect_capacity: bool = True
    time_aware: bool = False
    speed_kph: float | None = None
    plan_start: datetime | None = None
    lateness_penalty: float = config.LATENESS_PENALTY
    vehicle_fixed_minutes: float = config.VEHICLE_FIXED_MINUTES
    balance_distance: float = config.BALANCE_DISTANCE
    balance_duration: float = config.BALANCE_DURATION
    time_budget_seconds: float = config.TIME_BUDGET_SECONDS
    max_rounds: int = config.MAX_IMPROVE_ROUNDS
    #: Bitta nuqta uchun ko'rib chiqiladigan eng ko'p o'rin. Uzun
    #: marshrutda barcha o'rinni sinash kvadratik o'sadi va vaqt
    #: byudjetini yeb qo'yadi. 0 — qisqartirish yo'q.
    insertion_candidates: int = config.INSERTION_CANDIDATES


# ----------------------------------------------------------------- Chiqish


@dataclass
class Visit:
    """Baholangan to'xtash — vaqti va yuki bilan."""

    stop: Stop
    distance_km: float | None = None
    travel_minutes: float | None = None
    arrival_at: datetime | None = None
    wait_minutes: float | None = None
    service_minutes: float | None = None
    departure_at: datetime | None = None
    late_minutes: float | None = None
    load_after_kg: float = 0.0
    load_after_m3: float = 0.0


@dataclass
class RouteEval:
    """Bitta mashina marshrutining to'liq bahosi."""

    feasible: bool = True
    reason: str | None = None
    cost: float = 0.0
    distance_km: float = 0.0
    driving_minutes: float | None = None
    waiting_minutes: float | None = None
    service_minutes: float | None = None
    late_minutes: float | None = None
    total_minutes: float | None = None
    max_load_kg: float = 0.0
    max_load_m3: float = 0.0
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    visits: list[Visit] = field(default_factory=list)


@dataclass
class Solution:
    """Tayyor reja."""

    routes: dict[str, list[Stop]] = field(default_factory=dict)
    evaluations: dict[str, RouteEval] = field(default_factory=dict)
    unassigned: dict[str, str] = field(default_factory=dict)   # order_id -> sabab kodi
    cost: float = 0.0
    rounds: int = 0
    time_budget_hit: bool = False


# ------------------------------------------------------------ Yordamchilar


def naive(value: Any) -> datetime | None:
    """Vaqt zonasini olib tashlaydi.

    Bazada `timestamp` (zonasiz) va `timestamptz` (zonali) aralash:
    `transport_request.planned_departure_at` zonasiz, `driver_shift`
    zonali. Ularni bevosita solishtirish Python da TypeError beradi,
    shuning uchun hammasi bir ko'rinishga keltiriladi.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, str):
        # Modul kutubxona sifatida ham chaqiriladi (Pydantic'siz), o'shanda
        # vaqt ISO matn bo'lib keladi. Jimgina `None` qaytarish vaqt
        # oynasini KO'RINMAS TARZDA o'chirib qo'yardi — eng xavfli xato.
        try:
            return naive(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            logger.warning("Vaqtni o'qib bo'lmadi: %r — e'tiborsiz qoldirildi", value[:40])
    return None


def _order_sort_key(order: Order) -> tuple[Any, ...]:
    """Joylashtirish tartibi: biriktirilgani, keyin muhimi va muddati yaqini.

    Bu BALL EMAS. Kech joylangan ariza mashinasiz qolishi mumkin,
    shuning uchun muhimi oldin joylanadi — tartib adolatni ta'minlaydi,
    natijaning "yaxshiligini" emas.

    BIRIKTIRILGAN ARIZA ENG BIRINCHI. Dispetcher uni qo'lda ma'lum bir
    mashinaga bergan, ya'ni uning o'rni allaqachon band qilingan.
    Boshqa arizalar avval joylansa, o'sha mashinaning sig'imi to'lib
    qoladi va ODAMNING QARORI siqib chiqariladi — optimizator "mashina
    bo'sh emas" deb uni tashlab ketardi. Sinovda aynan shu bo'ldi:
    20 t li mashinaga 19.5 t yuk joylandi va unga biriktirilgan 7 t li
    ariza sig'may qoldi.
    """
    priority = config.PRIORITY_ORDER.get((order.priority or "NORMAL").upper(), 9)
    deadline = order.delivery.window_to or order.pickup.window_to
    return (
        0 if order.locked_vehicle_id else 1,
        priority,
        deadline or datetime.max,
        -(order.weight_kg or 0.0),
        order.id,
    )


def compatible(vehicle: Vehicle, order: Order, options: Options) -> str | None:
    """Mashina arizani PRINSIPIAL ko'tara oladimi. `None` — mos.

    Bu yerda faqat MARSHRUTDAN QAT'I NAZAR to'g'ri bo'lgan tekshiruvlar:
    biriktirish, xavfli yuk, transport turi va sig'im. Vaqt va yo'l
    tekshiruvi marshrut ichida (`evaluate`) qilinadi, chunki ular
    tartibga bog'liq.
    """
    # ODAMNING QARORI BIRINCHI. Dispetcher arizani qo'lda biriktirgan
    # bo'lsa optimizator uni boshqa mashinaga ko'chirmaydi. Bu qoida
    # eng boshida turadi: qolgan tekshiruvlar bekor.
    if order.locked_vehicle_id and vehicle.id != order.locked_vehicle_id:
        return BOUND_VEHICLE_UNAVAILABLE

    if order.requires_tank and (vehicle.transport_type or "") not in TANK_TRANSPORT_TYPES:
        return HAZARD

    if order.required_transport_type and vehicle.transport_type:
        if order.required_transport_type != vehicle.transport_type:
            return NO_MATCHING_VEHICLE

    if options.respect_capacity:
        if (
            vehicle.capacity_kg is not None
            and order.weight_kg is not None
            and order.weight_kg > vehicle.capacity_kg
        ):
            return CAPACITY
        if (
            vehicle.capacity_m3 is not None
            and order.volume_m3 is not None
            and order.volume_m3 > vehicle.capacity_m3
        ):
            return CAPACITY
    return None


# -------------------------------------------------------------- Baholash


def evaluate(
    vehicle: Vehicle,
    sequence: list[Stop],
    matrix: Matrix,
    options: Options,
) -> RouteEval:
    """Marshrutni boshidan oxirigacha yuradi va narxini hisoblaydi.

    Bu modulning ISHCHI OTI: joylashtirish va yaxshilash paytida minglab
    marta chaqiriladi. Shuning uchun ichida ortiqcha ish yo'q — bitta
    o'tish, bitta sikl.

    QAYTARADI: yaroqsiz bo'lsa `feasible=False` va SABAB kodi. Sabab
    keyin arizaning `unassigned` yozuviga tushadi.
    """
    result = RouteEval()
    if not sequence:
        result.cost = 0.0
        return result

    if vehicle.start_node is None:
        result.feasible = False
        result.reason = NO_COORDINATES
        return result

    time_aware = options.time_aware
    clock = naive(vehicle.shift_from) or naive(options.plan_start)
    if time_aware and clock is None:
        # Vaqt hisoblanadi, lekin boshlanish nuqtasi yo'q — vaqtsiz davom
        # etamiz (masofa baribir to'g'ri chiqadi).
        time_aware = False

    result.starts_at = clock if time_aware else None

    node = vehicle.start_node
    load_kg = 0.0
    load_m3 = 0.0
    driving = 0.0
    waiting = 0.0
    service = 0.0
    late_total = 0.0

    for stop in sequence:
        km = matrix.km(node, stop.node)
        if km is None:
            result.feasible = False
            result.reason = NO_COORDINATES
            return result

        result.distance_km += km
        visit = Visit(stop=stop, distance_km=km)

        if time_aware:
            minutes = matrix.minutes(node, stop.node)
            if minutes is None:
                time_aware = False
            else:
                driving += minutes
                arrival = clock + timedelta(minutes=minutes)
                visit.travel_minutes = minutes
                visit.arrival_at = arrival

                if stop.window_from and arrival < stop.window_from:
                    wait = (stop.window_from - arrival).total_seconds() / 60.0
                    waiting += wait
                    visit.wait_minutes = wait
                    arrival = stop.window_from

                if stop.window_to and arrival > stop.window_to:
                    late = (arrival - stop.window_to).total_seconds() / 60.0
                    if options.respect_time_windows:
                        result.feasible = False
                        result.reason = TIME_WINDOW
                        return result
                    late_total += late
                    visit.late_minutes = late

                service += stop.service_minutes
                visit.service_minutes = stop.service_minutes
                clock = arrival + timedelta(minutes=stop.service_minutes)
                visit.departure_at = clock

        load_kg += stop.demand_kg
        load_m3 += stop.demand_m3
        # Kichik manfiy qoldiq (suzuvchi nuqta xatosi) nolga tenglashtiriladi.
        load_kg = 0.0 if abs(load_kg) < 1e-9 else load_kg
        load_m3 = 0.0 if abs(load_m3) < 1e-9 else load_m3
        visit.load_after_kg = load_kg
        visit.load_after_m3 = load_m3
        result.max_load_kg = max(result.max_load_kg, load_kg)
        result.max_load_m3 = max(result.max_load_m3, load_m3)

        if options.respect_capacity:
            if vehicle.capacity_kg is not None and load_kg > vehicle.capacity_kg + 1e-6:
                result.feasible = False
                result.reason = CAPACITY
                return result
            if vehicle.capacity_m3 is not None and load_m3 > vehicle.capacity_m3 + 1e-6:
                result.feasible = False
                result.reason = CAPACITY
                return result

        result.visits.append(visit)
        node = stop.node

    # ------------------------------------------------ Boshlang'ich nuqtaga qaytish
    if vehicle.return_to_start:
        km = matrix.km(node, vehicle.start_node)
        if km is None:
            result.feasible = False
            result.reason = NO_COORDINATES
            return result
        result.distance_km += km
        if time_aware:
            minutes = matrix.minutes(node, vehicle.start_node)
            if minutes is not None:
                driving += minutes
                clock = clock + timedelta(minutes=minutes)

    if time_aware:
        result.driving_minutes = driving
        result.waiting_minutes = waiting
        result.service_minutes = service
        result.late_minutes = late_total
        result.total_minutes = driving + waiting + service
        result.ends_at = clock

        if vehicle.shift_to and clock > naive(vehicle.shift_to):
            result.feasible = False
            result.reason = SHIFT_LIMIT
            return result
        if (
            vehicle.max_duration_minutes is not None
            and result.total_minutes > vehicle.max_duration_minutes
        ):
            result.feasible = False
            result.reason = SHIFT_LIMIT
            return result

    result.cost = _cost(result, options)
    return result


def _cost(route: RouteEval, options: Options) -> float:
    """Marshrut narxi.

    O'LCHOV BIRLIGI BITTA. Vaqt hisoblanayotgan bo'lsa hammasi DAQIQADA:
    masofa ham kalibrlangan tezlik orqali daqiqaga aylantiriladi. Aks
    holda hammasi KILOMETRDA. Kilometr bilan daqiqani qo'shib yuborish
    — mana shu joyda qilinadigan eng keng tarqalgan xato.
    """
    if not route.visits:
        return 0.0

    if options.time_aware and options.speed_kph and route.total_minutes is not None:
        distance_minutes = route.distance_km / options.speed_kph * 60.0
        if options.objective == "distance":
            base = distance_minutes
        elif options.objective == "duration":
            base = route.total_minutes
        else:
            base = (
                options.balance_distance * distance_minutes
                + options.balance_duration * route.total_minutes
            )
        penalty = options.lateness_penalty * (route.late_minutes or 0.0)
        return base + penalty + options.vehicle_fixed_minutes

    # Vaqtsiz rejim: faqat masofa. Mashina ustamasi ham km da bo'lishi
    # kerak edi, lekin uni km ga aylantiradigan kurs yo'q — shuning uchun
    # qo'shilmaydi (`calibration.notes` da tezlik yo'qligi yozilgan).
    return route.distance_km


def solution_cost(solution: Solution) -> float:
    return sum(ev.cost for ev in solution.evaluations.values())


# --------------------------------------------------------- Joylashtirish


def _insert_positions(length: int) -> Iterable[tuple[int, int]]:
    """Yuklash va tushirishni qo'yish mumkin bo'lgan BARCHA o'rin juftliklari.

    `pickup` `i` ga, `delivery` `j` ga qo'yiladi va HAR DOIM `i < j` —
    ya'ni tushirish yuklashdan oldin bo'lishi mumkin emas. Bu cheklov
    algoritmning ichiga qurilgan, keyin tekshirilmaydi.

    DIQQAT: bu to'liq ro'yxat `O(L^2)` ta variant beradi. Uzun marshrutda
    (L=50) bu 1250 ta to'liq baholash, har biri marshrutni boshidan
    oxirigacha yuradi — ya'ni 60 mingdan ortiq amal. Shuning uchun asosiy
    yo'lda `_candidate_positions` ishlatiladi; bu funksiya faqat qisqa
    marshrutlar va qaytarib qo'yish uchun qoldi.
    """
    for i in range(length + 1):
        for j in range(i + 1, length + 2):
            yield i, j


def _detour_km(
    vehicle: Vehicle,
    sequence: list[Stop],
    stop: Stop,
    index: int,
    matrix: Matrix,
) -> float | None:
    """Nuqtani `index` ga qo'yish qancha qo'shimcha yo'l qo'shadi.

    Bu TO'LIQ BAHO EMAS — vaqt oynasi ham, sig'im ham hisobga olinmaydi.
    Faqat geometriya: "oldingi -> yangi -> keyingi" minus "oldingi -> keyingi".
    Vazifasi — arzon o'rinlarni tez saralash, qaror qabul qilish emas.
    """
    prev_node = vehicle.start_node if index == 0 else sequence[index - 1].node
    if index >= len(sequence):
        next_node = vehicle.start_node if vehicle.return_to_start else None
    else:
        next_node = sequence[index].node

    to_new = matrix.km(prev_node, stop.node)
    if to_new is None:
        return None
    if next_node is None:
        return to_new
    from_new = matrix.km(stop.node, next_node)
    direct = matrix.km(prev_node, next_node)
    if from_new is None or direct is None:
        return to_new
    return to_new + from_new - direct


def _candidate_positions(
    vehicle: Vehicle,
    sequence: list[Stop],
    stop: Stop,
    matrix: Matrix,
    limit: int,
    *,
    start: int = 0,
) -> list[int]:
    """Nuqtani qo'yish uchun eng arzon `limit` ta o'rin.

    NIMA UCHUN QISQARTIRAMIZ: marshrutning narigi uchiga nuqta qo'yish
    hech qachon eng arzon variant bo'lmaydi — u yerga borib qaytish
    kerak. Ya'ni uzoq o'rinlarni baholash bekorga ketgan vaqt.

    Saralash `_detour_km` bo'yicha (arzon geometrik baho), TANLASH esa
    baribir to'liq `evaluate()` bilan qilinadi. Ya'ni bu tezlashtirish
    yaroqsiz yechimni o'tkazib yubormaydi — u faqat KO'RIB CHIQILADIGAN
    variantlar sonini kamaytiradi.

    `limit <= 0` bo'lsa qisqartirish o'chadi va hamma o'rin qaytadi.
    """
    positions = list(range(start, len(sequence) + 1))
    if limit <= 0 or len(positions) <= limit:
        return positions

    scored: list[tuple[float, int]] = []
    for index in positions:
        detour = _detour_km(vehicle, sequence, stop, index, matrix)
        if detour is None:
            continue
        scored.append((detour, index))
    if not scored:
        return positions
    scored.sort()
    # Tartib saqlanadi: joylashtirish natijasi o'rinlar ketma-ketligiga
    # bog'liq bo'lmasligi uchun (determinlashgan bo'lib qolishi shart).
    return sorted(index for _, index in scored[:limit])


def _with_order(sequence: list[Stop], order: Order, i: int, j: int) -> list[Stop]:
    seq = list(sequence)
    seq.insert(i, order.pickup)
    seq.insert(j, order.delivery)
    return seq


def _without_order(sequence: list[Stop], order_id: str) -> list[Stop]:
    return [s for s in sequence if s.order_id != order_id]


@dataclass
class Insertion:
    vehicle_id: str
    sequence: list[Stop]
    evaluation: RouteEval
    delta: float


def _best_insertion(
    order: Order,
    vehicles: list[Vehicle],
    routes: dict[str, list[Stop]],
    evaluations: dict[str, RouteEval],
    matrix: Matrix,
    options: Options,
    deadline: float,
) -> tuple[Insertion | None, str | None]:
    """Arizani eng arzon joyga qo'yadi.

    HAMMA mashina va HAMMA o'rin ko'rib chiqiladi, eng kichik narx
    o'sishi tanlanadi. "Birinchi sig'gan joyga qo'yish" tezroq bo'lardi,
    lekin natija sezilarli yomon chiqadi — bu yerda sifat muhimroq.

    Ikkinchi qaytariladigan qiymat — joylashtirib bo'lmagan bo'lsa
    ENG ANIQ sabab.
    """
    best: Insertion | None = None
    reason: str | None = None

    def note(code: str | None) -> None:
        nonlocal reason
        if code is None:
            return
        if reason is None or _REASON_RANK.get(code, 9) < _REASON_RANK.get(reason, 9):
            reason = code

    if order.pickup.node is None or order.delivery.node is None:
        return None, NO_COORDINATES

    for vehicle in vehicles:
        mismatch = compatible(vehicle, order, options)
        if mismatch is not None:
            note(mismatch)
            continue

        sequence = routes.get(vehicle.id, [])
        current = evaluations.get(vehicle.id)
        current_cost = current.cost if current else 0.0

        limit = options.insertion_candidates
        for i in _candidate_positions(vehicle, sequence, order.pickup, matrix, limit):
            if time.perf_counter() > deadline:
                return best, reason
            # Tushirish o'rinlari YUKLASHDAN KEYIN qo'yilgan ketma-ketlik
            # ustida saralanadi — aks holda geometrik baho noto'g'ri
            # chiqardi (yuklash nuqtasi hali ro'yxatda yo'q edi).
            with_pickup = list(sequence)
            with_pickup.insert(i, order.pickup)
            for j in _candidate_positions(
                vehicle, with_pickup, order.delivery, matrix, limit, start=i + 1
            ):
                candidate = list(with_pickup)
                candidate.insert(j, order.delivery)
                ev = evaluate(vehicle, candidate, matrix, options)
                if not ev.feasible:
                    note(ev.reason)
                    continue
                delta = ev.cost - current_cost
                if best is None or delta < best.delta - 1e-9:
                    best = Insertion(vehicle.id, candidate, ev, delta)

    if best is None and reason is None:
        reason = NO_VEHICLE_LEFT
    return best, reason


def _apply(
    solution: Solution,
    insertion: Insertion,
) -> None:
    solution.routes[insertion.vehicle_id] = insertion.sequence
    solution.evaluations[insertion.vehicle_id] = insertion.evaluation


# ---------------------------------------------------------------- Asosiy


def solve(
    orders: list[Order],
    vehicles: list[Vehicle],
    matrix: Matrix,
    options: Options,
) -> Solution:
    """Rejani quradi va yaxshilaydi.

    Ikki bosqich ham vaqt byudjetiga bo'ysunadi: byudjet tugasa
    qurilgan qismi bilan qaytadi. YARIM REJA EMAS — har bir joylangan
    ariza to'liq joylangan bo'ladi, faqat qolganlari `unassigned` ga
    tushadi.
    """
    started = time.perf_counter()
    deadline = started + max(0.5, options.time_budget_seconds)

    solution = Solution()
    solution.routes = {v.id: [] for v in vehicles}
    solution.evaluations = {
        v.id: evaluate(v, [], matrix, options) for v in vehicles
    }
    by_id = {v.id: v for v in vehicles}

    if not vehicles:
        # Mashina yo'q — lekin sabab baribir ANIQ bo'lishi kerak:
        # koordinatasiz ariza mashina bo'lganda ham joylanmasdi.
        for order in orders:
            solution.unassigned[order.id] = (
                NO_COORDINATES
                if order.pickup.node is None or order.delivery.node is None
                else NO_VEHICLE_LEFT
            )
        return solution

    # ------------------------------------------------------------ 1. Qurish
    for order in sorted(orders, key=_order_sort_key):
        insertion, reason = _best_insertion(
            order, vehicles, solution.routes, solution.evaluations,
            matrix, options, deadline,
        )
        if insertion is None:
            solution.unassigned[order.id] = reason or NO_VEHICLE_LEFT
            continue
        _apply(solution, insertion)

    solution.cost = solution_cost(solution)

    if time.perf_counter() > deadline:
        solution.time_budget_hit = True
        return solution

    # -------------------------------------------------------- 2. Yaxshilash
    assigned = {o.id: o for o in orders if o.id not in solution.unassigned}
    order_list = [assigned[k] for k in sorted(assigned)]

    for round_index in range(options.max_rounds):
        if time.perf_counter() > deadline:
            solution.time_budget_hit = True
            break
        improved = _relocate_round(
            solution, order_list, by_id, vehicles, matrix, options, deadline
        )
        improved = _exchange_round(
            solution, order_list, by_id, matrix, options, deadline
        ) or improved
        solution.rounds = round_index + 1
        if not improved:
            break

    solution.cost = solution_cost(solution)
    return solution


def _vehicle_of(solution: Solution, order_id: str) -> str | None:
    for vehicle_id, sequence in solution.routes.items():
        if any(s.order_id == order_id for s in sequence):
            return vehicle_id
    return None


def _relocate_round(
    solution: Solution,
    orders: list[Order],
    by_id: dict[str, Vehicle],
    vehicles: list[Vehicle],
    matrix: Matrix,
    options: Options,
    deadline: float,
) -> bool:
    """Har bir arizani chiqarib, eng yaxshi joyga qayta qo'yishga urinadi.

    Qurish bosqichi arizalarni BIRMA-BIR joylagan, ya'ni keyingi arizalar
    haqida bilmagan. Ko'chirish shu kamchilikni tuzatadi: endi butun
    manzara ma'lum.
    """
    improved = False

    for order in orders:
        if time.perf_counter() > deadline:
            solution.time_budget_hit = True
            return improved

        source_id = _vehicle_of(solution, order.id)
        if source_id is None:
            continue

        source_vehicle = by_id[source_id]
        trimmed = _without_order(solution.routes[source_id], order.id)
        trimmed_eval = evaluate(source_vehicle, trimmed, matrix, options)
        if not trimmed_eval.feasible:
            # Bo'lishi qiyin (kamroq to'xtash — yengilroq marshrut),
            # lekin yaroqsiz oraliq holatga o'tib ketmaymiz.
            continue

        before = solution.evaluations[source_id].cost
        gain = before - trimmed_eval.cost

        # Vaqtincha chiqarib qo'yamiz — shunda o'z marshrutidagi boshqa
        # o'rinlar ham nomzod bo'ladi.
        solution.routes[source_id] = trimmed
        solution.evaluations[source_id] = trimmed_eval

        insertion, _ = _best_insertion(
            order, vehicles, solution.routes, solution.evaluations,
            matrix, options, deadline,
        )

        if insertion is not None and insertion.delta < gain - 1e-9:
            _apply(solution, insertion)
            improved = True
        else:
            # Yaxshilanmadi — hamma narsani joyiga qaytaramiz.
            restored = _with_order_back(solution, order, source_vehicle, matrix, options)
            if not restored:
                # Qaytarib bo'lmadi (bo'lmasligi kerak) — hech bo'lmasa
                # ariza yo'qolmasin.
                if insertion is not None:
                    _apply(solution, insertion)
                else:
                    solution.unassigned[order.id] = NO_VEHICLE_LEFT

    return improved


def _with_order_back(
    solution: Solution,
    order: Order,
    vehicle: Vehicle,
    matrix: Matrix,
    options: Options,
) -> bool:
    """Chiqarilgan arizani o'z mashinasiga eng arzon o'ringa qaytaradi."""
    sequence = solution.routes[vehicle.id]
    best: Insertion | None = None
    for i, j in _insert_positions(len(sequence)):
        candidate = _with_order(sequence, order, i, j)
        ev = evaluate(vehicle, candidate, matrix, options)
        if not ev.feasible:
            continue
        delta = ev.cost - solution.evaluations[vehicle.id].cost
        if best is None or delta < best.delta - 1e-9:
            best = Insertion(vehicle.id, candidate, ev, delta)
    if best is None:
        return False
    _apply(solution, best)
    return True


def _exchange_round(
    solution: Solution,
    orders: list[Order],
    by_id: dict[str, Vehicle],
    matrix: Matrix,
    options: Options,
    deadline: float,
) -> bool:
    """Ikki mashinadagi ikki arizani almashtirishga urinadi.

    Ko'chirish yolg'iz yetmaydigan holat: ikkala mashina ham to'la, lekin
    yuklarni almashtirsa ikkalasi ham yutadi. Bunday juftlik ko'chirish
    bilan hech qachon topilmaydi, chunki oraliq qadam yomonroq.
    """
    improved = False
    count = len(orders)

    for a_index in range(count):
        for b_index in range(a_index + 1, count):
            if time.perf_counter() > deadline:
                solution.time_budget_hit = True
                return improved

            order_a, order_b = orders[a_index], orders[b_index]
            veh_a = _vehicle_of(solution, order_a.id)
            veh_b = _vehicle_of(solution, order_b.id)
            if veh_a is None or veh_b is None or veh_a == veh_b:
                continue

            vehicle_a, vehicle_b = by_id[veh_a], by_id[veh_b]
            if (
                compatible(vehicle_a, order_b, options) is not None
                or compatible(vehicle_b, order_a, options) is not None
            ):
                continue

            before = solution.evaluations[veh_a].cost + solution.evaluations[veh_b].cost

            base_a = _without_order(solution.routes[veh_a], order_a.id)
            base_b = _without_order(solution.routes[veh_b], order_b.id)

            new_a = _cheapest(vehicle_a, base_a, order_b, matrix, options)
            if new_a is None:
                continue
            new_b = _cheapest(vehicle_b, base_b, order_a, matrix, options)
            if new_b is None:
                continue

            after = new_a[1].cost + new_b[1].cost
            if after < before - 1e-9:
                solution.routes[veh_a], solution.evaluations[veh_a] = new_a
                solution.routes[veh_b], solution.evaluations[veh_b] = new_b
                improved = True

    return improved


def _cheapest(
    vehicle: Vehicle,
    sequence: list[Stop],
    order: Order,
    matrix: Matrix,
    options: Options,
) -> tuple[list[Stop], RouteEval] | None:
    """Berilgan marshrutga arizani eng arzon qo'yish varianti."""
    best: tuple[list[Stop], RouteEval] | None = None
    for i, j in _insert_positions(len(sequence)):
        candidate = _with_order(sequence, order, i, j)
        ev = evaluate(vehicle, candidate, matrix, options)
        if not ev.feasible:
            continue
        if best is None or ev.cost < best[1].cost - 1e-9:
            best = (candidate, ev)
    return best


# ------------------------------------------------------------- Solishtirish


def baseline_distance_km(
    orders: list[Order],
    vehicles: list[Vehicle],
    matrix: Matrix,
) -> float | None:
    """Optimizatsiyasiz variant: har ariza alohida mashinada.

    Chiqish -> yuklash -> tushirish -> qaytish. Dispetcher qo'lda ishlaganda
    amalda shunday bo'ladi, shuning uchun foyda ANIQ SHUNGA solishtiriladi.
    Solishtirish bazasi bo'lmasa "23% tejaldi" degan gap ham bo'lmaydi.

    Har ariza uchun ENG YAQIN mashina olinadi — qo'lda ishlaganda ham
    dispetcher yaqinini tanlaydi, ya'ni baza adolatli bo'ladi.
    """
    if not orders or not vehicles:
        return None

    total = 0.0
    counted = 0
    for order in orders:
        best: float | None = None
        for vehicle in vehicles:
            legs = (
                matrix.km(vehicle.start_node, order.pickup.node),
                matrix.km(order.pickup.node, order.delivery.node),
                matrix.km(order.delivery.node, vehicle.start_node)
                if vehicle.return_to_start else 0.0,
            )
            if any(leg is None for leg in legs):
                continue
            distance = sum(leg for leg in legs if leg is not None)
            if best is None or distance < best:
                best = distance
        if best is not None:
            total += best
            counted += 1

    return total if counted else None
