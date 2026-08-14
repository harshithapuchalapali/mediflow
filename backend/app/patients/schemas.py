import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^.+@.+$")
_GENDER_VALUES = {"MALE", "FEMALE", "OTHER"}
_BLOOD_GROUP_VALUES = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "UNKNOWN"}
_SEVERITY_VALUES = {"MILD", "MODERATE", "SEVERE"}


def _email_shape(value: str) -> str:
    stripped = value.strip()
    if not _EMAIL_RE.match(stripped):
        raise ValueError("email must look like an email address")
    return stripped


def _non_blank(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be blank")
    return stripped


class PatientRegister(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    dob: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    height_cm: Optional[Decimal] = Field(default=None, ge=0, le=300)
    weight_kg: Optional[Decimal] = Field(default=None, ge=0, le=500)
    emergency_contact_name: Optional[str] = Field(default=None, max_length=150)
    emergency_contact_phone: Optional[str] = Field(default=None, max_length=30)
    address: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        return _email_shape(value)

    @field_validator("first_name", "last_name")
    @classmethod
    def _validate_names(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("dob")
    @classmethod
    def _validate_dob(cls, value: Optional[date]) -> Optional[date]:
        if value is not None and value > date.today():
            raise ValueError("dob must not be in the future")
        return value

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _GENDER_VALUES:
            raise ValueError("gender must be one of MALE, FEMALE, OTHER")
        return value

    @field_validator("blood_group")
    @classmethod
    def _validate_blood_group(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _BLOOD_GROUP_VALUES:
            raise ValueError("blood_group is invalid")
        return value

    @field_validator("emergency_contact_phone")
    @classmethod
    def _validate_emergency_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if not stripped:
                raise ValueError("emergency_contact_phone must not be blank")
            return stripped
        return value


class PatientCreate(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    dob: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    height_cm: Optional[Decimal] = Field(default=None, ge=0, le=300)
    weight_kg: Optional[Decimal] = Field(default=None, ge=0, le=500)
    emergency_contact_name: Optional[str] = Field(default=None, max_length=150)
    emergency_contact_phone: Optional[str] = Field(default=None, max_length=30)
    address: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        return _email_shape(value)

    @field_validator("first_name", "last_name")
    @classmethod
    def _validate_names(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("dob")
    @classmethod
    def _validate_dob(cls, value: Optional[date]) -> Optional[date]:
        if value is not None and value > date.today():
            raise ValueError("dob must not be in the future")
        return value

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _GENDER_VALUES:
            raise ValueError("gender must be one of MALE, FEMALE, OTHER")
        return value

    @field_validator("blood_group")
    @classmethod
    def _validate_blood_group(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _BLOOD_GROUP_VALUES:
            raise ValueError("blood_group is invalid")
        return value

    @field_validator("emergency_contact_phone")
    @classmethod
    def _validate_emergency_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if not stripped:
                raise ValueError("emergency_contact_phone must not be blank")
            return stripped
        return value


class PatientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    dob: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    height_cm: Optional[Decimal] = Field(default=None, ge=0, le=300)
    weight_kg: Optional[Decimal] = Field(default=None, ge=0, le=500)
    emergency_contact_name: Optional[str] = Field(default=None, max_length=150)
    emergency_contact_phone: Optional[str] = Field(default=None, max_length=30)
    address: Optional[str] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def _validate_names(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _non_blank(value)
        return value

    @field_validator("dob")
    @classmethod
    def _validate_dob(cls, value: Optional[date]) -> Optional[date]:
        if value is not None and value > date.today():
            raise ValueError("dob must not be in the future")
        return value

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _GENDER_VALUES:
            raise ValueError("gender must be one of MALE, FEMALE, OTHER")
        return value

    @field_validator("blood_group")
    @classmethod
    def _validate_blood_group(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _BLOOD_GROUP_VALUES:
            raise ValueError("blood_group is invalid")
        return value

    @field_validator("emergency_contact_phone")
    @classmethod
    def _validate_emergency_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if not stripped:
                raise ValueError("emergency_contact_phone must not be blank")
            return stripped
        return value


class AllergyCreate(BaseModel):
    allergen: str = Field(min_length=1, max_length=150)
    severity: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("allergen")
    @classmethod
    def _validate_allergen(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("allergen must not be blank")
        return stripped.lower()

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _SEVERITY_VALUES:
            raise ValueError("severity must be one of MILD, MODERATE, SEVERE")
        return value


class AllergyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    allergen: str
    severity: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class PatientSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    mrn: str
    email: str
    first_name: str
    last_name: str
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    status: str
    deactivated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    mrn: str
    email: str
    first_name: str
    last_name: str
    dob: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    height_cm: Optional[Decimal] = None
    weight_kg: Optional[Decimal] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    address: Optional[str] = None
    allergies: List[AllergyOut] = []
    status: str
    deactivated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime