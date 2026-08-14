from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, Request, status
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.models import (
    Appointment,
    MedicalRecord,
    Patient,
    PatientAllergy,
    RefreshToken,
    User,
)
from app.security import hash_password

# Audit actions recorded by this module.
ACTION_PATIENT_CREATE = "PATIENT_CREATE"
ACTION_PATIENT_UPDATE = "PATIENT_UPDATE"
ACTION_PATIENT_DEACTIVATE = "PATIENT_DEACTIVATE"
ACTION_PATIENT_ACTIVATE = "PATIENT_ACTIVATE"
ACTION_ALLERGY_ADD = "ALLERGY_ADD"
ACTION_ALLERGY_REMOVE = "ALLERGY_REMOVE"

MRN_SEQUENCE = "patient_mrn_seq"
MRN_FORMAT = "PT-%06d"
_MAX_MRN_RETRIES = 5

_PATCHABLE_FIELDS = (
    "first_name",
    "last_name",
    "dob",
    "gender",
    "blood_group",
    "height_cm",
    "weight_kg",
    "emergency_contact_name",
    "emergency_contact_phone",
    "address",
)


def _forbidden(detail: str = "Insufficient permissions for this action") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _not_found(detail: str = "Patient not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _fail_if_email_taken(db: Session, email: str) -> None:
    clash = db.query(User).filter(User.email == email).first()
    if clash is not None:
        raise _conflict("Email is already registered")


def _own_doctor_id(db: Session, user: User) -> Optional[int]:
    from app.models import Doctor

    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    return doctor.id if doctor else None


def _own_patient_id(db: Session, user: User) -> Optional[int]:
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    return patient.id if patient else None


def _doctor_has_relation(db: Session, user: User, patient_id: int) -> bool:
    """A doctor may access a patient they are assigned to or have consulted."""
    own = _own_doctor_id(db, user)
    if own is None:
        return False
    has_appointment = (
        db.query(Appointment.id)
        .filter(Appointment.doctor_id == own, Appointment.patient_id == patient_id)
        .first()
    )
    if has_appointment is not None:
        return True
    has_record = (
        db.query(MedicalRecord.id)
        .filter(MedicalRecord.doctor_id == own, MedicalRecord.patient_id == patient_id)
        .first()
    )
    return has_record is not None


def _can_view_patient(db: Session, patient: Patient, user: User) -> bool:
    if user.role in ("ADMIN", "RECEPTIONIST"):
        return True
    if user.role == "PATIENT":
        return _own_patient_id(db, user) == patient.id
    if user.role == "DOCTOR":
        return _doctor_has_relation(db, user, patient.id)
    return False


def _get_patient(db: Session, patient_id: int) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise _not_found()
    return patient


def _next_mrn(db: Session) -> str:
    for _ in range(_MAX_MRN_RETRIES):
        value = db.execute(text(f"SELECT nextval('{MRN_SEQUENCE}')")).scalar()
        mrn = MRN_FORMAT % int(value)
        if db.query(Patient).filter(Patient.mrn == mrn).first() is None:
            return mrn
    raise _conflict("Could not allocate a unique MRN")


def _build_patient(db: Session, email: str, password: str, data) -> Patient:
    """Create the User + Patient rows. Caller owns the transaction/audit."""
    user = User(
        email=email,
        password_hash=hash_password(password),
        role="PATIENT",
        status="ACTIVE",
    )
    db.add(user)
    db.flush()

    patient = Patient(
        user_id=user.id,
        mrn=_next_mrn(db),
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        dob=data.dob,
        gender=data.gender,
        blood_group=data.blood_group,
        height_cm=data.height_cm,
        weight_kg=data.weight_kg,
        emergency_contact_name=data.emergency_contact_name,
        emergency_contact_phone=data.emergency_contact_phone,
        address=data.address,
    )
    db.add(patient)
    db.flush()
    return patient


def register_patient(
    db: Session, payload, request: Request
) -> Patient:
    """Public patient self-registration (creates role = PATIENT)."""
    email = _normalize_email(payload.email)
    _fail_if_email_taken(db, email)

    patient = _build_patient(db, email, payload.password, payload)

    # D10: the actor is the newly created patient's own user account.
    write_audit_log(
        db,
        user_id=patient.user_id,
        action=ACTION_PATIENT_CREATE,
        entity_type="PATIENT",
        entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _fail_if_email_taken(db, email)
        raise
    db.refresh(patient)
    return patient


def create_patient(
    db: Session, current_user: User, payload, request: Request
) -> Patient:
    """Create a patient account on behalf of another person (staff)."""
    email = _normalize_email(payload.email)
    _fail_if_email_taken(db, email)

    patient = _build_patient(db, email, payload.password, payload)

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_PATIENT_CREATE,
        entity_type="PATIENT",
        entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _fail_if_email_taken(db, email)
        raise
    db.refresh(patient)
    return patient


def list_patients(
    db: Session,
    user: User,
    q: Optional[str] = None,
    gender: Optional[str] = None,
    blood_group: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Patient]:
    if user.role == "PATIENT":
        raise _forbidden("Patients may not search patient records")

    query = db.query(Patient).join(User, User.id == Patient.user_id)

    if user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            return []
        rel_patient_ids = (
            db.query(Appointment.patient_id)
            .filter(Appointment.doctor_id == own)
            .union(
                db.query(MedicalRecord.patient_id).filter(
                    MedicalRecord.doctor_id == own
                )
            )
        )
        query = query.filter(Patient.id.in_(rel_patient_ids))

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Patient.first_name.ilike(like),
                Patient.last_name.ilike(like),
                Patient.mrn.ilike(like),
            )
        )
    if gender is not None:
        query = query.filter(Patient.gender == gender)
    if blood_group is not None:
        query = query.filter(Patient.blood_group == blood_group)
    if is_active is not None:
        query = query.filter(
            User.status == ("ACTIVE" if is_active else "DEACTIVATED")
        )

    return query.order_by(Patient.id).limit(limit).offset(offset).all()


def get_patient(db: Session, user: User, patient_id: int) -> Patient:
    patient = _get_patient(db, patient_id)
    if not _can_view_patient(db, patient, user):
        raise _not_found()
    return patient


def update_patient(
    db: Session, current_user: User, patient_id: int, payload, request: Request
) -> Patient:
    patient = _get_patient(db, patient_id)

    if current_user.role == "PATIENT":
        if _own_patient_id(db, current_user) != patient.id:
            raise _not_found()
    elif current_user.role != "ADMIN":
        raise _forbidden("Role may not edit patient profiles")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise _unprocessable("No updatable fields provided")

    for field, value in fields.items():
        if field in _PATCHABLE_FIELDS:
            setattr(patient, field, value)
    patient.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_PATIENT_UPDATE,
        entity_type="PATIENT",
        entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(patient)
    return patient


def list_allergies(
    db: Session, user: User, patient_id: int
) -> List[PatientAllergy]:
    patient = _get_patient(db, patient_id)
    if not _can_view_patient(db, patient, user):
        raise _not_found()
    return (
        db.query(PatientAllergy)
        .filter(PatientAllergy.patient_id == patient.id)
        .order_by(PatientAllergy.id)
        .all()
    )


def _require_allergy_write(db: Session, patient: Patient, user: User) -> None:
    """D6: patients (own), doctors (with relation), receptionists, admins."""
    if user.role in ("ADMIN", "RECEPTIONIST"):
        return
    if user.role == "PATIENT":
        if _own_patient_id(db, user) != patient.id:
            raise _not_found()
        return
    if user.role == "DOCTOR":
        if not _doctor_has_relation(db, user, patient.id):
            raise _not_found()
        return
    raise _forbidden()


def add_allergy(
    db: Session, current_user: User, patient_id: int, payload, request: Request
) -> PatientAllergy:
    patient = _get_patient(db, patient_id)
    _require_allergy_write(db, patient, current_user)

    duplicate = (
        db.query(PatientAllergy)
        .filter(
            PatientAllergy.patient_id == patient.id,
            PatientAllergy.allergen == payload.allergen,
        )
        .first()
    )
    if duplicate is not None:
        raise _conflict("Allergy is already recorded for this patient")

    allergy = PatientAllergy(
        patient_id=patient.id,
        allergen=payload.allergen,
        severity=payload.severity,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(allergy)
    db.flush()

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_ALLERGY_ADD,
        entity_type="PATIENT",
        entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(allergy)
    return allergy


def remove_allergy(
    db: Session,
    current_user: User,
    patient_id: int,
    allergy_id: int,
    request: Request,
) -> dict:
    patient = _get_patient(db, patient_id)
    _require_allergy_write(db, patient, current_user)

    allergy = db.get(PatientAllergy, allergy_id)
    if allergy is None or allergy.patient_id != patient.id:
        raise _not_found("Allergy not found")

    db.delete(allergy)

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_ALLERGY_REMOVE,
        entity_type="PATIENT",
        entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "Allergy removed"}


def _revoke_refresh_tokens(db: Session, user_id: int) -> None:
    now = datetime.now(timezone.utc)
    for token in db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    ):
        token.revoked_at = now


def deactivate_patient(
    db: Session, current_user: User, patient_id: int, request: Request
) -> dict:
    patient = _get_patient(db, patient_id)
    if patient.user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    user = patient.user
    if user.status == "DEACTIVATED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Patient is already deactivated",
        )

    user.status = "DEACTIVATED"
    user.deactivated_at = datetime.now(timezone.utc)
    _revoke_refresh_tokens(db, user.id)

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_PATIENT_DEACTIVATE,
        entity_type="PATIENT",
        entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "Patient deactivated"}


def activate_patient(
    db: Session, current_user: User, patient_id: int, request: Request
) -> dict:
    patient = _get_patient(db, patient_id)
    user = patient.user
    if user.status == "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Patient is already active",
        )

    user.status = "ACTIVE"
    user.deactivated_at = None
    user.failed_attempts = 0
    user.locked_until = None

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_PATIENT_ACTIVATE,
        entity_type="PATIENT",
        entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "Patient activated"}