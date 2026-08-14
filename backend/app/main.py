from fastapi import FastAPI

from app.admin_console.routes import (
    audit_router,
    dashboard_router,
    departments_router,
    settings_router,
)
from app.appointments.routes import router as appointments_router
from app.billing.routes import router as billing_router
from app.doctor_schedules.routes import (
    schedules_router as doctor_schedules_router,
    unavailable_router as doctor_unavailable_router,
)
from app.lab_requests.routes import router as lab_requests_router
from app.medical_records.routes import router as medical_records_router
from app.patients.routes import patients_router
from app.patients.routes import register_router
from app.prescriptions.routes import router as prescriptions_router
from app.routers.auth import router as auth_router
from app.staff_management.routes import (
    doctors_router,
    receptionists_router,
    users_router,
)

app = FastAPI(title="MediFlow API")

app.include_router(auth_router)
app.include_router(register_router)
app.include_router(patients_router)
app.include_router(appointments_router)
app.include_router(medical_records_router)
app.include_router(prescriptions_router)
app.include_router(lab_requests_router)
app.include_router(billing_router)
app.include_router(doctor_schedules_router)
app.include_router(doctor_unavailable_router)
app.include_router(settings_router)
app.include_router(departments_router)
app.include_router(audit_router)
app.include_router(dashboard_router)
app.include_router(doctors_router)
app.include_router(receptionists_router)
app.include_router(users_router)


@app.get("/")
def root():
    return {"message": "MediFlow API is running"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "MediFlow API"}