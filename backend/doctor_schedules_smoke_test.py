import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    Appointment,
    Department,
    Doctor,
    DoctorSchedule,
    DoctorUnavailable,
    Patient,
    Receptionist,
    User,
)
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time() * 1000))

CLINIC_TZ = ZoneInfo("Asia/Kolkata")


def main():
    db = SessionLocal()
    users = {}
    doctors = {}
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
        return {
            "Authorization": f"Bearer {create_access_token(users[role].id, role)}"
        }

    try:
        # ---- Setup ----
        dept = Department(name=f"Sch Dept {suffix}")
        db.add(dept)
        db.flush()

        for role in ("ADMIN", "DOCTOR", "DOCTOR_B", "RECEPTIONIST", "PATIENT"):
            u = User(
                email=f"sch.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("SchPass!42"),
                role="DOCTOR" if role in ("DOCTOR", "DOCTOR_B") else role,
                status="ACTIVE",
            )
            db.add(u)
            db.flush()
            users[role] = u

        doc_a = Doctor(
            user_id=users["DOCTOR"].id,
            license_number=f"SCHEA{suffix[:6]}",
            consultation_fee=500.00,
        )
        doc_b = Doctor(
            user_id=users["DOCTOR_B"].id,
            license_number=f"SCHEB{suffix[:6]}",
            consultation_fee=600.00,
        )
        db.add_all([doc_a, doc_b])
        db.flush()
        doctors["A"] = doc_a
        doctors["B"] = doc_b

        patient = Patient(
            user_id=users["PATIENT"].id,
            mrn=f"SCHEP{suffix[:6]}",
            first_name="Sched",
            last_name="Patient",
        )
        receptionist = Receptionist(user_id=users["RECEPTIONIST"].id)
        db.add_all([patient, receptionist])
        db.commit()
        db.refresh(patient)
        db.refresh(dept)

        admin_h = token_for("ADMIN")
        doctor_h = token_for("DOCTOR")
        doctor_b_h = token_for("DOCTOR_B")
        receptionist_h = token_for("RECEPTIONIST")
        patient_h = token_for("PATIENT")

        # ============ 1. Schedule creation RBAC ============
        MONDAY_DB = 1          # database-design.md §3.9: 0=Sun ... 6=Sat
        START = "09:00:00"
        END = "17:00:00"

        body = {
            "doctor_id": doctors["A"].id,
            "day_of_week": MONDAY_DB,
            "start_time": START,
            "end_time": END,
        }

        r = client.post("/doctor-schedules", json=body, headers=admin_h)
        check("admin creates schedule -> 201", r.status_code == 201)
        sched_a = r.json()
        check("schedule echoes doctor_id/day/time",
              sched_a["doctor_id"] == doctors["A"].id
              and sched_a["day_of_week"] == MONDAY_DB
              and sched_a["start_time"].startswith("09:00")
              and sched_a["end_time"].startswith("17:00"))
        schedule_a_id = sched_a["id"]

        r = client.post("/doctor-schedules", json={
            **body, "day_of_week": 2,
        }, headers=doctor_h)
        check("doctor creates own schedule -> 201", r.status_code == 201)
        own_sched_id = r.json()["id"]

        r = client.post("/doctor-schedules", json=body, headers=doctor_b_h)
        check("doctor creating another doctor's schedule -> 403",
              r.status_code == 403)

        r = client.post("/doctor-schedules", json=body, headers=receptionist_h)
        check("receptionist creating schedule -> 403", r.status_code == 403)

        r = client.post("/doctor-schedules", json=body, headers=patient_h)
        check("patient creating schedule -> 403", r.status_code == 403)

        r = client.post("/doctor-schedules", json={
            **body, "doctor_id": 999999,
        }, headers=admin_h)
        check("admin create for unknown doctor -> 404", r.status_code == 404)

        r = client.post("/doctor-schedules", json={
            **body, "day_of_week": 7,
        }, headers=admin_h)
        check("day_of_week out of range (7) -> 422", r.status_code == 422)

        r = client.post("/doctor-schedules", json={
            **body, "start_time": "17:00:00", "end_time": "09:00:00",
        }, headers=admin_h)
        check("end_time <= start_time -> 422", r.status_code == 422)

        r = client.post("/doctor-schedules", json=body, headers=admin_h)
        check("duplicate (doctor, day, start) -> 409", r.status_code == 409)

        r = client.post("/doctor-schedules", json=body)
        check("create schedule without token -> 401", r.status_code == 401)

        # ============ 2. Schedule list/get RBAC + IDOR ============
        r = client.get("/doctor-schedules", headers=doctor_h)
        check("doctor lists only own schedules",
              r.status_code == 200
              and all(s["doctor_id"] == doctors["A"].id for s in r.json()))

        r = client.get(
            "/doctor-schedules?doctor_id=%d" % doctors["A"].id,
            headers=admin_h,
        )
        check("admin lists schedules filtered by doctor",
              r.status_code == 200
              and all(s["doctor_id"] == doctors["A"].id for s in r.json()))

        r = client.get(
            "/doctor-schedules?day_of_week=%d" % MONDAY_DB,
            headers=admin_h,
        )
        check("list filter by day_of_week",
              r.status_code == 200
              and all(s["day_of_week"] == MONDAY_DB for s in r.json()))

        r = client.get(
            "/doctor-schedules/%d" % schedule_a_id,
            headers=doctor_b_h,
        )
        check("doctor reading another doctor's schedule -> 404",
              r.status_code == 404)

        r = client.get("/doctor-schedules/%d" % schedule_a_id, headers=doctor_h)
        check("doctor reads own schedule -> 200", r.status_code == 200)

        r = client.get("/doctor-schedules/999999", headers=admin_h)
        check("get unknown schedule -> 404", r.status_code == 404)

        r = client.get("/doctor-schedules", headers=receptionist_h)
        check("receptionist listing schedules -> 403", r.status_code == 403)

        # ============ 3. Schedule update / delete RBAC + IDOR ============
        r = client.patch(
            "/doctor-schedules/%d" % schedule_a_id,
            json={"end_time": "18:00:00"},
            headers=doctor_h,
        )
        check("doctor updates own schedule -> 200",
              r.status_code == 200
              and r.json()["end_time"].startswith("18:00"))

        r = client.patch(
            "/doctor-schedules/%d" % own_sched_id,
            json={"end_time": "18:00:00"},
            headers=doctor_b_h,
        )
        check("doctor updating another doctor's schedule -> 404",
              r.status_code == 404)

        r = client.patch(
            "/doctor-schedules/%d" % schedule_a_id,
            json={},
            headers=doctor_h,
        )
        check("update schedule with empty body -> 422", r.status_code == 422)

        r = client.patch(
            "/doctor-schedules/%d" % own_sched_id,
            json={"day_of_week": MONDAY_DB, "start_time": "09:00:00"},
            headers=doctor_h,
        )
        check("patch to duplicate (doctor, day, start) -> 409",
              r.status_code == 409)

        r = client.delete(
            "/doctor-schedules/%d" % own_sched_id,
            headers=doctor_b_h,
        )
        check("doctor deleting another doctor's schedule -> 404",
              r.status_code == 404)

        r = client.delete(
            "/doctor-schedules/%d" % own_sched_id,
            headers=doctor_h,
        )
        check("doctor deletes own schedule -> 204", r.status_code == 204)

        r = client.delete("/doctor-schedules/999999", headers=doctor_h)
        check("delete unknown schedule -> 404", r.status_code == 404)

        # ============ 4. Unavailability creation RBAC ============
        unavail_body = {
            "doctor_id": doctors["A"].id,
            "from_date": "2026-12-20",
            "to_date": "2026-12-24",
            "reason": "Vacation",
        }

        r = client.post("/doctor-unavailable", json=unavail_body, headers=doctor_h)
        check("doctor creates own unavailable -> 201", r.status_code == 201)
        period_id = r.json()["id"]

        r = client.post("/doctor-unavailable", json=unavail_body, headers=admin_h)
        check("admin creates unavailable -> 201", r.status_code == 201)
        admin_period_id = r.json()["id"]

        r = client.post(
            "/doctor-unavailable",
            json={**unavail_body, "doctor_id": doctors["B"].id},
            headers=doctor_h,
        )
        check("doctor creating unavailable for another doctor -> 403",
              r.status_code == 403)

        r = client.post("/doctor-unavailable", json=unavail_body, headers=receptionist_h)
        check("receptionist creating unavailable -> 403", r.status_code == 403)

        r = client.post("/doctor-unavailable", json=unavail_body, headers=patient_h)
        check("patient creating unavailable -> 403", r.status_code == 403)

        r = client.post("/doctor-unavailable", json={
            **unavail_body, "to_date": "2026-12-01",
        }, headers=doctor_h)
        check("to_date before from_date -> 422", r.status_code == 422)

        r = client.post("/doctor-unavailable", json={
            **unavail_body, "doctor_id": 999999,
        }, headers=doctor_h)
        check("unavailable for unknown doctor -> 404", r.status_code == 404)

        # ============ 5. Unavailability list/get update/delete RBAC + IDOR ============
        r = client.get("/doctor-unavailable", headers=doctor_h)
        check("doctor lists only own unavailable",
              r.status_code == 200
              and all(p["doctor_id"] == doctors["A"].id for p in r.json()))

        r = client.get(
            "/doctor-unavailable?doctor_id=%d" % doctors["A"].id,
            headers=admin_h,
        )
        check("admin lists unavailable for doctor",
              r.status_code == 200
              and all(p["doctor_id"] == doctors["A"].id for p in r.json()))

        r = client.get(
            "/doctor-unavailable?date_from=2026-12-23T00:00:00"
            "&date_to=2026-12-25T00:00:00",
            headers=admin_h,
        )
        check("list unavailable by overlapping date range",
              r.status_code == 200 and len(r.json()) >= 1)

        r = client.get("/doctor-unavailable/%d" % period_id, headers=doctor_b_h)
        check("doctor reading another doctor's unavailable -> 404",
              r.status_code == 404)

        r = client.get("/doctor-unavailable/%d" % period_id, headers=doctor_h)
        check("doctor reads own unavailable -> 200", r.status_code == 200)

        r = client.get("/doctor-unavailable/999999", headers=admin_h)
        check("get unknown unavailable -> 404", r.status_code == 404)

        r = client.patch(
            "/doctor-unavailable/%d" % period_id,
            json={"reason": "Extended leave"},
            headers=doctor_h,
        )
        check("doctor updates own unavailable -> 200",
              r.status_code == 200
              and r.json()["reason"] == "Extended leave")

        r = client.patch(
            "/doctor-unavailable/%d" % admin_period_id,
            json={"reason": "hack"},
            headers=doctor_b_h,
        )
        check("doctor updating another's unavailable -> 404",
              r.status_code == 404)

        r = client.delete(
            "/doctor-unavailable/%d" % admin_period_id,
            headers=doctor_b_h,
        )
        check("doctor deleting another's unavailable -> 404", r.status_code == 404)

        r = client.delete(
            "/doctor-unavailable/%d" % admin_period_id,
            headers=admin_h,
        )
        check("admin deletes unavailable -> 204", r.status_code == 204)

        r = client.delete("/doctor-unavailable/999999", headers=admin_h)
        check("delete unknown unavailable -> 404", r.status_code == 404)

        # ============ 6. Appointment integration (create) ============
        # Restore schedule A to its original 09:00-17:00 window so the
        # boundary checks below are against the intended end time.
        r = client.patch(
            "/doctor-schedules/%d" % schedule_a_id,
            json={"end_time": "17:00:00"},
            headers=doctor_h,
        )
        check("restore schedule window to 17:00 -> 200", r.status_code == 200)

        # Build a future Monday in IST, then convert to UTC for the API.
        today_local = datetime.now(CLINIC_TZ)
        days_until_next_monday = (0 - today_local.weekday()) % 7
        monday_base = (today_local + timedelta(days=days_until_next_monday + 7))\
            .replace(hour=0, minute=0, second=0, microsecond=0)
        monday = monday_base + timedelta(hours=12)      # 12:00 IST Mon
        tuesday = (monday_base + timedelta(hours=10)
                   + timedelta(days=1))                 # 10:00 IST Tue

        def iso(dt):
            return dt.astimezone(timezone.utc).isoformat()

        def create_appt(doctor_id, dt, duration=30, headers=None):
            return client.post("/appointments", json={
                "patient_id": patient.id,
                "doctor_id": doctor_id,
                "department_id": dept.id,
                "date_time": iso(dt),
                "duration_minutes": duration,
                "priority": "NORMAL",
                "appointment_type": "INITIAL_CONSULTATION",
                "reason": None,
            }, headers=headers or admin_h)

        # doctor A scheduled Mon 09:00-17:00 IST
        r = create_appt(doctors["A"].id, monday)
        check("appointment inside schedule -> 201", r.status_code == 201)
        created_appointments.append(r.json()["id"])

        r = create_appt(doctors["A"].id, tuesday)
        check("appointment outside scheduled weekday -> 409", r.status_code == 409)

        before_window = monday_base + timedelta(hours=8)   # 08:00 IST Mon
        r = create_appt(doctors["A"].id, before_window)
        check("appointment before schedule window -> 409", r.status_code == 409)

        after_window = monday_base + timedelta(hours=16, minutes=30)
        r = create_appt(doctors["A"].id, after_window, duration=60)
        check("appointment exceeding schedule end -> 409", r.status_code == 409)

        # Unavailability now blocks that Monday
        r = client.post("/doctor-unavailable", json={
            "doctor_id": doctors["A"].id,
            "from_date": monday_base.date().isoformat(),
            "to_date": monday_base.date().isoformat(),
        }, headers=admin_h)
        check("mark Monday unavailable -> 201", r.status_code == 201)
        monday_block_id = r.json()["id"]

        r = create_appt(doctors["A"].id, monday)
        check("appointment blocked by unavailable date -> 409",
              r.status_code == 409)

        # Doctor B has no schedule -> should remain bookable (backward compat)
        r = create_appt(doctors["B"].id, monday)
        check("doctor without schedule still bookable -> 201", r.status_code == 201)
        created_appointments.append(r.json()["id"])

        # Reuse the slot once unavailability removed
        r = client.delete(
            "/doctor-unavailable/%d" % monday_block_id, headers=admin_h)
        check("remove unavailable -> 204", r.status_code == 204)

        r = create_appt(doctors["A"].id, monday_base + timedelta(hours=11))
        check("slot reusable after removing unavailability -> 201",
              r.status_code == 201)
        created_appointments.append(r.json()["id"])

        # ============ 7. Appointment integration (reschedule) ============
        r = client.patch(
            "/appointments/%d" % created_appointments[0],
            json={"date_time": iso(tuesday)},
            headers=admin_h,
        )
        check("reschedule outside schedule -> 409", r.status_code == 409)

        reschedule_target = monday_base + timedelta(hours=15)  # 15:00 IST Mon
        r = client.patch(
            "/appointments/%d" % created_appointments[0],
            json={"date_time": iso(reschedule_target)},
            headers=admin_h,
        )
        check("reschedule inside schedule -> 200", r.status_code == 200)

        # ============ 8. Overlap constraint still intact ============
        slot_dt = monday_base + timedelta(hours=14)
        r = create_appt(doctors["A"].id, slot_dt)
        check("create at 14:00 -> 201", r.status_code == 201)
        created_appointments.append(r.json()["id"])

        r = create_appt(doctors["A"].id, slot_dt + timedelta(minutes=15))
        check("overlapping active appointment still 409 -> 409",
              r.status_code == 409)

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            if dept is not None:
                db.query(Appointment).filter(
                    Appointment.department_id == dept.id
                ).delete(synchronize_session=False)
            doc_ids = db.query(Doctor.id).filter(
                Doctor.license_number.like(f"SCHE%{suffix[:6]}%")
            ).all()
            doc_ids = [d[0] for d in doc_ids]
            if doc_ids:
                db.query(Appointment).filter(
                    Appointment.doctor_id.in_(doc_ids)
                ).delete(synchronize_session=False)
                db.query(DoctorUnavailable).filter(
                    DoctorUnavailable.doctor_id.in_(doc_ids)
                ).delete(synchronize_session=False)
                db.query(DoctorSchedule).filter(
                    DoctorSchedule.doctor_id.in_(doc_ids)
                ).delete(synchronize_session=False)
                db.query(Doctor).filter(Doctor.id.in_(doc_ids)).delete(
                    synchronize_session=False)
            if dept is not None:
                db.query(Department).filter(Department.id == dept.id).delete(
                    synchronize_session=False)
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id).filter(
                        User.email.like("sch.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(Patient).filter(
                Patient.mrn.like(f"SCHEP{suffix[:6]}%")
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("sch.%@mediflow.local")
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