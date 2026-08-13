from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    doctor: Mapped[Optional["Doctor"]] = relationship(
        back_populates="user"
    )
    receptionist: Mapped[Optional["Receptionist"]] = relationship(
        back_populates="user"
    )
    medical_record_versions: Mapped[list["MedicalRecordVersion"]] = relationship(
        back_populates="changed_by_user"
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
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="patient"
    )
    medical_records: Mapped[list["MedicalRecord"]] = relationship(
        back_populates="patient"
    )

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


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True
    )
    license_number: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )
    consultation_fee: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        server_default=text("0"),
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

    user: Mapped["User"] = relationship(back_populates="doctor")
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="doctor"
    )
    medical_records: Mapped[list["MedicalRecord"]] = relationship(
        back_populates="doctor"
    )

    __table_args__ = (
        CheckConstraint(
            "consultation_fee >= 0",
            name="ck_doctors_consultation_fee",
        ),
    )


class Receptionist(Base):
    __tablename__ = "receptionists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True
    )
    employee_code: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, unique=True
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

    user: Mapped["User"] = relationship(back_populates="receptionist")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"), nullable=False
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id"), nullable=False
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id"), nullable=False
    )
    date_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("30")
    )
    priority: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'NORMAL'")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PENDING'")
    )
    appointment_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'INITIAL_CONSULTATION'"),
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
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

    patient: Mapped["Patient"] = relationship(back_populates="appointments")
    doctor: Mapped["Doctor"] = relationship(back_populates="appointments")
    medical_record: Mapped[Optional["MedicalRecord"]] = relationship(
        back_populates="appointment",
        uselist=False,
    )

    __table_args__ = (
        CheckConstraint(
            "duration_minutes BETWEEN 5 AND 480",
            name="ck_appointments_duration_minutes",
        ),
        CheckConstraint(
            "priority IN ('NORMAL', 'URGENT', 'EMERGENCY')",
            name="ck_appointments_priority",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'CHECKED_IN', 'COMPLETED', 'CANCELLED', 'NO_SHOW')",
            name="ck_appointments_status",
        ),
        CheckConstraint(
            "appointment_type IN ('INITIAL_CONSULTATION', 'FOLLOW_UP')",
            name="ck_appointments_appointment_type",
        ),
        Index("idx_appt_doctor_time", "doctor_id", "date_time"),
        Index("idx_appt_patient", "patient_id", "date_time"),
        Index("idx_appt_status_date", "status", "date_time"),
    )


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("appointments.id"), nullable=False, unique=True
    )
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id"), nullable=False
    )
    doctor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("doctors.id"), nullable=False
    )
    latest_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    patient: Mapped["Patient"] = relationship(back_populates="medical_records")
    doctor: Mapped["Doctor"] = relationship(back_populates="medical_records")
    appointment: Mapped["Appointment"] = relationship(
        back_populates="medical_record"
    )
    versions: Mapped[list["MedicalRecordVersion"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="MedicalRecordVersion.version_number",
    )


class MedicalRecordVersion(Base):
    __tablename__ = "medical_record_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medical_records.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    symptoms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    vitals_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    record: Mapped["MedicalRecord"] = relationship(back_populates="versions")
    changed_by_user: Mapped["User"] = relationship(
        back_populates="medical_record_versions"
    )

    __table_args__ = (
        CheckConstraint(
            "version_number >= 1",
            name="ck_medical_record_versions_version_number",
        ),
        UniqueConstraint(
            "record_id", "version_number", name="uq_medical_record_versions_record_version"
        ),
    )