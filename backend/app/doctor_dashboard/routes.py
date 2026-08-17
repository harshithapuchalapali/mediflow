from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.doctor_dashboard import service
from app.doctor_dashboard.schemas import DoctorDashboardOut
from app.models import User

router = APIRouter(prefix="/doctor", tags=["doctor-dashboard"])

doctor_dep = Depends(require_roles("DOCTOR"))


@router.get("/dashboard", response_model=DoctorDashboardOut)
def get_doctor_dashboard(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = doctor_dep,
) -> DoctorDashboardOut:
    return DoctorDashboardOut.model_validate(
        service.dashboard_stats(db, current_user, start_date, end_date)
    )