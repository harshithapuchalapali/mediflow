from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import Date, case, cast, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin_console.schemas import (
    DepartmentCreate,
    DepartmentUpdate,
    HospitalSettingsCreate,
    HospitalSettingsUpdate,
)
from app.audit import write_audit_log
from app.models import (
    Appointment,
    AuditLog,
    Bill,
    BillItem,
    Department,
    HospitalSettings,
    LabRequest,
    Payment,
    User,
)

# v1 clinic timezone (requirements.md / database-design.md §1): all display
# and dashboard "day" boundaries use Asia/Kolkata. DB stores UTC.
CLINIC_TZ = "Asia/Kolkata"

# Actions recorded on the audit log for this module.
ACTION_SETTINGS_CREATE = "SETTINGS_CREATE"
ACTION_SETTINGS_UPDATE = "SETTINGS_UPDATE"
ACTION_DEPARTMENT_CREATE = "DEPARTMENT_CREATE"
ACTION_DEPARTMENT_UPDATE = "DEPARTMENT_UPDATE"
ACTION_DEPARTMENT_DEACTIVATE = "DEPARTMENT_DEACTIVATE"


def _ip(request) -> Optional[str]:
    if request is None:
        return None
    client = getattr(request, "client", None)
    return client.host if client else None


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
    )


# ---------------------------------------------------------------------------
# Hospital settings (database-design.md §3.1 — single-row, id locked to 1)
# ---------------------------------------------------------------------------


def get_settings(db: Session) -> HospitalSettings:
    settings = db.get(HospitalSettings, 1)
    if settings is None:
        raise _not_found("Hospital settings have not been configured yet")
    return settings


def create_settings(
    db: Session, user: User, data: HospitalSettingsCreate, request=None
) -> HospitalSettings:
    if db.get(HospitalSettings, 1) is not None:
        raise _conflict("Hospital settings already exist (single row only)")
    settings = HospitalSettings(
        id=1,
        hospital_name=data.hospital_name,
        address=data.address,
        phone=data.phone,
        email=data.email,
        timezone=data.timezone,
        logo_path=data.logo_path,
    )
    db.add(settings)
    write_audit_log(
        db,
        user_id=user.id,
        action=ACTION_SETTINGS_CREATE,
        entity_type="HOSPITAL_SETTINGS",
        entity_id=1,
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(settings)
    return settings


def update_settings(
    db: Session, user: User, data: HospitalSettingsUpdate, request=None
) -> HospitalSettings:
    settings = get_settings(db)
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise _unprocessable("Nothing to update")
    # Explicit null would violate the NOT NULL column: pydantic runs its
    # validators on omitted fields too, so keep the null check in service.
    if "hospital_name" in fields and fields["hospital_name"] is None:
        raise _unprocessable("hospital_name must not be null")

    for field, value in fields.items():
        setattr(settings, field, value)

    db.add(settings)
    write_audit_log(
        db,
        user_id=user.id,
        action=ACTION_SETTINGS_UPDATE,
        entity_type="HOSPITAL_SETTINGS",
        entity_id=1,
        ip_address=_ip(request),
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _unprocessable("Invalid hospital settings values")
    db.refresh(settings)
    return settings


# ---------------------------------------------------------------------------
# Departments (database-design.md §3.7 — soft-close via is_active)
# ---------------------------------------------------------------------------


def create_department(
    db: Session, user: User, data: DepartmentCreate, request=None
) -> Department:
    department = Department(name=data.name, description=data.description)
    db.add(department)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflict("A department with this name already exists")
    write_audit_log(
        db,
        user_id=user.id,
        action=ACTION_DEPARTMENT_CREATE,
        entity_type="DEPARTMENT",
        entity_id=department.id,
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(department)
    return department


def list_departments(
    db: Session, is_active: Optional[bool] = None
) -> List[Department]:
    query = db.query(Department)
    if is_active is not None:
        query = query.filter(Department.is_active == is_active)
    return query.order_by(Department.name).all()


def get_department(db: Session, department_id: int) -> Department:
    department = db.get(Department, department_id)
    if department is None:
        raise _not_found("Department not found")
    return department


def update_department(
    db: Session,
    user: User,
    department_id: int,
    data: DepartmentUpdate,
    request=None,
) -> Department:
    department = get_department(db, department_id)
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise _unprocessable("Nothing to update")

    for field, value in fields.items():
        setattr(department, field, value)

    db.add(department)
    write_audit_log(
        db,
        user_id=user.id,
        action=ACTION_DEPARTMENT_UPDATE,
        entity_type="DEPARTMENT",
        entity_id=department.id,
        ip_address=_ip(request),
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("A department with this name already exists")
    db.refresh(department)
    return department


def deactivate_department(
    db: Session, user: User, department_id: int, request=None
) -> None:
    """Soft-close (§3.7: ``is_active`` instead of DELETE). Historical rows
    (appointments, bills) keep referencing the department."""
    department = get_department(db, department_id)
    department.is_active = False
    db.add(department)
    write_audit_log(
        db,
        user_id=user.id,
        action=ACTION_DEPARTMENT_DEACTIVATE,
        entity_type="DEPARTMENT",
        entity_id=department.id,
        ip_address=_ip(request),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Audit log (database-design.md §3.22 — append-only, ADMIN read)
# ---------------------------------------------------------------------------


def list_audit_logs(
    db: Session,
    *,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[AuditLog]:
    query = db.query(AuditLog)
    if action is not None:
        query = query.filter(AuditLog.action == action)
    if entity_type is not None:
        query = query.filter(AuditLog.entity_type == entity_type)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if date_from is not None:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to is not None:
        query = query.filter(AuditLog.created_at <= date_to)
    return (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


# ---------------------------------------------------------------------------
# Dashboard statistics (requirements.md, Admins: "View key statistics")
# ---------------------------------------------------------------------------


def _role_totals(db: Session) -> Dict[str, Dict[str, int]]:
    roles = ("PATIENT", "DOCTOR", "RECEPTIONIST", "ADMIN")
    labels = {
        "PATIENT": "patients",
        "DOCTOR": "doctors",
        "RECEPTIONIST": "receptionists",
        "ADMIN": "admins",
    }
    registered = dict(
        db.query(User.role, func.count(User.id))
        .filter(User.role.in_(roles))
        .group_by(User.role)
        .all()
    )
    active = dict(
        db.query(User.role, func.count(User.id))
        .filter(User.role.in_(roles), User.status == "ACTIVE")
        .group_by(User.role)
        .all()
    )
    return {
        labels[role]: {
            "active": active.get(role, 0),
            "registered": registered.get(role, 0),
        }
        for role in roles
    }


def _appointment_trends(
    db: Session, date_from: date, date_to: date
) -> Tuple[List[Dict[str, object]], Dict[str, int]]:
    day = cast(func.timezone(CLINIC_TZ, Appointment.date_time), Date)
    rows = (
        db.query(day, func.count(Appointment.id))
        .filter(day >= date_from, day <= date_to)
        .group_by(day)
        .order_by(day)
        .all()
    )
    points = [{"date": d, "total": c} for d, c in rows]

    statuses = ("PENDING", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    summary = {s: 0 for s in statuses}
    status_rows = (
        db.query(Appointment.status, func.count(Appointment.id))
        .filter(day >= date_from, day <= date_to)
        .group_by(Appointment.status)
        .all()
    )
    for s, c in status_rows:
        if s in summary:
            summary[s] = c
    return points, summary


def _bills_overview(db: Session) -> Dict[str, object]:
    billed = (
        db.query(func.sum(BillItem.quantity * BillItem.unit_price))
        .join(Bill, BillItem.bill_id == Bill.id)
        .scalar()
    )
    collected = db.query(func.sum(Payment.amount)).scalar()
    billed = billed if billed is not None else Decimal("0")
    collected = collected if collected is not None else Decimal("0")

    by_status = dict(
        db.query(Bill.status, func.count(Bill.id)).group_by(Bill.status).all()
    )
    return {
        "bills_count": db.query(func.count(Bill.id)).scalar(),
        "billed_total": billed,
        "collected_total": collected,
        "outstanding": billed - collected,
        "by_status": by_status,
    }


def _labs_per_department(db: Session) -> List[Dict[str, object]]:
    rows = (
        db.query(Department.id, Department.name, LabRequest.status, func.count(LabRequest.id))
        .join(Appointment, Appointment.department_id == Department.id)
        .join(LabRequest, LabRequest.appointment_id == Appointment.id)
        .group_by(Department.id, Department.name, LabRequest.status)
        .order_by(Department.name)
        .all()
    )
    grouped: Dict[int, Dict[str, object]] = {}
    for dept_id, dept_name, lab_status, count in rows:
        entry = grouped.setdefault(
            dept_id, {"department_id": dept_id, "department_name": dept_name, "by_status": {}}
        )
        entry["by_status"][lab_status] = count
    for entry in grouped.values():
        entry["total"] = sum(entry["by_status"].values())
    return list(grouped.values())


def dashboard_stats(
    db: Session, date_from: Optional[date] = None, date_to: Optional[date] = None
) -> Dict[str, object]:
    today = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    ).date()
    end = date_to or today
    start = date_from or (end - timedelta(days=29))
    if start > end:
        start, end = end, start

    points, summary = _appointment_trends(db, start, end)
    return {
        "totals": _role_totals(db),
        "appointment_trends": points,
        "appointment_trend_summary": summary,
        "bills_overview": _bills_overview(db),
        "labs_per_department": _labs_per_department(db),
    }
