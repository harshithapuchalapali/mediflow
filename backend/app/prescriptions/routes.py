from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Prescription, User
from app.prescriptions import service
from app.prescriptions.schemas import (
    PrescriptionCreate,
    PrescriptionCreateResponse,
    PrescriptionItemOut,
    PrescriptionOut,
)

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


def _to_out(prescription: Prescription) -> PrescriptionOut:
    return PrescriptionOut(
        id=prescription.id,
        medical_record_id=prescription.medical_record_id,
        doctor_id=prescription.doctor_id,
        patient_id=prescription.patient_id,
        created_at=prescription.created_at,
        items=[PrescriptionItemOut.model_validate(i) for i in prescription.items],
    )


@router.post(
    "", response_model=PrescriptionCreateResponse, status_code=status.HTTP_201_CREATED
)
def create_prescription(
    payload: PrescriptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PrescriptionCreateResponse:
    prescription, warnings = service.create_prescription(db, current_user, payload)
    return PrescriptionCreateResponse(
        prescription=_to_out(prescription),
        allergy_warnings=warnings or [],
    )


@router.get("", response_model=List[PrescriptionOut])
def list_prescriptions(
    patient_id: Optional[int] = Query(default=None),
    doctor_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[PrescriptionOut]:
    prescriptions = service.list_prescriptions(
        db, current_user, patient_id=patient_id, doctor_id=doctor_id
    )
    return [_to_out(p) for p in prescriptions]


@router.get("/{prescription_id}", response_model=PrescriptionOut)
def get_prescription(
    prescription_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PrescriptionOut:
    prescription = service.get_prescription(db, current_user, prescription_id)
    return _to_out(prescription)