from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class SafetyPolicy(Input):
    name: str = Field('Pilot-v1', min_length=1, max_length=80)
    # This is an operator's fleet threshold, never an inferred legal road limit.
    speed_limit_kph: float | None = Field(None, ge=5, le=150)
    tolerance_kph: float = Field(0, ge=0, le=20)
    minimum_speeding_seconds: float = Field(10, ge=1, le=120)
    max_gap_seconds: float = Field(120, ge=2, le=120)
    harsh_gap_seconds: float = Field(2, ge=.1, le=2)
    braking_mps2: float = Field(3, ge=1, le=10)
    acceleration_mps2: float = Field(3, ge=1, le=10)
    cornering_mps2: float = Field(3, ge=1, le=10)
    minimum_driving_minutes: float = Field(15, ge=5, le=120)
    include_maneuvers_in_score: bool = False
    maneuver_events_per_hour_at_100: float = Field(10, ge=1, le=100)


class SafetyRequest(Input):
    plate_number: str | None = Field(None, min_length=1, max_length=32)
    hours: int = Field(24, ge=1, le=168)
    end_at: datetime | None = None
    policy: SafetyPolicy = Field(default_factory=SafetyPolicy)

    @model_validator(mode='after')
    def aware(self):
        if self.end_at and (self.end_at.tzinfo is None or self.end_at.utcoffset() is None):
            raise ValueError('end_at vaqt zonasini o‘z ichiga olishi kerak')
        if self.end_at and self.end_at > datetime.now(timezone.utc):
            raise ValueError('end_at kelajakda bo‘lishi mumkin emas')
        return self


class ETARequest(Input):
    plate_number: str | None = Field(None, min_length=1, max_length=32)
    minimum_samples: int = Field(5, ge=5, le=100)
    lookback_days: int = Field(180, ge=7, le=365)
    horizon_hours: int = Field(24, ge=1, le=168)
    # Legacy local timestamps cannot silently be assumed to be UTC or Tashkent.
    legacy_timezone: Literal['UTC', 'Asia/Tashkent'] | None = None
