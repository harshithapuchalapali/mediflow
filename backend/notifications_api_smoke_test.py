import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    Appointment,
    Bill,
    BillItem,
    Department,
    Doctor,
    LabRequest,
    MedicalRecord,
    MedicalRecordVersion,
    Notification,
    Payment,
    Patient,
    Prescription,
    PrescriptionItem,
    Receptionist,
    User,
)
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time()))

BASE = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def main():
    db = SessionLocal()
    users = {}
    patients = {}
    doctor_ids = []
    dept_id = None
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

    def count_notifs(user_id, ntype=None):
        q = db.query(Notification).filter(Notification.user_id == user_id)
        if ntype is not None:
            q = q.filter(Notification.type == ntype)
        return q.count()

    try:
        dept = Department(name=f"Notif Dept {suffix}")
        db.add(dept)
        db.flush()
        dept_id = dept.id

        for role in ("ADMIN", "RECEPTIONIST", "DOCTOR", "PATIENT", "PATIENT_B", "PATIENT_C"):
            u = User(
                email=f"noti.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("NotifApiPass!42"),
                role="ADMIN" if role == "ADMIN" else (
                    "RECEPTIONIST" if role == "RECEPTIONIST" else (
                        "DOCTOR" if role == "DOCTOR" else "PATIENT"
                    )
                ),
                status="ACTIVE",
            )
            db.add(u)
            db.flush()
            users[role] = u

        doctor_a = Doctor(
            user_id=users["DOCTOR"].id,
            license_number=f"NTDA{suffix[:6]}",
            consultation_fee=500.00,
        )
        db.add(doctor_a)
        db.flush()
        doctor_ids.append(doctor_a.id)

        receptionist = Receptionist(user_id=users["RECEPTIONIST"].id)
        db.add(receptionist)

        patient_map = {
            "PATIENT": ("P1", "Two"),
            "PATIENT_B": ("P2", "Beta"),
            "PATIENT_C": ("P3", "Gamma"),
        }
        active_roles = {"PATIENT", "PATIENT_B"}
        for role, (first, last) in patient_map.items():
            p = Patient(
                user_id=users[role].id,
                mrn=f"NOTI-{suffix}-{first}",
                first_name=first,
                last_name=last,
            )
            db.add(p)
            db.flush()
            patients[role] = p

        # Patient C is deactivated up front for the deactivated-user test.
        users["PATIENT_C"].status = "DEACTIVATED"
        users["PATIENT_C"].deactivated_at = datetime.now(timezone.utc)

        db.commit()
        for obj in list(patients.values()) + [dept, doctor_a, receptionist]:
            db.refresh(obj)

        admin_h = token_for("ADMIN")
        receptionist_h = token_for("RECEPTIONIST")
        doctor_h = token_for("DOCTOR")
        patient_a_h = token_for("PATIENT")
        patient_b_h = token_for("PATIENT_B")
        patient_c_h = token_for("PATIENT_C")

        # ============ 1. Auth guards ============
        r = client.get("/notifications")
        check("GET /notifications unauth -> 401", r.status_code == 401)
        r = client.get("/notifications/unread-count")
        check("GET unread-count unauth -> 401", r.status_code == 401)
        r = client.patch("/notifications/1/read")
        check("PATCH mark-read unauth -> 401", r.status_code == 401)
        r = client.post("/notifications/read-all")
        check("POST read-all unauth -> 401", r.status_code == 401)
        r = client.post("/notifications")
        check("no client create endpoint (405)", r.status_code == 405)

        # ============ 2. Empty state / ownership ============
        r = client.get("/notifications", headers=patient_b_h)
        check("other patient list is empty -> 200", r.status_code == 200 and r.json() == [])
        r = client.get("/notifications", headers=patient_a_h)
        check("fresh patient list empty -> 200", r.status_code == 200 and r.json() == [])
        r = client.get("/notifications/unread-count", headers=patient_a_h)
        check("initial unread-count == 0",
              r.status_code == 200 and r.json()["unread_count"] == 0)

        # ============ 3. Event generation ============
        a1_body = {
            "patient_id": patients["PATIENT"].id,
            "doctor_id": doctor_a.id,
            "department_id": dept.id,
            "date_time": iso(BASE),
            "duration_minutes": 30,
            "priority": "NORMAL",
            "appointment_type": "INITIAL_CONSULTATION",
            "reason": None,
        }
        r = client.post("/appointments", json=a1_body, headers=receptionist_h)
        check("receptionist books appointment -> 201", r.status_code == 201)
        appt1_id = r.json()["id"]
        pa_user_id = users["PATIENT"].id
        check("APPOINTMENT_BOOKED created", count_notifs(pa_user_id, "APPOINTMENT_BOOKED") == 1)
        r = client.get("/notifications/unread-count", headers=patient_a_h)
        check("unread-count == 1 after booking",
              r.status_code == 200 and r.json()["unread_count"] == 1)

        r = client.patch("/appointments/%d" % appt1_id, json={"status": "CONFIRMED"},
                         headers=admin_h)
        check("admin confirms appointment -> 200", r.status_code == 200)
        check("APPOINTMENT_CONFIRMED created",
              count_notifs(pa_user_id, "APPOINTMENT_CONFIRMED") == 1)

        lab_body = {"appointment_id": appt1_id, "test_name": "CBC", "notes": None}
        r = client.post("/lab-requests", json=lab_body, headers=doctor_h)
        check("doctor creates lab request -> 201", r.status_code == 201)
        lab_id = r.json()["id"]
        r = client.patch("/lab-requests/%d" % lab_id,
                         json={"target_status": "IN_PROGRESS"}, headers=doctor_h)
        check("lab IN_PROGRESS -> 200", r.status_code == 200)
        check("no notification for IN_PROGRESS",
              count_notifs(pa_user_id) == 2)
        r = client.patch("/lab-requests/%d" % lab_id,
                         json={"target_status": "RESULT_READY",
                               "result_details": "Normal range"},
                         headers=doctor_h)
        check("lab RESULT_READY -> 200", r.status_code == 200)
        check("LAB_READY created", count_notifs(pa_user_id, "LAB_READY") == 1)
        r = client.patch("/lab-requests/%d" % lab_id,
                         json={"target_status": "VERIFIED"}, headers=doctor_h)
        check("lab VERIFIED -> 200", r.status_code == 200)
        check("LAB_VERIFIED created", count_notifs(pa_user_id, "LAB_VERIFIED") == 1)

        mr_body = {
            "appointment_id": appt1_id,
            "symptoms": "cough",
            "diagnosis": "URTI",
            "notes": "mild",
        }
        r = client.post("/medical-records", json=mr_body, headers=doctor_h)
        check("doctor creates medical record -> 201", r.status_code == 201)
        record_id = r.json()["id"]
        check("MEDICAL_RECORD_CREATED created",
              count_notifs(pa_user_id, "MEDICAL_RECORD_CREATED") == 1)

        rx_body = {
            "medical_record_id": record_id,
            "items": [{"medicine_name": "Paracetamol", "dosage": "500mg",
                       "frequency": "twice daily", "duration_in_days": 5}],
        }
        r = client.post("/prescriptions", json=rx_body, headers=doctor_h)
        check("doctor creates prescription -> 201", r.status_code == 201)
        check("PRESCRIPTION_CREATED created",
              count_notifs(pa_user_id, "PRESCRIPTION_CREATED") == 1)

        bill_body = {
            "appointment_id": appt1_id,
            "items": [{"description": "Consultation", "category": "CONSULTATION",
                       "quantity": 1, "unit_price": "500.00"}],
        }
        r = client.post("/bills", json=bill_body, headers=receptionist_h)
        check("receptionist creates bill -> 201", r.status_code == 201)
        bill_id = r.json()["id"]
        check("BILL_CREATED created", count_notifs(pa_user_id, "BILL_CREATED") == 1)

        r = client.post("/bills/%d/payments" % bill_id,
                        json={"amount": "500.00", "method": "CASH"}, headers=receptionist_h)
        check("receptionist records payment -> 200", r.status_code == 200)
        check("BILL_PAID created", count_notifs(pa_user_id, "BILL_PAID") == 1)

        r = client.get("/notifications/unread-count", headers=patient_a_h)
        check("unread-count == 8 after all events",
              r.status_code == 200 and r.json()["unread_count"] == 8)

        r = client.get("/notifications?type=LAB_READY", headers=patient_a_h)
        check("list filter by type",
              r.status_code == 200 and len(r.json()) == 1
              and r.json()[0]["type"] == "LAB_READY")

        r = client.get("/notifications?unread_only=true", headers=patient_a_h)
        check("unread_only filter returns 8",
              r.status_code == 200 and len(r.json()) == 8
              and all(n["is_read"] is False for n in r.json()))

        r = client.get("/notifications?limit=3&offset=0", headers=patient_a_h)
        check("pagination page 1 -> 3 rows", r.status_code == 200 and len(r.json()) == 3)
        r = client.get("/notifications?limit=3&offset=3", headers=patient_a_h)
        check("pagination page 2 -> 3 rows (no overlap)",
              r.status_code == 200 and len(r.json()) == 3
              and all(n["id"] not in [x["id"] for x in
                                      client.get("/notifications?limit=3&offset=0",
                                                 headers=patient_a_h).json()]
                      for n in r.json()))
        r = client.get("/notifications", headers=patient_a_h)
        check("list response omits password_hash", "password_hash" not in r.text)

        # ============ 4. Read / unread behavior ============
        first_id = (client.get("/notifications?limit=1", headers=patient_a_h)
                    .json()[0]["id"])
        r = client.patch("/notifications/%d/read" % first_id, headers=patient_a_h)
        check("mark one notification read -> 200", r.status_code == 200 and r.json()["is_read"] is True)
        r = client.get("/notifications/unread-count", headers=patient_a_h)
        check("unread-count decremented to 7",
              r.status_code == 200 and r.json()["unread_count"] == 7)
        r = client.patch("/notifications/%d/read" % first_id, headers=patient_a_h)
        check("re-reading is idempotent -> 200 is_read",
              r.status_code == 200 and r.json()["is_read"] is True)
        r = client.get("/notifications/unread-count", headers=patient_a_h)
        check("unread-count still 7 after idempotent re-read",
              r.status_code == 200 and r.json()["unread_count"] == 7)

        r = client.post("/notifications/read-all", headers=patient_a_h)
        check("read-all updates 7", r.status_code == 200 and r.json()["updated"] == 7)
        r = client.get("/notifications/unread-count", headers=patient_a_h)
        check("unread-count == 0 after read-all",
              r.status_code == 200 and r.json()["unread_count"] == 0)
        r = client.post("/notifications/read-all", headers=patient_a_h)
        check("read-all again updates 0", r.status_code == 200 and r.json()["updated"] == 0)
        r = client.get("/notifications?unread_only=true", headers=patient_a_h)
        check("unread_only empty after read-all", r.status_code == 200 and r.json() == [])

        # ============ 5. IDOR / ownership ============
        r = client.patch("/notifications/%d/read" % first_id, headers=patient_b_h)
        check("other patient mark-read -> 404", r.status_code == 404)
        r = client.patch("/notifications/%d/read" % first_id, headers=admin_h)
        check("admin mark-read another's notification -> 404", r.status_code == 404)
        r = client.post("/notifications/read-all", headers=patient_b_h)
        check("other patient read-all -> 200 updated 0",
              r.status_code == 200 and r.json()["updated"] == 0)
        r = client.get("/notifications", headers=admin_h)
        check("admin list own notifications empty", r.status_code == 200 and r.json() == [])
        r = client.get("/notifications?type=BILL_CREATED", headers=patient_b_h)
        check("other patient cannot see any BILL_CREATED", r.status_code == 200 and r.json() == [])
        r = client.patch("/notifications/999999/read", headers=patient_a_h)
        check("unknown notification -> 404", r.status_code == 404)

        # ============ 6. Lazy reminder + no duplicates ============
        a2_body = dict(a1_body)
        a2_body["date_time"] = iso(datetime.now(timezone.utc) + timedelta(hours=2))
        r = client.post("/appointments", json=a2_body, headers=receptionist_h)
        check("book second appointment (within 24h) -> 201", r.status_code == 201)
        check("second APPOINTMENT_BOOKED (new entity)",
              count_notifs(pa_user_id, "APPOINTMENT_BOOKED") == 2)

        r = client.get("/notifications?limit=50", headers=patient_a_h)
        check("list triggers lazy reminder (200)",
              r.status_code == 200
              and any(n["type"] == "APPOINTMENT_REMINDER" for n in r.json()))
        check("exactly one reminder created",
              count_notifs(pa_user_id, "APPOINTMENT_REMINDER") == 1)
        r = client.get("/notifications?limit=50", headers=patient_a_h)
        check("relisting does not duplicate reminder",
              count_notifs(pa_user_id, "APPOINTMENT_REMINDER") == 1)
        r = client.get("/notifications/unread-count", headers=patient_a_h)
        check("unread-count does not duplicate reminder",
              r.status_code == 200 and count_notifs(pa_user_id, "APPOINTMENT_REMINDER") == 1)

        # ============ 7. No duplicates on guarded retries ============
        r = client.patch("/lab-requests/%d" % lab_id,
                         json={"target_status": "VERIFIED"}, headers=doctor_h)
        check("re-verify lab rejected 422", r.status_code == 422)
        check("LAB_VERIFIED still exactly one row",
              count_notifs(pa_user_id, "LAB_VERIFIED") == 1)
        r = client.post("/bills", json=bill_body, headers=receptionist_h)
        check("duplicate bill for same appointment -> 409", r.status_code == 409)
        check("BILL_CREATED still exactly one row",
              count_notifs(pa_user_id, "BILL_CREATED") == 1)
        r = client.patch("/appointments/%d" % appt1_id, json={"status": "CONFIRMED"},
                         headers=admin_h)
        check("re-confirm terminal-free CONFIRMED rejected -> 422",
              r.status_code == 422)
        check("APPOINTMENT_CONFIRMED still exactly one row",
              count_notifs(pa_user_id, "APPOINTMENT_CONFIRMED") == 1)

        # ============ 8. Deactivated-user behavior ============
        r = client.get("/notifications", headers=patient_c_h)
        check("deactivated patient list -> 401", r.status_code == 401)
        r = client.get("/notifications/unread-count", headers=patient_c_h)
        check("deactivated patient unread-count -> 401", r.status_code == 401)
    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            ids = [u.id for u in db.query(User).filter(
                User.email.like("noti.%@mediflow.local")).all()]
            if ids:
                db.query(Notification).filter(
                    Notification.user_id.in_(ids)
                ).delete(synchronize_session=False)
            pids = [p.id for p in db.query(Patient).filter(
                Patient.user_id.in_(ids)).all()] if ids else []
            if pids:
                bill_ids = [b.id for b in db.query(Bill).filter(
                    Bill.patient_id.in_(pids)).all()]
                if bill_ids:
                    db.query(BillItem).filter(
                        BillItem.bill_id.in_(bill_ids)
                    ).delete(synchronize_session=False)
                    db.query(Payment).filter(
                        Payment.bill_id.in_(bill_ids)
                    ).delete(synchronize_session=False)
                db.query(Bill).filter(Bill.patient_id.in_(pids)).delete(
                    synchronize_session=False)
                rx_ids = [x.id for x in db.query(Prescription).filter(
                    Prescription.patient_id.in_(pids)).all()]
                if rx_ids:
                    db.query(PrescriptionItem).filter(
                        PrescriptionItem.prescription_id.in_(rx_ids)
                    ).delete(synchronize_session=False)
                db.query(Prescription).filter(
                    Prescription.patient_id.in_(pids)
                ).delete(synchronize_session=False)
                rec_ids = [m.id for m in db.query(MedicalRecord).filter(
                    MedicalRecord.patient_id.in_(pids)).all()]
                if rec_ids:
                    db.query(MedicalRecordVersion).filter(
                        MedicalRecordVersion.record_id.in_(rec_ids)
                    ).delete(synchronize_session=False)
                db.query(MedicalRecord).filter(
                    MedicalRecord.patient_id.in_(pids)
                ).delete(synchronize_session=False)
                db.query(LabRequest).filter(
                    LabRequest.patient_id.in_(pids)
                ).delete(synchronize_session=False)
                db.query(Appointment).filter(
                    Appointment.patient_id.in_(pids)
                ).delete(synchronize_session=False)
                db.query(Patient).filter(Patient.id.in_(pids)).delete(
                    synchronize_session=False)
            if ids:
                doc_ids = [d.id for d in db.query(Doctor).filter(
                    Doctor.user_id.in_(ids)).all()]
                if doc_ids:
                    db.query(Doctor).filter(Doctor.id.in_(doc_ids)).delete(
                        synchronize_session=False)
                db.query(Receptionist).filter(
                    Receptionist.user_id.in_(ids)
                ).delete(synchronize_session=False)
                db.query(Notification).filter(
                    Notification.user_id.in_(ids)
                ).delete(synchronize_session=False)
                db.query(User).filter(User.id.in_(ids)).delete(
                    synchronize_session=False)
            if dept_id is not None:
                db.query(Department).filter(Department.id == dept_id).delete(
                    synchronize_session=False)
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