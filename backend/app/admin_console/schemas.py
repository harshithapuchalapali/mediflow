import re
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^.+@.+$")


class HospitalSettingsCreate(BaseModel):
    hospital_name: str = Field(min_length=1, max_length=150)
    address: Optional[str] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=255)
    timezone: str = Field(default="Asia/Kolkata", max_length=50)
    logo_path: Optional[str] = Field(default=None, max_length=500)

    @field_validator("hospital_name")
    @classmethod
    def _non_blank_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("hospital_name must not be blank")
        return stripped

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _EMAIL_RE.match(value.strip()):
            raise ValueError("email must look like an email address")
        return value


class HospitalSettingsUpdate(BaseModel):
    hospital_name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    address: Optional[str] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=255)
    timezone: Optional[str] = Field(default=None, max_length=50)
    logo_path: Optional[str] = Field(default=None, max_length=500)

    @field_validator("hospital_name")
    @classmethod
    def _non_blank_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("hospital_name must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _EMAIL_RE.match(value.strip()):
            raise ValueError("email must look like an email address")
        return value


class HospitalSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hospital_name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    timezone: str
    logo_path: Optional[str] = None


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _non_blank_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _non_blank_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("name must not be blank")
        return value


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    ip_address: Optional[str] = None
    created_at: datetime


class DashboardRoleTotals(BaseModel):
    active: int
    registered: int


class DashboardTotals(BaseModel):
    patients: DashboardRoleTotals
    doctors: DashboardRoleTotals
    receptionists: DashboardRoleTotals
    admins: DashboardRoleTotals


class AppointmentTrendPoint(BaseModel):
    date: date
    total: int


class DashboardBillsOverview(BaseModel):
    bills_count: int
    billed_total: Decimal
    collected_total: Decimal
    outstanding: Decimal
    by_status: Dict[str, int]


class DashboardLabPerDepartment(BaseModel):
    department_id: int
    department_name: str
    total: int
    by_status: Dict[str, int]


class DashboardOut(BaseModel):
    totals: DashboardTotals
    appointment_trends: List[AppointmentTrendPoint]
    appointment_trend_summary: Dict[str, int]
    bills_overview: DashboardBillsOverview
    labs_per_department: List[DashboardLabPerDepartment]