from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import Date, cast, func
from sqlalchemy.orm import Session

from app.models import Appointment, Doctor, MedicalRecord, Prescription, User

# v1 clinic timezone (database-design.md §1): dashboard "day" boundaries are
# Asia/Kolkata (IST); timestamps stay UTC in the database.
IST_TZ = ZoneInfo("Asia/Kolkata")
CLINIC_TZ = "Asia/Kolkata"


def _not_found(detail: str = "Doctor not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
    )


def _appointment_ist_day():
    """Appointment date_time converted to its Asia/Kolkata calendar date."""
    return cast(func.timezone(CLINIC_TZ, Appointment.date_time), Date)


def _own_doctor(db: Session, user: User) -> Optional[Doctor]:
    return (
        db.query(Doctor).filter(Doctor.user_id == user.id).first()
    )


def dashboard_stats(
    db: Session,
    user: User,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """Aggregated statistics scoped to the authenticated doctor.

    Ownership is always derived from the JWT user (never from a client-supplied
    doctor_id). All date boundaries are computed in Asia/Kolkata while the DB
    stays on UTC timestamps.
    """
    doctor = _own_doctor(db, user)
    if doctor is None:
        raise _not_found()

    today = datetime.now(timezone.utc).astimezone(IST_TZ).date()

    if start_date is not None and end_date is not None and start_date > end_date:
        raise _unprocessable("start_date must be on or before end_date")

    # Default window: the trailing 30 IST days ending today (admin dashboard
    # convention in app/admin_console/service.py).
    date_to = end_date or today
    date_from = start_date or (date_to - timedelta(days=29))
    if date_from > date_to:
        raise _unprocessable("start_date must be on or before end_date")

    appt_filter = Appointment.doctor_id == doctor.id
    day_col = _appointment_ist_day()

    # Appointment status totals (single grouped count across all statuses).
    status_counts: Dict[str, int] = {
        s: 0
        for s in (
            "PENDING",
            "CONFIRMED",
            "CHECKED_IN",
            "COMPLETED",
            "CANCELLED",
            "NO_SHOW",
        )
    }
    status_counts.update(
        dict(
            db.query(Appointment.status, func.count(Appointment.id))
            .filter(appt_filter)
            .group_by(Appointment.status)
            .all()
        )
    )

    today_appointments = (
        db.query(func.count(Appointment.id))
        .filter(appt_filter, day_col == today)
        .scalar()
        or 0
    )

    by_day: List[Dict[str, object]] = [
        {"date": d, "total": c}
        for d, c in db.query(day_col, func.count(Appointment.id))
        .filter(appt_filter, day_col >= date_from, day_col <= date_to)
        .group_by(day_col)
        .order_by(day_col)
        .all()
    ]

    patients_total = (
        db.query(func.count(func.distinct(Appointment.patient_id)))
        .filter(appt_filter)
        .scalar()
        or 0
    )
    patients_today = (
        db.query(func.count(func.distinct(Appointment.patient_id)))
        .filter(appt_filter, day_col == today)
        .scalar()
        or 0
    )

    # Consultation footprint: medical records and prescriptions the doctor
    # actually created, plus the same "today" (IST) breakdown.
    records_total = (
        db.query(func.count(MedicalRecord.id))
        .filter(MedicalRecord.doctor_id == doctor.id)
        .scalar()
        or 0
    )
    records_today = (
        db.query(func.count(MedicalRecord.id))
        .filter(
            MedicalRecord.doctor_id == doctor.id,
            cast(func.timezone(CLINIC_TZ, MedicalRecord.created_at), Date) == today,
        )
        .scalar()
        or 0
    )

    prescriptions_total = (
        db.query(func.count(Prescription.id))
        .filter(Prescription.doctor_id == doctor.id)
        .scalar()
        or 0
    )
    prescriptions_today = (
        db.query(func.count(Prescription.id))
        .filter(
            Prescription.doctor_id == doctor.id,
            cast(func.timezone(CLINIC_TZ, Prescription.created_at), Date) == today,
        )
        .scalar()
        or 0
    )

    return {
        "doctor_id": doctor.id,
        "today": today,
        "date_from": date_from,
        "date_to": date_to,
        "appointments": {
            "total": sum(status_counts.values()),
            "today": today_appointments,
            "completed": status_counts["COMPLETED"],
            "confirmed": status_counts["CONFIRMED"],
            "cancelled": status_counts["CANCELLED"],
            "no_show": status_counts["NO_SHOW"],
        },
        "appointment_by_day": by_day,
        "patients": {"total": patients_total, "today": patients_today},
        "consultations": {
            "total_records": records_total,
            "records_today": records_today,
            "total_prescriptions": prescriptions_total,
            "prescriptions_today": prescriptions_today,
        },
    }