"""HTTP kontrakti: barcha GPS vaqtlari UTC offset bilan keladi."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from atil_ai_dispetcher.fleet_yard_llm import config
from atil_ai_dispetcher.fleet_yard_llm.ai_models import EvidenceFact, VehicleAssessment


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CircleZone(InputModel):
    name: str = Field(min_length=1, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(gt=0, le=50000)


class DetectionPolicy(InputModel):
    # Pilot parametrlari; tasdiqlangan ishlab chiqarish me'yori emas.
    hysteresis_meters: float = Field(30, ge=0, le=1000)
    confirmation_points: int = Field(2, ge=2, le=20)
    confirmation_seconds: float = Field(30, ge=0, le=3600)
    max_gap_seconds: float = Field(300, gt=0, le=86400)
    stationary_speed_kph: float = Field(1, ge=0, le=20)


class GPSPoint(InputModel):
    timestamp: AwareDatetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    valid: bool = True
    speed_kph: float | None = Field(None, ge=0, le=400)
    engine_on: bool | None = None
    speed_basis: Literal["REPORTED_KPH", "CONVERTED_KNOTS", "CONVERTED_MPH", "CONVERTED_MPS"] = Field("REPORTED_KPH", exclude=True)


class YardScope(InputModel):
    vehicle_id: UUID
    from_at: AwareDatetime
    to_at: AwareDatetime
    zone: CircleZone
    policy: DetectionPolicy = Field(default_factory=DetectionPolicy)
    analyze: bool = True

    @model_validator(mode="after")
    def validate_scope(self):
        if self.to_at <= self.from_at:
            raise ValueError("to_at from_at dan keyin bo'lishi kerak")
        if (self.to_at - self.from_at).total_seconds() > config.MAX_HISTORY_DAYS * 86400:
            raise ValueError(f"GPS tarixi ko'pi bilan {config.MAX_HISTORY_DAYS} kun")
        if self.zone.radius_meters <= self.policy.hysteresis_meters:
            raise ValueError("radius_meters hysteresis_meters dan katta bo'lishi kerak")
        return self


class HistoryRequest(YardScope):
    source: Literal["telematics_event", "position_log", "gps_archive_point"] = "telematics_event"


class EvaluateRequest(YardScope):
    points: list[GPSPoint] = Field(default_factory=list, max_length=config.MAX_POINTS)


class Quality(BaseModel):
    status: Literal["OK", "PARTIAL", "NO_DATA"]
    notes: list[str] = Field(default_factory=list)
    input_points: int = 0
    used_points: int = 0
    rejected_points: int = 0
    duplicate_points: int = 0
    conflicting_timestamps: int = 0
    signal_gaps: int = 0
    truncated: bool = False


class Crossing(BaseModel):
    kind: Literal["ENTER", "EXIT"]
    occurred_at: datetime
    confirmed_at: datetime
    previous_observed_at: datetime | None = None


class GarageVisit(BaseModel):
    entered_at: datetime | None = None
    exited_at: datetime | None = None
    observed_from: datetime
    observed_until: datetime
    left_censored: bool
    right_censored: bool
    end_reason: Literal["EXIT", "SIGNAL_GAP", "WINDOW_END"]
    duration_minutes: float | None = None
    observed_inside_minutes: float = 0
    speed_observed_minutes: float = 0
    engine_observed_minutes: float = 0
    observed_stopped_minutes: float | None = None
    engine_on_stopped_minutes: float | None = None


class Analysis(BaseModel):
    text: str
    overview_source: Literal["calculated", "llm"] = "calculated"
    source: Literal["template", "llm"] = "template"
    warning: str | None = None
    status: Literal["DISABLED", "COMPLETE"] = "DISABLED"
    provider: str | None = None
    model: str | None = None
    vehicles_returned: int = 0
    vehicles_analyzed: int = 0
    overview_evidence: list[EvidenceFact] = Field(default_factory=list)
    vehicle_assessments: list[VehicleAssessment] = Field(default_factory=list)
    safeguards: list[str] = Field(default_factory=list)


class YardReport(BaseModel):
    generated_at: datetime
    vehicle_id: str
    plate_number: str | None = None
    source: str
    from_at: datetime
    to_at: datetime
    zone: CircleZone
    policy: DetectionPolicy
    state_at_window_end: Literal["INSIDE", "OUTSIDE", "UNKNOWN", "NO_SIGNAL"]
    last_signal_at: datetime | None = None
    summary: dict[str, Any]
    events: list[Crossing]
    visits: list[GarageVisit]
    data_quality: Quality
    analysis: Analysis


class UtilizationItem(BaseModel):
    vehicle_id: str
    plate_number: str | None = None
    brand: str
    model: str
    usage_mode: str
    ownership_type: str
    current_status: str
    review_status: str
    recommendation: str
    work_count: int
    distance_km: float | None = None
    engine_hours: float | None = None
    latest_recorded_work_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)
    transport_type: str | None = None
    recorded_activity_days: int = 0
    history_days_in_window: float | None = None
    peer_comparison: dict[str, Any] = Field(default_factory=dict)
    gps_context: dict[str, Any] = Field(default_factory=dict)
    repair_context: list[dict[str, Any]] = Field(default_factory=list)
    demand_context: dict[str, Any] = Field(default_factory=dict)
    record_quality: dict[str, Any] = Field(default_factory=dict)


class UtilizationReport(BaseModel):
    generated_at: datetime
    from_at: datetime
    to_at: datetime
    days: int
    summary: dict[str, Any]
    items: list[UtilizationItem]
    data_quality: dict[str, Any]
    analysis: Analysis

