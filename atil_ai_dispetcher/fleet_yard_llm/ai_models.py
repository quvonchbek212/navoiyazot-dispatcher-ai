"""Modeldan keladigan JSON va dalil bilan boyitilgan ochiq AI kontrakti."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CauseCode = Literal[
    "INSUFFICIENT_EVIDENCE", "DATA_RECORDING_GAP", "GPS_NOT_REPORTING",
    "REPAIR_IN_PROGRESS", "SHORT_HISTORY", "RESERVE_OR_BLOCK",
    "ALLOCATION_IMBALANCE", "NO_RECORDED_DEMAND", "ENGINE_ON_STATIONARY", "GPS_MAPPING_UNVERIFIED",
]
ActionCode = Literal[
    "VERIFY_RECORDS", "CHECK_GPS", "CHECK_REPAIR", "BUILD_HISTORY",
    "REVIEW_RESERVE", "REVIEW_ALLOCATION", "REVIEW_DEMAND",
    "REVIEW_RENTAL_COSTS", "REDUCE_ENGINE_IDLE", "MONITOR",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawCause(StrictModel):
    code: CauseCode
    explanation: str = Field(min_length=5, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class RawAction(StrictModel):
    code: ActionCode
    action: str = Field(min_length=5, max_length=400)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class RawAssessment(StrictModel):
    vehicle_id: str
    explanation: str = Field(min_length=10, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)
    possible_causes: list[RawCause] = Field(max_length=3)
    recommended_actions: list[RawAction] = Field(min_length=1, max_length=3)


class ModelResponse(StrictModel):
    overview: str = Field(min_length=10, max_length=700)
    overview_evidence_ids: list[str] = Field(min_length=1, max_length=6)
    vehicles: list[RawAssessment] = Field(min_length=1, max_length=1)


class EvidenceFact(BaseModel):
    id: str
    metric: str
    value: Any
    source: str


class Cause(RawCause):
    status: Literal["HYPOTHESIS"] = "HYPOTHESIS"


class VehicleAssessment(BaseModel):
    vehicle_id: str
    plate_number: str | None = None
    review_status: str
    explanation: str
    evidence_ids: list[str]
    evidence: list[EvidenceFact]
    possible_causes: list[Cause]
    recommended_actions: list[RawAction]
    missing_evidence: list[str]
    human_approval_required: bool = True
    disposal_decision: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"

