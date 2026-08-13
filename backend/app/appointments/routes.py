from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.appointments import service
from app.appointments.schemas import (
    AppointmentCreate,
    AppointmentOut,
    AppointmentUpdate,
)
from app.db import get_db
from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _to_out(appointment) -> AppointmentOut:
    return AppointmentOut.model_validate(appointment)


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AppointmentOut:
    appointment = service.create_appointment(db, current_user, payload)
    return _to_out(appointment)


@router.get("/{appointment_id}", response_model=AppointmentOut)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AppointmentOut:
    appointment = service.get_appointment(db, current_user, appointment_id)
    return _to_out(appointment)


@router.get("", response_model=List[AppointmentOut])
def list_appointments(
    status: Optional[str] = Query(default=None),
    patient_id: Optional[int] = Query(default=None),
    doctor_id: Optional[int] = Query(default=None),
    department_id: Optional[int] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[AppointmentOut]:
    statuses = [s.strip() for s in status.split(",")] if status else None
    appointments = service.list_appointments(
        db,
        current_user,
        statuses=statuses,
        patient_id=patient_id,
        doctor_id=doctor_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    )
    return [_to_out(a) for a in appointments]


@router.patch("/{appointment_id}", response_model=AppointmentOut)
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AppointmentOut:
    appointment = service.update_appointment(db, current_user, appointment_id, payload)
    return _to_out(appointment)


@router.delete("/{appointment_id}", response_model=AppointmentOut)
def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AppointmentOut:
    appointment = service.cancel_appointment(db, current_user, appointment_id)
    return _to_out(appointment)