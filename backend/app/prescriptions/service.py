from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import (
    Doctor,
    MedicalRecord,
    Patient,
    PatientAllergy,
    Prescription,
    PrescriptionItem,
    User,
)
from app.notifications import service as notification_service
from app.prescriptions.schemas import (
    AllergyWarningOut,
    PrescriptionCreate,
)


def _forbidden(detail: str = "Not permitted for this prescription") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _not_found(detail: str = "Prescription not found") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail,
    )


def _own_doctor_id(db: Session, user: User) -> Optional[int]:
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    return doctor.id if doctor else None


def _own_patient_id(db: Session, user: User) -> Optional[int]:
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    return patient.id if patient else None


def _can_read_prescription(
    prescription: Prescription, user: User, db: Session
) -> bool:
    """Ownership check (IDOR). ADMIN reads all; DOCTOR/PATIENT only their own."""
    if user.role == "ADMIN":
        return True
    if user.role == "DOCTOR":
        return _own_doctor_id(db, user) == prescription.doctor_id
    if user.role == "PATIENT":
        return _own_patient_id(db, user) == prescription.patient_id
    return False


def create_prescription(
    db: Session, user: User, data: PrescriptionCreate
) -> Tuple[Prescription, List[AllergyWarningOut]]:
    if user.role != "DOCTOR":
        raise _forbidden("Only doctors may create prescriptions")

    record = db.get(MedicalRecord, data.medical_record_id)
    if record is None:
        raise _not_found("Medical record not found")

    own_doctor = _own_doctor_id(db, user)
    if own_doctor is None or record.doctor_id != own_doctor:
        raise _forbidden("Doctors may prescribe only for their own consultations")

    items = [
        PrescriptionItem(
            medicine_name=item.medicine_name.strip().lower(),
            dosage=item.dosage,
            frequency=item.frequency,
            duration_in_days=item.duration_in_days,
        )
        for item in data.items
    ]
    prescription = Prescription(
        medical_record_id=record.id,
        doctor_id=record.doctor_id,
        patient_id=record.patient_id,
        items=items,
    )
    db.add(prescription)
    db.flush()
    notification_service.notify_prescription_created(db, prescription)
    db.commit()
    db.refresh(prescription)

    warnings = _compute_allergy_warnings(db, record.patient_id, items)
    return prescription, warnings


def _compute_allergy_warnings(
    db: Session, patient_id: int, items: List[PrescriptionItem]
) -> List[AllergyWarningOut]:
    """Informational match only — never blocks a prescription."""
    allergens = {
        a.allergen: a
        for a in db.query(PatientAllergy)
        .filter(PatientAllergy.patient_id == patient_id)
        .all()
    }
    warnings = []
    for item in items:
        match = allergens.get(item.medicine_name)
        if match is not None:
            warnings.append(
                AllergyWarningOut(
                    medicine_name=item.medicine_name,
                    allergen=match.allergen,
                    severity=match.severity,
                )
            )
    return warnings


def get_prescription(
    db: Session, user: User, prescription_id: int
) -> Prescription:
    if user.role == "RECEPTIONIST":
        raise _forbidden("Receptionists may not access prescriptions")
    prescription = db.get(Prescription, prescription_id)
    if prescription is None or not _can_read_prescription(prescription, user, db):
        raise _not_found()
    return prescription


def list_prescriptions(
    db: Session,
    user: User,
    patient_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
) -> List[Prescription]:
    query = db.query(Prescription)

    if user.role == "ADMIN":
        if patient_id is not None:
            query = query.filter(Prescription.patient_id == patient_id)
        if doctor_id is not None:
            query = query.filter(Prescription.doctor_id == doctor_id)
    elif user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            return []
        query = query.filter(Prescription.doctor_id == own)
    elif user.role == "PATIENT":
        own = _own_patient_id(db, user)
        if own is None:
            return []
        query = query.filter(Prescription.patient_id == own)
    else:
        raise _forbidden("Receptionists may not access prescriptions")

    return query.order_by(Prescription.created_at.desc()).all()