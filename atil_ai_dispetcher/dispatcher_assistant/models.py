"""Javob sxemasi — Swagger shu modellardan chiziladi.

TO'RTTA ENDPOINT, BITTA KONVERT. Har biri o'z qatorlarini qaytaradi,
lekin tashqi tuzilma bir xil:

    generated_at, scope, summary, items[], analysis, data_quality, elapsed_seconds

Shu tufayli dispetcher paneli to'rt bo'limni bitta komponent bilan
chizadi va yangi bo'lim qo'shilganda kod o'zgarmaydi.

IKKI QOIDA BUTUN SXEMA BO'YICHA:

  1. `null` — NOL EMAS. `minutes_since_last_event: null` "hozirgina
     aloqa bo'ldi" degani emas, "telematika yozuvi yo'q" degani.

  2. Tekshirilmagan narsa "muammo yo'q" deb ko'rsatilmaydi. Manba
     jadval bo'sh bo'lsa `data_quality.notes` da ochiq yoziladi —
     bo'sh ro'yxat "hammasi joyida" degani emas.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------- Umumiy


class Summary(BaseModel):
    total: int = Field(0, description="Topilgan qatorlar soni (limitgacha qirqilmagan)")
    returned: int = Field(0, description="Javobda qaytgan qatorlar soni")
    by_kind: dict[str, int] = Field(
        default_factory=dict, description="Tur bo'yicha taqsimot")
    worst: str | None = Field(
        None, description="Eng og'ir qator — qisqa matn bilan")
    expired: int | None = Field(
        None,
        description="Muddati O'TGANLAR soni. Faqat `/documents` da to'ladi — "
                    "muddati o'tgan hujjat bilan tugayotgani bir xil emas",
    )


class Analysis(BaseModel):
    """Ro'yxat bo'yicha bir xatboshi xulosa.

    Ro'yxatni ARIFMETIKA quradi, bu matnni LLM yozadi. LLM o'chirilgan
    yoki Ollama ishlamayotgan bo'lsa `source` `"template"` bo'lib
    qoladi — javob baribir to'liq.
    """

    text: str = ""
    source: Literal["template", "llm"] = "template"
    items_considered: int = 0


class DataQuality(BaseModel):
    """Qaysi manbada ma'lumot bor.

    Bu maydon SHART: manba bo'sh bo'lsa javob "muammo yo'q" bo'lib
    ko'rinadi. Aslida "tekshirishga ma'lumot yo'q".
    """

    row_counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class Scope(BaseModel):
    checked_at: datetime = Field(..., description="Qaysi paytga nisbatan tekshirildi")
    filters: dict[str, Any] = Field(
        default_factory=dict, description="So'rovda berilgan filtrlar")


# ------------------------------------------------------- 1. Kechikish


class DelayedTrip(BaseModel):
    """Kechikayotgan bitta reys.

    IKKI XIL KECHIKISH BOR va ular bir xil emas:

      `NOT_DEPARTED`   jo'nash vaqti o'tgan, mashina hali yo'lga
                       chiqmagan. Dispetcher hali TO'XTATA oladi.
      `LATE_EN_ROUTE`  yo'lda, lekin yetib borish vaqti o'tgan.
                       Endi faqat mijozni ogohlantirish qoladi.

    Shuning uchun ular alohida `kind` bilan qaytadi va aralashtirilmaydi.
    """

    kind: Literal["NOT_DEPARTED", "LATE_EN_ROUTE"]
    trip_id: str
    trip_number: str | None = None
    status: str | None = None
    delay_minutes: float = Field(..., description="Hozirgi vaqtdan orqada qolgan daqiqa")

    scheduled_departure_at: datetime | None = None
    actual_departure_at: datetime | None = None
    scheduled_arrival_at: datetime | None = None

    vehicle_id: str | None = None
    plate_number: str | None = None
    driver_id: str | None = None
    driver_name: str | None = None
    driver_phone: str | None = None

    route_id: str | None = None
    route_number: str | None = None
    request_number: str | None = None
    destination: str | None = None

    last_event_type: str | None = Field(
        None, description="Oxirgi `trip_event` — reys qayerda to'xtab qolgani")
    last_event_at: datetime | None = None


class DelayedReport(BaseModel):
    generated_at: datetime
    scope: Scope
    summary: Summary
    analysis: Analysis = Field(default_factory=Analysis)
    items: list[DelayedTrip] = Field(default_factory=list)
    data_quality: DataQuality
    elapsed_seconds: float = 0.0


# ------------------------------------------------- 2. Yo'nalishdan og'ish


class Deviation(BaseModel):
    """Yo'nalishdan og'gan bitta mashina.

    OG'ISHNI BU MODUL ANIQLAMAYDI. Uni telematika xizmati aniqlaydi va
    `vehicle_telemetry_state.deviation_active` ga yozadi; chegara ham
    o'sha yerda — `deviation_threshold_meters`. Bu endpoint o'sha
    natijani o'qiydi va odam o'qiydigan holga keltiradi.

    `distance_from_route_meters` — qo'shimcha o'lchov: mashinaning
    hozirgi nuqtasidan rejadagi yo'lgacha bo'lgan masofa. U
    `route_points_json` bo'lganda hisoblanadi, bo'lmasa `null`.
    """

    vehicle_id: str
    plate_number: str | None = None
    driver_id: str | None = None
    driver_name: str | None = None
    driver_phone: str | None = None

    deviation_active: bool = True
    threshold_meters: float | None = Field(
        None, description="Bazadagi chegara (`deviation_threshold_meters`)")
    distance_from_route_meters: float | None = Field(
        None, description="Rejadagi yo'ldan qancha chetda. Hisoblanmasa null")

    trip_id: str | None = None
    trip_number: str | None = None
    route_id: str | None = None
    route_number: str | None = None

    latitude: float | None = None
    longitude: float | None = None
    speed_kph: float | None = None
    heading: float | None = None
    last_event_at: datetime | None = None
    minutes_since_last_event: float | None = Field(
        None, description="Oxirgi GPS yozuvidan beri o'tgan vaqt")


class DeviationReport(BaseModel):
    generated_at: datetime
    scope: Scope
    summary: Summary
    analysis: Analysis = Field(default_factory=Analysis)
    items: list[Deviation] = Field(default_factory=list)
    data_quality: DataQuality
    elapsed_seconds: float = 0.0


# --------------------------------------------------------- 3. Bekor turish


class IdleVehicle(BaseModel):
    """Bekor turgan bitta mashina.

    "UZOQ" DEGAN CHEGARA YO'Q. Ro'yxat to'xtash davomiyligi bo'yicha
    saralanadi — eng uzog'i tepada. Kesish kerak bo'lsa chaqiruvchi
    `min_minutes` beradi.

    `minutes_since_last_event` MUHIM: GPS uzilib qolgan mashina ham
    "to'xtagan" bo'lib ko'rinadi. Ikkalasini ajratish uchun oxirgi
    yozuv vaqti har doim qaytadi.
    """

    vehicle_id: str
    plate_number: str | None = None
    driver_id: str | None = None
    driver_name: str | None = None
    driver_phone: str | None = None

    stop_active: bool = True
    stopped_since: datetime | None = Field(
        None, description="`stop_candidate_since` — qachondan beri turibdi")
    stopped_minutes: float | None = Field(
        None, description="Hozirgacha bo'lgan to'xtash davomiyligi")
    idle_time_seconds: int | None = Field(
        None, description="Telematika hisoblagan jami bekor turish")
    moving_time_seconds: int | None = None

    engine_on: bool | None = Field(
        None, description="Dvigatel ishlab turibdimi — yoqilg'i behuda yonmoqdami")
    speed_kph: float | None = None
    latitude: float | None = None
    longitude: float | None = None

    trip_id: str | None = None
    trip_number: str | None = None
    route_number: str | None = None

    last_event_at: datetime | None = None
    minutes_since_last_event: float | None = Field(
        None, description="GPS uzilganini shundan bilinadi")


class IdleReport(BaseModel):
    generated_at: datetime
    scope: Scope
    summary: Summary
    analysis: Analysis = Field(default_factory=Analysis)
    items: list[IdleVehicle] = Field(default_factory=list)
    data_quality: DataQuality
    elapsed_seconds: float = 0.0


# ------------------------------------------------------- 4. Hujjat muddati


class ExpiringDocument(BaseModel):
    """Muddati tugayotgan yoki tugagan bitta hujjat.

    KUNLIK KO'RIKLAR BU YERGA KIRMAYDI. `medical_inspection` va
    `vehicle_technical_inspection` (PRE_TRIP) har kuni yangilanadi —
    ularning "muddati" ertaga tugaydi va bu normal holat. Ro'yxatga
    qo'shilsa har kuni 200 dan ortiq qator chiqib, haqiqiy muammoni
    ko'mib tashlardi. Reysga chiqishga tayyorlikni `vehicle-selection`
    tekshiradi.

    Bu yerda faqat UZOQ MUDDATLI hujjatlar: guvohnoma, tibbiy
    sertifikat, mashina hujjatlari, sug'urta.
    """

    subject_type: Literal["DRIVER", "VEHICLE"]
    subject_id: str
    subject_name: str | None = Field(None, description="Haydovchi ismi yoki davlat raqami")
    document_type: str = Field(
        ..., description="LICENSE, MEDICAL_CERTIFICATE, CREDENTIAL, VEHICLE_DOCUMENT, INSURANCE")
    document_label: str | None = Field(None, description="Hujjat nomi yoki raqami")
    valid_until: date = Field(..., description="Muddat tugash sanasi")
    days_left: int = Field(
        ..., description="Bugundan necha kun qolgan. MANFIY — muddati o'tgan")
    expired: bool = Field(..., description="Muddati o'tganmi")
    source_table: str = Field(..., description="Qaysi jadvaldan olingani")

    driver_phone: str | None = None
    department: str | None = None


class DocumentsReport(BaseModel):
    generated_at: datetime
    scope: Scope
    summary: Summary
    analysis: Analysis = Field(default_factory=Analysis)
    items: list[ExpiringDocument] = Field(default_factory=list)
    data_quality: DataQuality
    elapsed_seconds: float = 0.0
