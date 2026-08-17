import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, User
from app.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY,
    ALGORITHM,
    create_access_token,
    hash_password,
)

client = TestClient(app)

PASSWORD = "CorrectHorseBatteryStaple"
suffix = str(int(time.time()))


def main():
    db = SessionLocal()
    active_user = None
    deactivated_user = None
    passes = 0
    fails = 0

    def check(label, condition):
        nonlocal passes, fails
        if condition:
            passes += 1
            print(f"  PASS | {label}")
        else:
            fails += 1
            print(f"  FAIL | {label}")

    try:
        active_user = User(
            email=f"auth.smoke.active.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="PATIENT",
            status="ACTIVE",
        )
        deactivated_user = User(
            email=f"auth.smoke.deactivated.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="DOCTOR",
            status="DEACTIVATED",
        )
        db.add(active_user)
        db.add(deactivated_user)
        db.commit()
        db.refresh(active_user)
        db.refresh(deactivated_user)

        email = active_user.email

        # 1. Valid login
        resp = client.post(
            "/auth/login",
            json={"email": email, "password": PASSWORD},
        )
        check(
            "valid login returns 200 + access token",
            resp.status_code == 200 and resp.json().get("access_token"),
        )
        login_body = resp.json()
        check(
            "login response never exposes password_hash",
            "password_hash" not in str(login_body),
        )
        check(
            "login returns user role",
            login_body.get("user", {}).get("role") == "PATIENT",
        )
        token = login_body.get("access_token", "")

        # 2. Invalid password
        resp = client.post(
            "/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        check("invalid password rejected (401)", resp.status_code == 401)

        # 3. Nonexistent user
        resp = client.post(
            "/auth/login",
            json={
                "email": f"nobody.{suffix}@mediflow.local",
                "password": PASSWORD,
            },
        )
        check("nonexistent user rejected (401)", resp.status_code == 401)

        # 4. Deactivated user
        resp = client.post(
            "/auth/login",
            json={
                "email": deactivated_user.email,
                "password": PASSWORD,
            },
        )
        check("deactivated user rejected (401)", resp.status_code == 401)

        # 5. Valid JWT (directly issued)
        direct_token = create_access_token(active_user.id, active_user.role)
        resp = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {direct_token}"},
        )
        check("valid JWT accepted by /auth/me", resp.status_code == 200)
        check(
            "/auth/me returns current user email",
            resp.json().get("email") == email,
        )
        check(
            "/auth/me never exposes password_hash",
            "password_hash" not in resp.text,
        )

        # 6. Invalid / expired JWT
        resp = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        check("malformed JWT rejected (401)", resp.status_code == 401)

        expired = jwt.encode(
            {
                "sub": str(active_user.id),
                "role": active_user.role,
                "iat": datetime.now(timezone.utc)
                - timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES + 10),
                "exp": datetime.now(timezone.utc)
                - timedelta(minutes=1),
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )
        resp = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {expired}"},
        )
        check("expired JWT rejected (401)", resp.status_code == 401)

        # 7. /auth/me with authentication (from login token)
        resp = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        check(
            "/auth/me with valid login token (200)",
            resp.status_code == 200 and resp.json().get("id") == active_user.id,
        )

        # 8. /auth/me without authentication
        resp = client.get("/auth/me")
        check("/auth/me without token rejected (401)", resp.status_code == 401)

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            user_ids = []
            for obj in (active_user, deactivated_user):
                if obj is not None:
                    user_ids.append(obj.id)
            # AuditLog rows reference users.id without cascade; remove them first.
            if user_ids:
                db.query(AuditLog).filter(AuditLog.user_id.in_(user_ids)).delete(
                    synchronize_session=False
                )
            for obj in (active_user, deactivated_user):
                if obj is not None:
                    db.delete(obj)
            db.commit()
            print("  TEMP | Cleanup removed temporary users")
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