from fastapi import FastAPI

app = FastAPI(title="MediFlow API")


@app.get("/")
def root():
    return {"message": "MediFlow API is running"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "MediFlow API"}