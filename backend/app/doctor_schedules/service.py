from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.doctor_schedules.schemas import (
    DoctorScheduleCreate,
    DoctorScheduleUpdate,
    DoctorUnavailableCreate,
    DoctorUnavailableUpdate,
)
from app.models import Doctor, DoctorSchedule, DoctorUnavailable, User

# v1 timezone is Asia/Kolkata for all schedule semantics
# (database-design.md §1: store UTC, display/schedule in IST).
CLINIC_TIMEZONE = ZoneInfo("Asia/Kolkata")

# database-design.md §3.9: day_of_week is 0 (Sun) … 6 (Sat) —
# the opposite numbering of Python's date.weekday() (Mon=0).


def _py_to_db_weekday(py_weekday: int) -> int:
    """Map Python weekday() (Mon=0) to DB day_of_week (Sun=0)."""
    return (py_weekday + 1) % 7


def _forbidden(detail: str = "Not permitted for this doctor's schedule") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _not_found(detail: str = "Schedule entry not found") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail,
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    )


def _own_doctor_id(db: Session, user: User) -> Optional[int]:
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    return doctor.id if doctor else None


def _manage_scoped_doctor(db: Session, user: User, doctor_id: int) -> int:
    """Return doctor_id the caller may manage. ADMIN manages any; DOCTOR only own."""
    if user.role == "ADMIN":
        return doctor_id
    if user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            raise _forbidden("No doctor profile linked to this account")
        if doctor_id != own:
            raise _forbidden("Doctors may only manage their own schedule")
        return own
    raise _forbidden()


def create_schedule(db: Session, user: User, data: DoctorScheduleCreate) -> DoctorSchedule:
    if db.get(Doctor, data.doctor_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found"
        )
    doctor_id = _manage_scoped_doctor(db, user, data.doctor_id)
    schedule = DoctorSchedule(
        doctor_id=doctor_id,
        day_of_week=data.day_of_week,
        start_time=data.start_time,
        end_time=data.end_time,
    )
    db.add(schedule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict(
            "A schedule already exists for this doctor on the same day at the same start time"
        )
    db.refresh(schedule)
    return schedule


def list_schedules(
    db: Session,
    user: User,
    doctor_id: Optional[int] = None,
    day_of_week: Optional[int] = None,
) -> List[DoctorSchedule]:
    query = db.query(DoctorSchedule)

    if user.role == "ADMIN":
        if doctor_id is not None:
            query = query.filter(DoctorSchedule.doctor_id == doctor_id)
    elif user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            return []
        query = query.filter(DoctorSchedule.doctor_id == own)
    else:
        raise _forbidden()

    if day_of_week is not None:
        query = query.filter(DoctorSchedule.day_of_week == day_of_week)
    return query.order_by(
        DoctorSchedule.doctor_id, DoctorSchedule.day_of_week, DoctorSchedule.start_time
    ).all()


def get_schedule(db: Session, user: User, schedule_id: int) -> DoctorSchedule:
    schedule = db.get(DoctorSchedule, schedule_id)
    if schedule is None or not _can_access_schedule(schedule, user, db):
        raise _not_found()
    return schedule


def _can_access_schedule(schedule: DoctorSchedule, user: User, db: Session) -> bool:
    if user.role == "ADMIN":
        return True
    if user.role == "DOCTOR":
        return _own_doctor_id(db, user) == schedule.doctor_id
    return False


def update_schedule(
    db: Session,
    user: User,
    schedule_id: int,
    data: DoctorScheduleUpdate,
) -> DoctorSchedule:
    schedule = get_schedule(db, user, schedule_id)

    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nothing to update",
        )

    if user.role == "DOCTOR":
        _manage_scoped_doctor(db, user, schedule.doctor_id)

    for field, value in fields.items():
        setattr(schedule, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict(
            "A schedule already exists for this doctor on the same day at the same start time"
        )
    db.refresh(schedule)
    return schedule


def delete_schedule(db: Session, user: User, schedule_id: int) -> None:
    schedule = get_schedule(db, user, schedule_id)
    db.delete(schedule)
    db.commit()


def create_unavailable(
    db: Session, user: User, data: DoctorUnavailableCreate
) -> DoctorUnavailable:
    if db.get(Doctor, data.doctor_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found"
        )
    doctor_id = _manage_scoped_doctor(db, user, data.doctor_id)
    period = DoctorUnavailable(
        doctor_id=doctor_id,
        from_date=data.from_date,
        to_date=data.to_date,
        reason=data.reason,
        created_by=user.id,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


def list_unavailable(
    db: Session,
    user: User,
    doctor_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> List[DoctorUnavailable]:
    query = db.query(DoctorUnavailable)

    if user.role == "ADMIN":
        if doctor_id is not None:
            query = query.filter(DoctorUnavailable.doctor_id == doctor_id)
    elif user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            return []
        query = query.filter(DoctorUnavailable.doctor_id == own)
    else:
        raise _forbidden()

    if from_date is not None:
        query = query.filter(DoctorUnavailable.to_date >= from_date.date())
    if to_date is not None:
        query = query.filter(DoctorUnavailable.from_date <= to_date.date())
    return query.order_by(DoctorUnavailable.doctor_id, DoctorUnavailable.from_date).all()


def get_unavailable(db: Session, user: User, period_id: int) -> DoctorUnavailable:
    period = db.get(DoctorUnavailable, period_id)
    if period is None or not _can_access_unavailable(period, user, db):
        raise _not_found("Unavailable period not found")
    return period


def _can_access_unavailable(period: DoctorUnavailable, user: User, db: Session) -> bool:
    if user.role == "ADMIN":
        return True
    if user.role == "DOCTOR":
        return _own_doctor_id(db, user) == period.doctor_id
    return False


def update_unavailable(
    db: Session,
    user: User,
    period_id: int,
    data: DoctorUnavailableUpdate,
) -> DoctorUnavailable:
    period = get_unavailable(db, user, period_id)

    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nothing to update",
        )
    if "from_date" in fields and "to_date" in fields:
        if fields["to_date"] < fields["from_date"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="to_date must be on or after from_date",
            )

    if user.role == "DOCTOR":
        _manage_scoped_doctor(db, user, period.doctor_id)

    for field, value in fields.items():
        setattr(period, field, value)

    db.commit()
    db.refresh(period)
    return period


def delete_unavailable(db: Session, user: User, period_id: int) -> None:
    period = get_unavailable(db, user, period_id)
    db.delete(period)
    db.commit()


# ---------------------------------------------------------------------------
# Appointment integration (database-design.md §6.2, §6.3)
#
# The PostgreSQL EXCLUDE constraint is the hard floor for slot conflicts.
# This service adds a friendlier pre-INSERT check: when a doctor has a
# working schedule defined, the appointment must fall inside one of that
# day's windows; an entry in doctor_unavailable for the local date always
# blocks the slot.
#
# Backwards compatibility: a doctor with no schedule rows at all is treated
# as always available (existing bookings remain valid), matching the current
# appointment contracts.
# ---------------------------------------------------------------------------


def validate_appointment_slot(
    db: Session,
    doctor_id: int,
    date_time_utc: datetime,
    duration_minutes: int,
) -> None:
    """Raise 409 when the slot is outside the doctor's schedule or on a blocked date.

    Called by the appointments service before INSERT; the DB EXCLUDE
    constraint still independently guards concurrency.
    """
    local_start = date_time_utc.astimezone(CLINIC_TIMEZONE)
    local_date = local_start.date()

    # Unavailable ranges block regardless of schedule.
    blocked = (
        db.query(DoctorUnavailable)
        .filter(
            DoctorUnavailable.doctor_id == doctor_id,
            DoctorUnavailable.from_date <= local_date,
            DoctorUnavailable.to_date >= local_date,
        )
        .first()
    )
    if blocked is not None:
        raise _conflict("Doctor is unavailable on the requested date")

    # A doctor with no schedule rows is treated as always available.
    schedule_count = (
        db.query(DoctorSchedule)
        .filter(DoctorSchedule.doctor_id == doctor_id)
        .count()
    )
    if schedule_count == 0:
        return

    db_weekday = _py_to_db_weekday(local_start.weekday())
    start_time = local_start.time()
    end_time = (local_start + timedelta(minutes=duration_minutes)).time()

    for slot in (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.day_of_week == db_weekday,
        )
        .all()
    ):
        if slot.start_time <= start_time and end_time <= slot.end_time:
            return

    raise _conflict(
        "Appointment falls outside the doctor's working schedule"
    )