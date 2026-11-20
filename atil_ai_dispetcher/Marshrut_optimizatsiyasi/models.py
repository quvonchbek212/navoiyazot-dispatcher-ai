"""Javob sxemasi — Swagger shu modellardan chiziladi.

Javob ATAYLAB qat'iy tiplangan: rejani keyin dispetcher paneli, `route`
jadvaliga yozadigan servis yoki ERP o'qiydi. Kalitlar nomi o'zgarib
ketmasligi uchun ular Pydantic modelida qulflangan.

IKKI QOIDA BUTUN SXEMA BO'YICHA:

  1. `null` — NOL EMAS. `duration_minutes: null` "vaqt nol" degani emas,
     "tezlik noma'lum, vaqt hisoblanmadi" degani. Sababi har doim
     `calibration` va `data_quality.notes` da yozilgan.

  2. Joylanmagan ariza JIMGINA YO'QOLMAYDI. Har bir joylanmagan ariza
     `unassigned` da SABABI bilan qaytadi. "Reja tayyor" deb 40 tadan
     12 tasini ko'rsatish — eng qimmat xato.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------- Kirish


class ManualStop(BaseModel):
    """POST uchun qo'lda beriladigan nuqta.

    Bazada koordinata to'lmaguncha modulni SHU ORQALI sinash mumkin:
    nuqtalar va mashinalar so'rovning o'zida beriladi, bazaga umuman
    murojaat qilinmaydi.
    """

    id: str = Field(..., description="Ariza/yuk id — pickup va delivery shu id bilan bog'lanadi")
    number: str | None = Field(None, description="Ariza raqami (javobda ko'rinadi)", examples=["TR-1042"])
    pickup_name: str | None = Field(None, examples=["Navoiyazot, Sex 14"])
    pickup_latitude: float = Field(..., ge=-90, le=90)
    pickup_longitude: float = Field(..., ge=-180, le=180)
    dropoff_name: str | None = Field(None, examples=["Samarqand ombori"])
    dropoff_latitude: float = Field(..., ge=-90, le=90)
    dropoff_longitude: float = Field(..., ge=-180, le=180)
    weight_kg: float | None = Field(None, ge=0)
    volume_m3: float | None = Field(None, ge=0)
    required_transport_type: str | None = Field(None, examples=["DUMP_TRUCK"])
    priority: str | None = Field("NORMAL", examples=["HIGH"])
    pickup_from: datetime | None = Field(None, description="Yuklash oynasi boshi")
    pickup_to: datetime | None = Field(None, description="Yuklash oynasi oxiri")
    dropoff_from: datetime | None = None
    dropoff_to: datetime | None = Field(None, description="Yetkazish muddati")
    service_minutes: float | None = Field(
        None, ge=0, description="Har bir nuqtadagi xizmat vaqti. Berilmasa kalibrovkadan")


class ManualVehicle(BaseModel):
    """POST uchun qo'lda beriladigan mashina."""

    id: str
    plate_number: str | None = Field(None, examples=["85896SAA"])
    transport_type: str | None = Field(None, examples=["DUMP_TRUCK"])
    capacity_kg: float | None = Field(None, ge=0)
    capacity_m3: float | None = Field(None, ge=0)
    start_latitude: float = Field(..., ge=-90, le=90, description="Mashina hozir qayerda / garaj")
    start_longitude: float = Field(..., ge=-180, le=180)
    start_name: str | None = Field(None, examples=["Garaj"])
    shift_from: datetime | None = Field(None, description="Smena boshi")
    shift_to: datetime | None = Field(None, description="Smena oxiri")
    max_duration_minutes: float | None = Field(None, ge=0, description="Reysning eng ko'p davomiyligi")
    driver_id: str | None = None
    driver_name: str | None = None
    return_to_start: bool = Field(True, description="Oxirida boshlang'ich nuqtaga qaytadimi")


class PlanRequest(BaseModel):
    """`POST /route-optimization/plan` tanasi — BITTA model, ikki rejim.

    Hamma maydon ixtiyoriy. Rejimni `stops` belgilaydi:

        {}                        -> bazadan o'qiladi (bugungi arizalar)
        {"stops": [...], ...}     -> shu nuqtalar bilan, bazaga tegilmaydi

    Ikkinchi rejim bazada koordinata to'lmaguncha kerak
    (`transport_request.origin_latitude` hozir 55 arizadan 0 tasida bor),
    va keyin ham qoladi: tashqi tizimdan kelgan ma'lumot bilan reja
    tuzish yoki "agar shunday qilsak nima bo'ladi" savoliga javob berish
    uchun.
    """

    # ------------------------------------------------------- Umumiy sozlama
    #
    # `lang` BU YERDA EMAS, QUERY PARAMETRDA (`?lang=ru`). Sabab: til —
    # javobning ko'rinishi, rejalashtirish masalasining bir qismi emas.
    # Query'da bo'lgani uchun Swagger uni RO'YXAT qilib ko'rsatadi va
    # tanani umuman ochmasdan tilni tanlash mumkin.
    objective: Literal["distance", "duration", "balanced"] | None = Field(
        None,
        description="Nima minimallashtirilsin. Berilmasa `.env` dagi `RO_OBJECTIVE`. "
                    "**Tezlik noma'lum bo'lsa avtomatik `distance` ga tushadi** — "
                    "vaqtni hisoblab bo'lmasa uni minimallashtirish yolg'on bo'lardi.",
    )
    respect_time_windows: bool = Field(
        True,
        description="Vaqt oynasi qattiq cheklovmi. `false` qilinsa kechikish mumkin, "
                    "lekin har biri javobda daqiqasigacha ko'rsatiladi.",
    )
    average_speed_kph: float | None = Field(
        None, gt=0,
        description="O'rtacha yo'l tezligi. Berilmasa **bazadan o'lchanadi** "
                    "(`trip` dagi haqiqiy reyslar, yetmasa `route_point`). "
                    "O'lchanmasa vaqt umuman hisoblanmaydi.",
    )
    # -------------------------------------------------- 1-rejim: bazadan
    on_date: date | None = Field(
        None,
        description="Reja sanasi. Shu sanagacha jo'nashi kerak bo'lgan arizalar "
                    "olinadi — kechagi rejalashtirilmagani ham tushadi, aks holda u "
                    "abadiy osilib qolardi. Berilmasa **bugun**. "
                    "`stops` berilgan bo'lsa e'tiborsiz qoldiriladi.",
    )
    request_ids: list[str] = Field(
        default_factory=list,
        description="Aniq arizalar. Berilsa **holat filtri o'chadi**: dispetcher aniq "
                    "arizani ko'rsatgan bo'lsa uning holati bizga emas, unga tegishli.",
    )
    depot_latitude: float | None = Field(
        None, ge=-90, le=90,
        description="Garaj (chiqish nuqtasi) kengligi. Mashinaning turgan joyi "
                    "`vehicle_telemetry_state` dan olinadi; u bo'sh bo'lsa "
                    "(hozir 0 qator) **shu garaj** ishlatiladi. Ikkalasi ham "
                    "bo'lmasa mashina rejaga kirmaydi.",
    )
    depot_longitude: float | None = Field(None, ge=-180, le=180, description="Garaj uzunligi")
    window_from: datetime | None = Field(
        None,
        description="Reja oynasining boshi. **Bandlik shu oyna bilan solishtiriladi**: "
                    "ertalabki reysini 11:00 da tugatadigan mashina tushdan keyingi "
                    "rejaga kiradi. Berilmasa `on_date` ning boshi.",
    )
    window_to: datetime | None = Field(
        None, description="Reja oynasining oxiri. Berilmasa `on_date` ning oxiri.")

    # --------------------------------------------------- 2-rejim: qo'lda
    stops: list[ManualStop] = Field(
        default_factory=list,
        description="Tashiladigan yuklar. **Berilsa bazaga umuman murojaat "
                    "qilinmaydi** va `vehicles` ham berilishi shart.",
    )
    vehicles: list[ManualVehicle] = Field(
        default_factory=list,
        description="Mavjud mashinalar — faqat `stops` bilan birga ishlatiladi.")
    road_factor: float | None = Field(
        None, gt=0,
        description="To'g'ri chiziqni yo'l masofasiga aylantiruvchi koeffitsient "
                    "(1.0 = to'g'ri chiziq). Qo'lda rejimda kerak, chunki u yerda "
                    "kalibrovka bazadan olinmaydi.",
    )

    @model_validator(mode="after")
    def _check_manual_pair(self) -> "PlanRequest":
        """Qo'lda rejimda ikkala ro'yxat ham bo'lishi shart.

        Faqat `stops` berilsa mashina yo'q — hamma ariza "mashina qolmadi"
        bilan qaytardi va foydalanuvchi nima xato qilganini bilmasdi.
        Shuning uchun bu jimgina o'tkazilmaydi.
        """
        if self.stops and not self.vehicles:
            raise ValueError("`stops` berilgan bo'lsa `vehicles` ham berilishi kerak")
        if self.vehicles and not self.stops:
            raise ValueError("`vehicles` berilgan bo'lsa `stops` ham berilishi kerak")
        return self


# ---------------------------------------------------------------- Chiqish


class Calibration(BaseModel):
    """Model parametrlari QAYERDAN olingani.

    Bu maydon SHART: reja raqamlari shu uch qiymatga tayanadi va ular
    o'ylab topilgan emasligi ko'rinib turishi kerak.
    """

    road_factor: float | None = Field(
        None, description="To'g'ri chiziq -> yo'l masofasi koeffitsienti")
    road_factor_source: str = Field("unknown", examples=["route_point", "request", "env", "unknown"])
    road_factor_samples: int = 0

    average_speed_kph: float | None = Field(None, description="O'rtacha yo'l tezligi")
    speed_source: str = Field("unknown", examples=["trip", "route_point", "request", "env", "unknown"])
    speed_samples: int = 0

    service_minutes: float | None = Field(
        None, description="Bitta nuqtadagi yuklash/tushirish vaqti")
    service_source: str = Field("unknown", examples=["trip_event", "request", "env", "unknown"])
    service_samples: int = 0

    distance_source: Literal["osrm", "haversine"] = Field(
        "haversine", description="Masofa haqiqiy yo'l bo'yichami yoki to'g'ri chiziqmi")
    time_aware: bool = Field(
        False,
        description="Vaqt hisoblandimi. `false` bo'lsa vaqt oynasi, smena va "
                    "xizmat vaqti TEKSHIRILMAGAN — tezlik noma'lum",
    )
    notes: list[str] = Field(default_factory=list)


class StopPlan(BaseModel):
    """Marshrutdagi bitta to'xtash."""

    sequence: int = Field(..., description="Tartib raqami, 0 — chiqish nuqtasi")
    kind: Literal["START", "PICKUP", "DELIVERY", "END"]
    request_id: str | None = None
    request_number: str | None = None
    location_id: str | None = None
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_from_previous_km: float | None = None
    travel_minutes_from_previous: float | None = None
    arrival_at: datetime | None = Field(None, description="Tezlik noma'lum bo'lsa null")
    wait_minutes: float | None = Field(None, description="Oyna ochilishini kutish")
    service_minutes: float | None = None
    departure_at: datetime | None = None
    window_from: datetime | None = None
    window_to: datetime | None = None
    late_minutes: float | None = Field(
        None, description="Oynadan kechikish. >0 faqat `respect_time_windows=false` da")
    load_after_kg: float | None = Field(None, description="Shu nuqtadan keyingi yuk, kg")
    load_after_m3: float | None = None


class VehicleRoute(BaseModel):
    """Bitta mashinaga tushgan marshrut."""

    vehicle_id: str
    plate_number: str | None = None
    brand: str | None = None
    model: str | None = None
    transport_type: str | None = Field(
        None, description="So'rovdagi `lang` tilida", examples=["samosval"])
    driver_id: str | None = None
    driver_name: str | None = None

    requests: list[str] = Field(
        default_factory=list, description="Shu marshrutga kirgan ariza raqamlari")
    stops: list[StopPlan] = Field(default_factory=list)

    total_distance_km: float = 0.0
    total_duration_minutes: float | None = Field(
        None, description="Yo'l + kutish + xizmat. Tezlik noma'lum bo'lsa null")
    driving_minutes: float | None = None
    waiting_minutes: float | None = None
    service_minutes_total: float | None = None
    late_minutes_total: float | None = None

    max_load_kg: float | None = None
    capacity_kg: float | None = None
    capacity_utilization: float | None = Field(
        None, ge=0, description="Eng yuqori yuk / sig'im. Sig'im noma'lum bo'lsa null")

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    explanation: str = Field("", description="O'zbekcha qisqa izoh")


class UnassignedRequest(BaseModel):
    """Rejaga tushmagan ariza — SABABI bilan.

    Sabab kodlari:
      `NO_COORDINATES`      — nuqtaning koordinatasi yo'q, masofa hisoblanmaydi
      `NO_MATCHING_VEHICLE` — talab qilingan transport turi bo'sh mashinalarda yo'q
      `CAPACITY`            — hech bir mashinaning sig'imi yetmaydi
      `TIME_WINDOW`         — vaqt oynasiga ulgurib bo'lmaydi
      `SHIFT_LIMIT`         — smena/reys davomiyligi chegarasidan oshadi
      `HAZARD`              — xavfli yuk maxsus sisterna talab qiladi
      `BOUND_VEHICLE_UNAVAILABLE` — bazada biriktirilgan mashina bo'sh emas
      `NO_VEHICLE_LEFT`     — bo'sh mashina qolmadi (hammasi to'lgan)
    """

    request_id: str
    request_number: str | None = None
    priority: str | None = None
    required_transport_type: str | None = Field(
        None,
        description="Talab qilingan transport turi — so'rovdagi `lang` "
                    "tilida (`AERIAL_PLATFORM` -> \"havo platformasi\")",
        examples=["havo platformasi"],
    )
    weight_kg: float | None = None
    origin_name: str | None = None
    destination_name: str | None = None
    reason_code: str = Field(..., examples=["NO_COORDINATES"])
    reason: str = Field(..., description="O'zbekcha sabab")


class PlanSummary(BaseModel):
    requests_considered: int = 0
    requests_assigned: int = 0
    requests_unassigned: int = 0
    vehicles_considered: int = Field(0, description="Rejalashtirishga tayyor (bo'sh) mashinalar")
    vehicles_used: int = 0
    total_distance_km: float = 0.0
    total_duration_minutes: float | None = None
    total_late_minutes: float | None = None
    objective: str = Field("balanced", examples=["balanced"])
    objective_value: float | None = Field(
        None, description="Yechim narxi — faqat variantlarni solishtirish uchun")
    baseline_distance_km: float | None = Field(
        None,
        description="Optimizatsiyasiz variant: har ariza alohida mashinada "
                    "(chiqish -> yuklash -> tushirish -> qaytish). Foydani shunga solishtiramiz",
    )
    saved_distance_km: float | None = None
    saved_percent: float | None = None
    unassigned_reasons: dict[str, int] = Field(
        default_factory=dict, description="Sabab kodi -> nechta ariza")
    improvement_rounds: int = Field(0, description="Yaxshilash sikli necha marta ishladi")
    time_budget_hit: bool = Field(
        False, description="Vaqt byudjeti tugadimi — tugagan bo'lsa yechim yanada yaxshilanishi mumkin")


class Analysis(BaseModel):
    """Reja bo'yicha umumiy tahlil.

    Rejani ARIFMETIKA quradi, bu matnni esa LLM yozadi.

    MATN FAQAT LLM DAN. Shablon bilan to'ldirilmaydi: LLM javob bermasa
    endpoint 503 qaytaradi. Marshrutning O'Z `explanation` i esa shablon
    bilan yoziladi va LLM ga bog'liq emas.
    """

    text: str = ""
    routes_considered: int = 0


class RequirementSource(BaseModel):
    """Talabni qondira oladigan bitta jadval."""

    table: str = Field(..., examples=["transport_request"])
    columns: list[str] = Field(
        default_factory=list,
        description="Shu jadvalda to'lishi kerak bo'lgan ustunlar",
        examples=[["origin_latitude", "origin_longitude"]],
    )
    rows: int = Field(0, description="Jadvaldagi jami qator")
    usable_rows: int = Field(
        0, description="Kerakli ustunlari to'lgan va sharti mos qator")
    ready: bool = Field(False, description="Shu manbaning o'zi yetadimi")


class DataRequirement(BaseModel):
    """Reja tuzish uchun bazadan nima kerakligi — MANZIL bilan.

    Bu maydon "ma'lumot yo'q" degan javobni "aynan SHU jadvalning SHU
    ustuni to'ldirilsin" degan topshiriqqa aylantiradi. Ma'lumot kiritilgan
    sari `ready` o'zi `true` bo'ladi — kod o'zgarmaydi.
    """

    need: str = Field(..., description="Talab kaliti", examples=["request_coordinates"])
    title: str = Field(..., description="O'zbekcha nomi")
    blocking: bool = Field(
        ..., description="`true` — busiz reja UMUMAN chiqmaydi; `false` — reja "
                         "chiqadi, lekin bitta cheklov tekshirilmay qoladi")
    ready: bool = Field(..., description="Hozir bajarilganmi")
    impact: str = Field(..., description="To'lmasa rejaga nima bo'ladi")
    sources: list[RequirementSource] = Field(
        default_factory=list,
        description="Manbalar kod qaraydigan TARTIBDA. Odatda bittasi yetadi "
                    "(zanjir); sig'im va xavfli yukda esa hammasi kerak",
    )
    hint: str = Field("", description="Nima qilinsa bajariladi")
    note: str = Field(
        "", description="Qo'shimcha holat: masalan qator bor-u qiymatlar xato")


class DataQuality(BaseModel):
    """Qaysi manbada ma'lumot bor va nima yetishmayapti.

    Bu maydon SHART: manba bo'sh bo'lsa javob "reja chiqmadi" bo'lib
    ko'rinadi. Aslida "rejalashtirishga ma'lumot yo'q".

    `row_counts` — jadvallardagi HAQIQIY qator soni (`count(*)`).
    `requirements` — nima yetishmayotgani, to'lmaganlari birinchi bo'lib.
    """

    ready: bool = Field(
        True,
        description="Bloklovchi talablarning hammasi bajarilganmi, ya'ni "
                    "bazadan reja tuzsa bo'ladimi. Qo'lda rejimda doim `true`",
    )
    row_counts: dict[str, int] = Field(default_factory=dict)
    requirements: list[DataRequirement] = Field(
        default_factory=list,
        description="Bajarilmaganlari birinchi, ichida bloklovchilari oldinda. "
                    "Qo'lda rejimda bo'sh — bazaga murojaat qilinmaydi",
    )
    notes: list[str] = Field(default_factory=list)


class PlanScope(BaseModel):
    """Nima rejalashtirildi — kirish ma'lumoti javobda takrorlanadi."""

    source: Literal["database", "manual"] = "database"
    on_date: date | None = None
    statuses: list[str] = Field(default_factory=list)
    request_ids: list[str] = Field(default_factory=list)
    window_from: datetime | None = Field(
        None, description="Bandlik shu oyna bilan solishtirildi")
    window_to: datetime | None = None
    depot_location_id: str | None = None
    depot_name: str | None = None
    depot_latitude: float | None = None
    depot_longitude: float | None = None
    respect_time_windows: bool = True
    respect_capacity: bool = True
    hazard_summary: dict[str, int] = Field(
        default_factory=dict,
        description="Xavfli yuk: `hazardous_requests`, `tank_required`, "
                    "`adr_required`. `shipment` -> `hazard_profile` zanjiridan "
                    "AVTOMATIK aniqlanadi. **Kalitlar tildan xoli** — ularni "
                    "dastur o'qiydi, shuning uchun `lang` ga qarab o'zgarmaydi",
    )
    locked_requests: int = Field(
        0,
        description="Bazada mashinaga biriktirilgan arizalar soni "
                    "(`binding_vehicle_id`) — ular ko'chirilmadi",
    )


class RoutePlanReport(BaseModel):
    generated_at: datetime
    scope: PlanScope
    calibration: Calibration
    summary: PlanSummary
    analysis: Analysis = Field(default_factory=Analysis)
    routes: list[VehicleRoute] = Field(default_factory=list)
    unassigned: list[UnassignedRequest] = Field(default_factory=list)
    data_quality: DataQuality
    elapsed_seconds: float = 0.0
