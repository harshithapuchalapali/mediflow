from fastapi import FastAPI

from app.appointments.routes import router as appointments_router
from app.routers.auth import router as auth_router

app = FastAPI(title="MediFlow API")

app.include_router(auth_router)
app.include_router(appointments_router)


@app.get("/")
def root():
    return {"message": "MediFlow API is running"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "MediFlow API"}