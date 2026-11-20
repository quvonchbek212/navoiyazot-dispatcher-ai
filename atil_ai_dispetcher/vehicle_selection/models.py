"""Javob sxemasi — Swagger shu modellardan chiziladi.

Javob ATAYLAB qat'iy tiplangan: natijani keyin dispetcher paneli, Telegram
bot yoki ERP o'qiydi. Kalitlar nomi o'zgarib ketmasligi uchun ular Pydantic
modelida qulflangan.

DIQQAT: har bir mezon balli `null` bo'la oladi va bu NOL EMAS. `null` —
"baholanmadi", nol — "baholandi va yomon". Farqi `criteria[...].detail` da
matn bilan ham yoziladi.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class VehicleRef(BaseModel):
    id: str
    plate_number: str | None = Field(None, examples=["85896SAA"])
    brand: str | None = Field(None, examples=["Isuzu"])
    model: str | None = None
    transport_type: str | None = Field(None, examples=["FLATBED"])
    category: str | None = Field(None, examples=["HEAVY"])
    current_status: str | None = Field(
        None, description="Bazadagi bayroq. DIQQAT: bandlikni bu emas, `trip`/`waybill` belgilaydi")
    payload_capacity_kg: float | None = None
    volume_m3: float | None = None
    seat_count: int | None = None


class DriverRef(BaseModel):
    id: str
    full_name: str | None = Field(None, examples=["Abdullayev Sherzod Sayfullayevich"])
    table_number: str | None = None
    phone: str | None = None
    position: str | None = None
    license_categories: list[str] = Field(default_factory=list, examples=[["B", "C", "CE"]])
    license_valid_until: date | None = None
    availability_flag: str | None = Field(
        None,
        description="`driver.driver_availability_status`. DIQQAT: 22.08.2026 da bu "
                    "bayroq yangilanmayotgani aniqlandi — bandlik `trip`/`waybill` dan olinadi",
    )
    medical_status: str | None = Field(None, description="Oxirgi `medical_inspection.status`")
    medical_shift_date: date | None = Field(None, description="Oxirgi ko'rik sanasi")


class CriterionScore(BaseModel):
    """Bitta mezon natijasi.

    `score` `null` bo'lsa mezon reytingga KIRMAGAN va og'irligi qolgan
    mezonlarga qayta taqsimlangan. Sababi `detail` da yozilgan.
    """

    score: float | None = Field(None, ge=0.0, le=1.0, description="0..1 yoki null (baholanmadi)")
    value: float | None = Field(None, description="Xom o'lchov: km, kun, ulush, reys soni")
    unit: str | None = Field(None, examples=["km"])
    weight: float = Field(0.0, description="Shu juftlik uchun amalda qo'llangan og'irlik")
    detail: str = Field("", description="Ball qanday chiqqani — o'zbekcha")


class Blocker(BaseModel):
    code: str = Field(..., examples=["LICENSE_CATEGORY_MISMATCH"])
    text: str = Field(..., description="O'zbekcha sabab")


class Pair(BaseModel):
    """Bitta mashina+haydovchi varianti."""

    rank: int = Field(..., description="1 — eng mos variant")
    score: float = Field(..., ge=0.0, le=1.0, description="Umumiy ball (og'irlikli o'rtacha)")
    vehicle: VehicleRef
    driver: DriverRef
    criteria: dict[str, CriterionScore] = Field(
        default_factory=dict,
        description="Olti mezon: capacity, distance, documents, shift, skill, technical",
    )
    criteria_used: list[str] = Field(
        default_factory=list, description="Ballga aslida kirgan mezonlar")
    assigned_pair: bool = Field(
        False, description="Bazada oldindan biriktirilgan juftlikmi (ustama ball oladi)")
    assigned_bonus: float = Field(0.0, description="Biriktirilgan juftlikka qo'shilgan ustama")
    blocked: bool = Field(False, description="Kesilganmi (faqat `include_blocked=true` da qaytadi)")
    blockers: list[Blocker] = Field(default_factory=list, description="Kesish sabablari")
    notes: list[str] = Field(default_factory=list)
    explanation: str = Field("", description="O'zbekcha qisqa xulosa")
    explanation_source: Literal["template", "llm"] = "template"


class Demand(BaseModel):
    """Tanlash nima uchun qilingani — kirish ma'lumoti javobda takrorlanadi."""

    source: Literal["route", "manual"] = Field(
        ..., description="Talab marshrutdan o'qildimi yoki parametrlardan yig'ildimi")
    route_id: str | None = None
    route_number: str | None = None
    required_transport_type: str | None = None
    required_driver_category: str | None = None
    cargo_weight_kg: float | None = None
    cargo_volume_m3: float | None = None
    passengers: int | None = None

    origin_location_id: str | None = None
    origin_location_name: str | None = Field(
        None, description="`route_point` dan yechilgan nom", examples=["Цех №014"])
    origin_latitude: float | None = None
    origin_longitude: float | None = None

    destination_location_id: str | None = None
    destination_location_name: str | None = Field(
        None, examples=["Склад готовой продукции"])
    destination_latitude: float | None = Field(
        None,
        description="Manzil koordinatasi javobda qaytadi, lekin bugun reytingga "
                    "ta'sir qilmaydi — sababi `ranker._resolve_locations` da",
    )
    destination_longitude: float | None = None

    total_distance_km: float | None = Field(
        None, description="Reysning o'z uzunligi (`route_point` yig'indisi)")
    window_from: datetime | None = Field(
        None, description="Reys oynasi boshi — marshrutdan olinadi")
    window_to: datetime | None = Field(
        None, description="Reys oynasi oxiri — marshrutdan olinadi")
    on_date: date


class Summary(BaseModel):
    vehicles_considered: int = 0
    drivers_considered: int = 0
    vehicles_available: int = Field(
        0, description="Kesishdan o'tgan mashinalar (bo'sh va yaroqli)")
    drivers_available: int = Field(
        0, description="Kesishdan o'tgan haydovchilar (bo'sh va yaroqli)")
    pairs_ranked: int = 0
    pairs_blocked: int = 0
    weights: dict[str, float] = Field(
        default_factory=dict, description="`.env` dagi asosiy og'irliklar")
    criteria_used: list[str] = Field(
        default_factory=list, description="Kamida bitta juftlikda ballga kirgan mezonlar")
    criteria_skipped: dict[str, str] = Field(
        default_factory=dict,
        description="Baholanmagan mezon -> sababi. Bu maydon SHART: mezon jimgina "
                    "yo'qolib qolmasligi kerak",
    )
    blocker_counts: dict[str, int] = Field(
        default_factory=dict, description="Qaysi sabab necha juftlikni kesdi")


class Analysis(BaseModel):
    """Yuqori variantlar bo'yicha umumiy tahlil.

    Ballarni ARIFMETIKA hisoblaydi, bu matnni esa LLM yozadi: variantlarni
    taqqoslaydi, xavfni ko'rsatadi va tavsiya beradi.

    MATN FAQAT LLM DAN. Shablon bilan to'ldirilmaydi: LLM javob bermasa
    endpoint 503 qaytaradi. `text` bo'sh bo'lishi mumkin bo'lgan yagona
    holat — mos juftlik umuman topilmagani, ya'ni tahlil qiladigan
    narsaning o'zi yo'qligi.
    """

    text: str = Field("", description="O'zbekcha tahlil")
    pairs_considered: int = Field(
        0, description="Tahlilga nechta yuqori variant kiritildi")


class DataQuality(BaseModel):
    """Qaysi manbada ma'lumot bor — bo'sh yoki g'alati natijani tushuntirish uchun.

    Bu maydon SHART: manba jadval bo'sh bo'lsa javob "mos variant yo'q" bo'lib
    ko'rinadi. Aslida "tanlashga ma'lumot yo'q".
    """

    row_counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SelectionReport(BaseModel):
    generated_at: datetime
    demand: Demand
    summary: Summary
    analysis: Analysis = Field(
        default_factory=Analysis,
        description="Yuqori variantlar bo'yicha tahlil — taqqoslash, xavf, tavsiya",
    )
    pairs: list[Pair] = Field(
        default_factory=list, description="Eng mos variant birinchi")
    data_quality: DataQuality
    elapsed_seconds: float = 0.0
