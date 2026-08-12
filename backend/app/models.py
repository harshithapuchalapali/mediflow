from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'ACTIVE'")
    )
    failed_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    patients: Mapped[Optional["Patient"]] = relationship(
        back_populates="user"
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN', 'DOCTOR', 'RECEPTIONIST', 'PATIENT')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'DEACTIVATED')",
            name="ck_users_status",
        ),
        CheckConstraint(
            "failed_attempts BETWEEN 0 AND 5",
            name="ck_users_failed_attempts",
        ),
        Index("idx_users_role", "role"),
    )


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True
    )
    mrn: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dob: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blood_group: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    height_cm: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 1), nullable=True
    )
    weight_kg: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 1), nullable=True
    )
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(
        String(150), nullable=True
    )
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="patients")

    __table_args__ = (
        CheckConstraint("dob <= CURRENT_DATE", name="ck_patients_dob"),
        CheckConstraint(
            "gender IN ('MALE', 'FEMALE', 'OTHER')",
            name="ck_patients_gender",
        ),
        CheckConstraint(
            "blood_group IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-', 'UNKNOWN')",
            name="ck_patients_blood_group",
        ),
        CheckConstraint(
            "height_cm > 0 AND height_cm < 300",
            name="ck_patients_height_cm",
        ),
        CheckConstraint(
            "weight_kg > 0 AND weight_kg < 500",
            name="ck_patients_weight_kg",
        ),
        Index("idx_patients_name", "last_name", "first_name"),
    )