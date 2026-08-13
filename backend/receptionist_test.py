from app.db import SessionLocal
from app.models import User, Receptionist


def main():
    db = SessionLocal()

    try:
        # Create a temporary user
        user = User(
            email="receptionist.test@mediflow.local",
            password_hash="temporary-test-hash",
            role="RECEPTIONIST",
            status="ACTIVE",
        )

        db.add(user)
        db.flush()

        # Create a receptionist linked to that user
        receptionist = Receptionist(
            user_id=user.id,
            employee_code="TEST-EMP-001",
        )

        db.add(receptionist)
        db.commit()
        db.refresh(receptionist)

        print("Created User:")
        print(f"  ID: {user.id}")
        print(f"  Email: {user.email}")

        print("\nCreated Receptionist:")
        print(f"  ID: {receptionist.id}")
        print(f"  User ID: {receptionist.user_id}")
        print(f"  Employee Code: {receptionist.employee_code}")

        # Read receptionist back
        saved_receptionist = (
            db.query(Receptionist)
            .filter(Receptionist.employee_code == "TEST-EMP-001")
            .first()
        )

        print("\nRead Receptionist from database:")
        print(f"  ID: {saved_receptionist.id}")
        print(f"  User ID: {saved_receptionist.user_id}")

        # Verify foreign-key relationship
        if saved_receptionist.user_id == user.id:
            print("\nUser to Receptionist relationship verified.")

        # Cleanup
        db.delete(saved_receptionist)
        db.delete(user)
        db.commit()

        print("Temporary User and Receptionist deleted.")
        print("Receptionist relationship test passed.")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()