from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DoctorScheduleCreate(BaseModel):
    doctor_id: int
    # database-design.md §3.9: day_of_week 0 (Sun) … 6 (Sat)
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class DoctorScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    day_of_week: int
    start_time: time
    end_time: time


class DoctorScheduleUpdate(BaseModel):
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    start_time: Optional[time] = None
    end_time: Optional[time] = None

    @model_validator(mode="after")
    def _end_after_start(self):
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time <= self.start_time
        ):
            raise ValueError("end_time must be after start_time")
        return self


class DoctorUnavailableCreate(BaseModel):
    doctor_id: int
    from_date: date
    to_date: date
    reason: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _range_valid(self):
        if self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        return self


class DoctorUnavailableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    from_date: date
    to_date: date
    reason: Optional[str] = None
    created_by: int
    created_at: datetime


class DoctorUnavailableUpdate(BaseModel):
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    reason: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _range_valid(self):
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.to_date < self.from_date
        ):
            raise ValueError("to_date must be on or after from_date")
        return self