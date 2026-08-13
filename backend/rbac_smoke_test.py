import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.deps import (
    get_current_user,
    require_authenticated_user,
    require_roles,
)
from app.models import User
from app.security import create_access_token, hash_password

suffix = str(int(time.time()))

# Temporary app wiring the production dependencies to protected routes.
test_app = FastAPI()


@test_app.get("/admin-only")
def admin_only(user: User = Depends(require_roles("ADMIN"))):
    return {"ok": True, "role": user.role}


@test_app.get("/doctor-only")
def doctor_only(user: User = Depends(require_roles("DOCTOR"))):
    return {"ok": True, "role": user.role}


@test_app.get("/patient-only")
def patient_only(user: User = Depends(require_roles("PATIENT"))):
    return {"ok": True, "role": user.role}


@test_app.get("/staff")
def staff(user: User = Depends(require_roles("ADMIN", "RECEPTIONIST"))):
    return {"ok": True, "role": user.role}


@test_app.get("/any-authenticated")
def any_authenticated(user: User = Depends(require_authenticated_user)):
    return {"ok": True, "role": user.role}


client = TestClient(test_app)


def main():
    db = SessionLocal()
    users = {}
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
        for role in ("ADMIN", "DOCTOR", "RECEPTIONIST", "PATIENT"):
            u = User(
                email=f"rbac.smoke.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("RbacTestPass!42"),
                role=role,
                status="ACTIVE",
            )
            db.add(u)
            db.flush()
            users[role] = u

        deactivated = User(
            email=f"rbac.smoke.deactivated.{suffix}@mediflow.local",
            password_hash=hash_password("RbacTestPass!42"),
            role="ADMIN",
            status="DEACTIVATED",
        )
        db.add(deactivated)
        db.flush()
        users["DEACTIVATED"] = deactivated
        db.commit()
        for u in users.values():
            db.refresh(u)

        token = {r: create_access_token(u.id, u.role) for r, u in users.items()}
        auth = {r: {"Authorization": f"Bearer {token[r]}"} for r in token}

        # 1. ADMIN can access ADMIN-only
        r = client.get("/admin-only", headers=auth["ADMIN"])
        check("ADMIN -> /admin-only (200)", r.status_code == 200)

        # 2-4. Non-admin roles blocked from ADMIN-only (role mismatch -> 403)
        for role in ("DOCTOR", "RECEPTIONIST", "PATIENT"):
            r = client.get("/admin-only", headers=auth[role])
            check(f"{role} -> /admin-only (403)", r.status_code == 403)

        # 5. DOCTOR can access DOCTOR-only
        r = client.get("/doctor-only", headers=auth["DOCTOR"])
        check("DOCTOR -> /doctor-only (200)", r.status_code == 200)

        # 6. PATIENT can access PATIENT-only
        r = client.get("/patient-only", headers=auth["PATIENT"])
        check("PATIENT -> /patient-only (200)", r.status_code == 200)

        # 7. Multiple allowed roles: ADMIN + RECEPTIONIST
        admin_staff = client.get("/staff", headers=auth["ADMIN"])
        rec_staff = client.get("/staff", headers=auth["RECEPTIONIST"])
        doc_staff = client.get("/staff", headers=auth["DOCTOR"])
        check(
            "ADMIN -> /staff (200)",
            admin_staff.status_code == 200,
        )
        check(
            "RECEPTIONIST -> /staff (200)",
            rec_staff.status_code == 200,
        )
        check(
            "DOCTOR -> /staff (403)",
            doc_staff.status_code == 403,
        )

        # 8. Missing JWT -> 401
        r = client.get("/admin-only")
        check("no token -> 401", r.status_code == 401)

        # 9. Invalid JWT -> 401
        r = client.get(
            "/admin-only",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        check("malformed token -> 401", r.status_code == 401)

        # 10. Authenticated but insufficient role -> 403
        r = client.get("/admin-only", headers=auth["PATIENT"])
        check("authenticated wrong role -> 403", r.status_code == 403)

        # 11. Previously issued valid JWT from deactivated user -> 401
        # (token is validly signed and unexpired; user is deactivated)
        r = client.get(
            "/admin-only",
            headers=auth["DEACTIVATED"],
        )
        check(
            "deactivated user's valid JWT rejected (401)",
            r.status_code == 401,
        )

        # Sanity: authenticated user still passes require_authenticated_user
        r = client.get("/any-authenticated", headers=auth["PATIENT"])
        check(
            "authenticated user -> /any-authenticated (200)",
            r.status_code == 200,
        )

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            for u in users.values():
                db.delete(u)
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