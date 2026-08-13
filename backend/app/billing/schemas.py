from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BillItemCreate(BaseModel):
    description: str = Field(min_length=1)
    category: Literal["CONSULTATION", "LAB_TEST", "PROCEDURE", "SERVICE"]
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)

    @field_validator("description")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("description must not be blank")
        return stripped


class BillCreate(BaseModel):
    appointment_id: int
    due_date: Optional[date] = None
    # @decision: an invoice must contain at least one line item.
    items: List[BillItemCreate] = Field(min_length=1)


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    method: Literal["CASH", "CARD", "UPI", "BANK_TRANSFER", "OTHER"]
    transaction_reference: Optional[str] = None


class BillUpdate(BaseModel):
    status: Literal["OVERDUE", "REFUNDED"]


class BillItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    category: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    method: str
    transaction_reference: Optional[str] = None
    paid_at: datetime
    recorded_by: int


class BillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bill_number: str
    patient_id: int
    appointment_id: int
    status: str
    due_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    total: Decimal
    amount_paid: Decimal
    remaining: Decimal
    items: List[BillItemOut] = []
    payments: List[PaymentOut] = []