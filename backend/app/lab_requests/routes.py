from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.lab_requests import report_files, service
from app.lab_requests.schemas import (
    LabRequestCreate,
    LabRequestOut,
    LabRequestUpdate,
)
from app.models import LabRequest, User

router = APIRouter(prefix="/lab-requests", tags=["lab-requests"])


def _to_out(request: LabRequest) -> LabRequestOut:
    return LabRequestOut.model_validate(request)


@router.post(
    "", response_model=LabRequestOut, status_code=status.HTTP_201_CREATED
)
def create_lab_request(
    payload: LabRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LabRequestOut:
    request = service.create_lab_request(db, current_user, payload)
    return _to_out(request)


@router.get("", response_model=List[LabRequestOut])
def list_lab_requests(
    patient_id: Optional[int] = Query(default=None),
    doctor_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[LabRequestOut]:
    statuses = [s.strip() for s in status.split(",")] if status else None
    requests = service.list_lab_requests(
        db,
        current_user,
        patient_id=patient_id,
        doctor_id=doctor_id,
        statuses=statuses,
    )
    return [_to_out(r) for r in requests]


@router.get("/{request_id}", response_model=LabRequestOut)
def get_lab_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LabRequestOut:
    request = service.get_lab_request(db, current_user, request_id)
    return _to_out(request)


@router.patch("/{request_id}", response_model=LabRequestOut)
def update_lab_request(
    request_id: int,
    payload: LabRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LabRequestOut:
    request = service.update_lab_request(db, current_user, request_id, payload)
    return _to_out(request)


@router.post("/{request_id}/report", response_model=LabRequestOut)
async def upload_lab_report(
    request_id: int,
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LabRequestOut:
    data = await file.read(report_files.MAX_REPORT_BYTES + 1)
    lab = service.upload_lab_report(
        db,
        current_user,
        request_id,
        data=data,
        original_filename=file.filename,
        request=request,
    )
    return _to_out(lab)


@router.get("/{request_id}/report")
def download_lab_report(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    path, media_type, filename = service.get_lab_report_file(
        db, current_user, request_id
    )
    return FileResponse(path=path, media_type=media_type, filename=filename)