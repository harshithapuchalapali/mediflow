from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import User
from app.patients import service
from app.patients.schemas import (
    AllergyCreate,
    AllergyOut,
    PatientCreate,
    PatientOut,
    PatientRegister,
    PatientSummaryOut,
    PatientUpdate,
)

register_router = APIRouter(prefix="/auth", tags=["patients"])
patients_router = APIRouter(prefix="/patients", tags=["patients"])

staff_dep = Depends(require_roles("DOCTOR", "RECEPTIONIST", "ADMIN"))
admin_dep = Depends(require_roles("ADMIN"))


def _allergies(patient) -> List[AllergyOut]:
    return [AllergyOut.model_validate(a) for a in patient.patient_allergies]


def _to_out(patient) -> PatientOut:
    return PatientOut(
        id=patient.id,
        user_id=patient.user_id,
        mrn=patient.mrn,
        email=patient.user.email,
        first_name=patient.first_name,
        last_name=patient.last_name,
        dob=patient.dob,
        gender=patient.gender,
        blood_group=patient.blood_group,
        height_cm=patient.height_cm,
        weight_kg=patient.weight_kg,
        emergency_contact_name=patient.emergency_contact_name,
        emergency_contact_phone=patient.emergency_contact_phone,
        address=patient.address,
        allergies=_allergies(patient),
        status=patient.user.status,
        deactivated_at=patient.user.deactivated_at,
        created_at=patient.created_at,
        updated_at=patient.updated_at,
    )


@register_router.post(
    "/register", response_model=PatientOut, status_code=status.HTTP_201_CREATED
)
def register(
    payload: PatientRegister,
    request: Request,
    db: Session = Depends(get_db),
) -> PatientOut:
    """Public patient self-registration (only role PATIENT can self-register)."""
    patient = service.register_patient(db, payload, request=request)
    db.refresh(patient)
    return _to_out(patient)


@patients_router.post(
    "", response_model=PatientOut, status_code=status.HTTP_201_CREATED
)
def create_patient(
    payload: PatientCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = staff_dep,
) -> PatientOut:
    patient = service.create_patient(db, current_user, payload, request=request)
    db.refresh(patient)
    return _to_out(patient)


@patients_router.get("", response_model=List[PatientSummaryOut])
def list_patients(
    q: Optional[str] = Query(default=None),
    gender: Optional[str] = Query(default=None),
    blood_group: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[PatientSummaryOut]:
    patients = service.list_patients(
        db,
        current_user,
        q=q,
        gender=gender,
        blood_group=blood_group,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return [
        PatientSummaryOut(
            id=p.id,
            user_id=p.user_id,
            mrn=p.mrn,
            email=p.user.email,
            first_name=p.first_name,
            last_name=p.last_name,
            gender=p.gender,
            blood_group=p.blood_group,
            status=p.user.status,
            deactivated_at=p.user.deactivated_at,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in patients
    ]


@patients_router.get("/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PatientOut:
    patient = service.get_patient(db, current_user, patient_id)
    return _to_out(patient)


@patients_router.patch("/{patient_id}", response_model=PatientOut)
def update_patient(
    patient_id: int,
    payload: PatientUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PatientOut:
    patient = service.update_patient(
        db, current_user, patient_id, payload, request=request
    )
    db.refresh(patient)
    return _to_out(patient)


@patients_router.get("/{patient_id}/allergies", response_model=List[AllergyOut])
def list_allergies(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[AllergyOut]:
    allergies = service.list_allergies(db, current_user, patient_id)
    return [AllergyOut.model_validate(a) for a in allergies]


@patients_router.post(
    "/{patient_id}/allergies",
    response_model=AllergyOut,
    status_code=status.HTTP_201_CREATED,
)
def add_allergy(
    patient_id: int,
    payload: AllergyCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AllergyOut:
    allergy = service.add_allergy(
        db, current_user, patient_id, payload, request=request
    )
    db.refresh(allergy)
    return AllergyOut.model_validate(allergy)


@patients_router.delete("/{patient_id}/allergies/{allergy_id}")
def remove_allergy(
    patient_id: int,
    allergy_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return service.remove_allergy(
        db, current_user, patient_id, allergy_id, request=request
    )


@patients_router.post("/{patient_id}/deactivate")
def deactivate_patient(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> dict:
    return service.deactivate_patient(
        db, current_user, patient_id, request=request
    )


@patients_router.post("/{patient_id}/activate")
def activate_patient(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> dict:
    return service.activate_patient(db, current_user, patient_id, request=request)