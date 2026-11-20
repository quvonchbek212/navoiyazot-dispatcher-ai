"""One public, plate-based request for garage and fleet monitoring."""

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from atil_ai_dispetcher.fleet_yard_llm.models import CircleZone, DetectionPolicy, InputModel


class MonitorPolicy(DetectionPolicy):
    # These are visible pilot thresholds, not statutory or company norms.
    signal_timeout_seconds: float = Field(300, gt=0, le=86400)
    long_stop_minutes: float = Field(15, gt=0, le=1440)
    slow_speed_kph: float = Field(10, gt=0, le=100)
    slow_duration_minutes: float = Field(10, gt=0, le=1440)
    stationary_radius_meters: float = Field(50, gt=0, le=1000)

    @model_validator(mode="after")
    def check_speed_thresholds(self):
        if self.slow_speed_kph <= self.stationary_speed_kph:
            raise ValueError("slow_speed_kph stationary_speed_kph dan katta bo'lishi kerak")
        return self


class MonitorGarage(CircleZone):
    name: str = Field("Garaj", min_length=1, max_length=255)
    radius_meters: float = Field(200, gt=0, le=50000)


class MonitorRequest(InputModel):
    garage: MonitorGarage
    plate_number: str | None = Field(None, max_length=64, description="Transport raqami; bo'sh bo'lsa barcha transportlar")
    days: Literal[1, 7, 15, 30, 60] = Field(60, description="1 kun, 1 hafta (7 kun), 15 kun, 1 oy (30 kun), 2 oy (60 kun). Tanlangan davrgacha bo'lgan kesimlar qaytadi.")
    as_of: AwareDatetime | None = Field(None, description="Hisobot vaqti; berilmasa hozir. Vaqt zonasi majburiy.")
    policy: MonitorPolicy = Field(default_factory=MonitorPolicy)
    analyze: bool = True

    @field_validator("plate_number", mode="before")
    @classmethod
    def blank_plate(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if not any(c.isalnum() for c in value):
                raise ValueError("Transport raqamida harf yoki son bo'lishi kerak")
        return value

    @model_validator(mode="after")
    def valid_radius(self):
        if self.garage.radius_meters <= self.policy.hysteresis_meters:
            raise ValueError("Garaj radiusi hysteresis_meters dan katta bo'lishi kerak")
        return self


class MonitorReport(InputModel):
    generated_at: datetime
    as_of: datetime
    from_at: datetime
    days: int
    garage: CircleZone
    plate_number: str | None
    policy: MonitorPolicy
    summary: dict[str, Any]
    periods: list[dict[str, Any]]
    vehicles: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    data_quality: dict[str, Any]
    analysis: dict[str, Any]
