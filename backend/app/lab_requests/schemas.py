from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LabRequestCreate(BaseModel):
    appointment_id: int
    test_name: str = Field(min_length=1)
    notes: Optional[str] = None

    @field_validator("test_name")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class LabRequestUpdate(BaseModel):
    target_status: str
    result_details: Optional[str] = None

    @field_validator("result_details")
    @classmethod
    def _strip_details(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("result_details must not be blank")
        return stripped


class LabRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    patient_id: int
    doctor_id: int
    test_name: str
    notes: Optional[str] = None
    status: str
    result_details: Optional[str] = None
    report_file_path: Optional[str] = None
    requested_at: datetime
    verified_by: Optional[int] = None
    verified_by_admin: Optional[int] = None
    verified_at: Optional[datetime] = None