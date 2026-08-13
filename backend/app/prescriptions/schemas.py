from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PrescriptionItemCreate(BaseModel):
    medicine_name: str = Field(min_length=1)
    dosage: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    duration_in_days: int = Field(gt=0)

    @field_validator("medicine_name", "dosage", "frequency")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class PrescriptionCreate(BaseModel):
    medical_record_id: int
    # @decision: a prescription must contain at least one item.
    items: List[PrescriptionItemCreate] = Field(min_length=1)


class PrescriptionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    medicine_name: str
    dosage: str
    frequency: str
    duration_in_days: Optional[int] = None


class PrescriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    medical_record_id: int
    doctor_id: int
    patient_id: int
    created_at: datetime
    items: List[PrescriptionItemOut] = []


class AllergyWarningOut(BaseModel):
    medicine_name: str
    allergen: str
    severity: Optional[str] = None


class PrescriptionCreateResponse(BaseModel):
    prescription: PrescriptionOut
    allergy_warnings: List[AllergyWarningOut]