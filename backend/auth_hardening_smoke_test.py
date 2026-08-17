import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, Patient, User
from app.security import create_access_token, hash_password

client = TestClient(app)

PASSWORD = "CorrectHorseBatteryStaple"
NEW_PASSWORD = "NewCorrectHorse42!"
suffix = str(int(time.time()))


def main():
    db = SessionLocal()
    users = {}
    patient_row = None
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

    def token_for(u, role=None):
        role = role or u.role
        return {"Authorization": f"Bearer {create_access_token(u.id, role)}"}

    try:
        # ---- Setup: users per scenario ----
        admin = User(
            email=f"authh.admin.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="ADMIN",
            status="ACTIVE",
        )
        refresh_user = User(
            email=f"authh.refresh.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="DOCTOR",
            status="ACTIVE",
        )
        lockout_user = User(
            email=f"authh.lockout.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="PATIENT",
            status="ACTIVE",
        )
        reset_user = User(
            email=f"authh.reset.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="PATIENT",
            status="ACTIVE",
        )
        profile_user = User(
            email=f"authh.profile.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="PATIENT",
            status="ACTIVE",
        )
        doctor_profile_user = User(
            email=f"authh.docprofile.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="DOCTOR",
            status="ACTIVE",
        )
        deact_user = User(
            email=f"authh.deact.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="RECEPTIONIST",
            status="ACTIVE",
        )
        db.add_all(
            [
                admin,
                refresh_user,
                lockout_user,
                reset_user,
                profile_user,
                doctor_profile_user,
                deact_user,
            ]
        )
        db.flush()
        patient_row = Patient(
            user_id=profile_user.id,
            mrn=f"AHPP{suffix[:6]}",
            first_name="Pat",
            last_name="Ient",
        )
        db.add(patient_row)
        db.commit()
        for u in (admin, refresh_user, lockout_user, reset_user, profile_user,
                  doctor_profile_user, deact_user):
            db.refresh(u)
            users[u.email] = u

        A = token_for(admin)
        admin_headers = A

        # ============ 1. Refresh token on login ============
        login = client.post(
            "/auth/login",
            json={"email": refresh_user.email, "password": PASSWORD},
        )
        check("login returns 200", login.status_code == 200)
        body = login.json()
        check("login returns access_token", bool(body.get("access_token")))
        check("login returns refresh_token", bool(body.get("refresh_token")))
        check(
            "login response never exposes password_hash",
            "password_hash" not in str(body),
        )
        access_1 = body["access_token"]
        refresh_1 = body["refresh_token"]

        # access token works
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {access_1}"})
        check("access token from login works on /auth/me", me.status_code == 200)

        # refresh with valid token -> rotation
        refreshed = client.post(
            "/auth/refresh", json={"refresh_token": refresh_1}
        )
        check("refresh with valid token -> 200", refreshed.status_code == 200)
        refreshed_body = refreshed.json()
        check(
            "refresh returns a new access_token",
            refreshed_body.get("access_token"),
        )
        check(
            "refresh returns a new refresh_token (rotation)",
            refreshed_body.get("refresh_token")
            and refreshed_body["refresh_token"] != refresh_1,
        )
        access_2 = refreshed_body["access_token"]
        refresh_2 = refreshed_body["refresh_token"]

        # old token must now be rejected
        replayed = client.post(
            "/auth/refresh", json={"refresh_token": refresh_1}
        )
        check("replayed (rotated-out) refresh token -> 401", replayed.status_code == 401)

        # new token still works
        refreshed2 = client.post(
            "/auth/refresh", json={"refresh_token": refresh_2}
        )
        check("new refresh token works after rotation", refreshed2.status_code == 200)

        # garbage / malformed refresh token
        garbage = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
        check("garbage refresh token -> 401", garbage.status_code == 401)

        # ============ 2. Logout ============
        refresh_3 = refreshed2.json()["refresh_token"]
        logout = client.post("/auth/logout", json={"refresh_token": refresh_3})
        check("logout -> 200", logout.status_code == 200)

        logged_out = client.post(
            "/auth/refresh", json={"refresh_token": refresh_3}
        )
        check("refresh after logout -> 401", logged_out.status_code == 401)

        idempotent = client.post("/auth/logout", json={"refresh_token": refresh_3})
        check("second logout is idempotent (200)", idempotent.status_code == 200)

        # ============ 3. Change password revokes refresh tokens ============
        login2 = client.post(
            "/auth/login",
            json={"email": refresh_user.email, "password": PASSWORD},
        )
        old_refresh = login2.json()["refresh_token"]

        wrong_cur = client.post(
            "/auth/change-password",
            json={
                "current_password": "totally-wrong",
                "new_password": NEW_PASSWORD,
            },
            headers={"Authorization": f"Bearer {create_access_token(refresh_user.id, refresh_user.role)}"},
        )
        check("change-password with wrong current -> 401", wrong_cur.status_code == 401)

        changed = client.post(
            "/auth/change-password",
            json={
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
            },
            headers={"Authorization": f"Bearer {create_access_token(refresh_user.id, refresh_user.role)}"},
        )
        check("change-password with correct current -> 200", changed.status_code == 200)

        old_pwd = client.post(
            "/auth/login",
            json={"email": refresh_user.email, "password": PASSWORD},
        )
        check("old password rejected after change (401)", old_pwd.status_code == 401)

        new_pwd = client.post(
            "/auth/login",
            json={"email": refresh_user.email, "password": NEW_PASSWORD},
        )
        check("new password accepted after change", new_pwd.status_code == 200)

        revoked_refresh = client.post(
            "/auth/refresh", json={"refresh_token": old_refresh}
        )
        check(
            "pre-change refresh token revoked after password change -> 401",
            revoked_refresh.status_code == 401,
        )

        # ============ 4. Lockout: 3 failed attempts -> 15 min lock ============
        lock_email = lockout_user.email
        for i in range(3):
            resp = client.post(
                "/auth/login",
                json={"email": lock_email, "password": "wrong-password"},
            )
            check(f"failed login #{i+1} rejected (401)", resp.status_code == 401)

        db.refresh(lockout_user)
        check(
            "failed_attempts tracked at 3",
            lockout_user.failed_attempts == 3,
        )
        check(
            "locked_until set after 3 failed attempts",
            lockout_user.locked_until is not None,
        )

        correct_while_locked = client.post(
            "/auth/login",
            json={"email": lock_email, "password": PASSWORD},
        )
        check(
            "correct password rejected while locked (401)",
            correct_while_locked.status_code == 401,
        )

        # Simulate 15 minutes passing, then correct login succeeds and resets.
        lockout_user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        after_lock = client.post(
            "/auth/login",
            json={"email": lock_email, "password": PASSWORD},
        )
        check("login succeeds after lockout expiry", after_lock.status_code == 200)
        db.refresh(lockout_user)
        check(
            "failed_attempts reset after successful login",
            lockout_user.failed_attempts == 0,
        )
        check(
            "locked_until cleared after successful login",
            lockout_user.locked_until is None,
        )

        # ============ 5. Forgot password + reset ============
        unknown_email = f"authh.nobody.{suffix}@mediflow.local"
        forgot_unknown = client.post(
            "/auth/forgot-password", json={"email": unknown_email}
        )
        check("forgot-password unknown email -> 200", forgot_unknown.status_code == 200)
        check(
            "no reset_token returned for unknown email (no enumeration)",
            "reset_token" not in forgot_unknown.json(),
        )

        forgot = client.post(
            "/auth/forgot-password", json={"email": reset_user.email}
        )
        check("forgot-password known email -> 200", forgot.status_code == 200)
        reset_token = forgot.json().get("reset_token")
        check("reset_token returned for known email", bool(reset_token))

        bad_reset = client.post(
            "/auth/reset-password",
            json={"token": "not-a-real-token", "new_password": NEW_PASSWORD},
        )
        check("reset-password with invalid token -> 400", bad_reset.status_code == 400)

        reset_resp = client.post(
            "/auth/reset-password",
            json={"token": reset_token, "new_password": NEW_PASSWORD},
        )
        check("reset-password with valid token -> 200", reset_resp.status_code == 200)

        old_pwd2 = client.post(
            "/auth/login",
            json={"email": reset_user.email, "password": PASSWORD},
        )
        check("previous password rejected after reset (401)", old_pwd2.status_code == 401)

        new_pwd2 = client.post(
            "/auth/login",
            json={"email": reset_user.email, "password": NEW_PASSWORD},
        )
        check("new password works after reset", new_pwd2.status_code == 200)

        reuse = client.post(
            "/auth/reset-password",
            json={"token": reset_token, "new_password": NEW_PASSWORD},
        )
        check("reset token is single-use -> 400", reuse.status_code == 400)

        # ============ 6. Profile update (PATCH /me) ============
        other_email = admin.email
        clash = client.patch(
            "/auth/me",
            json={"email": other_email},
            headers={"Authorization": f"Bearer {create_access_token(profile_user.id, profile_user.role)}"},
        )
        check("PATCH /me with clashing email -> 409", clash.status_code == 409)

        new_email = f"authh.profile.renamed.{suffix}@mediflow.local"
        ren = client.patch(
            "/auth/me",
            json={"email": new_email, "first_name": "Ren", "last_name": "Amed", "phone": "9876543210"},
            headers={"Authorization": f"Bearer {create_access_token(profile_user.id, profile_user.role)}"},
        )
        check("PATCH /me updates email + patient name/phone -> 200", ren.status_code == 200)
        ren_body = ren.json()
        check("reponse email updated", ren_body.get("email") == new_email)
        check("PATCH /me response never exposes password_hash", "password_hash" not in str(ren_body))

        db.refresh(profile_user)
        check("email persisted in DB", profile_user.email == new_email)
        db.refresh(patient_row)
        check("patient first_name persisted", patient_row.first_name == "Ren")
        check("patient last_name persisted", patient_row.last_name == "Amed")
        check(
            "patient emergency_contact_phone persisted",
            patient_row.emergency_contact_phone == "9876543210",
        )

        login_new_email = client.post(
            "/auth/login", json={"email": new_email, "password": PASSWORD}
        )
        check("login works with updated email", login_new_email.status_code == 200)

        # Doctors cannot update patient-only name/phone fields
        doc_update = client.patch(
            "/auth/me",
            json={"first_name": "Doc"},
            headers={"Authorization": f"Bearer {create_access_token(doctor_profile_user.id, doctor_profile_user.role)}"},
        )
        check("doctor updating patient name field -> 422", doc_update.status_code == 422)

        me_no_token = client.patch("/auth/me", json={"email": "x@y.local"})
        check("PATCH /me without token -> 401", me_no_token.status_code == 401)

        # ============ 7. Admin deactivate / activate ============
        deact_email = deact_user.email

        # Non-admin cannot deactivate
        non_admin_deact = client.post(
            f"/auth/users/{deact_user.id}/deactivate",
            headers=token_for(profile_user),
        )
        check("non-admin deactivate -> 403", non_admin_deact.status_code == 403)

        # Login first to get a refresh token that deactivation should kill
        deact_login = client.post(
            "/auth/login", json={"email": deact_email, "password": PASSWORD}
        )
        deact_refresh = deact_login.json().get("refresh_token")
        deact_access = deact_login.json().get("access_token")

        deactivated = client.post(
            f"/auth/users/{deact_user.id}/deactivate",
            headers=admin_headers,
        )
        check("admin deactivate -> 200", deactivated.status_code == 200)

        db.refresh(deact_user)
        check("user status becomes DEACTIVATED", deact_user.status == "DEACTIVATED")
        check("deactivated_at set", deact_user.deactivated_at is not None)

        deact_login_after = client.post(
            "/auth/login", json={"email": deact_email, "password": PASSWORD}
        )
        check("deactivated user login -> 401", deact_login_after.status_code == 401)

        deact_me = client.get(
            "/auth/me", headers={"Authorization": f"Bearer {deact_access}"}
        )
        check(
            "deactivated user's existing access token -> 401",
            deact_me.status_code == 401,
        )

        deact_refresh_after = client.post(
            "/auth/refresh", json={"refresh_token": deact_refresh}
        )
        check(
            "deactivated user's refresh token -> 401",
            deact_refresh_after.status_code == 401,
        )

        # Admin cannot deactivate self
        self_deact = client.post(
            f"/auth/users/{admin.id}/deactivate",
            headers=admin_headers,
        )
        check("admin deactivating self -> 400", self_deact.status_code == 400)

        unknown_deact = client.post(
            "/auth/users/999999999/deactivate",
            headers=admin_headers,
        )
        check("deactivate unknown user -> 404", unknown_deact.status_code == 404)

        activated = client.post(
            f"/auth/users/{deact_user.id}/activate",
            headers=admin_headers,
        )
        check("admin activate -> 200", activated.status_code == 200)

        db.refresh(deact_user)
        check("user status back to ACTIVE", deact_user.status == "ACTIVE")
        check("deactivated_at cleared", deact_user.deactivated_at is None)

        deact_login_back = client.post(
            "/auth/login", json={"email": deact_email, "password": PASSWORD}
        )
        check("reactivated user can log in", deact_login_back.status_code == 200)

        already_active = client.post(
            f"/auth/users/{deact_user.id}/activate",
            headers=admin_headers,
        )
        check("activate already-active user -> 400", already_active.status_code == 400)

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            for obj in (patient_row,):
                if obj is not None:
                    db.delete(obj)
            db.commit()
            from app.models import RefreshToken, PasswordResetToken

            ids = [u.id for u in users.values()]
            if ids:
                # AuditLog rows reference users.id without cascade; remove first.
                db.query(AuditLog).filter(
                    AuditLog.user_id.in_(ids)
                ).delete(synchronize_session=False)
                db.query(RefreshToken).filter(
                    RefreshToken.user_id.in_(ids)
                ).delete(synchronize_session=False)
                db.query(PasswordResetToken).filter(
                    PasswordResetToken.user_id.in_(ids)
                ).delete(synchronize_session=False)
            for u in users.values():
                db.delete(u)
            db.commit()
            print("  TEMP | Cleanup removed temporary records")
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