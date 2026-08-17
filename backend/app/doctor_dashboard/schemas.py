from datetime import date
from typing import List

from pydantic import BaseModel


class AppointmentStats(BaseModel):
    total: int
    today: int
    completed: int
    confirmed: int
    cancelled: int
    no_show: int


class AppointmentByDay(BaseModel):
    date: date
    total: int


class PatientStats(BaseModel):
    total: int
    today: int


class ConsultationStats(BaseModel):
    total_records: int
    records_today: int
    total_prescriptions: int
    prescriptions_today: int


class DoctorDashboardOut(BaseModel):
    doctor_id: int
    today: date
    date_from: date
    date_to: date
    appointments: AppointmentStats
    appointment_by_day: List[AppointmentByDay]
    patients: PatientStats
    consultations: ConsultationStats