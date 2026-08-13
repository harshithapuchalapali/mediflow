import re
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^.+@.+$")


def _email_shape_value(value: Optional[str]) -> Optional[str]:
    if value is not None and not _EMAIL_RE.match(value.strip()):
        raise ValueError("email must look like an email address")
    return value


def _non_blank_stripped(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be blank")
    return stripped


class DoctorCreate(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    license_number: str = Field(min_length=1, max_length=50)
    consultation_fee: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=12, decimal_places=2
    )

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        return _email_shape_value(value)

    @field_validator("license_number")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        return _non_blank_stripped(value)


class DoctorUpdate(BaseModel):
    email: Optional[str] = Field(default=None, min_length=1, max_length=255)
    license_number: Optional[str] = Field(
        default=None, min_length=1, max_length=50
    )
    consultation_fee: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: Optional[str]) -> Optional[str]:
        return _email_shape_value(value)

    @field_validator("license_number")
    @classmethod
    def _non_blank(cls, value: Optional[str]) -> Optional[str]:
        return _non_blank_stripped(value)


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    email: str
    license_number: str
    consultation_fee: Decimal
    status: str
    deactivated_at: Optional[datetime] = None
    department_ids: List[int]
    created_at: datetime
    updated_at: datetime


class ReceptionistCreate(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    employee_code: Optional[str] = Field(default=None, min_length=1, max_length=50)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        return _email_shape_value(value)

    @field_validator("employee_code")
    @classmethod
    def _non_blank(cls, value: Optional[str]) -> Optional[str]:
        return _non_blank_stripped(value)


class ReceptionistUpdate(BaseModel):
    email: Optional[str] = Field(default=None, min_length=1, max_length=255)
    employee_code: Optional[str] = Field(default=None, min_length=1, max_length=50)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: Optional[str]) -> Optional[str]:
        return _email_shape_value(value)

    @field_validator("employee_code")
    @classmethod
    def _non_blank(cls, value: Optional[str]) -> Optional[str]:
        return _non_blank_stripped(value)


class ReceptionistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    email: str
    employee_code: Optional[str] = None
    status: str
    deactivated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AdminUserCreate(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        return _email_shape_value(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    status: str
    deactivated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime