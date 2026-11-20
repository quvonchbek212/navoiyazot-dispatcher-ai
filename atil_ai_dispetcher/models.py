from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

class GarageConfig(Strict):
    name: str=Field('Garaj',min_length=1,max_length=120)
    latitude: float=Field(ge=-90,le=90)
    longitude: float=Field(ge=-180,le=180)
    radius_meters: float=Field(200,ge=50,le=50000)
    is_example: bool=False

class GarageSettings(Strict):
    garage: GarageConfig | None=None
    garage_hours: int=Field(24,ge=1,le=168)
    garage_stop_minutes: int=Field(15,ge=5,le=1440)

class Settings(Strict):
    schema_version: Literal[2]=2
    schedule_enabled: bool=True
    daily_time: str=Field('07:30',pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    monitor_minutes: int=Field(15,ge=5,le=1440)
    analyze: bool=True
    garage: GarageConfig | None=None
    garage_hours: int=Field(24,ge=1,le=168)
    garage_stop_minutes: int=Field(15,ge=5,le=1440)

class SelectionRequest(Strict):
    request_id: UUID

class GPSRequest(Strict):
    vehicle_id: UUID
    hours: int=Field(24,ge=1,le=168)

class JobRequest(Strict):
    kind: Literal['snapshot','briefing','selection','gps']
    analyze: bool=True
    selection: SelectionRequest | None=None
    gps: GPSRequest | None=None

    @model_validator(mode='after')
    def matching(self):
        for name in ('selection','gps'):
            if getattr(self,name) is not None and self.kind!=name:
                raise ValueError('Parametrlar vazifa turiga mos emas')
        if self.kind in ('selection','gps') and getattr(self,self.kind) is None:
            raise ValueError('Vazifa parametrlari kerak')
        return self
