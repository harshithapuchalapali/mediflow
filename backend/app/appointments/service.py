from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.appointments.schemas import AppointmentCreate, AppointmentUpdate
from app.doctor_schedules.service import validate_appointment_slot
from app.models import Appointment, Department, Doctor, Patient, User

# Status workflow (docs/requirements.md): pending → confirmed → checked-in →
# completed | cancelled | no-show
VALID_TRANSITIONS = {
    "PENDING": {"CONFIRMED", "CANCELLED"},
    "CONFIRMED": {"CHECKED_IN", "CANCELLED"},
    "CHECKED_IN": {"COMPLETED", "CANCELLED", "NO_SHOW"},
    "COMPLETED": set(),
    "CANCELLED": set(),
    "NO_SHOW": set(),
}

# Which statuses each role may set (database-design.md role matrix).
ROLE_ALLOWED_STATUS_TARGETS = {
    "ADMIN": {"CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"},
    "DOCTOR": {"CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"},
    "RECEPTIONIST": {"CHECKED_IN", "CANCELLED"},
    "PATIENT": {"CANCELLED"},
}

HOURS_ALLOWED_BEFORE = 24

_TERMINAL = {"COMPLETED", "CANCELLED", "NO_SHOW"}


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Appointment not found",
    )


def _forbidden(detail: str = "Not permitted for this appointment") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def _is_overlap_error(exc: IntegrityError) -> bool:
    """True when the IntegrityError is the appointment overlap EXCLUDE constraint."""
    orig = str(exc.orig)
    return "no_overlapping_active_appointments" in orig or getattr(
        exc.orig, "sqlstate", None
    ) == "23P01"


def _own_doctor_id(db: Session, user: User) -> Optional[int]:
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    return doctor.id if doctor else None


def _own_patient_id(db: Session, user: User) -> Optional[int]:
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    return patient.id if patient else None


def _user_active(user_id: int, db: Session) -> bool:
    user = db.get(User, user_id)
    return user is not None and user.status == "ACTIVE" and user.deactivated_at is None


def _validate_references(db: Session, patient_id: int, doctor_id: int, department_id: int) -> None:
    patient = db.get(Patient, patient_id)
    if patient is None or not _user_active(patient.user_id, db):
        raise _unprocessable("Patient not found or inactive")

    doctor = db.get(Doctor, doctor_id)
    if doctor is None or not _user_active(doctor.user_id, db):
        raise _unprocessable("Doctor not found or inactive")

    department = db.get(Department, department_id)
    if department is None or not department.is_active:
        raise _unprocessable("Department not found or inactive")


def _can_modify_calendar(role: str) -> bool:
    return role in {"ADMIN", "DOCTOR", "RECEPTIONIST", "PATIENT"}


def _check_24h(appointment: Appointment, new_date_time: Optional[datetime], role: str) -> None:
    """Patients & receptionists are bound by the 24h reschedule/cancel rule; admin overrides."""
    if role == "ADMIN":
        return
    if role not in {"PATIENT", "RECEPTIONIST"}:
        return
    reference = new_date_time or appointment.date_time
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= reference - timedelta(hours=HOURS_ALLOWED_BEFORE):
        raise _forbidden(
            "Cannot reschedule or cancel within 24 hours of the appointment"
        )


def create_appointment(db: Session, user: User, data: AppointmentCreate) -> Appointment:
    _validate_references(db, data.patient_id, data.doctor_id, data.department_id)

    if user.role == "PATIENT":
        own_patient = _own_patient_id(db, user)
        if own_patient is None or data.patient_id != own_patient:
            raise _forbidden("Patients may only book appointments for themselves")
    elif user.role == "DOCTOR":
        own_doctor = _own_doctor_id(db, user)
        if own_doctor is None or data.doctor_id != own_doctor:
            raise _forbidden("Doctors may only create appointments assigned to themselves")

    validate_appointment_slot(
        db, data.doctor_id, data.date_time_utc, data.duration_minutes
    )

    appointment = Appointment(
        patient_id=data.patient_id,
        doctor_id=data.doctor_id,
        department_id=data.department_id,
        date_time=data.date_time_utc,
        duration_minutes=data.duration_minutes,
        priority=data.priority,
        appointment_type=data.appointment_type,
        reason=data.reason,
        status="PENDING",
        created_by=user.id,  # never client-provided
    )
    db.add(appointment)
    try:
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_overlap_error(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Appointment conflicts with an existing appointment for this doctor",
            )
        raise _unprocessable("Could not create appointment")
    db.refresh(appointment)
    return appointment


def get_appointment(db: Session, user: User, appointment_id: int) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None or not _can_access(appointment, user, db):
        raise _not_found()
    return appointment


def _can_access(appointment: Appointment, user: User, db: Session) -> bool:
    if user.role == "ADMIN":
        return True
    if user.role == "RECEPTIONIST":
        return True  # books/checks-in on behalf of any patient
    if user.role == "DOCTOR":
        return _own_doctor_id(db, user) == appointment.doctor_id
    if user.role == "PATIENT":
        return _own_patient_id(db, user) == appointment.patient_id
    return False


def list_appointments(
    db: Session,
    user: User,
    statuses: Optional[list[str]] = None,
    patient_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
    department_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> list[Appointment]:
    query = db.query(Appointment)

    if user.role == "ADMIN" or user.role == "RECEPTIONIST":
        if patient_id is not None:
            query = query.filter(Appointment.patient_id == patient_id)
        if doctor_id is not None:
            query = query.filter(Appointment.doctor_id == doctor_id)
    elif user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            return []
        query = query.filter(Appointment.doctor_id == own)
    elif user.role == "PATIENT":
        own = _own_patient_id(db, user)
        if own is None:
            return []
        query = query.filter(Appointment.patient_id == own)

    if department_id is not None:
        query = query.filter(Appointment.department_id == department_id)
    if statuses:
        query = query.filter(Appointment.status.in_(statuses))
    if date_from is not None:
        query = query.filter(Appointment.date_time >= date_from)
    if date_to is not None:
        query = query.filter(Appointment.date_time <= date_to)

    return query.order_by(Appointment.date_time).all()


def update_appointment(
    db: Session,
    user: User,
    appointment_id: int,
    data: AppointmentUpdate,
) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None or not _can_access(appointment, user, db):
        raise _not_found()

    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise _unprocessable("Nothing to update")

    # Terminal appointments are immutable except idempotently re-cancelling.
    if appointment.status in _TERMINAL:
        only_cancel = set(fields) == {"status"} and fields.get("status") == "CANCELLED"
        if not only_cancel:
            raise _unprocessable("Cannot modify a terminal appointment")

    new_date_time = data.date_time_utc

    # Calendar changes (reschedule)
    if "date_time" in fields or "duration_minutes" in fields:
        if not _can_modify_calendar(user.role):
            raise _forbidden()
        _check_24h(appointment, new_date_time or appointment.date_time, user.role)
        # Re-validate against the doctor's schedule/unavailability for the new slot.
        slot_datetime = new_date_time or appointment.date_time
        slot_duration = fields.get("duration_minutes", appointment.duration_minutes)
        validate_appointment_slot(db, appointment.doctor_id, slot_datetime, slot_duration)

    # Status changes. The 24h rule only guards cancel (and reschedule), never
    # normal status transitions (confirm / check-in / completion).
    if "status" in fields:
        target = fields["status"]
        allowed_targets = ROLE_ALLOWED_STATUS_TARGETS.get(user.role, set())
        if target not in allowed_targets:
            raise _forbidden("Role may not set this status")
        if target not in VALID_TRANSITIONS.get(appointment.status, set()):
            raise _unprocessable(
                f"Invalid status transition {appointment.status} -> {target}"
            )
        if target == "CANCELLED":
            _check_24h(appointment, appointment.date_time, user.role)

    if "priority" in fields and user.role not in {"ADMIN", "RECEPTIONIST"}:
        raise _forbidden("Role may not change appointment priority")
    if "appointment_type" in fields and user.role not in {"ADMIN", "RECEPTIONIST"}:
        raise _forbidden("Role may not change appointment type")
    if "reason" in fields and user.role not in {"ADMIN", "RECEPTIONIST", "PATIENT"}:
        raise _forbidden("Role may not change appointment reason")

    for field, value in fields.items():
        if field == "date_time":
            value = data.date_time_utc
        setattr(appointment, field, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_overlap_error(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Appointment conflicts with an existing appointment for this doctor",
            )
        raise _unprocessable("Could not update appointment")
    db.refresh(appointment)
    return appointment


def cancel_appointment(db: Session, user: User, appointment_id: int) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None or not _can_access(appointment, user, db):
        raise _not_found()

    if appointment.status == "CANCELLED":
        return appointment  # idempotent

    if user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None or appointment.doctor_id != own:
            raise _forbidden()
    elif user.role == "PATIENT":
        own = _own_patient_id(db, user)
        if own is None or appointment.patient_id != own:
            raise _forbidden()

    _check_24h(appointment, appointment.date_time, user.role)

    if appointment.status not in VALID_TRANSITIONS or "CANCELLED" not in VALID_TRANSITIONS.get(appointment.status, set()):
        raise _unprocessable("This appointment cannot be cancelled")

    appointment.status = "CANCELLED"
    db.commit()
    db.refresh(appointment)
    return appointment