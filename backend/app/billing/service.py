from decimal import Decimal
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing.schemas import (
    BillCreate,
    BillItemCreate,
    BillUpdate,
    PaymentCreate,
)
from app.models import (
    Appointment,
    Bill,
    BillItem,
    Doctor,
    Patient,
    Payment,
    User,
)

_MAX_BILL_NUMBER_RETRIES = 5


def _forbidden(detail: str = "Not permitted for this bill") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _not_found(detail: str = "Bill not found") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail,
    )


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    )


def _own_patient_id(db: Session, user: User) -> Optional[int]:
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    return patient.id if patient else None


def _own_doctor_id(db: Session, user: User) -> Optional[int]:
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    return doctor.id if doctor else None


def _can_read_bill(bill: Bill, user: User, db: Session) -> bool:
    """IDOR ownership check. ADMIN reads all; PATIENT own; DOCTOR own consultations."""
    if user.role == "ADMIN":
        return True
    if user.role == "PATIENT":
        return _own_patient_id(db, user) == bill.patient_id
    if user.role == "DOCTOR":
        return bill.appointment is not None and (
            _own_doctor_id(db, user) == bill.appointment.doctor_id
        )
    return False


def bill_totals(bill: Bill) -> Tuple[Decimal, Decimal]:
    """Total is always recomputed from items; paid from accumulated payments."""
    total = sum(
        (item.unit_price or Decimal("0")) * item.quantity
        for item in bill.items
    )
    paid = sum((payment.amount or Decimal("0")) for payment in bill.payments)
    return Decimal(total), Decimal(paid)


def _recompute_status(bill: Bill, total: Decimal, paid: Decimal) -> None:
    if bill.status == "REFUNDED":
        return
    if paid >= total:
        bill.status = "PAID"
        return
    if bill.status == "OVERDUE":
        return
    bill.status = "PARTIALLY_PAID" if paid > 0 else "PENDING"


def _next_bill_number(db: Session) -> str:
    value = db.execute(text("SELECT nextval('bill_number_seq')")).scalar()
    return f"INV-{int(value):06d}"


def create_bill(db: Session, user: User, data: BillCreate) -> Bill:
    if user.role not in ("ADMIN", "RECEPTIONIST"):
        raise _forbidden("Only admin or receptionist may create bills")

    appointment = db.get(Appointment, data.appointment_id)
    if appointment is None:
        raise _not_found("Appointment not found")

    existing = (
        db.query(Bill).filter(Bill.appointment_id == appointment.id).first()
    )
    if existing is not None:
        raise _conflict("A bill already exists for this appointment")

    items = [
        BillItem(
            description=item.description,
            category=item.category,
            quantity=item.quantity,
            unit_price=item.unit_price,
        )
        for item in data.items
    ]

    for _ in range(_MAX_BILL_NUMBER_RETRIES):
        bill = Bill(
            bill_number=_next_bill_number(db),
            patient_id=appointment.patient_id,
            appointment_id=appointment.id,
            status="PENDING",
            due_date=data.due_date,
            items=items,
        )
        db.add(bill)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
    else:
        raise _conflict("Could not allocate a unique bill number")

    db.refresh(bill)
    return bill


def get_bill(db: Session, user: User, bill_id: int) -> Bill:
    if user.role == "RECEPTIONIST":
        raise _forbidden("Receptionists may not view bills")
    bill = db.get(Bill, bill_id)
    if bill is None or not _can_read_bill(bill, user, db):
        raise _not_found()
    return bill


def list_bills(
    db: Session,
    user: User,
    patient_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
    statuses: Optional[List[str]] = None,
) -> List[Bill]:
    if user.role == "RECEPTIONIST":
        raise _forbidden("Receptionists may not view bills")

    query = db.query(Bill)

    if user.role == "ADMIN":
        if patient_id is not None:
            query = query.filter(Bill.patient_id == patient_id)
        if doctor_id is not None:
            query = query.join(Appointment, Bill.appointment_id == Appointment.id)
            query = query.filter(Appointment.doctor_id == doctor_id)
        if statuses:
            query = query.filter(Bill.status.in_(statuses))
    elif user.role == "PATIENT":
        own = _own_patient_id(db, user)
        if own is None:
            return []
        query = query.filter(Bill.patient_id == own)
        if statuses:
            query = query.filter(Bill.status.in_(statuses))
    elif user.role == "DOCTOR":
        own = _own_doctor_id(db, user)
        if own is None:
            return []
        query = query.join(Appointment, Bill.appointment_id == Appointment.id)
        query = query.filter(Appointment.doctor_id == own)
        if statuses:
            query = query.filter(Bill.status.in_(statuses))
    else:
        raise _forbidden("Receptionists may not view bills")

    return query.order_by(Bill.created_at.desc()).all()


def update_bill(
    db: Session, user: User, bill_id: int, data: BillUpdate
) -> Bill:
    if user.role != "ADMIN":
        raise _forbidden("Only admins may change a bill's status")

    bill = db.get(Bill, bill_id)
    if bill is None:
        raise _not_found()

    if bill.status == "REFUNDED":
        raise _unprocessable("Refunded bills are immutable")

    if data.status == "REFUNDED":
        bill.status = "REFUNDED"
    elif data.status == "OVERDUE":
        if bill.status not in ("PENDING", "PARTIALLY_PAID"):
            raise _unprocessable("Only unpaid bills can be marked OVERDUE")
        bill.status = "OVERDUE"

    db.commit()
    db.refresh(bill)
    return bill


def add_bill_item(
    db: Session, user: User, bill_id: int, data: BillItemCreate
) -> Bill:
    if user.role not in ("ADMIN", "RECEPTIONIST"):
        raise _forbidden("Only admin or receptionist may modify bills")

    bill = db.get(Bill, bill_id)
    if bill is None:
        raise _not_found()

    if bill.status in ("PAID", "REFUNDED"):
        raise _unprocessable("Settled bills cannot be modified")

    total, paid = bill_totals(bill)
    item = BillItem(
        bill_id=bill.id,
        description=data.description,
        category=data.category,
        quantity=data.quantity,
        unit_price=data.unit_price,
    )
    bill.items.append(item)
    _recompute_status(bill, total + data.quantity * data.unit_price, paid)

    db.commit()
    db.refresh(bill)
    return bill


def record_payment(
    db: Session, user: User, bill_id: int, data: PaymentCreate
) -> Bill:
    if user.role not in ("ADMIN", "RECEPTIONIST"):
        raise _forbidden("Only admin or receptionist may record payments")

    bill = db.get(Bill, bill_id)
    if bill is None:
        raise _not_found()

    if bill.status == "REFUNDED":
        raise _unprocessable("Refunded bills cannot accept payments")

    total, paid = bill_totals(bill)
    remaining = total - paid
    if data.amount > remaining:
        raise _unprocessable("Payment exceeds the remaining balance")

    payment = Payment(
        bill_id=bill.id,
        amount=data.amount,
        method=data.method,
        transaction_reference=data.transaction_reference,
        recorded_by=user.id,
    )
    _recompute_status(bill, total, paid + data.amount)
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("A payment with this transaction_reference already exists")

    db.refresh(bill)
    return bill