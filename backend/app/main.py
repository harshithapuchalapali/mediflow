from fastapi import FastAPI

from app.appointments.routes import router as appointments_router
from app.lab_requests.routes import router as lab_requests_router
from app.medical_records.routes import router as medical_records_router
from app.prescriptions.routes import router as prescriptions_router
from app.routers.auth import router as auth_router

app = FastAPI(title="MediFlow API")

app.include_router(auth_router)
app.include_router(appointments_router)
app.include_router(medical_records_router)
app.include_router(prescriptions_router)
app.include_router(lab_requests_router)


@app.get("/")
def root():
    return {"message": "MediFlow API is running"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "MediFlow API"}