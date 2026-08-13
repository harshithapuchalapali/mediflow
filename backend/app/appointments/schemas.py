from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Priority = Literal["NORMAL", "URGENT", "EMERGENCY"]
Status = Literal[
    "PENDING",
    "CONFIRMED",
    "CHECKED_IN",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
]
AppointmentType = Literal["INITIAL_CONSULTATION", "FOLLOW_UP"]


def _coerce_utc(value: datetime) -> datetime:
    """Ensure a naive datetime is treated as UTC (DB stores TIMESTAMPTZ)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AppointmentCreate(BaseModel):
    patient_id: int
    doctor_id: int
    department_id: int
    date_time: datetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    priority: Priority = "NORMAL"
    appointment_type: AppointmentType = "INITIAL_CONSULTATION"
    reason: Optional[str] = None

    @property
    def date_time_utc(self) -> datetime:
        return _coerce_utc(self.date_time)


class AppointmentUpdate(BaseModel):
    date_time: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    priority: Optional[Priority] = None
    appointment_type: Optional[AppointmentType] = None
    status: Optional[Status] = None
    reason: Optional[str] = None

    @property
    def date_time_utc(self) -> Optional[datetime]:
        return _coerce_utc(self.date_time) if self.date_time else None


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    doctor_id: int
    department_id: int
    date_time: datetime
    duration_minutes: int
    priority: str
    status: str
    appointment_type: str
    reason: Optional[str]
    created_by: int
    created_at: datetime
    updated_at: datetime