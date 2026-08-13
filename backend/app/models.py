from datetime import date, datetime, time
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
    Time,
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
    patient_allergies: Mapped[list["PatientAllergy"]] = relationship(
        back_populates="created_by_user"
    )
    admin_verified_lab_requests: Mapped[list["LabRequest"]] = relationship(
        back_populates="verified_by_admin_user"
    )
    recorded_payments: Mapped[list["Payment"]] = relationship(
        back_populates="recorded_by_user"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    created_unavailability: Mapped[list["DoctorUnavailable"]] = relationship(
        back_populates="created_by_user"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")

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
    patient_allergies: Mapped[list["PatientAllergy"]] = relationship(
        back_populates="patient"
    )
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="patient"
    )
    lab_requests: Mapped[list["LabRequest"]] = relationship(
        back_populates="patient"
    )
    bills: Mapped[list["Bill"]] = relationship(back_populates="patient")

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
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="doctor"
    )
    lab_requests: Mapped[list["LabRequest"]] = relationship(
        back_populates="doctor",
        foreign_keys="LabRequest.doctor_id",
    )
    verified_lab_requests: Mapped[list["LabRequest"]] = relationship(
        back_populates="verifier",
        foreign_keys="LabRequest.verified_by",
    )
    schedules: Mapped[list["DoctorSchedule"]] = relationship(
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
    unavailable_periods: Mapped[list["DoctorUnavailable"]] = relationship(
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
    departments: Mapped[list["Department"]] = relationship(
        secondary="doctor_departments",
        back_populates="doctors",
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
    lab_requests: Mapped[list["LabRequest"]] = relationship(
        back_populates="appointment"
    )
    bill: Mapped[Optional["Bill"]] = relationship(
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

    doctors: Mapped[list["Doctor"]] = relationship(
        secondary="doctor_departments",
        back_populates="departments",
    )


class DoctorDepartment(Base):
    """M:N join between doctors and departments (database-design.md §3.8)."""

    __tablename__ = "doctor_departments"

    doctor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("doctors.id"), primary_key=True
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id"), primary_key=True
    )


class HospitalSettings(Base):
    __tablename__ = "hospital_settings"

    # Single-row resource per database-design.md §3.1: id is locked to 1
    # so the CHECK constraint guarantees exactly one row.
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    hospital_name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'Asia/Kolkata'"),
    )
    logo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_hospital_settings_single_row"),
        CheckConstraint(
            "email ~ '^.+@.+$'",
            name="ck_hospital_settings_email",
        ),
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
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="medical_record"
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


class PatientAllergy(Base):
    __tablename__ = "patient_allergies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id"), nullable=False
    )
    allergen: Mapped[str] = mapped_column(String(150), nullable=False)
    severity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    patient: Mapped["Patient"] = relationship(back_populates="patient_allergies")
    created_by_user: Mapped[Optional["User"]] = relationship(
        back_populates="patient_allergies"
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('MILD', 'MODERATE', 'SEVERE')",
            name="ck_patient_allergies_severity",
        ),
        Index("idx_patient_allergies_patient", "patient_id"),
    )


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    medical_record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medical_records.id"), nullable=False
    )
    doctor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("doctors.id"), nullable=False
    )
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    medical_record: Mapped["MedicalRecord"] = relationship(
        back_populates="prescriptions"
    )
    doctor: Mapped["Doctor"] = relationship(back_populates="prescriptions")
    patient: Mapped["Patient"] = relationship(back_populates="prescriptions")
    items: Mapped[list["PrescriptionItem"]] = relationship(
        back_populates="prescription",
        cascade="all, delete-orphan",
        order_by="PrescriptionItem.id",
    )

    __table_args__ = (
        Index("idx_prescriptions_patient", "patient_id"),
        Index("idx_prescriptions_record", "medical_record_id"),
        Index("idx_prescriptions_doctor", "doctor_id"),
    )


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prescription_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prescriptions.id"), nullable=False
    )
    medicine_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dosage: Mapped[str] = mapped_column(String(100), nullable=False)
    frequency: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_in_days: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True
    )

    prescription: Mapped["Prescription"] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint(
            "duration_in_days > 0",
            name="ck_prescription_items_duration_in_days",
        ),
        Index("idx_prescription_items_prescription", "prescription_id"),
    )


class LabRequest(Base):
    __tablename__ = "lab_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("appointments.id"), nullable=False
    )
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id"), nullable=False
    )
    doctor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("doctors.id"), nullable=False
    )
    test_name: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'REQUESTED'")
    )
    result_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_file_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    verified_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("doctors.id"), nullable=True
    )
    verified_by_admin: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    appointment: Mapped["Appointment"] = relationship(back_populates="lab_requests")
    patient: Mapped["Patient"] = relationship(back_populates="lab_requests")
    doctor: Mapped["Doctor"] = relationship(
        back_populates="lab_requests",
        foreign_keys=[doctor_id],
    )
    verifier: Mapped[Optional["Doctor"]] = relationship(
        back_populates="verified_lab_requests",
        foreign_keys=[verified_by],
    )
    verified_by_admin_user: Mapped[Optional["User"]] = relationship(
        back_populates="admin_verified_lab_requests",
        foreign_keys=[verified_by_admin],
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('REQUESTED', 'IN_PROGRESS', 'RESULT_READY', 'VERIFIED')",
            name="ck_lab_requests_status",
        ),
        Index("idx_lab_patient", "patient_id", "status"),
        Index("idx_lab_appointment", "appointment_id"),
        Index("idx_lab_doctor", "doctor_id"),
    )


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bill_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id"), nullable=False
    )
    appointment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("appointments.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'PENDING'"),
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
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

    patient: Mapped["Patient"] = relationship(back_populates="bills")
    appointment: Mapped["Appointment"] = relationship(back_populates="bill")
    items: Mapped[list["BillItem"]] = relationship(
        back_populates="bill",
        cascade="all, delete-orphan",
        order_by="BillItem.id",
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="bill",
        order_by="Payment.paid_at",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'REFUNDED')",
            name="ck_bills_status",
        ),
        Index("idx_bills_patient", "patient_id"),
        Index("idx_bills_appointment", "appointment_id"),
        Index("idx_bills_status", "status"),
    )


class BillItem(Base):
    __tablename__ = "bill_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bill_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bills.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    unit_price: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False
    )

    bill: Mapped["Bill"] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint(
            "category IN ('CONSULTATION', 'LAB_TEST', 'PROCEDURE', 'SERVICE')",
            name="ck_bill_items_category",
        ),
        CheckConstraint("quantity > 0", name="ck_bill_items_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_bill_items_unit_price"),
        Index("idx_bill_items_bill", "bill_id"),
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bill_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bills.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_reference: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    recorded_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )

    bill: Mapped["Bill"] = relationship(back_populates="payments")
    recorded_by_user: Mapped["User"] = relationship(
        back_populates="recorded_payments"
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount"),
        CheckConstraint(
            "method IN ('CASH', 'CARD', 'UPI', 'BANK_TRANSFER', 'OTHER')",
            name="ck_payments_method",
        ),
Index(
            "uq_payments_transaction_reference",
            "transaction_reference",
            unique=True,
            postgresql_where=text("transaction_reference IS NOT NULL"),
        ),
        Index("idx_payments_bill", "bill_id"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("idx_refresh_user", "user_id"),
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="password_reset_tokens")

    __table_args__ = (
        Index("idx_password_reset_user", "user_id"),
    )


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doctor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("doctors.id"), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    doctor: Mapped["Doctor"] = relationship(back_populates="schedules")

    __table_args__ = (
        CheckConstraint(
            "day_of_week BETWEEN 0 AND 6",
            name="ck_doctor_schedules_day_of_week",
        ),
        CheckConstraint(
            "end_time > start_time",
            name="ck_doctor_schedules_time_range",
        ),
        UniqueConstraint(
            "doctor_id", "day_of_week", "start_time",
            name="uq_doctor_schedules_doctor_day_start",
        ),
        Index("idx_doctor_schedules_doctor", "doctor_id"),
    )


class DoctorUnavailable(Base):
    __tablename__ = "doctor_unavailable"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doctor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("doctors.id"), nullable=False
    )
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    doctor: Mapped["Doctor"] = relationship(back_populates="unavailable_periods")
    created_by_user: Mapped["User"] = relationship(back_populates="created_unavailability")

    __table_args__ = (
        CheckConstraint(
            "to_date >= from_date",
            name="ck_doctor_unavailable_date_range",
        ),
        Index("idx_doc_unavail_doctor", "doctor_id", "from_date", "to_date"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_time", "created_at"),
    )