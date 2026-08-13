import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    Appointment,
    Bill,
    BillItem,
    Department,
    Doctor,
    MedicalRecord,
    MedicalRecordVersion,
    Patient,
    Payment,
    Receptionist,
    User,
)
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time()))

BASE = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def D(value):
    return Decimal(str(value))


def main():
    db = SessionLocal()
    users = {}
    doctors = {}
    patients = {}
    appointment_ids = []
    bill_ids = []
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
        dept = Department(name=f"Bill Dept {suffix}")
        db.add(dept)
        db.flush()

        for role in ("ADMIN", "DOCTOR_A", "DOCTOR_B", "RECEPTIONIST",
                     "PATIENT_A", "PATIENT_B"):
            u = User(
                email=f"bill.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("BillApiPass!42"),
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
            license_number=f"BILDA{suffix[:6]}",
            consultation_fee=500.00,
        )
        db.add(da)
        db.flush()
        dbb = Doctor(
            user_id=users["DOCTOR_B"].id,
            license_number=f"BILDB{suffix[:6]}",
            consultation_fee=600.00,
        )
        db.add(dbb)
        db.flush()
        doctors["A"] = da
        doctors["B"] = dbb

        pa = Patient(
            user_id=users["PATIENT_A"].id,
            mrn=f"BPA{suffix[:6]}",
            first_name="Alice",
            last_name="Bill",
        )
        pb = Patient(
            user_id=users["PATIENT_B"].id,
            mrn=f"BPB{suffix[:6]}",
            first_name="Bob",
            last_name="Bill",
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

        # ================= CREATE + VALIDATION =================
        r = client.post(
            "/bills",
            json={
                "appointment_id": appt_a_id,
                "due_date": "2026-09-01",
                "items": [{"description": "Consultation",
                           "category": "CONSULTATION", "quantity": 1,
                           "unit_price": "500.00"}],
            },
            headers=rec_h,
        )
        check("receptionist creates bill -> 201", r.status_code == 201)
        bill1 = r.json()
        check("bill_number format INV-%06d", re.fullmatch(r"INV-\d{6}", bill1["bill_number"]) is not None)
        check("default status PENDING", bill1["status"] == "PENDING")
        check("total computed from items", D(bill1["total"]) == D("500.00"))
        check("amount_paid starts at 0", D(bill1["amount_paid"]) == D("0.00"))
        check("remaining equals total", D(bill1["remaining"]) == D("500.00"))
        check("patient_id derived from appointment", bill1["patient_id"] == patients["A"].id)
        bill1_id = bill1["id"]
        bill_ids.append(bill1_id)

        # client-supplied patient_id ignored
        r = client.post(
            "/bills",
            json={
                "appointment_id": appt_b_id,
                "items": [{"description": "Consultation",
                           "category": "CONSULTATION", "quantity": 1,
                           "unit_price": "600.00"}],
                "patient_id": 999999,
            },
            headers=admin_h,
        )
        check("admin creates bill -> 201", r.status_code == 201)
        bill2 = r.json()
        check("client-supplied patient_id ignored (derived)",
              bill2["patient_id"] == patients["B"].id)
        bill2_id = bill2["id"]
        bill_ids.append(bill2_id)
        check("bill_number unique across creates",
              bill1["bill_number"] != bill2["bill_number"])

        # unauthorized creates
        r = client.post("/bills", json={"appointment_id": appt_a_id,
                                        "items": [{"description": "X", "category": "SERVICE",
                                                   "quantity": 1, "unit_price": "1.00"}]},
                        headers=doca_h)
        check("doctor creates bill -> 403", r.status_code == 403)
        r = client.post("/bills", json={"appointment_id": appt_a_id,
                                        "items": [{"description": "X", "category": "SERVICE",
                                                   "quantity": 1, "unit_price": "1.00"}]},
                        headers=pata_h)
        check("patient creates bill -> 403", r.status_code == 403)

        # duplicate appointment
        r = client.post("/bills", json={"appointment_id": appt_a_id,
                                        "items": [{"description": "X", "category": "SERVICE",
                                                   "quantity": 1, "unit_price": "1.00"}]},
                        headers=rec_h)
        check("second bill same appointment -> 409", r.status_code == 409)

        # validation
        r = client.post("/bills", json={"appointment_id": appt_a_id,
                                        "items": [{"description": "X", "category": "CONSULTATION",
                                                   "quantity": 0, "unit_price": "1.00"}]},
                        headers=rec_h)
        check("quantity 0 -> 422", r.status_code == 422)
        r = client.post("/bills", json={"appointment_id": appt_a_id,
                                        "items": [{"description": "X", "category": "CONSULTATION",
                                                   "quantity": 1, "unit_price": "-1.00"}]},
                        headers=rec_h)
        check("negative unit_price -> 422", r.status_code == 422)
        r = client.post("/bills", json={"appointment_id": appt_a_id,
                                        "items": [{"description": "X", "category": "FOO",
                                                   "quantity": 1, "unit_price": "1.00"}]},
                        headers=rec_h)
        check("invalid category -> 422", r.status_code == 422)
        r = client.post("/bills", json={"appointment_id": appt_a_id, "items": []},
                        headers=rec_h)
        check("empty items -> 422", r.status_code == 422)
        r = client.post("/bills", json={"appointment_id": 99999999,
                                        "items": [{"description": "X", "category": "SERVICE",
                                                   "quantity": 1, "unit_price": "1.00"}]},
                        headers=rec_h)
        check("unknown appointment -> 404", r.status_code == 404)

        # ================= ADD ITEMS =================
        r = client.post(
            "/bills/%d/items" % bill1_id,
            json={"description": "CBC", "category": "LAB_TEST",
                  "quantity": 1, "unit_price": "300.00"},
            headers=rec_h,
        )
        check("add item -> 200", r.status_code == 200)
        check("total recomputed after item add", D(r.json()["total"]) == D("800.00"))
        check("amount_paid unchanged", D(r.json()["amount_paid"]) == D("0.00"))
        check("status still PENDING", r.json()["status"] == "PENDING")
        r = client.post("/bills/%d/items" % bill1_id,
                        json={"description": "X", "category": "SERVICE",
                              "quantity": 1, "unit_price": "5.00"},
                        headers=doca_h)
        check("doctor adds item -> 403", r.status_code == 403)
        r = client.get("/bills/%d" % bill1_id)
        check("get bill without token -> 401", r.status_code == 401)

        # ================= PAYMENTS =================
        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "0.00", "method": "CASH"}, headers=rec_h)
        check("payment amount 0 -> 422", r.status_code == 422)
        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "-5.00", "method": "CASH"}, headers=rec_h)
        check("negative payment -> 422", r.status_code == 422)
        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "10.00", "method": "BITCOIN"}, headers=rec_h)
        check("invalid method -> 422", r.status_code == 422)

        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "500.00", "method": "CASH"}, headers=rec_h)
        check("receptionist records payment -> 200", r.status_code == 200)
        body = r.json()
        check("first payment -> PARTIALLY_PAID", body["status"] == "PARTIALLY_PAID")
        check("amount_paid accumulates", D(body["amount_paid"]) == D("500.00"))
        check("remaining reduced", D(body["remaining"]) == D("300.00"))
        check("payment recorded_by = receptionist user",
              body["payments"][0]["recorded_by"] == users["RECEPTIONIST"].id)

        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "100.00", "method": "CARD",
                              "transaction_reference": "TXN-1"}, headers=rec_h)
        check("installment with reference -> 200", r.status_code == 200)
        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "50.00", "method": "CARD",
                              "transaction_reference": "TXN-1"}, headers=rec_h)
        check("duplicate transaction_reference -> 409", r.status_code == 409)
        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "500.00", "method": "CASH"}, headers=rec_h)
        check("overpayment -> 422", r.status_code == 422)
        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "200.00", "method": "CASH"}, headers=rec_h)
        body = r.json()
        check("payment to settle -> PAID", r.status_code == 200 and body["status"] == "PAID")
        check("amount_paid equals total", D(body["amount_paid"]) == D("800.00"))
        check("remaining zero", D(body["remaining"]) == D("0.00"))

        r = client.post("/bills/%d/payments" % bill1_id,
                        json={"amount": "10.00", "method": "CASH"}, headers=rec_h)
        check("payment on PAID bill -> 422", r.status_code == 422)
        r = client.post("/bills/%d/items" % bill1_id,
                        json={"description": "X", "category": "SERVICE",
                              "quantity": 1, "unit_price": "1.00"}, headers=rec_h)
        check("add item on PAID bill -> 422", r.status_code == 422)

        r = client.get("/bills/%d" % bill1_id, headers=rec_h)
        check("receptionist cannot view bill detail -> 403", r.status_code == 403)
        r = client.get("/bills", headers=rec_h)
        check("receptionist cannot list bills -> 403", r.status_code == 403)

        # unauthorized payment actors
        r = client.post("/bills/%d/payments" % bill2_id,
                        json={"amount": "10.00", "method": "CASH"}, headers=doca_h)
        check("doctor records payment -> 403", r.status_code == 403)
        r = client.post("/bills/%d/payments" % bill2_id,
                        json={"amount": "10.00", "method": "CASH"}, headers=pata_h)
        check("patient records payment -> 403", r.status_code == 403)

        # ================= STATUS TRANSITIONS =================
        r = client.patch("/bills/%d" % bill2_id, json={"status": "OVERDUE"}, headers=admin_h)
        check("admin sets OVERDUE -> 200", r.status_code == 200 and r.json()["status"] == "OVERDUE")
        r = client.patch("/bills/%d" % bill2_id, json={"status": "OVERDUE"}, headers=rec_h)
        check("receptionist sets status -> 403", r.status_code == 403)
        r = client.patch("/bills/%d" % bill1_id, json={"status": "OVERDUE"}, headers=admin_h)
        check("OVERDUE on PAID bill -> 422", r.status_code == 422)
        r = client.patch("/bills/%d" % bill2_id, json={"status": "REFUNDED"}, headers=admin_h)
        check("admin sets REFUNDED -> 200", r.status_code == 200 and r.json()["status"] == "REFUNDED")
        r = client.post("/bills/%d/items" % bill2_id,
                        json={"description": "X", "category": "SERVICE",
                              "quantity": 1, "unit_price": "1.00"}, headers=rec_h)
        check("add item on REFUNDED bill -> 422", r.status_code == 422)
        r = client.post("/bills/%d/payments" % bill2_id,
                        json={"amount": "10.00", "method": "CASH"}, headers=admin_h)
        check("payment on REFUNDED bill -> 422", r.status_code == 422)
        r = client.patch("/bills/%d" % bill2_id, json={"status": "OVERDUE"}, headers=admin_h)
        check("transition after REFUNDED -> 422", r.status_code == 422)
        r = client.patch("/bills/%d" % bill2_id, json={"status": "GIVEAWAY"}, headers=admin_h)
        check("arbitrary status -> 422", r.status_code == 422)

        # ================= IDOR / OWNERSHIP =================
        r = client.get("/bills/%d" % bill1_id, headers=patb_h)
        check("patient B reads patient A bill -> 404", r.status_code == 404)
        r = client.get("/bills/%d" % bill1_id, headers=docb_h)
        check("doctor B reads doctor A consult bill -> 404", r.status_code == 404)
        r = client.get("/bills/%d" % bill2_id, headers=pata_h)
        check("patient A reads patient B bill -> 404", r.status_code == 404)
        r = client.get("/bills/%d" % bill2_id, headers=doca_h)
        check("doctor A reads doctor B consult bill -> 404", r.status_code == 404)
        r = client.get("/bills/%d" % bill1_id, headers=pata_h)
        check("patient reads own bill -> 200", r.status_code == 200)
        r = client.get("/bills/%d" % bill1_id, headers=doca_h)
        check("doctor reads own consult bill -> 200", r.status_code == 200)
        r = client.get("/bills/%d" % bill2_id, headers=patb_h)
        check("patient B reads own bill -> 200", r.status_code == 200)
        r = client.get("/bills/%d" % bill2_id, headers=docb_h)
        check("doctor B reads own consult bill -> 200", r.status_code == 200)
        r = client.get("/bills/%d" % bill1_id, headers=admin_h)
        check("admin reads any bill -> 200", r.status_code == 200)
        r = client.get("/bills/%d" % 99999999, headers=admin_h)
        check("unknown bill id -> 404", r.status_code == 404)

        # ================= LIST SCOPING =================
        r = client.get("/bills", headers=pata_h)
        check("patient list only own bills",
              r.status_code == 200 and all(b["patient_id"] == patients["A"].id for b in r.json()))
        r = client.get("/bills", headers=docb_h)
        check("doctor B list only own consultation bills",
              r.status_code == 200 and all(b["id"] == bill2_id for b in r.json()))
        r = client.get("/bills", headers=admin_h)
        check("admin list includes both bills", r.status_code == 200 and len(r.json()) >= 2)

        # ================= DATA INTEGRITY / LEAKS =================
        r = client.get("/bills/%d" % bill1_id, headers=admin_h)
        check("no password_hash in detail", "password_hash" not in r.text)
        r = client.get("/bills", headers=admin_h)
        check("no password_hash in list", "password_hash" not in r.text)

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            if bill_ids:
                db.query(Payment).filter(Payment.bill_id.in_(bill_ids)).delete(
                    synchronize_session=False
                )
                db.query(BillItem).filter(BillItem.bill_id.in_(bill_ids)).delete(
                    synchronize_session=False
                )
                db.query(Bill).filter(Bill.id.in_(bill_ids)).delete(
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
            for mrn in ("BPA", "BPB"):
                db.query(Patient).filter(
                    Patient.mrn.like(f"{mrn}%")
                ).delete(synchronize_session=False)
            for lic in ("BILDA", "BILDB"):
                db.query(Doctor).filter(
                    Doctor.license_number.like(f"{lic}%")
                ).delete(synchronize_session=False)
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id).filter(User.email.like("bill.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("bill.%@mediflow.local")
            ).delete(synchronize_session=False)
            db.query(Department).filter(Department.name.like(f"Bill Dept {suffix}%")).delete(
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