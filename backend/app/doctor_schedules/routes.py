from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.doctor_schedules import service
from app.doctor_schedules.schemas import (
    DoctorScheduleCreate,
    DoctorScheduleOut,
    DoctorScheduleUpdate,
    DoctorUnavailableCreate,
    DoctorUnavailableOut,
    DoctorUnavailableUpdate,
)
from app.models import User

schedules_router = APIRouter(prefix="/doctor-schedules", tags=["doctor-schedules"])
unavailable_router = APIRouter(prefix="/doctor-unavailable", tags=["doctor-unavailable"])


@schedules_router.post("", response_model=DoctorScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: DoctorScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DoctorScheduleOut:
    schedule = service.create_schedule(db, current_user, payload)
    return DoctorScheduleOut.model_validate(schedule)


@schedules_router.get("", response_model=List[DoctorScheduleOut])
def list_schedules(
    doctor_id: Optional[int] = Query(default=None),
    day_of_week: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[DoctorScheduleOut]:
    schedules = service.list_schedules(
        db, current_user, doctor_id=doctor_id, day_of_week=day_of_week
    )
    return [DoctorScheduleOut.model_validate(s) for s in schedules]


@schedules_router.get("/{schedule_id}", response_model=DoctorScheduleOut)
def get_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DoctorScheduleOut:
    schedule = service.get_schedule(db, current_user, schedule_id)
    return DoctorScheduleOut.model_validate(schedule)


@schedules_router.patch("/{schedule_id}", response_model=DoctorScheduleOut)
def update_schedule(
    schedule_id: int,
    payload: DoctorScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DoctorScheduleOut:
    schedule = service.update_schedule(db, current_user, schedule_id, payload)
    return DoctorScheduleOut.model_validate(schedule)


@schedules_router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    service.delete_schedule(db, current_user, schedule_id)


@unavailable_router.post("", response_model=DoctorUnavailableOut, status_code=status.HTTP_201_CREATED)
def create_unavailable(
    payload: DoctorUnavailableCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DoctorUnavailableOut:
    period = service.create_unavailable(db, current_user, payload)
    return DoctorUnavailableOut.model_validate(period)


@unavailable_router.get("", response_model=List[DoctorUnavailableOut])
def list_unavailable(
    doctor_id: Optional[int] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[DoctorUnavailableOut]:
    periods = service.list_unavailable(
        db,
        current_user,
        doctor_id=doctor_id,
        from_date=date_from,
        to_date=date_to,
    )
    return [DoctorUnavailableOut.model_validate(p) for p in periods]


@unavailable_router.get("/{period_id}", response_model=DoctorUnavailableOut)
def get_unavailable(
    period_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DoctorUnavailableOut:
    period = service.get_unavailable(db, current_user, period_id)
    return DoctorUnavailableOut.model_validate(period)


@unavailable_router.patch("/{period_id}", response_model=DoctorUnavailableOut)
def update_unavailable(
    period_id: int,
    payload: DoctorUnavailableUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DoctorUnavailableOut:
    period = service.update_unavailable(db, current_user, period_id, payload)
    return DoctorUnavailableOut.model_validate(period)


@unavailable_router.delete("/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unavailable(
    period_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    service.delete_unavailable(db, current_user, period_id)
