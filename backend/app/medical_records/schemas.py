from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class MedicalRecordCreate(BaseModel):
    appointment_id: int
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    vitals_json: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class MedicalRecordVersionCreate(BaseModel):
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    vitals_json: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class MedicalRecordVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_number: int
    symptoms: Optional[str]
    diagnosis: Optional[str]
    vitals_json: Optional[Dict[str, Any]]
    notes: Optional[str]
    changed_by: int
    changed_at: datetime


class MedicalRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    patient_id: int
    doctor_id: int
    latest_version: int
    created_at: datetime
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    vitals_json: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: Optional[datetime] = None


class MedicalRecordDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    patient_id: int
    doctor_id: int
    latest_version: int
    created_at: datetime
    versions: list[MedicalRecordVersionOut]


def has_clinical_field(data: BaseModel) -> bool:
    """True when at least one clinical field is present (@decision: project rule)."""
    return any(
        getattr(data, field) is not None
        for field in ("symptoms", "diagnosis", "vitals_json", "notes")
    )