from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models import User
from app.staff_management import service
from app.staff_management.schemas import (
    AdminUserCreate,
    DoctorCreate,
    DoctorOut,
    DoctorUpdate,
    ReceptionistCreate,
    ReceptionistOut,
    ReceptionistUpdate,
    UserOut,
)

admin_dep = Depends(require_roles("ADMIN"))

doctors_router = APIRouter(prefix="/admin/doctors", tags=["staff-management"])
receptionists_router = APIRouter(
    prefix="/admin/receptionists", tags=["staff-management"]
)
users_router = APIRouter(prefix="/admin/users", tags=["staff-management"])


def _to_doctor_out(doctor) -> DoctorOut:
    return DoctorOut(
        id=doctor.id,
        user_id=doctor.user_id,
        email=doctor.user.email,
        license_number=doctor.license_number,
        consultation_fee=doctor.consultation_fee,
        status=doctor.user.status,
        deactivated_at=doctor.user.deactivated_at,
        department_ids=[d.id for d in doctor.departments],
        created_at=doctor.created_at,
        updated_at=doctor.updated_at,
    )


def _to_receptionist_out(receptionist) -> ReceptionistOut:
    return ReceptionistOut(
        id=receptionist.id,
        user_id=receptionist.user_id,
        email=receptionist.user.email,
        employee_code=receptionist.employee_code,
        status=receptionist.user.status,
        deactivated_at=receptionist.user.deactivated_at,
        created_at=receptionist.created_at,
        updated_at=receptionist.updated_at,
    )


@doctors_router.post("", response_model=DoctorOut, status_code=status.HTTP_201_CREATED)
def create_doctor(
    payload: DoctorCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> DoctorOut:
    doctor = service.create_doctor(db, current_user, payload, request=request)
    db.refresh(doctor)
    return _to_doctor_out(doctor)


@doctors_router.get("", response_model=List[DoctorOut])
def list_doctors(
    is_active: Optional[bool] = Query(default=None),
    department_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> List[DoctorOut]:
    doctors = service.list_doctors(
        db,
        is_active=is_active,
        department_id=department_id,
        limit=limit,
        offset=offset,
    )
    return [_to_doctor_out(d) for d in doctors]


@doctors_router.get("/{doctor_id}", response_model=DoctorOut)
def get_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> DoctorOut:
    doctor = service.get_doctor(db, doctor_id)
    return _to_doctor_out(doctor)


@doctors_router.patch("/{doctor_id}", response_model=DoctorOut)
def update_doctor(
    doctor_id: int,
    payload: DoctorUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> DoctorOut:
    doctor = service.update_doctor(db, current_user, doctor_id, payload, request=request)
    db.refresh(doctor)
    return _to_doctor_out(doctor)


@doctors_router.put("/{doctor_id}/departments", response_model=DoctorOut)
def set_doctor_departments(
    doctor_id: int,
    payload: List[int],
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> DoctorOut:
    doctor = service.set_doctor_departments(
        db, current_user, doctor_id, payload, request=request
    )
    db.refresh(doctor)
    return _to_doctor_out(doctor)


@receptionists_router.post(
    "", response_model=ReceptionistOut, status_code=status.HTTP_201_CREATED
)
def create_receptionist(
    payload: ReceptionistCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> ReceptionistOut:
    receptionist = service.create_receptionist(
        db, current_user, payload, request=request
    )
    db.refresh(receptionist)
    return _to_receptionist_out(receptionist)


@receptionists_router.get("", response_model=List[ReceptionistOut])
def list_receptionists(
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> List[ReceptionistOut]:
    receptionists = service.list_receptionists(
        db, is_active=is_active, limit=limit, offset=offset
    )
    return [_to_receptionist_out(r) for r in receptionists]


@receptionists_router.get(
    "/{receptionist_id}", response_model=ReceptionistOut
)
def get_receptionist(
    receptionist_id: int,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> ReceptionistOut:
    receptionist = service.get_receptionist(db, receptionist_id)
    return _to_receptionist_out(receptionist)


@receptionists_router.patch(
    "/{receptionist_id}", response_model=ReceptionistOut
)
def update_receptionist(
    receptionist_id: int,
    payload: ReceptionistUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> ReceptionistOut:
    receptionist = service.update_receptionist(
        db, current_user, receptionist_id, payload, request=request
    )
    db.refresh(receptionist)
    return _to_receptionist_out(receptionist)


@users_router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> UserOut:
    user = service.create_admin_user(db, current_user, payload, request=request)
    db.refresh(user)
    return UserOut.model_validate(user)


@users_router.get("", response_model=List[UserOut])
def list_users(
    role: Optional[str] = Query(default=None),
    user_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> List[UserOut]:
    users = service.list_users(
        db,
        role=role,
        status_filter=user_status,
        limit=limit,
        offset=offset,
    )
    return [UserOut.model_validate(u) for u in users]