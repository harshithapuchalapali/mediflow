from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.medical_records.schemas import (
    MedicalRecordCreate,
    MedicalRecordVersionCreate,
    has_clinical_field,
)
from app.models import (
    Appointment,
    Doctor,
    MedicalRecord,
    MedicalRecordVersion,
    Patient,
    User,
)


def _forbidden(detail: str = "Not permitted for this medical record") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Medical record not found",
    )


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def _conflict(detail: str = "A medical record already exists for this appointment") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    )


def _own_doctor_id(db: Session, user: User) -> Optional[int]:
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    return doctor.id if doctor else None


def _own_patient_id(db: Session, user: User) -> Optional[int]:
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    return patient.id if patient else None


def _can_read_record(record: MedicalRecord, user: User, db: Session) -> bool:
    """Ownership check (IDOR). ADMIN reads all; DOCTOR/PATIENT only their own."""
    if user.role == "ADMIN":
        return True
    if user.role == "DOCTOR":
        return _own_doctor_id(db, user) == record.doctor_id
    if user.role == "PATIENT":
        return _own_patient_id(db, user) == record.patient_id
    return False


def create_medical_record(
    db: Session, user: User, data: MedicalRecordCreate
) -> MedicalRecord:
    if user.role != "DOCTOR":
        raise _forbidden("Only doctors may create medical records")

    if not has_clinical_field(data):
        raise _unprocessable(
            "At least one clinical field (symptoms, diagnosis, vitals_json, notes) is required"
        )

    appointment = db.get(Appointment, data.appointment_id)
    if appointment is None:
        raise _unprocessable("Appointment not found")

    own_doctor = _own_doctor_id(db, user)
    if own_doctor is None or appointment.doctor_id != own_doctor:
        raise _forbidden("Doctors may create records only for their own consultations")

    record = MedicalRecord(
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
        latest_version=1,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflict()

    version = MedicalRecordVersion(
        record_id=record.id,
        version_number=1,
        symptoms=data.symptoms,
        diagnosis=data.diagnosis,
        vitals_json=data.vitals_json,
        notes=data.notes,
        changed_by=user.id,
    )
    db.add(version)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict()
    db.refresh(record)
    return record


def get_medical_record(
    db: Session, user: User, record_id: int
) -> MedicalRecord:
    if user.role == "RECEPTIONIST":
        raise _forbidden("Receptionists may not access clinical records")
    record = db.get(MedicalRecord, record_id)
    if record is None or not _can_read_record(record, user, db):
        raise _not_found()
    return record


def list_medical_records(
    db: Session,
    user: User,
    patient_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
) -> list[MedicalRecord]:
    query = db.query(MedicalRecord)

    if user.role == "ADMIN":
        if patient_id is not None:
            query = query.filter(MedicalRecord.patient_id == patient_id)
        if doctor_id is not None:
            query = query.filter(MedicalRecord.doctor_id == doctor_id)
    elif user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            return []
        query = query.filter(MedicalRecord.doctor_id == own)
    elif user.role == "PATIENT":
        own = _own_patient_id(db, user)
        if own is None:
            return []
        query = query.filter(MedicalRecord.patient_id == own)
    else:
        raise _forbidden("Receptionists may not access clinical records")

    return query.order_by(MedicalRecord.created_at.desc()).all()


def append_version(
    db: Session, user: User, record_id: int, data: MedicalRecordVersionCreate
) -> MedicalRecord:
    record = db.get(MedicalRecord, record_id)
    if record is None:
        raise _not_found()

    if user.role != "DOCTOR":
        raise _forbidden("Only doctors may update medical records")

    own_doctor = _own_doctor_id(db, user)
    if own_doctor is None or record.doctor_id != own_doctor:
        raise _forbidden("Doctors may update only their own consultation records")

    if not has_clinical_field(data):
        raise _unprocessable(
            "At least one clinical field (symptoms, diagnosis, vitals_json, notes) is required"
        )

    next_version = (record.latest_version or 0) + 1
    version = MedicalRecordVersion(
        record_id=record.id,
        version_number=next_version,
        symptoms=data.symptoms,
        diagnosis=data.diagnosis,
        vitals_json=data.vitals_json,
        notes=data.notes,
        changed_by=user.id,
    )
    record.latest_version = next_version
    db.add(version)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _unprocessable("Could not append version")
    db.refresh(record)
    return record