"""Mashina va haydovchi tanlash — orkestrator.

BITTA KIRISH NUQTASI: `rank(...)`. Bitta JSON qaytaradi, ichida
reytinglangan MASHINA+HAYDOVCHI JUFTLIKLARI bo'ladi.

OQIM:
    1. talab o'qiladi   — `route`, `transport_request` yoki so'rov parametri
    2. nomzodlar        — mashinalar va haydovchilar bazadan
    3. kesish           — band, hujjati o'tgan, toifasi mos kelmagani chiqadi
    4. mezonlar         — har bir tomon uchun alohida (`rules.py`)
    5. juftlik          — qolganlaridan
    6. normalizatsiya   — nisbiy mezonlar nomzodlar bilan solishtiriladi
    7. ball             — og'irlikli o'rtacha, `null` mezonlarsiz

NIMA UCHUN AVVAL KESISH, KEYIN JUFTLIK: juftliklar soni mashina x haydovchi
bo'lgani uchun tez o'sadi. Bandini oldin chiqarib tashlash 127x206 = 26 162
o'rniga 114x22 = 2 508 juftlik qoldiradi.

OG'IRLIK QAYTA TAQSIMLANADI. Mezon `null` bo'lsa (ma'lumot yo'q) uning
og'irligi qolganlarga bo'linadi. Ya'ni sig'imi noma'lum mashina jazolanmaydi,
shunchaki qolgan besh mezon bo'yicha baholanadi. Qaysi mezon nima uchun
tushib qolgani `summary.criteria_skipped` da OCHIQ yoziladi.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from atil_ai_dispetcher.vehicle_selection import config, labels, queries, rules, texts
from atil_ai_dispetcher.vehicle_selection.explain import template_explanation
from atil_ai_dispetcher.vehicle_selection.texts import t
from atil_ai_dispetcher.vehicle_selection.queries import to_float

logger = logging.getLogger(__name__)


class DemandNotFound(LookupError):
    """`route_id` bazada topilmadi — router buni 404 ga aylantiradi."""


@dataclass
class Side:
    """Bitta mashina yoki haydovchi bo'yicha oldindan hisoblangan natija."""

    row: dict[str, Any]
    criteria: dict[str, rules.Criterion] = field(default_factory=dict)
    doc_check: rules.DocumentCheck = field(default_factory=lambda: ([], [], []))
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------- Talab


def _build_demand(
    *,
    route_id: str | None,
    transport_type: str | None,
    driver_category: str | None,
    cargo_weight_kg: float | None,
    cargo_volume_m3: float | None,
    passengers: int | None,
    origin_location_id: str | None,
    destination_location_id: str | None,
    on_date: date | None,
) -> dict[str, Any]:
    """Talabni yig'adi: bazadagi marshrut + so'rov parametrlari.

    USTUVORLIK: so'rov parametri BAZADAN USTUN turadi. Sababi — bazadagi
    ustunlar hozircha bo'sh (`cargo_weight_kg` 0/36, koordinatalar 0/36),
    shuning uchun chaqiruvchi qo'lda to'ldira olishi kerak. Ma'lumot
    yozila boshlaganda bu parametrlarni bermaslik kifoya: o'shanda baza
    qiymati ishlatiladi.
    """
    demand: dict[str, Any] = {"source": "manual"}

    if route_id:
        row = queries.fetch_route_demand(route_id)
        if row is None:
            raise DemandNotFound(f"Marshrut topilmadi: {route_id}")
        demand.update(
            source="route",
            route_id=row["route_id"],
            route_number=row["route_number"],
            required_transport_type=row["required_transport_type"],
            required_driver_category=row["required_driver_category"],
            origin_latitude=to_float(row["origin_latitude"] or row["first_point_latitude"]),
            origin_longitude=to_float(row["origin_longitude"] or row["first_point_longitude"]),
            total_distance_km=to_float(row["total_distance_km"]),
            # Reys oynasi marshrutdan olinadi — bandlik shu oyna bilan
            # tekshiriladi. So'rov parametri sifatida chiqarilmagan:
            # `driver_shift` da 206 haydovchidan 2 tasida yozuv bor, ya'ni
            # soatlik aniqlikni baza baribir ko'tarmaydi.
            window_from=row["planned_departure_at"],
            window_to=row["planned_arrival_at"],
        )

    # So'rov parametrlari bazadagini bekor qiladi
    overrides = {
        "required_transport_type": transport_type,
        "required_driver_category": driver_category,
        "cargo_weight_kg": cargo_weight_kg,
        "cargo_volume_m3": cargo_volume_m3,
        "passengers": passengers,
    }
    for key, value in overrides.items():
        if value is not None:
            demand[key] = value

    _resolve_locations(demand, origin_location_id, destination_location_id)

    # Jo'nash sanasi: berilgani, bo'lmasa reys oynasi boshi, u ham bo'lmasa bugun.
    if on_date is not None:
        demand["on_date"] = on_date
    elif isinstance(demand.get("window_from"), datetime):
        demand["on_date"] = demand["window_from"].date()
    else:
        demand["on_date"] = date.today()

    return demand


def _resolve_locations(
    demand: dict[str, Any],
    origin_location_id: str | None,
    destination_location_id: str | None,
) -> None:
    """Manzil id'larini nom va koordinataga aylantiradi (joyida).

    Manzil `route_point` dan yechiladi — sababi `queries.fetch_location`
    da yozilgan (`reference_data.LOCATIONS` bo'sh).

    JO'NASH nuqtasi koordinatasi masofa mezoniga boradi. MANZIL koordinatasi
    esa bugun HECH NARSAGA ta'sir qilmaydi va bu ataylab shunday: reysning
    borish masofasi mashinani tanlashga ta'sir qilishi uchun mashinaning
    o'zida sarf/zaxira ma'lumoti bo'lishi kerak (`fuel_norm` — 0 yozuv).
    Manzil hozircha yozib qo'yiladi va javobda qaytadi; telematika va norma
    to'ldirilganda u yerda ishlatiladi.
    """
    for key, location_id in (
        ("origin", origin_location_id),
        ("destination", destination_location_id),
    ):
        if not location_id:
            continue
        row = queries.fetch_location(location_id)
        demand[f"{key}_location_id"] = location_id
        if row is None:
            # Kesish emas: id noto'g'ri bo'lsa ham tanlash davom etadi,
            # lekin javobda buni ko'rish kerak.
            demand[f"{key}_location_name"] = None
            demand.setdefault("location_notes", []).append(
                f"{location_id} manzili `route_point` da topilmadi"
            )
            continue
        demand[f"{key}_location_name"] = row["location_name"]
        lat, lon = to_float(row["latitude"]), to_float(row["longitude"])
        demand[f"{key}_latitude"] = lat
        demand[f"{key}_longitude"] = lon
        if lat is None:
            demand.setdefault("location_notes", []).append(
                f"{row['location_name']} manzilida koordinata yo'q "
                f"(44 manzildan 16 tasida bor)"
            )


# ----------------------------------------------------- Tomonlarni baholash


def _evaluate_vehicle(
    row: dict[str, Any], demand: dict[str, Any], on_date: date,
    lang: str = texts.DEFAULT_LANG,
) -> Side:
    """Mashinaga tegishli mezonlar va kesishlar — haydovchidan mustaqil."""
    side = Side(row=row)

    side.blockers.extend(rules.type_blockers(row, demand))

    availability, notes = rules.vehicle_availability(row, lang)
    side.blockers.extend(availability)
    side.notes.extend(notes)

    capacity, blockers = rules.capacity(row, demand, lang)
    side.criteria["capacity"] = capacity
    side.blockers.extend(blockers)

    distance, blockers = rules.distance(row, demand, lang)
    side.criteria["distance"] = distance
    side.blockers.extend(blockers)

    technical, blockers = rules.technical(row, on_date=on_date, lang=lang)
    side.criteria["technical"] = technical
    side.blockers.extend(blockers)

    side.doc_check = rules.vehicle_documents(row, on_date=on_date, lang=lang)
    side.blockers.extend(side.doc_check[1])

    return side


def _evaluate_driver(
    row: dict[str, Any],
    demand: dict[str, Any],
    on_date: date,
    *,
    require_medical: bool,
    lang: str = texts.DEFAULT_LANG,
) -> Side:
    """Haydovchiga tegishli mezonlar va kesishlar — mashinadan mustaqil."""
    side = Side(row=row)

    availability, notes = rules.driver_availability(
        row, on_date=on_date, require_medical=require_medical, lang=lang
    )
    side.blockers.extend(availability)
    side.notes.extend(notes)

    skill, blockers = rules.skill(row, demand, lang)
    side.criteria["skill"] = skill
    side.blockers.extend(blockers)

    shift, blockers = rules.shift(
        row, window_from=demand.get("window_from"),
        window_to=demand.get("window_to"), lang=lang,
    )
    side.criteria["shift"] = shift
    side.blockers.extend(blockers)

    side.doc_check = rules.driver_documents(row, on_date=on_date, lang=lang)
    side.blockers.extend(side.doc_check[1])

    return side


# --------------------------------------------------------- Normalizatsiya


def _normalize(pairs: list[dict[str, Any]]) -> None:
    """Nisbiy mezonlarni 0..1 ga o'tkazadi — joyida.

    "Necha km uzoq" yoki "necha kun qolgani kam" degan savolga bazadagi
    hech narsa javob bermaydi, shuning uchun bu mezonlar NOMZODLAR BILAN
    solishtiriladi: eng yaxshisi 1, eng yomoni 0.

    HAMMA QIYMAT BIR XIL bo'lsa hammasiga 1.0 beriladi — bunday mezon
    variantlarni bir-biridan ajratmaydi, ya'ni jazolashi ham noto'g'ri
    bo'lardi.
    """
    for name in config.CRITERIA:
        values = [
            p["criteria"][name].value
            for p in pairs
            if p["criteria"].get(name)
            and p["criteria"][name].score is None
            and p["criteria"][name].normalize
            and p["criteria"][name].value is not None
        ]
        if not values:
            continue

        low, high = min(values), max(values)
        span = high - low

        for pair in pairs:
            crit = pair["criteria"].get(name)
            if crit is None or crit.score is not None or not crit.normalize:
                continue
            if crit.value is None:
                continue
            if span == 0:
                crit.score = 1.0
                continue
            share = (crit.value - low) / span
            crit.score = share if crit.normalize == "higher_better" else 1.0 - share


def _score_pair(pair: dict[str, Any], weights: dict[str, float]) -> None:
    """Og'irlikli o'rtacha — faqat balli bor mezonlar ustida.

    `null` mezon nolga aylanmaydi, og'irligi qolganlarga taqsimlanadi.
    Buning uchun bo'luvchi sifatida BARCHA og'irliklar emas, faqat
    ishlatilganlari yig'indisi olinadi.
    """
    total_weight = 0.0
    total_score = 0.0
    used: list[str] = []

    for name, crit in pair["criteria"].items():
        weight = weights.get(name, 0.0)
        if crit.score is None or weight <= 0:
            crit.weight = 0.0
            continue
        crit.weight = weight
        total_weight += weight
        total_score += crit.score * weight
        used.append(name)

    base = total_score / total_weight if total_weight else 0.0

    bonus = config.ASSIGNED_PAIR_BONUS if pair["assigned_pair"] else 0.0
    score = min(1.0, base + bonus)

    # `assigned_bonus` da HAQIQATAN qo'shilgan miqdor turadi, sozlamadagi
    # qiymat emas. Ball 1.0 da to'xtagani uchun ustama to'liq sig'masligi
    # mumkin: base=1.0 bo'lsa min(1.0, 1.05) = 1.0, ya'ni hech nima
    # qo'shilmagan. "0.05 qo'shildi" deb yozish javobni chalg'itardi —
    # o'quvchi ballning bir qismini ustamadan deb o'ylardi.
    # Teng ballda biriktirilgan juftlik baribir oldinda turadi: tartib
    # `rank()` dagi saralash kalitida `assigned_pair` bilan ham buziladi.
    pair["assigned_bonus"] = round(score - base, 4)
    pair["score"] = round(score, 4)
    pair["criteria_used"] = used

    # Og'irliklar javobda ULUSH bo'lib ko'rinsin — qaysi mezon ballning
    # qanchasini belgilaganini o'qish oson bo'ladi.
    if total_weight:
        for name in used:
            pair["criteria"][name].weight = round(weights[name] / total_weight, 4)


# ---------------------------------------------------------------- Asosiy


def rank(
    *,
    route_id: str | None = None,
    transport_type: str | None = None,
    driver_category: str | None = None,
    cargo_weight_kg: float | None = None,
    cargo_volume_m3: float | None = None,
    passengers: int | None = None,
    origin_location_id: str | None = None,
    destination_location_id: str | None = None,
    on_date: date | None = None,
    require_medical: bool = True,
    include_blocked: bool = False,
    limit: int = config.DEFAULT_LIMIT,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    """Mashina+haydovchi juftliklarini reytinglaydi.

    `include_blocked=True` bo'lsa kesilgan juftliklar ham qaytadi (ballari
    0, `blockers` to'ldirilgan) — "nega bu mashina ro'yxatda yo'q" degan
    savolga javob berish uchun. Endpoint uni chiqarmaydi; kutubxona
    sifatida va `python -m atil_ai_dispetcher.vehicle_selection.ranker` uchun qoldirilgan.
    """
    started = time.perf_counter()
    # Javobda transport turi NOM bo'lib chiqadi, shuning uchun filtrga
    # ham nom yozilishi tabiiy. Kod ham, nom ham (uch tilda) qabul
    # qilinadi — ichkarida esa doim KOD ishlatiladi.
    transport_type = labels.code_of("transport_type", transport_type)

    demand = _build_demand(
        route_id=route_id,
        transport_type=transport_type,
        driver_category=driver_category,
        cargo_weight_kg=cargo_weight_kg,
        cargo_volume_m3=cargo_volume_m3,
        passengers=passengers,
        origin_location_id=origin_location_id,
        destination_location_id=destination_location_id,
        on_date=on_date,
    )
    day: date = demand["on_date"]
    notes: list[str] = list(demand.pop("location_notes", []))

    vehicle_rows = queries.fetch_vehicles(
        on_date=day.isoformat(),
        window_from=_iso(demand.get("window_from")),
        window_to=_iso(demand.get("window_to")),
        transport_type=demand.get("required_transport_type"),
        limit=config.MAX_VEHICLES,
    )
    driver_rows = queries.fetch_drivers(
        on_date=day.isoformat(),
        window_from=_iso(demand.get("window_from")),
        window_to=_iso(demand.get("window_to")),
        history_days=config.HISTORY_DAYS,
        limit=config.MAX_DRIVERS,
    )
    assigned_pairs = queries.fetch_assigned_pairs()
    counts = queries.row_counts()

    if len(vehicle_rows) >= config.MAX_VEHICLES:
        notes.append(t(lang, "note.max_vehicles", limit=config.MAX_VEHICLES))
    if len(driver_rows) >= config.MAX_DRIVERS:
        notes.append(t(lang, "note.max_drivers", limit=config.MAX_DRIVERS))

    vehicles = [_evaluate_vehicle(row, demand, day, lang) for row in vehicle_rows]
    drivers = [
        _evaluate_driver(row, demand, day, require_medical=require_medical, lang=lang)
        for row in driver_rows
    ]

    free_vehicles = [v for v in vehicles if not v.blockers]
    free_drivers = [d for d in drivers if not d.blockers]

    # Kesilganlarni ham ko'rsatish so'ralgan bo'lsa juftlik yasashda
    # ishlatiladigan ro'yxat kengayadi.
    pool_vehicles = vehicles if include_blocked else free_vehicles
    pool_drivers = drivers if include_blocked else free_drivers

    estimated = len(pool_vehicles) * len(pool_drivers)
    if estimated > config.MAX_PAIRS:
        # Qirqish KO'R-KO'RONA emas: har bir tomon o'zining mavjud mezonlari
        # bo'yicha saralanadi va kuchlilari qoldiriladi.
        keep = max(1, int(config.MAX_PAIRS ** 0.5))
        pool_vehicles = sorted(pool_vehicles, key=_side_key, reverse=True)[:keep]
        pool_drivers = sorted(pool_drivers, key=_side_key, reverse=True)[:keep]
        notes.append(t(lang, "note.max_pairs", estimated=estimated,
                       limit=config.MAX_PAIRS, keep=keep))

    pairs: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}

    for veh in pool_vehicles:
        for drv in pool_drivers:
            blockers = [*veh.blockers, *drv.blockers]

            doc_crit, doc_blockers = rules.documents(
                veh.doc_check, drv.doc_check, on_date=day, lang=lang
            )
            # Hujjat kesishlari tomonlarda allaqachon sanalgan — takrorlamaymiz.
            for code in doc_blockers:
                if code not in blockers:
                    blockers.append(code)

            if blockers and not include_blocked:
                continue

            for code in blockers:
                blocker_counts[code] = blocker_counts.get(code, 0) + 1

            criteria = {
                "capacity": _copy(veh.criteria["capacity"]),
                "distance": _copy(veh.criteria["distance"]),
                "documents": doc_crit,
                "shift": _copy(drv.criteria["shift"]),
                "skill": _copy(drv.criteria["skill"]),
                "technical": _copy(veh.criteria["technical"]),
            }

            key = (veh.row["vehicle_id"], drv.row["driver_id"])
            pairs.append(
                {
                    "vehicle": veh.row,
                    "driver": drv.row,
                    "criteria": criteria,
                    "assigned_pair": key in assigned_pairs,
                    "blocked": bool(blockers),
                    "blockers": blockers,
                    "notes": [*veh.notes, *drv.notes],
                }
            )

    # Nisbiy mezonlar faqat KESILMAGAN juftliklar orasida solishtiriladi:
    # kesilganlar baribir reytingga kirmaydi, lekin ular chegaralarni
    # (eng yaqin/eng uzoq) surib yuborardi.
    _normalize([p for p in pairs if not p["blocked"]])

    weights = dict(config.WEIGHTS)
    for pair in pairs:
        if pair["blocked"]:
            pair["score"] = 0.0
            pair["assigned_bonus"] = 0.0
            pair["criteria_used"] = []
        else:
            _score_pair(pair, weights)
        pair["explanation"] = template_explanation(pair, lang)
        pair["explanation_source"] = "template"

    pairs.sort(key=lambda p: (not p["blocked"], p["score"], p["assigned_pair"]), reverse=True)
    for index, pair in enumerate(pairs, start=1):
        pair["rank"] = index

    ranked = [p for p in pairs if not p["blocked"]]
    blocked = [p for p in pairs if p["blocked"]]

    used, skipped = _criteria_coverage(ranked, lang)
    notes.extend(_data_notes(counts, demand, lang))

    result = {
        "generated_at": datetime.now(timezone.utc),
        "demand": _demand_out(demand, lang),
        "summary": {
            "vehicles_considered": len(vehicles),
            "drivers_considered": len(drivers),
            "vehicles_available": len(free_vehicles),
            "drivers_available": len(free_drivers),
            "pairs_ranked": len(ranked),
            "pairs_blocked": len(blocked),
            "weights": {k: round(v, 4) for k, v in weights.items()},
            "criteria_used": used,
            "criteria_skipped": skipped,
            "blocker_counts": dict(sorted(blocker_counts.items(), key=lambda kv: -kv[1])),
        },
        "pairs": [_pair_out(p, lang) for p in pairs[:limit]],
        # Entity exclusions remain useful even when zero pairs can be built.
        # Separate denominators: one driver can have more than one blocker.
        "eligibility": {
            kind: [
                {"code": code, "text": rules.blocker_text(code, lang),
                 "count": sum(code in side.blockers for side in sides)}
                for code in sorted({code for side in sides for code in side.blockers})
            ] for kind, sides in (("vehicles", vehicles), ("drivers", drivers))
        },
        "data_quality": {"row_counts": counts, "notes": notes},
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }

    # Bo'sh o'rin: tahlilni `explain.analyze` LLM bilan to'ldiradi.
    # Shablon matni YOZILMAYDI — LLM javob bermasa endpoint 503 qaytaradi,
    # ya'ni bu qiymat javobga faqat juftlik umuman topilmaganda chiqadi.
    result["analysis"] = {"text": "", "pairs_considered": 0}
    return result


# ------------------------------------------------------------------ Yordamchi


def _copy(crit: rules.Criterion) -> rules.Criterion:
    """Mezon nusxasi — normalizatsiya bir tomonni bir necha juftlikda
    ishlatgani uchun umumiy obyektni o'zgartirib yubormasin."""
    return rules.Criterion(
        name=crit.name,
        score=crit.score,
        value=crit.value,
        unit=crit.unit,
        detail=crit.detail,
        normalize=crit.normalize,
    )


def _side_key(side: Side) -> float:
    """Tomonni qirqishda ishlatiladigan tartib — mavjud ballar o'rtachasi."""
    scores = [c.score for c in side.criteria.values() if c.score is not None]
    return sum(scores) / len(scores) if scores else 0.0


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _criteria_coverage(
    pairs: list[dict[str, Any]], lang: str = texts.DEFAULT_LANG
) -> tuple[list[str], dict[str, str]]:
    """Qaysi mezon ballga kirdi, qaysi biri nima uchun kirmadi.

    Bu maydon SHART: mezon jimgina yo'qolib qolsa, foydalanuvchi "sig'im
    hisobga olindi" deb o'ylab qoladi.
    """
    used: list[str] = []
    skipped: dict[str, str] = {}

    for name in config.CRITERIA:
        scored = [p for p in pairs if p["criteria"].get(name) and p["criteria"][name].score is not None]
        if scored:
            used.append(name)
            continue
        reasons = {
            p["criteria"][name].detail
            for p in pairs
            if p["criteria"].get(name) and p["criteria"][name].detail
        }
        skipped[name] = (
            sorted(reasons)[0] if reasons
            else t(lang, "misc.not_rated", reason=t(lang, "misc.no_data"))
        )
    return used, skipped


def _data_notes(
    counts: dict[str, int], demand: dict[str, Any], lang: str = texts.DEFAULT_LANG
) -> list[str]:
    """Bo'sh jadvallar haqida ogohlantirish — natijani tushuntirish uchun."""
    notes: list[str] = []
    empty = [name for name, n in counts.items() if n == 0]
    if empty:
        notes.append(t(lang, "note.empty_tables", tables=", ".join(sorted(empty))))
    if not demand.get("required_driver_category"):
        notes.append(t(lang, "note.no_driver_category"))
    if demand.get("origin_latitude") is None:
        notes.append(t(lang, "note.no_pickup_coords"))
    return notes


def _demand_out(
    demand: dict[str, Any], lang: str = texts.DEFAULT_LANG
) -> dict[str, Any]:
    keys = (
        "source", "route_id", "route_number",
        "required_transport_type", "required_driver_category",
        "cargo_weight_kg", "cargo_volume_m3", "passengers",
        "origin_location_id", "origin_location_name",
        "origin_latitude", "origin_longitude",
        "destination_location_id", "destination_location_name",
        "destination_latitude", "destination_longitude",
        "total_distance_km", "window_from", "window_to", "on_date",
    )
    out = {key: demand.get(key) for key in keys}
    # Transport turi javobda KOD emas, NOM bo'lib chiqadi — juftlikdagi
    # `vehicle.transport_type` bilan bir xil bo'lishi uchun. Guvohnoma
    # toifasi (`C`, `BE`) esa xalqaro belgi, u tarjima qilinmaydi.
    out["required_transport_type"] = labels.label(
        "transport_type", demand.get("required_transport_type"), lang
    ) if demand.get("required_transport_type") else None
    return out


def _pair_out(pair: dict[str, Any], lang: str = texts.DEFAULT_LANG) -> dict[str, Any]:
    veh, drv = pair["vehicle"], pair["driver"]
    return {
        "rank": pair["rank"],
        "score": pair["score"],
        "vehicle": {
            "id": veh["vehicle_id"],
            "plate_number": veh.get("plate_number"),
            "brand": veh.get("brand"),
            "model": veh.get("model"),
            # Kod emas, NOM: javob tanlangan tilda o'qiladi.
            "transport_type": labels.label(
                "transport_type", veh.get("transport_type"), lang),
            "category": veh.get("category"),
            "current_status": labels.label(
                "vehicle_status", veh.get("current_status"), lang),
            "payload_capacity_kg": to_float(veh.get("payload_capacity_kg")),
            "volume_m3": to_float(veh.get("volume_m3")),
            "seat_count": veh.get("seat_count"),
        },
        "driver": {
            "id": drv["driver_id"],
            "full_name": drv.get("full_name"),
            "table_number": drv.get("table_number"),
            "phone": drv.get("phone"),
            "position": drv.get("position"),
            "license_categories": list(drv.get("license_categories") or []),
            "license_valid_until": drv.get("license_valid_until"),
            "availability_flag": labels.label(
                "availability", drv.get("driver_availability_status"), lang),
            "medical_status": labels.label(
                "medical", drv.get("medical_status"), lang),
            "medical_shift_date": drv.get("medical_shift_date"),
        },
        "criteria": {
            name: {
                "score": None if crit.score is None else round(crit.score, 4),
                "value": None if crit.value is None else round(crit.value, 3),
                "unit": crit.unit,
                "weight": crit.weight,
                "detail": crit.detail,
            }
            for name, crit in pair["criteria"].items()
        },
        "criteria_used": pair["criteria_used"],
        "assigned_pair": pair["assigned_pair"],
        "assigned_bonus": pair["assigned_bonus"],
        "blocked": pair["blocked"],
        "blockers": [
            {"code": code, "text": rules.blocker_text(code, lang)}
            for code in pair["blockers"]
        ],
        "notes": pair["notes"],
        "explanation": pair["explanation"],
        "explanation_source": pair["explanation_source"],
    }


if __name__ == "__main__":  # pragma: no cover
    # Serversiz tez tekshirish:
    #   python -m atil_ai_dispetcher.vehicle_selection.ranker <route_id>
    #   python -m atil_ai_dispetcher.vehicle_selection.ranker --type DUMP_TRUCK --category C
    import json
    import sys

    args = sys.argv[1:]
    kwargs: dict[str, Any] = {}
    if len(args) == 1 and not args[0].startswith("--"):
        kwargs["route_id"] = args[0]
    else:
        for i in range(0, len(args) - 1, 2):
            if args[i] == "--type":
                kwargs["transport_type"] = args[i + 1]
            elif args[i] == "--category":
                kwargs["driver_category"] = args[i + 1]
    if not kwargs:
        print("Foydalanish: python -m atil_ai_dispetcher.vehicle_selection.ranker <route_id>")
        print("         yoki python -m atil_ai_dispetcher.vehicle_selection.ranker --type DUMP_TRUCK --category C")
        raise SystemExit(2)
    print(json.dumps(rank(**kwargs), ensure_ascii=False, indent=2, default=str))
