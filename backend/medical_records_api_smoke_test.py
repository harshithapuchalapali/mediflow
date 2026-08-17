import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    Appointment,
    Department,
    Doctor,
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
    dept = None
    appointment_ids = []
    record_ids = []
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
        # ---- Setup: unique user+profile per role, one department ----
        dept = Department(name=f"MR Dept {suffix}")
        db.add(dept)
        db.flush()

        for role in ("ADMIN", "DOCTOR_A", "DOCTOR_B", "RECEPTIONIST",
                     "PATIENT_A", "PATIENT_B"):
            u = User(
                email=f"mr.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("MrApiPass!42"),
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
            license_number=f"MRDA{suffix[:6]}",
            consultation_fee=500.00,
        )
        db.add(da)
        db.flush()
        dbb = Doctor(
            user_id=users["DOCTOR_B"].id,
            license_number=f"MRDB{suffix[:6]}",
            consultation_fee=600.00,
        )
        db.add(dbb)
        db.flush()
        doctors["A"] = da
        doctors["B"] = dbb

        pa = Patient(
            user_id=users["PATIENT_A"].id,
            mrn=f"MRPTA{suffix[:6]}",
            first_name="Alice",
            last_name="Record",
        )
        pb = Patient(
            user_id=users["PATIENT_B"].id,
            mrn=f"MRPTB{suffix[:6]}",
            first_name="Bob",
            last_name="Record",
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

        appt_a = create_appointment(
            doctors["A"], patients["A"], BASE
        )
        appt_b = create_appointment(
            doctors["B"], patients["B"], BASE + timedelta(days=1)
        )
        appt_a_other_doc = create_appointment(
            doctors["B"], patients["A"], BASE + timedelta(days=2)
        )
        check("setup: appointment for doctor A (201)",
              appt_a.status_code == 201)
        check("setup: appointment for doctor B (201)",
              appt_b.status_code == 201)
        appt_a_id = appt_a.json()["id"]
        appt_b_id = appt_b.json()["id"]
        appt_a_other_doc_id = appt_a_other_doc.json()["id"]

        # ---- 1. Successful create (own consultation) ----
        r = client.post(
            "/medical-records",
            json={
                "appointment_id": appt_a_id,
                "symptoms": "Fever",
                "diagnosis": "Viral infection",
                "vitals_json": {"bp": "120/80", "pulse": "72"},
                "notes": "Rest and fluids",
            },
            headers=doca_h,
        )
        check("doctor creates record -> 201 + id", r.status_code == 201 and r.json().get("id"))
        check("record latest_version = 1", r.json().get("latest_version") == 1)
        check("record patient_id matches appointment", r.json().get("patient_id") == patients["A"].id)
        check("record doctor_id matches appointment", r.json().get("doctor_id") == doctors["A"].id)
        check("create response has clinical data", r.json().get("diagnosis") == "Viral infection")
        record_a_id = r.json()["id"]
        record_ids.append(record_a_id)

        # ---- 2. Doctor cannot create for another doctor's consultation ----
        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_a_other_doc_id, "diagnosis": "Test"},
            headers=doca_h,
        )
        check("doctor creates record for other doctor's appt -> 403",
              r.status_code == 403)

        # ---- 3. Unauthenticated ----
        r = client.post("/medical-records", json={"appointment_id": appt_b_id, "diagnosis": "x"})
        check("create without token -> 401", r.status_code == 401)
        r = client.get("/medical-records/%d" % record_a_id)
        check("get without token -> 401", r.status_code == 401)
        r = client.get("/medical-records")
        check("list without token -> 401", r.status_code == 401)

        # ---- 4. Duplicate record for same appointment -> 409 ----
        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_a_id, "diagnosis": "Duplicate"},
            headers=doca_h,
        )
        check("duplicate record for appointment -> 409", r.status_code == 409)

        # ---- 5. Invalid appointment reference -> 422 ----
        r = client.post(
            "/medical-records",
            json={"appointment_id": 99999999, "diagnosis": "x"},
            headers=doca_h,
        )
        check("invalid appointment_id -> 422", r.status_code == 422)

        # ---- 6. Empty clinical data -> 422 ----
        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_b_id},
            headers=docb_h,
        )
        check("no clinical fields on create -> 422", r.status_code == 422)

        # ---- 7. Read own record as doctor / patient ----
        r = client.get("/medical-records/%d" % record_a_id, headers=doca_h)
        check("doctor reads own record -> 200", r.status_code == 200)
        check("detail includes version history",
              r.status_code == 200 and len(r.json().get("versions", [])) == 1)
        r = client.get("/medical-records/%d" % record_a_id, headers=pata_h)
        check("patient reads own record -> 200", r.status_code == 200)

        # ---- 8. IDOR: patient reads another patient's record -> 404 ----
        r = client.get("/medical-records/%d" % record_a_id, headers=patb_h)
        check("patient reads other's record -> 404", r.status_code == 404)

        # ---- 9. IDOR: doctor reads another doctor's consult record ----
        # Create a record on doctor B's appointment, then try doctor A reading it.
        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_b_id, "diagnosis": "DocB diagnosis"},
            headers=docb_h,
        )
        check("doctor B creates record -> 201", r.status_code == 201)
        record_b_id = r.json()["id"]
        record_ids.append(record_b_id)
        r = client.get("/medical-records/%d" % record_b_id, headers=doca_h)
        check("doctor A reads doctor B's record -> 404", r.status_code == 404)

        # ---- 10. Receptionist cannot read ----
        r = client.get("/medical-records/%d" % record_a_id, headers=rec_h)
        check("receptionist reads record -> 403", r.status_code == 403)
        r = client.get("/medical-records", headers=rec_h)
        check("receptionist lists records -> 403", r.status_code == 403)
        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_b_id, "diagnosis": "x"},
            headers=rec_h,
        )
        check("receptionist creates record -> 403", r.status_code == 403)

        # ---- 11. Admin reads any record, cannot create ----
        r = client.get("/medical-records/%d" % record_a_id, headers=admin_h)
        check("admin reads any record -> 200", r.status_code == 200)
        r = client.get("/medical-records/%d" % record_b_id, headers=admin_h)
        check("admin reads other record -> 200", r.status_code == 200)
        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_b_id, "diagnosis": "x"},
            headers=admin_h,
        )
        check("admin creates record -> 403", r.status_code == 403)

        # ---- 12. List scoping ----
        r = client.get("/medical-records", headers=docb_h)
        check("doctor B list only own records",
              r.status_code == 200 and all(
                  rec["doctor_id"] == doctors["B"].id for rec in r.json()))
        r = client.get("/medical-records", headers=patb_h)
        check("patient B list only own records",
              r.status_code == 200 and all(
                  rec["patient_id"] == patients["B"].id for rec in r.json()))
        r = client.get("/medical-records", headers=admin_h)
        check("admin list includes both records",
              r.status_code == 200 and len(r.json()) >= 2)

        # ---- 13. Append version as author doctor -> 200, version increments ----
        r = client.patch(
            "/medical-records/%d/versions" % record_a_id,
            json={"diagnosis": "Updated diagnosis", "notes": "Follow-up notes"},
            headers=doca_h,
        )
        check("append version -> 200", r.status_code == 200)
        check("latest_version incremented to 2", r.json().get("latest_version") == 2)
        check("current version shows updated data",
              r.json().get("diagnosis") == "Updated diagnosis")

        # ---- 14. Append empty version -> 422 ----
        r = client.patch(
            "/medical-records/%d/versions" % record_a_id,
            json={},
            headers=doca_h,
        )
        check("append empty version -> 422", r.status_code == 422)

        # ---- 15. Append as another doctor -> 403 ----
        r = client.patch(
            "/medical-records/%d/versions" % record_a_id,
            json={"notes": "Intrusion"},
            headers=docb_h,
        )
        check("doctor B appends to doctor A record -> 403", r.status_code == 403)
        r = client.patch(
            "/medical-records/%d/versions" % record_a_id,
            json={"notes": "Patient edit"},
            headers=pata_h,
        )
        check("patient appends to record -> 403", r.status_code == 403)

        # ---- 16. Version history integrity (versions never overwritten) ----
        r = client.get("/medical-records/%d" % record_a_id, headers=admin_h)
        versions = r.json().get("versions", [])
        check("history has 2 versions", len(versions) == 2)
        check("version 1 immutable (original diagnosis)",
              versions[0].get("diagnosis") == "Viral infection")
        check("version numbers 1 and 2",
              [v.get("version_number") for v in versions] == [1, 2])
        check("changed_by is doctor user id",
              versions[0].get("changed_by") == users["DOCTOR_A"].id)
        check("no password_hash leaked",
              "password_hash" not in r.text)

        # ---- 17. Update/delete routes do not exist ----
        r = client.put("/medical-records/%d" % record_a_id, json={}, headers=admin_h)
        check("PUT record (no route) -> 405", r.status_code in (404, 405))
        r = client.delete("/medical-records/%d" % record_a_id, headers=admin_h)
        check("DELETE record (no route) -> 405", r.status_code in (404, 405))

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            if record_ids:
                db.query(MedicalRecordVersion).filter(
                    MedicalRecordVersion.record_id.in_(record_ids)
                ).delete(synchronize_session=False)
            if record_ids:
                db.query(MedicalRecord).filter(
                    MedicalRecord.id.in_(record_ids)
                ).delete(synchronize_session=False)
            if appointment_ids:
                db.query(Appointment).filter(
                    Appointment.id.in_(appointment_ids)
                ).delete(synchronize_session=False)
            if dept is not None:
                db.query(Department).filter(Department.id == dept.id).delete(
                    synchronize_session=False
                )
            for mrn in ("MRPTA", "MRPTB"):
                db.query(Patient).filter(Patient.mrn.like(f"{mrn}%")).delete(
                    synchronize_session=False
                )
            for lic in ("MRDA", "MRDB"):
                db.query(Doctor).filter(
                    Doctor.license_number.like(f"{lic}%")
                ).delete(synchronize_session=False)
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id).filter(User.email.like("mr.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            tmp_user_ids = db.query(User.id).filter(
                User.email.like("mr.%@mediflow.local")
            )
            db.query(Notification).filter(
                Notification.user_id.in_(tmp_user_ids)
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("mr.%@mediflow.local")
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
