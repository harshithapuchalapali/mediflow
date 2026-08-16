from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.billing import service
from app.billing.schemas import (
    BillCreate,
    BillItemCreate,
    BillItemOut,
    BillOut,
    BillUpdate,
    PaymentCreate,
    PaymentOut,
)
from app.db import get_db
from app.deps import get_current_user
from app.models import Bill, HospitalSettings, User
from app.pdf.bill_pdf import bill_pdf_bytes

router = APIRouter(prefix="/bills", tags=["bills"])


def _to_out(bill: Bill) -> BillOut:
    total, paid = service.bill_totals(bill)
    return BillOut(
        id=bill.id,
        bill_number=bill.bill_number,
        patient_id=bill.patient_id,
        appointment_id=bill.appointment_id,
        status=bill.status,
        due_date=bill.due_date,
        created_at=bill.created_at,
        updated_at=bill.updated_at,
        total=total,
        amount_paid=paid,
        remaining=total - paid,
        items=[
            BillItemOut(
                id=i.id,
                description=i.description,
                category=i.category,
                quantity=i.quantity,
                unit_price=i.unit_price,
                line_total=i.unit_price * i.quantity,
            )
            for i in bill.items
        ],
        payments=[PaymentOut.model_validate(p) for p in bill.payments],
    )


@router.post("", response_model=BillOut, status_code=status.HTTP_201_CREATED)
def create_bill(
    payload: BillCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillOut:
    bill = service.create_bill(db, current_user, payload)
    return _to_out(bill)


@router.get("", response_model=List[BillOut])
def list_bills(
    patient_id: Optional[int] = Query(default=None),
    doctor_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[BillOut]:
    statuses = [s.strip() for s in status.split(",")] if status else None
    bills = service.list_bills(
        db,
        current_user,
        patient_id=patient_id,
        doctor_id=doctor_id,
        statuses=statuses,
    )
    return [_to_out(b) for b in bills]


@router.get("/{bill_id}", response_model=BillOut)
def get_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillOut:
    bill = service.get_bill(db, current_user, bill_id)
    return _to_out(bill)


@router.get("/{bill_id}/pdf")
def download_bill_pdf(
    bill_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    bill = service.get_bill(db, current_user, bill_id)
    settings = db.get(HospitalSettings, 1)
    pdf = bill_pdf_bytes(db, bill, settings)
    filename = "%s.pdf" % bill.bill_number
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )


@router.patch("/{bill_id}", response_model=BillOut)
def update_bill(
    bill_id: int,
    payload: BillUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillOut:
    bill = service.update_bill(db, current_user, bill_id, payload)
    return _to_out(bill)


@router.post("/{bill_id}/items", response_model=BillOut)
def add_bill_item(
    bill_id: int,
    payload: BillItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillOut:
    bill = service.add_bill_item(db, current_user, bill_id, payload)
    return _to_out(bill)


@router.post("/{bill_id}/payments", response_model=BillOut)
def record_payment(
    bill_id: int,
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillOut:
    bill = service.record_payment(db, current_user, bill_id, payload)
    return _to_out(bill)