from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.lab_requests import report_files
from app.lab_requests.schemas import LabRequestCreate, LabRequestUpdate
from app.models import Appointment, Doctor, LabRequest, Patient, User
from app.notifications import service as notification_service

_VALID_TRANSITIONS = {
    "REQUESTED": "IN_PROGRESS",
    "IN_PROGRESS": "RESULT_READY",
    "RESULT_READY": "VERIFIED",
}

ACTION_LAB_REPORT_UPLOAD = "LAB_REPORT_UPLOAD"


def _forbidden(detail: str = "Not permitted for this lab request") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _not_found(detail: str = "Lab request not found") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail,
    )


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def _own_doctor_id(db: Session, user: User) -> Optional[int]:
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    return doctor.id if doctor else None


def _own_patient_id(db: Session, user: User) -> Optional[int]:
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    return patient.id if patient else None


def _ip(request) -> Optional[str]:
    if request is None:
        return None
    client = getattr(request, "client", None)
    return client.host if client else None


def upload_lab_report(
    db: Session,
    user: User,
    request_id: int,
    *,
    data: bytes,
    original_filename: Optional[str] = None,
    request=None,
) -> LabRequest:
    """Attach a verified lab-report file to a lab request (or replace it).

    Authorization mirrors the existing lab rules: the owning DOCTOR may upload;
    ADMIN may as well (full clinical access + verify rights). Patients and
    receptionists are rejected outright — they must never upload clinical
    reports. Ownership comes from the authenticated user, never the client.
    """
    if user.role not in ("DOCTOR", "ADMIN"):
        raise _forbidden("Only doctors and admins may upload lab reports")

    lab = db.get(LabRequest, request_id)
    if lab is None:
        raise _not_found()

    if user.role == "DOCTOR" and _own_doctor_id(db, user) != lab.doctor_id:
        raise _not_found()

    ext = report_files.validate_report(data, original_filename)
    new_path = report_files.store_report(data, ext)
    previous_path = lab.report_file_path

    lab.report_file_path = new_path
    write_audit_log(
        db,
        user_id=user.id,
        action=ACTION_LAB_REPORT_UPLOAD,
        entity_type="LAB_REQUEST",
        entity_id=lab.id,
        ip_address=_ip(request),
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        report_files.delete_report(new_path)
        raise

    # Replacement: supersede the old file only after the new one is stored
    # and committed, so no orphaned report is left behind.
    report_files.delete_report(previous_path)
    db.refresh(lab)
    return lab


def get_lab_report_file(
    db: Session, user: User, request_id: int
) -> Tuple[Path, str, str]:
    """Authorize and resolve a report for download.

    Access rules are exactly the existing lab visibility rules
    (get_lab_request): own doctor / own verified patient / admin, 403 for
    receptionists, 404 for unknown or inaccessible requests, and 404 when no
    report is attached.
    """
    lab = get_lab_request(db, user, request_id)
    if not lab.report_file_path:
        raise _not_found("Lab report not found")

    path = report_files.resolve_report_path(lab.report_file_path)
    if path is None:
        raise _not_found("Lab report not found")

    suffix = path.suffix.lower()
    media_type = report_files.MEDIA_TYPES.get(suffix, "application/octet-stream")
    filename = "lab-report-%d%s" % (lab.id, suffix)
    return path, media_type, filename


def create_lab_request(
    db: Session, user: User, data: LabRequestCreate
) -> LabRequest:
    if user.role != "DOCTOR":
        raise _forbidden("Only doctors may create lab requests")

    appointment = db.get(Appointment, data.appointment_id)
    if appointment is None:
        raise _not_found("Appointment not found")

    own_doctor = _own_doctor_id(db, user)
    if own_doctor is None or appointment.doctor_id != own_doctor:
        raise _forbidden("Doctors may request labs only for their own consultations")

    request = LabRequest(
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
        test_name=data.test_name,
        notes=data.notes,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def get_lab_request(
    db: Session, user: User, request_id: int
) -> LabRequest:
    if user.role == "RECEPTIONIST":
        raise _forbidden("Receptionists may not access lab requests")

    request = db.get(LabRequest, request_id)
    if request is None:
        raise _not_found()

    if user.role == "ADMIN":
        return request
    if user.role == "DOCTOR":
        if _own_doctor_id(db, user) != request.doctor_id:
            raise _not_found()
        return request
    if user.role == "PATIENT":
        if (
            _own_patient_id(db, user) != request.patient_id
            or request.status != "VERIFIED"
        ):
            raise _not_found()
        return request
    raise _not_found()


def list_lab_requests(
    db: Session,
    user: User,
    patient_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
    statuses: Optional[List[str]] = None,
) -> List[LabRequest]:
    if user.role == "RECEPTIONIST":
        raise _forbidden("Receptionists may not access lab requests")

    query = db.query(LabRequest)

    if user.role == "ADMIN":
        if patient_id is not None:
            query = query.filter(LabRequest.patient_id == patient_id)
        if doctor_id is not None:
            query = query.filter(LabRequest.doctor_id == doctor_id)
        if statuses:
            query = query.filter(LabRequest.status.in_(statuses))
    elif user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            return []
        query = query.filter(LabRequest.doctor_id == own)
        if statuses:
            query = query.filter(LabRequest.status.in_(statuses))
    elif user.role == "PATIENT":
        own = _own_patient_id(db, user)
        if own is None:
            return []
        # @decision(8): patients see only their own VERIFIED results.
        query = query.filter(
            LabRequest.patient_id == own, LabRequest.status == "VERIFIED"
        )
    else:
        raise _forbidden("Receptionists may not access lab requests")

    return query.order_by(LabRequest.requested_at.desc()).all()


def update_lab_request(
    db: Session, user: User, request_id: int, data: LabRequestUpdate
) -> LabRequest:
    if user.role not in ("DOCTOR", "ADMIN"):
        raise _forbidden("Only doctors may update lab requests")

    request = db.get(LabRequest, request_id)
    if request is None:
        raise _not_found()

    if user.role == "DOCTOR":
        if _own_doctor_id(db, user) != request.doctor_id:
            raise _not_found()

    if request.status == "VERIFIED":
        raise _unprocessable("Verified lab requests are immutable")

    # @decision(10): admin may only move a request to VERIFIED.
    if user.role == "ADMIN" and data.target_status != "VERIFIED":
        raise _forbidden("Admins may only verify lab results")

    expected_next = _VALID_TRANSITIONS.get(request.status)
    if expected_next is None or data.target_status != expected_next:
        raise _unprocessable(
            f"Invalid status transition from {request.status} to {data.target_status}"
        )

    # @decision(12): result_details required and non-blank when entering RESULT_READY.
    if data.target_status == "RESULT_READY":
        if not data.result_details:
            raise _unprocessable(
                "result_details is required when entering RESULT_READY"
            )

    # @decision(13): result_details editable only before VERIFIED.
    if data.target_status in ("IN_PROGRESS", "RESULT_READY") and data.result_details:
        request.result_details = data.result_details

    if data.target_status == "VERIFIED":
        if user.role == "ADMIN":
            request.verified_by = None
            request.verified_by_admin = user.id
        else:  # DOCTOR
            request.verified_by = request.doctor_id
            request.verified_by_admin = None
        request.verified_at = datetime.now(timezone.utc)

    request.status = data.target_status
    if data.target_status == "RESULT_READY":
        notification_service.notify_lab_ready(db, request)
    elif data.target_status == "VERIFIED":
        notification_service.notify_lab_verified(db, request)
    db.commit()
    db.refresh(request)
    return request