from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Appointment, Notification, Patient

# v1 timezone is Asia/Kolkata for display (database-design.md §1); timestamps
# are stored as TIMESTAMPTZ (UTC internally) and only formatted here.
IST_TZ = ZoneInfo("Asia/Kolkata")

# Lazy appointment-reminder window and the statuses a reminder applies to.
REMINDER_WINDOW_HOURS = 24
_REMINDER_STATUSES = ("PENDING", "CONFIRMED", "CHECKED_IN")

# The DB has no CHECK on `type` (database-design.md §3.20), so the allowed set
# is enforced here (D7: app-level allowlist).
NOTIFICATION_TYPES = (
    "APPOINTMENT_BOOKED",
    "APPOINTMENT_CONFIRMED",
    "APPOINTMENT_CANCELLED",
    "APPOINTMENT_REMINDER",
    "LAB_READY",
    "LAB_VERIFIED",
    "PRESCRIPTION_CREATED",
    "MEDICAL_RECORD_CREATED",
    "BILL_CREATED",
    "BILL_PAID",
)


def _forbidden(detail: str = "Not permitted for this notification") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _not_found(detail: str = "Notification not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _fmt_ist(value: Optional[datetime]) -> str:
    if value is None:
        return "at an unknown time"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST_TZ).strftime("%d %b %Y, %I:%M %p")


def _patient_user_id(db: Session, patient_id: int) -> Optional[int]:
    patient = db.get(Patient, patient_id)
    return patient.user_id if patient is not None else None


def _notify(
    db: Session, *, user_id: Optional[int], type: str, message: str
) -> Optional[Notification]:
    """Insert a notification in the caller's transaction.

    Deduplicates on (user_id, type, message) so retried operations never
    produce duplicate rows. Returns the new row, or None when skipped.
    """
    if user_id is None:
        return None
    exists = (
        db.query(Notification.id)
        .filter(
            Notification.user_id == user_id,
            Notification.type == type,
            Notification.message == message,
        )
        .first()
    )
    if exists is not None:
        return None
    note = Notification(
        user_id=user_id, type=type, message=message, channel="IN_APP"
    )
    db.add(note)
    db.flush()
    return note


# ---- Event generators (called by domain services in-transaction) ----

def notify_appointment_booked(db: Session, appointment: Appointment) -> None:
    message = (
        f"Your appointment (#{appointment.id}) is booked for "
        f"{_fmt_ist(appointment.date_time)}."
    )
    _notify(
        db,
        user_id=_patient_user_id(db, appointment.patient_id),
        type="APPOINTMENT_BOOKED",
        message=message,
    )


def notify_appointment_confirmed(db: Session, appointment: Appointment) -> None:
    message = (
        f"Your appointment (#{appointment.id}) on {_fmt_ist(appointment.date_time)} "
        "has been confirmed."
    )
    _notify(
        db,
        user_id=_patient_user_id(db, appointment.patient_id),
        type="APPOINTMENT_CONFIRMED",
        message=message,
    )


def notify_appointment_cancelled(db: Session, appointment: Appointment) -> None:
    message = (
        f"Your appointment (#{appointment.id}) scheduled for "
        f"{_fmt_ist(appointment.date_time)} has been cancelled."
    )
    _notify(
        db,
        user_id=_patient_user_id(db, appointment.patient_id),
        type="APPOINTMENT_CANCELLED",
        message=message,
    )


def notify_lab_ready(db: Session, request) -> None:
    message = (
        f"Your lab report for \"{request.test_name}\" "
        f"(Lab Request #{request.id}) is ready for review."
    )
    _notify(
        db,
        user_id=_patient_user_id(db, request.patient_id),
        type="LAB_READY",
        message=message,
    )


def notify_lab_verified(db: Session, request) -> None:
    message = (
        f"Your lab report for \"{request.test_name}\" "
        f"(Lab Request #{request.id}) has been verified."
    )
    _notify(
        db,
        user_id=_patient_user_id(db, request.patient_id),
        type="LAB_VERIFIED",
        message=message,
    )


def notify_prescription_created(db: Session, prescription) -> None:
    message = (
        f"A new prescription (Prescription #{prescription.id}) has been "
        "added to your record."
    )
    _notify(
        db,
        user_id=_patient_user_id(db, prescription.patient_id),
        type="PRESCRIPTION_CREATED",
        message=message,
    )


def notify_medical_record_created(db: Session, record) -> None:
    message = f"A new medical record (Record #{record.id}) has been added to your file."
    _notify(
        db,
        user_id=_patient_user_id(db, record.patient_id),
        type="MEDICAL_RECORD_CREATED",
        message=message,
    )


def notify_bill_created(db: Session, bill) -> None:
    message = f"Bill {bill.bill_number} has been generated for your consultation."
    _notify(
        db,
        user_id=_patient_user_id(db, bill.patient_id),
        type="BILL_CREATED",
        message=message,
    )


def notify_bill_paid(db: Session, bill) -> None:
    message = f"Your bill {bill.bill_number} has been settled."
    _notify(
        db,
        user_id=_patient_user_id(db, bill.patient_id),
        type="BILL_PAID",
        message=message,
    )


def generate_reminders(db: Session, user) -> int:
    """Lazy APPOINTMENT_REMINDER generation (no scheduler in v1).

    Fired on notification reads: any of the current patient's active
    appointments starting within the next 24 hours that do not already carry a
    reminder gets one. Deduped by (user_id, type, message), so repeated calls
    never create duplicates.
    """
    if user.role != "PATIENT":
        return 0
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if patient is None:
        return 0
    now = datetime.now(timezone.utc)
    boundary = now + timedelta(hours=REMINDER_WINDOW_HOURS)
    upcoming = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == patient.id,
            Appointment.status.in_(_REMINDER_STATUSES),
            Appointment.date_time >= now,
            Appointment.date_time <= boundary,
        )
        .all()
    )
    created = 0
    for appt in upcoming:
        message = (
            f"Reminder: you have an appointment (#{appt.id}) at "
            f"{_fmt_ist(appt.date_time)}."
        )
        if _notify(db, user_id=user.id, type="APPOINTMENT_REMINDER", message=message):
            created += 1
    if created:
        db.commit()
    return created


# ---- Read API (owner-only) ----

def list_notifications(
    db: Session,
    user,
    *,
    unread_only: bool = False,
    ntype: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Notification]:
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    if ntype is not None:
        query = query.filter(Notification.type == ntype)
    return (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def unread_count(db: Session, user) -> int:
    return (
        db.query(Notification.id)
        .filter(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .count()
    )


def mark_read(db: Session, user, notification_id: int) -> Notification:
    note = db.get(Notification, notification_id)
    if note is None or note.user_id != user.id:
        raise _not_found()
    if not note.is_read:
        note.is_read = True
        db.commit()
    return note


def read_all(db: Session, user) -> dict:
    unread = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .all()
    )
    for note in unread:
        note.is_read = True
    db.commit()
    return {"message": "All notifications marked as read", "updated": len(unread)}