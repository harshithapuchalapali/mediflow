import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import (
    User,
    Patient,
    Doctor,
    Department,
    Appointment,
)


def main():
    db = SessionLocal()
    suffix = str(int(time.time()))

    user_patient = None
    user_doctor1 = None
    user_doctor2 = None
    user_created_by = None
    patient = None
    doctor1 = None
    doctor2 = None
    department = None
    appt_a = None
    appt_c = None
    appt_d = None
    appt_e = None

    passes = 0
    fails = 0

    def record(result: bool, label: str) -> bool:
        nonlocal passes, fails
        if result:
            passes += 1
            print(f"  PASS | {label}")
        else:
            fails += 1
            print(f"  FAIL | {label}")
        return result

    try:
        # ---- 2. Temporary records ----
        user_patient = User(
            email=f"appt.smoke.patient.{suffix}@mediflow.local",
            password_hash="temporary-test-hash",
            role="PATIENT",
            status="ACTIVE",
        )
        db.add(user_patient)
        db.flush()

        patient = Patient(
            user_id=user_patient.id,
            mrn=f"APT-SMOKE-{suffix}",
            first_name="Smoke",
            last_name="Patient",
        )
        db.add(patient)
        db.flush()

        user_doctor1 = User(
            email=f"appt.smoke.doc1.{suffix}@mediflow.local",
            password_hash="temporary-test-hash",
            role="DOCTOR",
            status="ACTIVE",
        )
        db.add(user_doctor1)
        db.flush()

        doctor1 = Doctor(
            user_id=user_doctor1.id,
            license_number=f"APT-SMOKE-D1-{suffix}",
            consultation_fee=500.00,
        )
        db.add(doctor1)
        db.flush()

        user_doctor2 = User(
            email=f"appt.smoke.doc2.{suffix}@mediflow.local",
            password_hash="temporary-test-hash",
            role="DOCTOR",
            status="ACTIVE",
        )
        db.add(user_doctor2)
        db.flush()

        doctor2 = Doctor(
            user_id=user_doctor2.id,
            license_number=f"APT-SMOKE-D2-{suffix}",
            consultation_fee=500.00,
        )
        db.add(doctor2)
        db.flush()

        user_created_by = User(
            email=f"appt.smoke.cb.{suffix}@mediflow.local",
            password_hash="temporary-test-hash",
            role="RECEPTIONIST",
            status="ACTIVE",
        )
        db.add(user_created_by)
        db.flush()

        department = Department(name=f"Smoke Test Dept {suffix}")
        db.add(department)
        db.flush()

        def make_appointment(doctor, start, status):
            return Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                department_id=department.id,
                date_time=start,
                duration_minutes=30,
                status=status,
                created_by=user_created_by.id,
            )

        slot = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)

        # ---- 3. Appointment A (baseline, same doctor @ 10:00) ----
        appt_a = make_appointment(
            doctor1, slot, "CONFIRMED"
        )
        db.add(appt_a)
        db.commit()
        db.refresh(appt_a)
        record(True, "A: doctor1 @ 10:00 CONFIRMED created")

        # ---- 4. Appointment B (same doctor, overlapping - MUST fail) ----
        appt_b = make_appointment(
            doctor1,
            slot + timedelta(minutes=15),
            "CONFIRMED",
        )
        db.add(appt_b)
        try:
            db.commit()
            record(
                False,
                "B: doctor1 @ 10:15 CONFIRMED overlap was INSERTED (must be rejected)",
            )
            db.rollback()
        except IntegrityError:
            db.rollback()
            record(True, "B: doctor1 @ 10:15 CONFIRMED overlap rejected")

        # ---- 5. Appointment C (different doctor, same time - must succeed) ----
        appt_c = make_appointment(
            doctor2, slot, "CONFIRMED"
        )
        db.add(appt_c)
        db.commit()
        db.refresh(appt_c)
        record(True, "C: doctor2 @ 10:00 CONFIRMED created")

        # ---- 6. Appointment D (same doctor/time as A, CANCELLED) ----
        appt_d = make_appointment(
            doctor1, slot, "CANCELLED"
        )
        db.add(appt_d)
        db.commit()
        db.refresh(appt_d)
        record(True, "D: doctor1 @ 10:00 CANCELLED created")

        # ---- 7. Appointment E (same doctor/time as A, NO_SHOW) ----
        appt_e = make_appointment(
            doctor1, slot, "NO_SHOW"
        )
        db.add(appt_e)
        db.commit()
        db.refresh(appt_e)
        record(True, "E: doctor1 @ 10:00 NO_SHOW created")

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        # ---- 9. Clean up every temporary record ----
        try:
            db.rollback()
            appt_ids = [
                a.id
                for a in (appt_a, appt_c, appt_d, appt_e)
                if a is not None
            ]
            if appt_ids:
                db.query(Appointment).filter(
                    Appointment.id.in_(appt_ids)
                ).delete(synchronize_session=False)
            for obj in (
                patient,
                doctor1,
                doctor2,
                department,
                user_patient,
                user_doctor1,
                user_doctor2,
                user_created_by,
            ):
                if obj is not None:
                    db.delete(obj)
            db.commit()
            print("  TEMP | Cleanup removed all temporary records")
        except Exception as exc:
            db.rollback()
            print(f"  FAIL | cleanup error: {type(exc).__name__}: {exc}")
        finally:
            db.close()

    print(f"\nResult: {passes} passed, {fails} failed")

    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    main()