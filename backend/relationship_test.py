import time

from app.db import SessionLocal
from app.models import User, Doctor

suffix = str(int(time.time()))


def main():
    db = SessionLocal()
    user = None
    doctor = None

    try:
        # Create a temporary user
        user = User(
            email=f"doctor.test.{suffix}@mediflow.local",
            password_hash="temporary-test-hash",
            role="DOCTOR",
            status="ACTIVE",
        )

        db.add(user)
        db.flush()

        # Create a doctor linked to that user
        doctor = Doctor(
            user_id=user.id,
            license_number=f"TEST-LICENSE-{suffix}",
            consultation_fee=500.00,
        )

        db.add(doctor)
        db.commit()
        db.refresh(doctor)

        print("Created User:")
        print(f"  ID: {user.id}")
        print(f"  Email: {user.email}")

        print("\nCreated Doctor:")
        print(f"  ID: {doctor.id}")
        print(f"  User ID: {doctor.user_id}")
        print(f"  License: {doctor.license_number}")
        print(f"  Fee: {doctor.consultation_fee}")

        # Read doctor back
        saved_doctor = (
            db.query(Doctor)
            .filter(Doctor.license_number == f"TEST-LICENSE-{suffix}")
            .first()
        )

        print("\nRead Doctor from database:")
        print(f"  ID: {saved_doctor.id}")
        print(f"  User ID: {saved_doctor.user_id}")

        # Verify relationship
        if saved_doctor.user_id == user.id:
            print("\nUser -> Doctor relationship verified.")

        print("Temporary User and Doctor deleted.")
        print("Relationship test passed.")

    except Exception:
        db.rollback()
        raise

    finally:
        try:
            db.rollback()
            if doctor is not None:
                db.delete(doctor)
            if user is not None:
                db.delete(user)
            db.commit()
        except Exception:
            db.rollback()
        db.close()


if __name__ == "__main__":
    main()