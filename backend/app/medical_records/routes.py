from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.medical_records import service
from app.medical_records.schemas import (
    MedicalRecordCreate,
    MedicalRecordDetailOut,
    MedicalRecordOut,
    MedicalRecordVersionCreate,
    MedicalRecordVersionOut,
)
from app.models import MedicalRecord, User

router = APIRouter(prefix="/medical-records", tags=["medical-records"])


def _to_out(record: MedicalRecord) -> MedicalRecordOut:
    version = record.versions[-1] if record.versions else None
    return MedicalRecordOut(
        id=record.id,
        appointment_id=record.appointment_id,
        patient_id=record.patient_id,
        doctor_id=record.doctor_id,
        latest_version=record.latest_version,
        created_at=record.created_at,
        symptoms=version.symptoms if version else None,
        diagnosis=version.diagnosis if version else None,
        vitals_json=version.vitals_json if version else None,
        notes=version.notes if version else None,
        changed_by=version.changed_by if version else None,
        changed_at=version.changed_at if version else None,
    )


def _to_detail(record: MedicalRecord) -> MedicalRecordDetailOut:
    versions = [MedicalRecordVersionOut.model_validate(v) for v in record.versions]
    return MedicalRecordDetailOut(
        id=record.id,
        appointment_id=record.appointment_id,
        patient_id=record.patient_id,
        doctor_id=record.doctor_id,
        latest_version=record.latest_version,
        created_at=record.created_at,
        versions=versions,
    )


@router.post("", response_model=MedicalRecordOut, status_code=201)
def create_medical_record(
    payload: MedicalRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MedicalRecordOut:
    record = service.create_medical_record(db, current_user, payload)
    db.refresh(record)
    return _to_out(record)


@router.get("", response_model=List[MedicalRecordOut])
def list_medical_records(
    patient_id: Optional[int] = Query(default=None),
    doctor_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MedicalRecordOut]:
    records = service.list_medical_records(
        db, current_user, patient_id=patient_id, doctor_id=doctor_id
    )
    return [_to_out(r) for r in records]


@router.get("/{record_id}", response_model=MedicalRecordDetailOut)
def get_medical_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MedicalRecordDetailOut:
    record = service.get_medical_record(db, current_user, record_id)
    return _to_detail(record)


@router.patch("/{record_id}/versions", response_model=MedicalRecordOut)
def append_version(
    record_id: int,
    payload: MedicalRecordVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MedicalRecordOut:
    record = service.append_version(db, current_user, record_id, payload)
    db.refresh(record)
    return _to_out(record)