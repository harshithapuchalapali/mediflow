from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.models import (
    Department,
    Doctor,
    DoctorDepartment,
    Receptionist,
    User,
)
from app.security import hash_password

# Audit actions recorded by this module.
ACTION_DOCTOR_CREATE = "DOCTOR_CREATE"
ACTION_DOCTOR_UPDATE = "DOCTOR_UPDATE"
ACTION_DOCTOR_DEPARTMENTS_SET = "DOCTOR_DEPARTMENTS_SET"
ACTION_RECEPTIONIST_CREATE = "RECEPTIONIST_CREATE"
ACTION_RECEPTIONIST_UPDATE = "RECEPTIONIST_UPDATE"
ACTION_ADMIN_CREATE = "ADMIN_CREATE"


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _fail_if_email_taken(db: Session, email: str, exclude_user_id: Optional[int] = None) -> None:
    query = db.query(User).filter(User.email == email)
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    if query.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )


def _fail_if_license_taken(
    db: Session, license_number: str, exclude_doctor_id: Optional[int] = None
) -> None:
    query = db.query(Doctor).filter(Doctor.license_number == license_number)
    if exclude_doctor_id is not None:
        query = query.filter(Doctor.id != exclude_doctor_id)
    if query.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="License number is already in use",
        )


def _fail_if_employee_code_taken(
    db: Session,
    employee_code: str,
    exclude_receptionist_id: Optional[int] = None,
) -> None:
    query = db.query(Receptionist).filter(
        Receptionist.employee_code == employee_code
    )
    if exclude_receptionist_id is not None:
        query = query.filter(Receptionist.id != exclude_receptionist_id)
    if query.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Employee code is already in use",
        )


def get_doctor(db: Session, doctor_id: int) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found"
        )
    return doctor


def create_doctor(
    db: Session, current_user: User, payload: object, request: Request
) -> Doctor:
    email = _normalize_email(payload.email)
    license_number = payload.license_number.strip()
    _fail_if_email_taken(db, email)
    _fail_if_license_taken(db, license_number)

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role="DOCTOR",
        status="ACTIVE",
    )
    db.add(user)
    db.flush()

    doctor = Doctor(
        user_id=user.id,
        license_number=license_number,
        consultation_fee=Decimal(payload.consultation_fee),
    )
    db.add(doctor)
    db.flush()

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_DOCTOR_CREATE,
        entity_type="DOCTOR",
        entity_id=doctor.id,
        ip_address=request.client.host if request.client else None,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _fail_if_email_taken(db, email)
        _fail_if_license_taken(db, license_number)
        raise
    db.refresh(doctor)
    return doctor


def list_doctors(
    db: Session,
    is_active: Optional[bool] = None,
    department_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Doctor]:
    query = db.query(Doctor)
    if is_active is not None:
        query = query.join(User, User.id == Doctor.user_id).filter(
            User.status == ("ACTIVE" if is_active else "DEACTIVATED")
        )
    if department_id is not None:
        query = query.join(
            DoctorDepartment,
            DoctorDepartment.doctor_id == Doctor.id,
        ).filter(DoctorDepartment.department_id == department_id)
    return (
        query.order_by(Doctor.id)
        .limit(limit)
        .offset(offset)
        .all()
    )


def update_doctor(
    db: Session,
    current_user: User,
    doctor_id: int,
    payload: object,
    request: Request,
) -> Doctor:
    doctor = get_doctor(db, doctor_id)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No updatable fields provided",
        )

    if "email" in fields:
        email = _normalize_email(fields["email"])
        _fail_if_email_taken(db, email, exclude_user_id=doctor.user_id)
        doctor.user.email = email
    if "license_number" in fields:
        license_number = fields["license_number"].strip()
        _fail_if_license_taken(db, license_number, exclude_doctor_id=doctor.id)
        doctor.license_number = license_number
    if "consultation_fee" in fields:
        doctor.consultation_fee = Decimal(fields["consultation_fee"])
    doctor.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_DOCTOR_UPDATE,
        entity_type="DOCTOR",
        entity_id=doctor.id,
        ip_address=request.client.host if request.client else None,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        doctor = get_doctor(db, doctor_id)
        if "email" in fields:
            _fail_if_email_taken(db, _normalize_email(fields["email"]),
                                 exclude_user_id=doctor.user_id)
        if "license_number" in fields:
            _fail_if_license_taken(db, fields["license_number"].strip(),
                                   exclude_doctor_id=doctor.id)
        raise
    db.refresh(doctor)
    return doctor


def set_doctor_departments(
    db: Session,
    current_user: User,
    doctor_id: int,
    department_ids: List[int],
    request: Request,
) -> Doctor:
    doctor = get_doctor(db, doctor_id)
    seen = set()
    unique_ids = []
    for dept_id in department_ids:
        if dept_id in seen:
            continue
        seen.add(dept_id)
        if db.get(Department, dept_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department {dept_id} not found",
            )
        unique_ids.append(dept_id)

    db.query(DoctorDepartment).filter(
        DoctorDepartment.doctor_id == doctor.id
    ).delete()
    for dept_id in unique_ids:
        db.add(DoctorDepartment(doctor_id=doctor.id, department_id=dept_id))
    doctor.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_DOCTOR_DEPARTMENTS_SET,
        entity_type="DOCTOR",
        entity_id=doctor.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(doctor)
    return doctor


def get_receptionist(db: Session, receptionist_id: int) -> Receptionist:
    receptionist = db.get(Receptionist, receptionist_id)
    if receptionist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receptionist not found",
        )
    return receptionist


def create_receptionist(
    db: Session, current_user: User, payload: object, request: Request
) -> Receptionist:
    email = _normalize_email(payload.email)
    _fail_if_email_taken(db, email)
    employee_code = (
        payload.employee_code.strip() if payload.employee_code else None
    )
    if employee_code:
        _fail_if_employee_code_taken(db, employee_code)

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role="RECEPTIONIST",
        status="ACTIVE",
    )
    db.add(user)
    db.flush()

    receptionist = Receptionist(user_id=user.id, employee_code=employee_code)
    db.add(receptionist)
    db.flush()

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_RECEPTIONIST_CREATE,
        entity_type="RECEPTIONIST",
        entity_id=receptionist.id,
        ip_address=request.client.host if request.client else None,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _fail_if_email_taken(db, email)
        if employee_code:
            _fail_if_employee_code_taken(db, employee_code)
        raise
    db.refresh(receptionist)
    return receptionist


def list_receptionists(
    db: Session,
    is_active: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Receptionist]:
    query = db.query(Receptionist)
    if is_active is not None:
        query = query.join(User, User.id == Receptionist.user_id).filter(
            User.status == ("ACTIVE" if is_active else "DEACTIVATED")
        )
    return query.order_by(Receptionist.id).limit(limit).offset(offset).all()


def update_receptionist(
    db: Session,
    current_user: User,
    receptionist_id: int,
    payload: object,
    request: Request,
) -> Receptionist:
    receptionist = get_receptionist(db, receptionist_id)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No updatable fields provided",
        )

    if "email" in fields:
        email = _normalize_email(fields["email"])
        _fail_if_email_taken(db, email, exclude_user_id=receptionist.user_id)
        receptionist.user.email = email
    if "employee_code" in fields:
        if fields["employee_code"] is None:
            receptionist.employee_code = None
        else:
            employee_code = fields["employee_code"].strip()
            if employee_code:
                _fail_if_employee_code_taken(
                    db, employee_code, exclude_receptionist_id=receptionist.id
                )
                receptionist.employee_code = employee_code
    receptionist.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_RECEPTIONIST_UPDATE,
        entity_type="RECEPTIONIST",
        entity_id=receptionist.id,
        ip_address=request.client.host if request.client else None,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        receptionist = get_receptionist(db, receptionist_id)
        _fail_if_email_taken(
            db, _normalize_email(fields["email"]),
            exclude_user_id=receptionist.user_id,
        ) if "email" in fields else None
        raise
    db.refresh(receptionist)
    return receptionist


def list_users(
    db: Session,
    role: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[User]:
    query = db.query(User)
    if role is not None:
        query = query.filter(User.role == role)
    if status_filter is not None:
        query = query.filter(User.status == status_filter)
    return query.order_by(User.id.desc()).limit(limit).offset(offset).all()


def create_admin_user(
    db: Session, current_user: User, payload: object, request: Request
) -> User:
    email = _normalize_email(payload.email)
    _fail_if_email_taken(db, email)

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role="ADMIN",
        status="ACTIVE",
    )
    db.add(user)
    db.flush()

    write_audit_log(
        db,
        user_id=current_user.id,
        action=ACTION_ADMIN_CREATE,
        entity_type="USER",
        entity_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _fail_if_email_taken(db, email)
        raise
    db.refresh(user)
    return user