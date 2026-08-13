from app.db import SessionLocal
from app.models import User


def main():
    db = SessionLocal()

    try:
        # 1. Create a temporary user
        user = User(
            email="smoke.test@mediflow.local",
            password_hash="temporary-test-hash",
            role="PATIENT",
            status="ACTIVE",
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        print("Created user:")
        print(f"  ID: {user.id}")
        print(f"  Email: {user.email}")
        print(f"  Role: {user.role}")

        # 2. Read the user back from PostgreSQL
        saved_user = (
            db.query(User)
            .filter(User.email == "smoke.test@mediflow.local")
            .first()
        )

        print("\nRead user from database:")
        print(f"  ID: {saved_user.id}")
        print(f"  Email: {saved_user.email}")
        print(f"  Role: {saved_user.role}")

        # 3. Delete the temporary user
        db.delete(saved_user)
        db.commit()

        print("\nSmoke test passed.")
        print("Temporary user deleted.")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()