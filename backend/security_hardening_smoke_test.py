"""Phase 4 security-hardening smoke test.

Covers the hardening added in Phase 4 on top of the existing auth coverage:
    - audit events written for login events (LOGIN / LOGIN_FAILED / LOCKOUT)
    - behaviour of the login lockout (failed_attempts, locked_until, expiry)
    - password-reset anti-enumeration, single-use and expiry behaviour
    - rate limiting on the unauthenticated password-reset endpoints (429 + Retry-After)
    - authorization: unauthenticated 401, wrong-role 403, cross-tenant 404 (IDOR)
    - CORS: allowed origin served, disallowed origin not served, no wildcard+credentials
    - regression: secrets never leak in responses on login / me paths

Run:  python security_hardening_smoke_test.py
"""

import os

# CORS is configured from the environment at import time; set it before
# importing the app so the middleware is deterministic inside this process.
os.environ["CORS_ORIGINS"] = "http://localhost:5173"

import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    AuditLog,
    PasswordResetToken,
    Patient,
    RateLimitEvent,
    RefreshToken,
    User,
)
from app.rate_limit import RATE_LIMIT_PASSWORD_RESET
from app.security import (
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
)

client = TestClient(app)

PASSWORD = "CorrectHorseBatteryStaple"
NEW_PASSWORD = "HardenedNewPass42!"
suffix = str(int(time.time()))
ORIGIN_OK = "http://localhost:5173"
ORIGIN_BAD = "http://evil.example"

# The API returns this on the password-reset endpoints. (v1 returns the token
# inline rather than emailing it — see docs/requirements.md.)
EXPECTED_GENERIC_MSG = "If a matching account exists, a reset token was issued."


def main():
    db = SessionLocal()
    users = {}
    patient_data = {}
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

    def audit_actions_for(user_id, action):
        return (
            db.query(AuditLog)
            .filter(AuditLog.user_id == user_id, AuditLog.action == action)
            .count()
        )

    try:
        # ---- Setup ------------------------------------------------------
        victim = User(
            email=f"sec.victim.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="PATIENT",
            status="ACTIVE",
        )
        attacker = User(
            email=f"sec.attacker.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="PATIENT",
            status="ACTIVE",
        )
        lockout_user = User(
            email=f"sec.lockout.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="PATIENT",
            status="ACTIVE",
        )
        reset_user = User(
            email=f"sec.reset.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="PATIENT",
            status="ACTIVE",
        )
        deact_user = User(
            email=f"sec.deact.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="RECEPTIONIST",
            status="ACTIVE",
        )
        admin = User(
            email=f"sec.admin.{suffix}@mediflow.local",
            password_hash=hash_password(PASSWORD),
            role="ADMIN",
            status="ACTIVE",
        )
        db.add_all([victim, attacker, lockout_user, reset_user, deact_user, admin])
        db.flush()
        patient_victim = Patient(
            user_id=victim.id,
            mrn=f"SECV{str(time.time_ns())[-8:]}",
            first_name="Vic",
            last_name="Tim",
        )
        patient_attacker = Patient(
            user_id=attacker.id,
            mrn=f"SECA{str(time.time_ns())[-8:]}",
            first_name="Att",
            last_name="Acker",
        )
        db.add_all([patient_victim, patient_attacker])
        db.commit()
        for u in (victim, attacker, lockout_user, reset_user, deact_user, admin):
            db.refresh(u)
            users[u.email] = u
        db.refresh(patient_victim)
        db.refresh(patient_attacker)
        patient_data["victim"] = patient_victim
        patient_data["attacker"] = patient_attacker

        # ============ 1. Audit events on login ============
        before = audit_actions_for(victim.id, "LOGIN")
        ok_login = client.post(
            "/auth/login",
            json={"email": victim.email, "password": PASSWORD},
        )
        check("login -> 200", ok_login.status_code == 200)
        check(
            "LOGIN audit event recorded",
            audit_actions_for(victim.id, "LOGIN") == before + 1,
        )

        wrong = client.post(
            "/auth/login",
            json={"email": victim.email, "password": "wrong-password"},
        )
        check("wrong password -> 401", wrong.status_code == 401)
        check(
            "LOGIN_FAILED audit event recorded",
            audit_actions_for(victim.id, "LOGIN_FAILED") >= 1,
        )

        # ============ 2. Lockout after repeated failures ============
        lock_email = lockout_user.email
        for i in range(3):
            resp = client.post(
                "/auth/login",
                json={"email": lock_email, "password": "wrong-password"},
            )
            check(f"lockout attempt #{i+1} -> 401", resp.status_code == 401)

        db.refresh(lockout_user)
        check(
            "failed_attempts tracked at 3",
            lockout_user.failed_attempts == 3,
        )
        check("locked_until set", lockout_user.locked_until is not None)
        check(
            "LOCKOUT audit event recorded",
            audit_actions_for(lockout_user.id, "LOCKOUT") == 1,
        )

        locked_correct = client.post(
            "/auth/login",
            json={"email": lock_email, "password": PASSWORD},
        )
        check(
            "correct password rejected while locked (401)",
            locked_correct.status_code == 401,
        )

        # Lockout expiry: simulate 15 minutes passing, then verify reset.
        lockout_user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        after = client.post(
            "/auth/login",
            json={"email": lock_email, "password": PASSWORD},
        )
        check("login succeeds after lockout expiry", after.status_code == 200)
        db.refresh(lockout_user)
        check("failed_attempts reset to 0", lockout_user.failed_attempts == 0)
        check("locked_until cleared", lockout_user.locked_until is None)

        # ============ 3. Password reset: anti-enumeration, validity, single-use ============
        # Clear the shared reset scopes so this section is deterministic even
        # when earlier suites (same test client IP) already consumed the window.
        db.query(RateLimitEvent).filter(
            RateLimitEvent.scope.in_(["forgot_password", "reset_password"])
        ).delete(synchronize_session=False)
        db.commit()
        unknown_email = f"sec.nobody.{suffix}@mediflow.local"
        forgot_unknown = client.post(
            "/auth/forgot-password", json={"email": unknown_email}
        )
        check("forgot-password unknown email -> 200", forgot_unknown.status_code == 200)
        check(
            "unknown email gets the generic message",
            forgot_unknown.json().get("message") == EXPECTED_GENERIC_MSG,
        )
        check(
            "no reset_token for unknown email (no enumeration)",
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
        check("invalid reset token -> 400", bad_reset.status_code == 400)

        # Expired token created directly so its expires_at is in the past.
        expired_raw = generate_opaque_token()
        PasswordResetToken(
            user_id=reset_user.id,
            token_hash=hash_token(expired_raw),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(
            PasswordResetToken(
                user_id=reset_user.id,
                token_hash=hash_token(expired_raw),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        db.commit()
        expired_reset = client.post(
            "/auth/reset-password",
            json={"token": expired_raw, "new_password": NEW_PASSWORD},
        )
        check("expired reset token -> 400", expired_reset.status_code == 400)

        good_reset = client.post(
            "/auth/reset-password",
            json={"token": reset_token, "new_password": NEW_PASSWORD},
        )
        check("valid reset token -> 200", good_reset.status_code == 200)

        reuse = client.post(
            "/auth/reset-password",
            json={"token": reset_token, "new_password": NEW_PASSWORD},
        )
        check("reset token is single-use -> 400", reuse.status_code == 400)

        new_pwd = client.post(
            "/auth/login",
            json={"email": reset_user.email, "password": NEW_PASSWORD},
        )
        check("new password accepted after reset", new_pwd.status_code == 200)

        # ============ 4. Rate limiting on password reset ============
        # Reset the counters so the limit check is deterministic in this run.
        db.query(RateLimitEvent).filter(
            RateLimitEvent.scope.in_(["forgot_password", "reset_password"])
        ).delete(synchronize_session=False)
        db.commit()

        sent = 0
        got_429_at = None
        retry_after = None
        for i in range(RATE_LIMIT_PASSWORD_RESET + 2):
            resp = client.post(
                "/auth/forgot-password", json={"email": unknown_email}
            )
            sent += 1
            if resp.status_code == 429:
                got_429_at = sent
                retry_after = resp.headers.get("Retry-After")
                break
        check(
            "forgot-password rate-limited (429)",
            got_429_at is not None,
        )
        check(
            "429 issued only after limit exceeded",
            got_429_at is not None and got_429_at == RATE_LIMIT_PASSWORD_RESET + 1,
        )
        check("retry-after header present", bool(retry_after))

        # Reset is separate scope; hitting it also rate limits abuse.
        rl = client.post(
            "/auth/reset-password",
            json={"token": "bad", "new_password": NEW_PASSWORD},
        )
        check("reset-password still functional under its own scope (400, not 429)", rl.status_code == 400)

        # ============ 5. Authorization: 401 / 403 / 404 (IDOR) ============
        anon = client.get(f"/patients/{patient_data['victim'].id}")
        check("unauthenticated patient view -> 401", anon.status_code == 401)

        attacker_headers = token_for(attacker)
        own = client.get(
            f"/patients/{patient_data['attacker'].id}", headers=attacker_headers
        )
        check("patient can view own profile", own.status_code == 200)

        idor = client.get(
            f"/patients/{patient_data['victim'].id}", headers=attacker_headers
        )
        check(
            "patient viewing another patient -> 404 (no IDOR leak)",
            idor.status_code == 404,
        )

        idor_patch = client.patch(
            f"/patients/{patient_data['victim'].id}",
            json={"first_name": "Hacked"},
            headers=attacker_headers,
        )
        check(
            "patient editing another patient -> 404",
            idor_patch.status_code == 404,
        )

        non_admin_deact = client.post(
            f"/auth/users/{deact_user.id}/deactivate", headers=attacker_headers
        )
        check("non-admin deactivate -> 403", non_admin_deact.status_code == 403)

        # ============ 6. Deactivated user rejected everywhere ============
        deact_user.status = "DEACTIVATED"
        deact_user.deactivated_at = datetime.now(timezone.utc)
        db.commit()
        deact_login = client.post(
            "/auth/login",
            json={"email": deact_user.email, "password": PASSWORD},
        )
        check("deactivated user login -> 401", deact_login.status_code == 401)
        stale = client.get(
            "/auth/me", headers=token_for(deact_user)
        )
        check(
            "deactivated user's existing access token -> 401",
            stale.status_code == 401,
        )

        # ============ 7. CORS: allowed vs denied, no wildcard ============
        allowed = client.get(
            "/health", headers={"Origin": ORIGIN_OK}
        )
        check("allowed origin -> 200", allowed.status_code == 200)
        check(
            "allowed origin gets Access-Control-Allow-Origin",
            allowed.headers.get("access-control-allow-origin") == ORIGIN_OK,
        )

        denied = client.get("/health", headers={"Origin": ORIGIN_BAD})
        check("disallowed origin request processed -> 200", denied.status_code == 200)
        check(
            "disallowed origin gets NO allow-origin header (browser blocks)",
            "access-control-allow-origin" not in denied.headers,
        )

        preflight_ok = client.options(
            "/auth/login",
            headers={
                "Origin": ORIGIN_OK,
                "Access-Control-Request-Method": "POST",
            },
        )
        check("preflight from allowed origin -> 200", preflight_ok.status_code == 200)
        preflight_bad = client.options(
            "/auth/login",
            headers={
                "Origin": ORIGIN_BAD,
                "Access-Control-Request-Method": "POST",
            },
        )
        check(
            "preflight from disallowed origin -> 400",
            preflight_bad.status_code == 400,
        )

        # ============ 8. Regression: no secrets in responses ============
        body_login = client.post(
            "/auth/login",
            json={"email": victim.email, "password": PASSWORD},
        )
        check(
            "login response never exposes password_hash",
            "password_hash" not in body_login.text,
        )
        me = client.get("/auth/me", headers=token_for(attacker))
        check(
            "/auth/me never exposes password_hash",
            "password_hash" not in me.text,
        )

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            all_ids = [u.id for u in users.values()]
            # Child rows that reference users without a delete cascade.
            # (expires_in_past_token belongs to reset_user, covered by all_ids.)
            if all_ids:
                db.query(AuditLog).filter(
                    AuditLog.user_id.in_(all_ids)
                ).delete(synchronize_session=False)
                db.query(RefreshToken).filter(
                    RefreshToken.user_id.in_(all_ids)
                ).delete(synchronize_session=False)
                db.query(PasswordResetToken).filter(
                    PasswordResetToken.user_id.in_(all_ids)
                ).delete(synchronize_session=False)
            db.query(RateLimitEvent).delete(synchronize_session=False)
            for p in patient_data.values():
                db.delete(p)
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