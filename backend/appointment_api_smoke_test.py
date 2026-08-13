import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Appointment, Department, Doctor, Patient, Receptionist, User
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time()))

BASE = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def main():
    db = SessionLocal()
    users = {}
    user_doctor_b = None
    doctors = {}
    patients = {}
    dept = None
    created_appointments = []
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

    def token_for(role):
        return {"Authorization": f"Bearer {create_access_token(users[role].id, role)}"}

    try:
        # ---- Setup: one user+profile per role, one department ----
        dept = Department(name=f"Appt API Dept {suffix}")
        db.add(dept)
        db.flush()

        for role in ("ADMIN", "DOCTOR", "RECEPTIONIST", "PATIENT"):
            u = User(
                email=f"apptapi.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("ApptApiPass!42"),
                role=role,
                status="ACTIVE",
            )
            db.add(u)
            db.flush()
            users[role] = u

        doctor_a = Doctor(
            user_id=users["DOCTOR"].id,
            license_number=f"APTDA{suffix[:6]}",
            consultation_fee=500.00,
        )
        db.add(doctor_a)
        db.flush()
        user_doctor_b = User(
            email=f"apptapi.doctorb.{suffix}@mediflow.local",
            password_hash=hash_password("ApptApiPass!42"),
            role="DOCTOR",
            status="ACTIVE",
        )
        db.add(user_doctor_b)
        db.flush()
        doctor_b = Doctor(
            user_id=user_doctor_b.id,
            license_number=f"APTDB{suffix[:6]}",
            consultation_fee=600.00,
        )
        doctors["A"] = doctor_a
        doctors["B"] = doctor_b

        patient_a = Patient(
            user_id=users["PATIENT"].id,
            mrn=f"APTPA{suffix[:6]}",
            first_name="Alice",
            last_name="Patient",
        )
        patient_b = Patient(
            user_id=users["ADMIN"].id,
            mrn=f"APTPB{suffix[:6]}",
            first_name="Bob",
            last_name="Patient",
        )
        patients["A"] = patient_a
        patients["B"] = patient_b

        receptionist = Receptionist(user_id=users["RECEPTIONIST"].id)
        db.add_all([doctor_a, doctor_b, patient_a, patient_b, receptionist])
        db.commit()
        for obj in (doctor_a, doctor_b, patient_a, patient_b, dept):
            db.refresh(obj)

        admin_h = token_for("ADMIN")
        doctor_h = token_for("DOCTOR")
        receptionist_h = token_for("RECEPTIONIST")
        patient_h = token_for("PATIENT")

        def create(body, headers):
            return client.post("/appointments", json=body, headers=headers)

        def base_body(patient_id=None, doctor_id=None, start=None, **over):
            body = {
                "patient_id": patient_id or patients["A"].id,
                "doctor_id": doctor_id or doctors["A"].id,
                "department_id": dept.id,
                "date_time": iso(start or BASE),
                "duration_minutes": 30,
                "priority": "NORMAL",
                "appointment_type": "INITIAL_CONSULTATION",
                "reason": None,
            }
            body.update(over)
            return body

        # ---- 1. Successful creation (receptionist books on behalf) ----
        r = create(base_body(), receptionist_h)
        check("create returns 201 + id",
              r.status_code == 201 and r.json().get("id"))
        created = r.json()
        created_id = created["id"]
        created_appointments.append(created_id)
        check("create defaults status PENDING",
              created.get("status") == "PENDING")
        check("created_by is not client-controlled",
              created.get("created_by") == users["RECEPTIONIST"].id)
        r = client.get("/appointments/%d" % created_id, headers=receptionist_h)
        check("create response omits password_hash",
              "password_hash" not in r.text)

        # ---- 2. Unauthenticated ----
        r = client.post("/appointments", json=base_body())
        check("create without token -> 401", r.status_code == 401)
        r = client.get("/appointments/%d" % created_id)
        check("get without token -> 401", r.status_code == 401)
        r = client.get("/appointments")
        check("list without token -> 401", r.status_code == 401)

        # ---- 3. IDOR: patient cannot read another patient's appointment ----
        patient_b_appt = create(
            base_body(
                patient_id=patients["B"].id,
                doctor_id=doctors["B"].id,
                start=BASE + timedelta(days=2),
            ),
            receptionist_h,
        )
        check("receptionist books appointment for patient B (201)",
              patient_b_appt.status_code == 201)
        patient_b_appt_id = patient_b_appt.json()["id"]
        created_appointments.append(patient_b_appt_id)
        r = client.get("/appointments/%d" % patient_b_appt_id, headers=patient_h)
        check("patient reading other's appointment -> 404",
              r.status_code == 404)
        r = create(base_body(start=BASE + timedelta(days=3)), patient_h)
        check("patient self-booking succeeds (201)",
              r.status_code == 201)
        own_id = r.json()["id"]
        created_appointments.append(own_id)
        r = client.get("/appointments/%d" % own_id, headers=patient_h)
        check("patient reads own appointment (200)", r.status_code == 200)
        r = create(
            base_body(patient_id=patients["B"].id, start=BASE + timedelta(days=4)),
            patient_h,
        )
        check("patient booking for another patient -> 403",
              r.status_code == 403)

        # ---- 4. Doctor scope ----
        r = client.get("/appointments/%d" % created_id, headers=doctor_h)
        check("doctor reads own scheduled appointment (200)",
              r.status_code == 200)
        r = create(base_body(patient_id=patients["A"].id, doctor_id=doctors["B"].id), doctor_h)
        check("doctor booking another doctor's slot -> 403", r.status_code == 403)

        # ---- 5. Listing + filtering ----
        r = client.get("/appointments", headers=receptionist_h)
        check("receptionist lists all appointments (200 list)",
              r.status_code == 200 and len(r.json()) >= 2)
        r = client.get("/appointments?status=PENDING", headers=receptionist_h)
        check("list filter by status",
              r.status_code == 200 and all(
                  a["status"] == "PENDING" for a in r.json()))
        r = client.get(
            "/appointments?date_from=%s&date_to=%s"
            % (
                quote(iso(BASE - timedelta(days=2)), safe=""),
                quote(iso(BASE + timedelta(days=2)), safe=""),
            ),
            headers=receptionist_h,
        )
        check("list filter by date range",
              r.status_code == 200 and all(
                  BASE - timedelta(days=2)
                  <= datetime.fromisoformat(a["date_time"])
                  <= BASE + timedelta(days=2)
                  for a in r.json()))
        r = client.get(
            "/appointments?patient_id=%d" % patients["A"].id,
            headers=receptionist_h,
        )
        check("list filter by patient_id", r.status_code == 200)
        r = client.get("/appointments", headers=doctor_h)
        check("doctor list scoped to own doctor_id",
              r.status_code == 200 and all(
                  a["doctor_id"] == doctors["A"].id for a in r.json()))
        r = client.get("/appointments", headers=patient_h)
        check("patient list scoped to own patient_id",
              r.status_code == 200 and all(
                  a["patient_id"] == patients["A"].id for a in r.json()))

        # ---- 6. Successful update (reschedule + status workflow) ----
        new_start = BASE + timedelta(days=7)
        r = client.patch(
            "/appointments/%d" % created_id,
            json={"date_time": iso(new_start)},
            headers=receptionist_h,
        )
        check("update reschedule -> 200", r.status_code == 200)
        check("reschedule applied new date_time",
              datetime.fromisoformat(r.json()["date_time"]) == new_start)
        r = client.patch(
            "/appointments/%d" % created_id,
            json={"status": "CONFIRMED"},
            headers=admin_h,
        )
        check("admin confirm -> 200", r.status_code == 200)
        r = client.patch(
            "/appointments/%d" % created_id,
            json={"status": "CHECKED_IN"},
            headers=receptionist_h,
        )
        check("receptionist check-in -> 200", r.status_code == 200)

        # ---- 7. Invalid update ----
        r = client.patch(
            "/appointments/%d" % created_id,
            json={"status": "COMPLETED"},
            headers=receptionist_h,
        )
        check("receptionist cannot set COMPLETED -> 403",
              r.status_code == 403)
        r = client.patch(
            "/appointments/%d" % own_id,
            json={"status": "NO_SHOW"},
            headers=admin_h,
        )
        check("admin invalid transition PENDING->NO_SHOW -> 422",
              r.status_code == 422)
        r = client.patch(
            "/appointments/%d" % patient_b_appt_id,
            json={"status": "CANCELLED"},
            headers=patient_h,
        )
        check("patient cannot modify another's appointment -> 404",
              r.status_code == 404)
        r = client.patch(
            "/appointments/%d" % own_id,
            json={"status": "CONFIRMED"},
            headers=patient_h,
        )
        check("patient cannot set CONFIRMED -> 403", r.status_code == 403)

        # ---- 8. Overlap -> 409 (same doctor, overlapping active) ----
        r = create(
            base_body(doctor_id=doctors["A"].id, start=BASE + timedelta(days=1)),
            receptionist_h,
        )
        check("create non-overlapping -> 201", r.status_code == 201)
        created_appointments.append(r.json()["id"])
        overlap = create(
            base_body(doctor_id=doctors["A"].id, start=BASE + timedelta(days=1),
                      duration_minutes=60),
            receptionist_h,
        )
        check("overlapping appointment -> 409", overlap.status_code == 409)

        # ---- 9. Different doctor, same time -> allowed ----
        r = create(
            base_body(doctor_id=doctors["B"].id, start=BASE + timedelta(days=1)),
            receptionist_h,
        )
        check("different doctor same time -> 201", r.status_code == 201)
        created_appointments.append(r.json()["id"])

        # ---- 10. Invalid references ----
        r = create(base_body(patient_id=999999), receptionist_h)
        check("invalid patient_id -> 422", r.status_code == 422)
        r = create(base_body(doctor_id=999999), receptionist_h)
        check("invalid doctor_id -> 422", r.status_code == 422)
        r = create(base_body(department_id=999999), receptionist_h)
        check("invalid department_id -> 422", r.status_code == 422)

        # ---- 11. Rollback after failed op; DB still usable after 409 ----
        r = create(
            base_body(
                doctor_id=doctors["A"].id,
                start=BASE + timedelta(days=1, hours=2),
            ),
            receptionist_h,
        )
        check("create works again after 409 rollback -> 201",
              r.status_code == 201)
        created_appointments.append(r.json()["id"])

        # ---- 12. Cancellation (soft, no physical delete) ----
        r = client.delete("/appointments/%d" % created_id, headers=admin_h)
        check("cancel -> 200 with status CANCELLED",
              r.status_code == 200 and r.json().get("status") == "CANCELLED")
        r = client.get("/appointments/%d" % created_id, headers=receptionist_h)
        check("cancelled appointment still exists (soft delete)",
              r.status_code == 200)
        r = create(
            base_body(doctor_id=doctors["A"].id, start=new_start),
            receptionist_h,
        )
        check("cancelled slot reusable -> 201", r.status_code == 201)
        created_appointments.append(r.json()["id"])

        # ---- 13. 24-hour rule applies only to cancel/reschedule ----
        now = datetime.now(timezone.utc)

        # cancel within 24h -> rejected
        r = create(base_body(start=now + timedelta(hours=2)), patient_h)
        check("create appt for cancel-within-24h test (201)",
              r.status_code == 201)
        cancel_within_id = r.json()["id"]
        created_appointments.append(cancel_within_id)
        r = client.delete(
            "/appointments/%d" % cancel_within_id, headers=patient_h
        )
        check("patient cancel within 24h -> 403", r.status_code == 403)
        r = client.patch(
            "/appointments/%d" % cancel_within_id,
            json={"status": "CANCELLED"},
            headers=patient_h,
        )
        check("patient set CANCELLED within 24h -> 403", r.status_code == 403)

        # cancel beyond 24h -> allowed
        r = create(base_body(start=now + timedelta(hours=48)), patient_h)
        check("create appt for cancel-beyond-24h test (201)",
              r.status_code == 201)
        cancel_beyond_id = r.json()["id"]
        created_appointments.append(cancel_beyond_id)
        r = client.delete(
            "/appointments/%d" % cancel_beyond_id, headers=patient_h
        )
        check("patient cancel > 24h -> 200 CANCELLED",
              r.status_code == 200 and r.json().get("status") == "CANCELLED")

        # reschedule within 24h -> rejected
        r = create(base_body(start=now + timedelta(hours=49)), patient_h)
        check("create appt for reschedule-within-24h test (201)",
              r.status_code == 201)
        resched_within_id = r.json()["id"]
        created_appointments.append(resched_within_id)
        r = client.patch(
            "/appointments/%d" % resched_within_id,
            json={"date_time": iso(now + timedelta(hours=2))},
            headers=patient_h,
        )
        check("patient reschedule within 24h -> 403", r.status_code == 403)

        # reschedule beyond 24h -> allowed
        r = create(base_body(start=now + timedelta(hours=72)), patient_h)
        check("create appt for reschedule-beyond-24h test (201)",
              r.status_code == 201)
        resched_beyond_id = r.json()["id"]
        created_appointments.append(resched_beyond_id)
        r = client.patch(
            "/appointments/%d" % resched_beyond_id,
            json={"date_time": iso(now + timedelta(hours=96))},
            headers=patient_h,
        )
        check("patient reschedule > 24h -> 200",
              r.status_code == 200 and datetime.fromisoformat(
                  r.json()["date_time"]) == now + timedelta(hours=96))

        # status transitions within 24h -> allowed
        r = create(base_body(start=now + timedelta(hours=5)), receptionist_h)
        check("create appt for within-24h status flow (201)",
              r.status_code == 201)
        wf_id = r.json()["id"]
        created_appointments.append(wf_id)
        r = client.patch(
            "/appointments/%d" % wf_id,
            json={"status": "CONFIRMED"},
            headers=admin_h,
        )
        check("admin confirm within 24h -> 200", r.status_code == 200)
        r = client.patch(
            "/appointments/%d" % wf_id,
            json={"status": "CHECKED_IN"},
            headers=receptionist_h,
        )
        check("receptionist check-in within 24h -> 200", r.status_code == 200)
        r = client.patch(
            "/appointments/%d" % wf_id,
            json={"status": "COMPLETED"},
            headers=doctor_h,
        )
        check("doctor complete within 24h -> 200", r.status_code == 200)

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            if created_appointments:
                db.query(Appointment).filter(
                    Appointment.id.in_(created_appointments)
                ).delete(synchronize_session=False)
            if dept is not None:
                db.query(Department).filter(Department.id == dept.id).delete(
                    synchronize_session=False
                )
            for mrn in ("APTPA", "APTPB"):
                db.query(Patient).filter(Patient.mrn.like(f"{mrn}%")).delete(
                    synchronize_session=False
                )
            for lic in ("APTDA", "APTDB"):
                db.query(Doctor).filter(
                    Doctor.license_number.like(f"{lic}%")
                ).delete(synchronize_session=False)
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id)
                    .filter(User.email.like("apptapi.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("apptapi.%@mediflow.local")
            ).delete(synchronize_session=False)
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