from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.admin_console import service
from app.admin_console.schemas import (
    AuditLogOut,
    DashboardOut,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    HospitalSettingsCreate,
    HospitalSettingsOut,
    HospitalSettingsUpdate,
)
from app.db import get_db
from app.deps import require_roles
from app.models import User

admin_dep = Depends(require_roles("ADMIN"))

settings_router = APIRouter(prefix="/admin/hospital-settings", tags=["admin-console"])
departments_router = APIRouter(prefix="/admin/departments", tags=["admin-console"])
audit_router = APIRouter(prefix="/admin/audit-logs", tags=["admin-console"])
dashboard_router = APIRouter(prefix="/admin/dashboard", tags=["admin-console"])


@settings_router.get("", response_model=HospitalSettingsOut)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> HospitalSettingsOut:
    settings = service.get_settings(db)
    return HospitalSettingsOut.model_validate(settings)


@settings_router.post("", response_model=HospitalSettingsOut, status_code=status.HTTP_201_CREATED)
def create_settings(
    payload: HospitalSettingsCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> HospitalSettingsOut:
    settings = service.create_settings(db, current_user, payload, request=request)
    return HospitalSettingsOut.model_validate(settings)


@settings_router.patch("", response_model=HospitalSettingsOut)
def update_settings(
    payload: HospitalSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> HospitalSettingsOut:
    settings = service.update_settings(db, current_user, payload, request=request)
    return HospitalSettingsOut.model_validate(settings)


@departments_router.get("", response_model=List[DepartmentOut])
def list_departments(
    is_active: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> List[DepartmentOut]:
    departments = service.list_departments(db, is_active=is_active)
    return [DepartmentOut.model_validate(d) for d in departments]


@departments_router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    payload: DepartmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> DepartmentOut:
    department = service.create_department(db, current_user, payload, request=request)
    return DepartmentOut.model_validate(department)


@departments_router.get("/{department_id}", response_model=DepartmentOut)
def get_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> DepartmentOut:
    department = service.get_department(db, department_id)
    return DepartmentOut.model_validate(department)


@departments_router.patch("/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> DepartmentOut:
    department = service.update_department(
        db, current_user, department_id, payload, request=request
    )
    return DepartmentOut.model_validate(department)


@departments_router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_department(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> None:
    # Soft-close (§3.7): the row stays, `is_active` flips to false.
    service.deactivate_department(db, current_user, department_id, request=request)


@audit_router.get("", response_model=List[AuditLogOut])
def list_audit_logs(
    action: Optional[str] = Query(default=None),
    entity_type: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> List[AuditLogOut]:
    logs = service.list_audit_logs(
        db,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return [AuditLogOut.model_validate(entry) for entry in logs]


@dashboard_router.get("", response_model=DashboardOut)
def get_dashboard(
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = admin_dep,
) -> DashboardOut:
    return DashboardOut.model_validate(service.dashboard_stats(db, date_from, date_to))
