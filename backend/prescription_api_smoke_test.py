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
    MedicalRecord,
    MedicalRecordVersion,
    Notification,
    Patient,
    PatientAllergy,
    Prescription,
    PrescriptionItem,
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
    prescription_ids = []
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
        dept = Department(name=f"Rx Dept {suffix}")
        db.add(dept)
        db.flush()

        for role in ("ADMIN", "DOCTOR_A", "DOCTOR_B", "RECEPTIONIST",
                     "PATIENT_A", "PATIENT_B"):
            u = User(
                email=f"rx.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("RxApiPass!42"),
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
            license_number=f"RXDA{suffix[:6]}",
            consultation_fee=500.00,
        )
        db.add(da)
        db.flush()
        dbb = Doctor(
            user_id=users["DOCTOR_B"].id,
            license_number=f"RXDB{suffix[:6]}",
            consultation_fee=600.00,
        )
        db.add(dbb)
        db.flush()
        doctors["A"] = da
        doctors["B"] = dbb

        pa = Patient(
            user_id=users["PATIENT_A"].id,
            mrn=f"RXPAN{suffix[:6]}",
            first_name="Alice",
            last_name="Rx",
        )
        pb = Patient(
            user_id=users["PATIENT_B"].id,
            mrn=f"RXPBN{suffix[:6]}",
            first_name="Bob",
            last_name="Rx",
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
        check("setup: appointment for doctor A (201)", appt_a.status_code == 201)
        check("setup: appointment for doctor B (201)", appt_b.status_code == 201)

        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_a.json()["id"], "diagnosis": "Rx case A"},
            headers=doca_h,
        )
        check("setup: medical record A (201)", r.status_code == 201)
        record_a_id = r.json()["id"]
        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_b.json()["id"], "diagnosis": "Rx case B"},
            headers=docb_h,
        )
        check("setup: medical record B (201)", r.status_code == 201)
        record_b_id = r.json()["id"]

        # ---- 1. Successful creation + derived ids + normalization ----
        r = client.post(
            "/prescriptions",
            json={
                "medical_record_id": record_a_id,
                "items": [
                    {
                        "medicine_name": "  Paracetamol ",
                        "dosage": "500 mg",
                        "frequency": "Twice a day",
                        "duration_in_days": 5,
                    }
                ],
            },
            headers=doca_h,
        )
        check("create prescription -> 201 + id", r.status_code == 201 and r.json()["prescription"].get("id"))
        rx = r.json()["prescription"]
        check("doctor_id derived from record", rx["doctor_id"] == doctors["A"].id)
        check("patient_id derived from record", rx["patient_id"] == patients["A"].id)
        check("medical_record_id echoes request", rx["medical_record_id"] == record_a_id)
        check("create has no allergy warnings when none exist", r.json()["allergy_warnings"] == [])
        check("medicine_name normalized (trimmed+lowercased)",
              rx["items"][0]["medicine_name"] == "paracetamol")
        rx1_id = rx["id"]
        prescription_ids.append(rx1_id)

        # ---- 2. Doctor cannot prescribe on another doctor's record ----
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": record_b_id, "items": [{"medicine_name": "X",
                                                               "dosage": "1", "frequency": "OD",
                                                               "duration_in_days": 1}]},
            headers=doca_h,
        )
        check("doctor A prescribes on doctor B record -> 403", r.status_code == 403)

        # ---- 3. Unauthenticated ----
        r = client.post("/prescriptions", json={"medical_record_id": record_a_id,
                                                "items": [{"medicine_name": "X", "dosage": "1",
                                                           "frequency": "OD", "duration_in_days": 1}]})
        check("create without token -> 401", r.status_code == 401)
        r = client.get("/prescriptions/%d" % rx1_id)
        check("get without token -> 401", r.status_code == 401)
        r = client.get("/prescriptions")
        check("list without token -> 401", r.status_code == 401)

        # ---- 4. Unknown medical_record_id -> 404 ----
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": 99999999, "items": [{"medicine_name": "X", "dosage": "1",
                                                           "frequency": "OD", "duration_in_days": 1}]},
            headers=doca_h,
        )
        check("unknown medical_record_id -> 404", r.status_code == 404)

        # ---- 5. Empty items -> 422 ----
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": record_a_id, "items": []},
            headers=doca_h,
        )
        check("empty items -> 422", r.status_code == 422)

        # ---- 6. Invalid item data -> 422 ----
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": record_a_id,
                  "items": [{"medicine_name": "X", "dosage": "1", "frequency": "OD",
                             "duration_in_days": 0}]},
            headers=doca_h,
        )
        check("duration_in_days = 0 -> 422", r.status_code == 422)
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": record_a_id,
                  "items": [{"medicine_name": "   ", "dosage": "1", "frequency": "OD",
                             "duration_in_days": 3}]},
            headers=doca_h,
        )
        check("blank medicine_name -> 422", r.status_code == 422)

        # ---- 7. Ownership reads ----
        r = client.get("/prescriptions/%d" % rx1_id, headers=pata_h)
        check("patient reads own prescription -> 200",
              r.status_code == 200 and r.json()["items"][0]["medicine_name"] == "paracetamol")
        r = client.get("/prescriptions/%d" % rx1_id, headers=doca_h)
        check("doctor reads own prescription -> 200", r.status_code == 200)

        # ---- 8. IDOR ----
        r = client.get("/prescriptions/%d" % rx1_id, headers=patb_h)
        check("patient B reads patient A rx -> 404", r.status_code == 404)
        r = client.get("/prescriptions/%d" % rx1_id, headers=docb_h)
        check("doctor B reads doctor A rx -> 404", r.status_code == 404)

        # ---- 9. Receptionist denied everywhere ----
        r = client.get("/prescriptions/%d" % rx1_id, headers=rec_h)
        check("receptionist reads rx -> 403", r.status_code == 403)
        r = client.get("/prescriptions", headers=rec_h)
        check("receptionist lists rx -> 403", r.status_code == 403)
        r = client.post("/prescriptions", json={"medical_record_id": record_b_id,
                                                "items": [{"medicine_name": "X", "dosage": "1",
                                                           "frequency": "OD", "duration_in_days": 1}]},
                        headers=rec_h)
        check("receptionist creates rx -> 403", r.status_code == 403)

        # ---- 10. Admin: reads all, cannot create ----
        r = client.get("/prescriptions/%d" % rx1_id, headers=admin_h)
        check("admin reads any rx -> 200", r.status_code == 200)
        r = client.post("/prescriptions", json={"medical_record_id": record_b_id,
                                                "items": [{"medicine_name": "X", "dosage": "1",
                                                           "frequency": "OD", "duration_in_days": 1}]},
                        headers=admin_h)
        check("admin creates rx -> 403", r.status_code == 403)

        # ---- 11. Multiple prescriptions per medical record allowed ----
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": record_a_id,
                  "items": [{"medicine_name": "Ibuprofen", "dosage": "400 mg",
                             "frequency": "Thrice a day", "duration_in_days": 3}]},
            headers=doca_h,
        )
        check("second rx on same record -> 201", r.status_code == 201)
        rx2_id = r.json()["prescription"]["id"]
        prescription_ids.append(rx2_id)

        # ---- 12. Doctor B creates a prescription on his record ----
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": record_b_id,
                  "items": [{"medicine_name": "Metformin", "dosage": "850 mg",
                             "frequency": "After breakfast", "duration_in_days": 30}]},
            headers=docb_h,
        )
        check("doctor B creates rx -> 201", r.status_code == 201)
        rx3_id = r.json()["prescription"]["id"]
        prescription_ids.append(rx3_id)

        # ---- 13. Allergy matching (informational, never blocks) ----
        allergy = PatientAllergy(
            patient_id=patients["A"].id,
            allergen="aspirin",
            severity="SEVERE",
            created_by=users["ADMIN"].id,
        )
        db.add(allergy)
        db.commit()
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": record_a_id,
                  "items": [{"medicine_name": " Aspirin ", "dosage": "75 mg",
                             "frequency": "Once a day", "duration_in_days": 10}]},
            headers=doca_h,
        )
        check("rx with matching allergy still created -> 201", r.status_code == 201)
        warnings = r.json().get("allergy_warnings", [])
        check("allergy_warnings contains match",
              any(w["medicine_name"] == "aspirin" and w["severity"] == "SEVERE"
                  for w in warnings))
        rx4_id = r.json()["prescription"]["id"]
        prescription_ids.append(rx4_id)
        r = client.post(
            "/prescriptions",
            json={"medical_record_id": record_b_id,
                  "items": [{"medicine_name": "Paracetamol", "dosage": "500 mg",
                             "frequency": "Once a day", "duration_in_days": 2}]},
            headers=docb_h,
        )
        check("non-matching medicine -> no warnings",
              r.status_code == 201 and r.json()["allergy_warnings"] == [])
        rx5_id = r.json()["prescription"]["id"]
        prescription_ids.append(rx5_id)

        # ---- 14. List scoping ----
        r = client.get("/prescriptions", headers=docb_h)
        check("doctor B list only own rx",
              r.status_code == 200 and all(p["doctor_id"] == doctors["B"].id for p in r.json()))
        r = client.get("/prescriptions", headers=pata_h)
        check("patient A list only own rx",
              r.status_code == 200 and all(p["patient_id"] == patients["A"].id for p in r.json()))
        r = client.get("/prescriptions", headers=admin_h)
        check("admin list returns all (>2 rx)",
              r.status_code == 200 and len(r.json()) >= 4)

        # ---- 15. Immutability: no update/delete routes ----
        for method in ("put", "patch", "delete"):
            r = getattr(client, method)("/prescriptions/%d" % rx1_id, headers=admin_h)
            check("%s prescription -> 405/404" % method.upper(), r.status_code in (404, 405))

        # ---- 16. No password_hash leakage ----
        r = client.get("/prescriptions/%d" % rx1_id, headers=admin_h)
        check("no password_hash leaked", "password_hash" not in r.text)
        r = client.get("/prescriptions", headers=pata_h)
        check("list response has no password_hash", "password_hash" not in r.text)

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            if prescription_ids:
                db.query(PrescriptionItem).filter(
                    PrescriptionItem.prescription_id.in_(prescription_ids)
                ).delete(synchronize_session=False)
                db.query(Prescription).filter(
                    Prescription.id.in_(prescription_ids)
                ).delete(synchronize_session=False)
            for mrn in ("RXPAN", "RXPBN"):
                patient_rows = db.query(Patient).filter(Patient.mrn.like(f"{mrn}%")).all()
                for p in patient_rows:
                    db.query(PatientAllergy).filter(
                        PatientAllergy.patient_id == p.id
                    ).delete(synchronize_session=False)
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
            for mrn in ("RXPAN", "RXPBN"):
                db.query(Patient).filter(
                    Patient.mrn.like(f"{mrn}%")
                ).delete(synchronize_session=False)
            for lic in ("RXDA", "RXDB"):
                db.query(Doctor).filter(
                    Doctor.license_number.like(f"{lic}%")
                ).delete(synchronize_session=False)
            db.query(Notification).filter(
                Notification.user_id.in_(
                    db.query(User.id).filter(User.email.like("rx.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(AuditLog).filter(
                AuditLog.user_id.in_(
                    db.query(User.id).filter(User.email.like("rx.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id).filter(User.email.like("rx.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("rx.%@mediflow.local")
            ).delete(synchronize_session=False)
            db.query(Department).filter(Department.name.like(f"Rx Dept {suffix}%")).delete(
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