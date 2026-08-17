import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    Appointment,
    AuditLog,
    Department,
    Doctor,
    LabRequest,
    MedicalRecord,
    MedicalRecordVersion,
    Notification,
    Patient,
    Receptionist,
    User,
)
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time()))

BASE = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def main():
    db = SessionLocal()
    users = {}
    doctors = {}
    patients = {}
    appointment_ids = []
    lab_ids = []
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
        dept = Department(name=f"Lab Dept {suffix}")
        db.add(dept)
        db.flush()

        for role in ("ADMIN", "DOCTOR_A", "DOCTOR_B", "RECEPTIONIST",
                     "PATIENT_A", "PATIENT_B"):
            u = User(
                email=f"lab.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("LabApiPass!42"),
                role="ADMIN" if role == "ADMIN" else (
                    "DOCTOR" if role.startswith("DOCTOR") else (
                        "RECEPTIONIST" if role == "RECEPTIONIST" else "PATIENT"
                    )
                ),
                status="ACTIVE",
            )
            db.add(u)
            db.flush()
            users[role] = u

        da = Doctor(
            user_id=users["DOCTOR_A"].id,
            license_number=f"LABDA{suffix[:6]}",
            consultation_fee=500.00,
        )
        db.add(da)
        db.flush()
        dbb = Doctor(
            user_id=users["DOCTOR_B"].id,
            license_number=f"LABDB{suffix[:6]}",
            consultation_fee=600.00,
        )
        db.add(dbb)
        db.flush()
        doctors["A"] = da
        doctors["B"] = dbb

        pa = Patient(
            user_id=users["PATIENT_A"].id,
            mrn=f"LAPA{suffix[:6]}",
            first_name="Alice",
            last_name="Lab",
        )
        pb = Patient(
            user_id=users["PATIENT_B"].id,
            mrn=f"LAPB{suffix[:6]}",
            first_name="Bob",
            last_name="Lab",
        )
        patients["A"] = pa
        patients["B"] = pb

        receptionist = Receptionist(user_id=users["RECEPTIONIST"].id)
        db.add_all([da, dbb, pa, pb, receptionist])
        db.commit()
        for obj in (da, dbb, pa, pb, dept):
            db.refresh(obj)

        admin_h = token_for("ADMIN")
        doca_h = token_for("DOCTOR_A")
        docb_h = token_for("DOCTOR_B")
        rec_h = token_for("RECEPTIONIST")
        pata_h = token_for("PATIENT_A")
        patb_h = token_for("PATIENT_B")

        def create_appointment(doctor, patient, start):
            r = client.post(
                "/appointments",
                json={
                    "patient_id": patient.id,
                    "doctor_id": doctor.id,
                    "department_id": dept.id,
                    "date_time": iso(start),
                    "duration_minutes": 30,
                    "priority": "NORMAL",
                    "appointment_type": "INITIAL_CONSULTATION",
                },
                headers=rec_h,
            )
            if r.status_code == 201:
                appointment_ids.append(r.json()["id"])
            return r

        appt_a = create_appointment(doctors["A"], patients["A"], BASE)
        appt_b = create_appointment(doctors["B"], patients["B"], BASE + timedelta(days=1))
        check("setup: appointment A (201)", appt_a.status_code == 201)
        check("setup: appointment B (201)", appt_b.status_code == 201)
        appt_a_id = appt_a.json()["id"]
        appt_b_id = appt_b.json()["id"]

        # ---- 1. Doctor creates own lab request -> 201 ----
        r = client.post(
            "/lab-requests",
            json={"appointment_id": appt_a_id, "test_name": "Complete Blood Count",
                  "notes": "Fasting sample"},
            headers=doca_h,
        )
        check("doctor A creates lab request -> 201 + id", r.status_code == 201 and r.json().get("id"))
        body = r.json()
        check("default status REQUESTED", body["status"] == "REQUESTED")
        check("patient_id derived from appointment", body["patient_id"] == patients["A"].id)
        check("doctor_id derived from appointment", body["doctor_id"] == doctors["A"].id)
        check("verified_by null on create", body["verified_by"] is None)
        check("verified_by_admin null on create", body["verified_by_admin"] is None)
        check("verified_at null on create", body["verified_at"] is None)
        lab1_id = body["id"]
        lab_ids.append(lab1_id)

        # ---- 2. Another doctor's appointment -> 403 ----
        r = client.post(
            "/lab-requests",
            json={"appointment_id": appt_b_id, "test_name": "X"},
            headers=doca_h,
        )
        check("doctor A requests on doctor B's appt -> 403", r.status_code == 403)

        # ---- 3. Receptionist -> 403 ----
        r = client.post("/lab-requests", json={"appointment_id": appt_a_id, "test_name": "X"}, headers=rec_h)
        check("receptionist create -> 403", r.status_code == 403)
        r = client.get("/lab-requests", headers=rec_h)
        check("receptionist list -> 403", r.status_code == 403)
        r = client.get("/lab-requests/%d" % lab1_id, headers=rec_h)
        check("receptionist get -> 403", r.status_code == 403)
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "IN_PROGRESS"}, headers=rec_h)
        check("receptionist patch -> 403", r.status_code == 403)

        # ---- 4. Admin cannot create or enter data ----
        r = client.post("/lab-requests", json={"appointment_id": appt_b_id, "test_name": "X"}, headers=admin_h)
        check("admin create -> 403", r.status_code == 403)
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "IN_PROGRESS"}, headers=admin_h)
        check("admin enters IN_PROGRESS -> 403", r.status_code == 403)

        # ---- 5. Patient cannot create ----
        r = client.post("/lab-requests", json={"appointment_id": appt_a_id, "test_name": "X"}, headers=pata_h)
        check("patient create -> 403", r.status_code == 403)

        # ---- 6. Unauthenticated -> 401 ----
        r = client.post("/lab-requests", json={"appointment_id": appt_a_id, "test_name": "X"})
        check("create without token -> 401", r.status_code == 401)
        r = client.get("/lab-requests/%d" % lab1_id)
        check("get without token -> 401", r.status_code == 401)
        r = client.get("/lab-requests")
        check("list without token -> 401", r.status_code == 401)
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "IN_PROGRESS"})
        check("patch without token -> 401", r.status_code == 401)

        # ---- 7. Unknown appointment -> 404 ----
        r = client.post("/lab-requests", json={"appointment_id": 99999999, "test_name": "X"}, headers=doca_h)
        check("unknown appointment -> 404", r.status_code == 404)

        # ---- 8. Blank test_name -> 422 ----
        r = client.post("/lab-requests", json={"appointment_id": appt_a_id, "test_name": "   "}, headers=doca_h)
        check("blank test_name -> 422", r.status_code == 422)

        # ---- 9. Status transitions: valid progression ----
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "IN_PROGRESS"}, headers=doca_h)
        check("REQUESTED -> IN_PROGRESS -> 200", r.status_code == 200 and r.json()["status"] == "IN_PROGRESS")

        # ---- 10. Missing result_details entering RESULT_READY -> 422 ----
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "RESULT_READY"}, headers=doca_h)
        check("RESULT_READY without details -> 422", r.status_code == 422)
        r = client.patch("/lab-requests/%d" % lab1_id,
                         json={"target_status": "RESULT_READY", "result_details": "   "}, headers=doca_h)
        check("RESULT_READY with blank details -> 422", r.status_code == 422)

        # ---- 11. IN_PROGRESS -> RESULT_READY with details ----
        r = client.patch("/lab-requests/%d" % lab1_id,
                         json={"target_status": "RESULT_READY", "result_details": "Hb 12.8, WBC 6.1K"},
                         headers=doca_h)
        check("IN_PROGRESS -> RESULT_READY -> 200", r.status_code == 200 and r.json()["status"] == "RESULT_READY")
        check("result_details persisted", r.json()["result_details"] == "Hb 12.8, WBC 6.1K")

        # ---- 12. Invalid/backward transitions -> 422 ----
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "REQUESTED"}, headers=doca_h)
        check("backward transition -> 422", r.status_code == 422)
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "mystatus"}, headers=doca_h)
        check("arbitrary status -> 422", r.status_code == 422)

        # ---- 13. Verify: RESULT_READY -> VERIFIED ----
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "VERIFIED"}, headers=doca_h)
        check("RESULT_READY -> VERIFIED -> 200", r.status_code == 200 and r.json()["status"] == "VERIFIED")
        body = r.json()
        check("verified_by = requesting doctor id", body["verified_by"] == doctors["A"].id)
        check("verified_by_admin null on doctor verification", body["verified_by_admin"] is None)
        check("verified_at set", body["verified_at"] is not None)
        check("result_details preserved", body["result_details"] == "Hb 12.8, WBC 6.1K")

        # ---- 14. Editing after VERIFIED rejected -> 422 ----
        r = client.patch("/lab-requests/%d" % lab1_id,
                         json={"target_status": "RESULT_READY", "result_details": "changed"}, headers=doca_h)
        check("edit after VERIFIED -> 422", r.status_code == 422)

        # ---- 15. Verify skip (REQUESTED -> VERIFIED) -> 422 ----
        r = client.post("/lab-requests", json={"appointment_id": appt_a_id, "test_name": "LFT"}, headers=doca_h)
        check("second lab request on same appt -> 201", r.status_code == 201)
        lab2_id = r.json()["id"]
        lab_ids.append(lab2_id)
        r = client.patch("/lab-requests/%d" % lab2_id, json={"target_status": "VERIFIED"}, headers=doca_h)
        check("skip REQUESTED -> VERIFIED -> 422", r.status_code == 422)

        # ---- 16. Admin can verify RESULT_READY ----
        r = client.patch("/lab-requests/%d" % lab2_id, json={"target_status": "IN_PROGRESS"}, headers=doca_h)
        check("lab2 REQUESTED -> IN_PROGRESS", r.status_code == 200)
        r = client.patch("/lab-requests/%d" % lab2_id,
                         json={"target_status": "RESULT_READY", "result_details": "AST 25 U/L"},
                         headers=doca_h)
        check("lab2 IN_PROGRESS -> RESULT_READY", r.status_code == 200)
        r = client.patch("/lab-requests/%d" % lab2_id, json={"target_status": "VERIFIED"}, headers=admin_h)
        body = r.json()
        check("admin verifies RESULT_READY -> 200", r.status_code == 200 and body["status"] == "VERIFIED")
        check("verified_by null on admin verification", body["verified_by"] is None)
        check("verified_by_admin = admin user id", body["verified_by_admin"] == users["ADMIN"].id)
        check("verified_at set on admin verification", body["verified_at"] is not None)

        # ---- 17. IDOR: doctor B cannot read/patch doctor A's ----
        r = client.get("/lab-requests/%d" % lab1_id, headers=docb_h)
        check("doctor B reads doctor A's lab -> 404", r.status_code == 404)
        r = client.patch("/lab-requests/%d" % lab1_id, json={"target_status": "RESULT_READY",
                                                             "result_details": "x"}, headers=docb_h)
        check("doctor B patches doctor A's lab -> 404", r.status_code == 404)

        # ---- 18. IDOR: patient B accessing patient A's lab -> 404 ----
        r = client.get("/lab-requests/%d" % lab1_id, headers=patb_h)
        check("patient B reads patient A's lab -> 404", r.status_code == 404)

        # ---- 19. Patient verified-only visibility ----
        r = client.post("/lab-requests", json={"appointment_id": appt_a_id, "test_name": "Thyroid"}, headers=doca_h)
        check("lab3 created (for verified-only test)", r.status_code == 201)
        lab3_id = r.json()["id"]
        lab_ids.append(lab3_id)
        check("lab3 status REQUESTED", r.json()["status"] == "REQUESTED")
        r = client.get("/lab-requests/%d" % lab3_id, headers=pata_h)
        check("patient cannot see own UNVERIFIED -> 404", r.status_code == 404)
        r = client.get("/lab-requests/%d" % lab1_id, headers=pata_h)
        check("patient sees own VERIFIED -> 200", r.status_code == 200)
        r = client.patch("/lab-requests/%d" % lab3_id, json={"target_status": "IN_PROGRESS"}, headers=doca_h)
        r = client.patch("/lab-requests/%d" % lab3_id,
                         json={"target_status": "RESULT_READY", "result_details": "TSH 2.1 mIU/L"},
                         headers=doca_h)
        r = client.patch("/lab-requests/%d" % lab3_id, json={"target_status": "VERIFIED"}, headers=doca_h)
        check("lab3 now VERIFIED", r.status_code == 200 and r.json()["status"] == "VERIFIED")
        r = client.get("/lab-requests/%d" % lab3_id, headers=pata_h)
        check("patient sees own VERIFIED (2) -> 200", r.status_code == 200)

        # ---- 20. Doctor list scoping ----
        r = client.get("/lab-requests", headers=docb_h)
        check("doctor B list only own labs",
              r.status_code == 200 and all(x["doctor_id"] == doctors["B"].id for x in r.json()))

        # ---- 21. Patient list scoping (verified only) ----
        r = client.get("/lab-requests", headers=pata_h)
        pata_labs = r.json()
        check("patient list only own + all VERIFIED",
              r.status_code == 200 and all(x["patient_id"] == patients["A"].id
                                           and x["status"] == "VERIFIED" for x in pata_labs))
        check("patient list contains the verified labs",
              len(pata_labs) == 3 and {x["id"] for x in pata_labs} == {lab1_id, lab2_id, lab3_id})

        # ---- 22. Admin list all ----
        r = client.get("/lab-requests", headers=admin_h)
        check("admin list includes all labs", r.status_code == 200 and len(r.json()) >= 3)

        # ---- 23. Patient_id/doctor_id not client-controlled ----
        r = client.post(
            "/lab-requests",
            json={"appointment_id": appt_a_id, "test_name": "RBS",
                  "patient_id": patients["B"].id, "doctor_id": doctors["B"].id},
            headers=doca_h,
        )
        body = r.json()
        lab4_id = body["id"]
        lab_ids.append(lab4_id)
        check("client-supplied patient_id ignored (derived)", body["patient_id"] == patients["A"].id)
        check("client-supplied doctor_id ignored (derived)", body["doctor_id"] == doctors["A"].id)

        # ---- 24. No password_hash leakage ----
        r = client.get("/lab-requests/%d" % lab1_id, headers=admin_h)
        check("detail has no password_hash", "password_hash" not in r.text)
        r = client.get("/lab-requests", headers=admin_h)
        check("list has no password_hash", "password_hash" not in r.text)

        # ---- 25. DELETE unavailable ----
        r = client.delete("/lab-requests/%d" % lab1_id, headers=admin_h)
        check("DELETE lab request -> 405/404", r.status_code in (404, 405))

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            if lab_ids:
                db.query(LabRequest).filter(LabRequest.id.in_(lab_ids)).delete(
                    synchronize_session=False
                )
            if appointment_ids:
                db.query(MedicalRecordVersion).filter(
                    MedicalRecordVersion.record_id.in_(
                        db.query(MedicalRecord.id).filter(
                            MedicalRecord.appointment_id.in_(appointment_ids)
                        )
                    )
                ).delete(synchronize_session=False)
                db.query(MedicalRecord).filter(
                    MedicalRecord.appointment_id.in_(appointment_ids)
                ).delete(synchronize_session=False)
                db.query(Appointment).filter(
                    Appointment.id.in_(appointment_ids)
                ).delete(synchronize_session=False)
            for mrn in ("LAPA", "LAPB"):
                db.query(Patient).filter(
                    Patient.mrn.like(f"{mrn}%")
                ).delete(synchronize_session=False)
            for lic in ("LABDA", "LABDB"):
                db.query(Doctor).filter(
                    Doctor.license_number.like(f"{lic}%")
                ).delete(synchronize_session=False)
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id).filter(User.email.like("lab.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            tmp_user_ids = db.query(User.id).filter(
                User.email.like("lab.%@mediflow.local")
            )
            db.query(AuditLog).filter(
                AuditLog.user_id.in_(tmp_user_ids)
            ).delete(synchronize_session=False)
            db.query(Notification).filter(
                Notification.user_id.in_(tmp_user_ids)
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("lab.%@mediflow.local")
            ).delete(synchronize_session=False)
            db.query(Department).filter(Department.name.like(f"Lab Dept {suffix}%")).delete(
                synchronize_session=False
            )
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