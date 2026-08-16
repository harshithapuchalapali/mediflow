import re
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    Appointment,
    AuditLog,
    Bill,
    BillItem,
    Department,
    Doctor,
    HospitalSettings,
    MedicalRecord,
    MedicalRecordVersion,
    Notification,
    Patient,
    Payment,
    Prescription,
    PrescriptionItem,
    Receptionist,
    User,
)
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time()))

BASE = datetime(2026, 12, 5, 9, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def pdf_text(data):
    text = []
    for m in re.finditer(rb"\(((?:[^()\\]|\\.)*)\)", data):
        raw = m.group(1)
        raw = re.sub(
            rb"\\[0-7]{3}", lambda mm: bytes([int(mm.group(0)[1:], 8)]), raw
        )
        raw = raw.replace(b"\\(", b"(").replace(b"\\)", b")")
        text.append(raw.decode("latin-1", errors="replace"))
    return " ".join(text)


def main():
    db = SessionLocal()
    users = {}
    doctors = {}
    patients = {}
    appointment_ids = []
    bill_ids = []
    prescription_ids = []
    created_settings = False
    hospital_name = None
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
        dept = Department(name=f"Pdf Dept {suffix}")
        db.add(dept)
        db.flush()

        for role in ("ADMIN", "DOCTOR_A", "DOCTOR_B", "RECEPTIONIST",
                     "PATIENT_A", "PATIENT_B"):
            u = User(
                email=f"pdf.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("PdfApiPass!42"),
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
            license_number=f"PDFDA{suffix[:6]}",
            consultation_fee=500.00,
        )
        db.add(da)
        db.flush()
        doctors["A"] = da
        dbb = Doctor(
            user_id=users["DOCTOR_B"].id,
            license_number=f"PDFDB{suffix[:6]}",
            consultation_fee=600.00,
        )
        db.add(dbb)
        db.flush()
        doctors["B"] = dbb

        pa = Patient(
            user_id=users["PATIENT_A"].id,
            mrn=f"PDFPA{suffix[:6]}",
            first_name="Alice",
            last_name="Pdf",
        )
        pb = Patient(
            user_id=users["PATIENT_B"].id,
            mrn=f"PDFPB{suffix[:6]}",
            first_name="Bob",
            last_name="Pdf",
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

        # ---- Settings (only to exercise the hospital-header path) ----
        r = client.get("/admin/hospital-settings", headers=admin_h)
        if r.status_code != 200:
            r = client.post(
                "/admin/hospital-settings",
                json={
                    "hospital_name": f"Pdf Test Hospital {suffix}",
                    "timezone": "Asia/Kolkata",
                },
                headers=admin_h,
            )
            if r.status_code in (200, 201):
                created_settings = True
                hospital_name = r.json()["hospital_name"]
            elif r.status_code == 409:
                r = client.get("/admin/hospital-settings", headers=admin_h)
                hospital_name = r.json().get("hospital_name")
        else:
            hospital_name = r.json()["hospital_name"]
        check("setup: hospital settings available for header",
              hospital_name is not None)

        # ---- Seed chain: appointment -> medical record -> prescription ----
        r = client.post(
            "/appointments",
            json={
                "patient_id": pa.id,
                "doctor_id": da.id,
                "department_id": dept.id,
                "date_time": iso(BASE),
                "duration_minutes": 30,
                "priority": "NORMAL",
                "appointment_type": "INITIAL_CONSULTATION",
            },
            headers=rec_h,
        )
        check("setup: appointment (201)", r.status_code == 201)
        appt_a_id = r.json()["id"]
        appointment_ids.append(appt_a_id)

        r = client.post(
            "/medical-records",
            json={"appointment_id": appt_a_id, "diagnosis": "PDF test case"},
            headers=doca_h,
        )
        check("setup: medical record (201)", r.status_code == 201)
        record_a_id = r.json()["id"]

        r = client.post(
            "/prescriptions",
            json={
                "medical_record_id": record_a_id,
                "items": [
                    {
                        "medicine_name": "Paracetamol",
                        "dosage": "500 mg",
                        "frequency": "Twice a day",
                        "duration_in_days": 5,
                    }
                ],
            },
            headers=doca_h,
        )
        check("setup: prescription (201)", r.status_code == 201)
        rx_id = r.json()["prescription"]["id"]
        prescription_ids.append(rx_id)

        # ---- Seed chain: bill + payment ----
        r = client.post(
            "/bills",
            json={
                "appointment_id": appt_a_id,
                "due_date": "2026-12-20",
                "items": [
                    {
                        "description": "Consultation",
                        "category": "CONSULTATION",
                        "quantity": 1,
                        "unit_price": "500.00",
                    }
                ],
            },
            headers=rec_h,
        )
        check("setup: bill (201)", r.status_code == 201)
        bill = r.json()
        bill_id = bill["id"]
        bill_number = bill["bill_number"]
        bill_ids.append(bill_id)

        r = client.post(
            "/bills/%d/payments" % bill_id,
            json={
                "amount": "200.00",
                "method": "CASH",
                "transaction_reference": "TXN-PDF-1",
            },
            headers=rec_h,
        )
        check("setup: payment (200)", r.status_code == 200)

        # ================= BILL PDF =================
        r = client.get(f"/bills/{bill_id}/pdf", headers=admin_h)
        check("admin bill pdf -> 200",
              r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"))
        check("admin bill pdf is pdf bytes", r.status_code == 200 and r.content.startswith(b"%PDF"))
        check("admin bill pdf filename header",
              "attachment; filename=\"%s.pdf\"" % bill_number in r.headers.get("content-disposition", ""))
        bill_body = pdf_text(r.content) if r.status_code == 200 else ""
        check("bill pdf has bill number", bill_number in bill_body)
        check("bill pdf has patient name", "Alice" in bill_body)
        check("bill pdf has item description", "Consultation" in bill_body)
        check("bill pdf has total header", "Total Amount" in bill_body)
        check("bill pdf has computed total", "500.00" in bill_body)
        check("bill pdf has balance due", "Balance Due" in bill_body)
        check("bill pdf has payment details", all(x in bill_body for x in ("TXN-PDF-1", "CASH", "200.00")))
        if hospital_name:
            check("bill pdf has hospital name header", hospital_name in bill_body)

        r = client.get(f"/bills/{bill_id}/pdf", headers=pata_h)
        check("patient own bill pdf -> 200", r.status_code == 200)
        r = client.get(f"/bills/{bill_id}/pdf", headers=patb_h)
        check("other patient bill pdf -> 404", r.status_code == 404)
        r = client.get(f"/bills/{bill_id}/pdf", headers=doca_h)
        check("treating doctor bill pdf -> 200", r.status_code == 200)
        r = client.get(f"/bills/{bill_id}/pdf", headers=docb_h)
        check("unrelated doctor bill pdf -> 404", r.status_code == 404)
        r = client.get(f"/bills/{bill_id}/pdf", headers=rec_h)
        check("receptionist bill pdf -> 403", r.status_code == 403)
        r = client.get(f"/bills/{bill_id}/pdf")
        check("bill pdf without token -> 401", r.status_code == 401)
        r = client.get("/bills/99999999/pdf", headers=admin_h)
        check("unknown bill pdf -> 404", r.status_code == 404)

        # ================= PRESCRIPTION PDF =================
        r = client.get(f"/prescriptions/{rx_id}/pdf", headers=admin_h)
        check("admin prescription pdf -> 200",
              r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"))
        check("admin prescription pdf is pdf bytes",
              r.status_code == 200 and r.content.startswith(b"%PDF"))
        check("admin prescription pdf filename header",
              "attachment; filename=\"prescription-%d.pdf\"" % rx_id in r.headers.get("content-disposition", ""))
        rx_body = pdf_text(r.content) if r.status_code == 200 else ""
        check("prescription pdf has title", "Prescription" in rx_body)
        check("prescription pdf has patient name", "Alice" in rx_body)
        check("prescription pdf has medicine", "paracetamol" in rx_body)
        check("prescription pdf has dosage", "500 mg" in rx_body)
        check("prescription pdf has frequency", "Twice a day" in rx_body)
        check("prescription pdf has duration", "5 day(s)" in rx_body)
        check("prescription pdf has doctor section", "Doctor" in rx_body)
        if hospital_name:
            check("prescription pdf has hospital name header", hospital_name in rx_body)

        r = client.get(f"/prescriptions/{rx_id}/pdf", headers=pata_h)
        check("patient own prescription pdf -> 200", r.status_code == 200)
        r = client.get(f"/prescriptions/{rx_id}/pdf", headers=patb_h)
        check("other patient prescription pdf -> 404", r.status_code == 404)
        r = client.get(f"/prescriptions/{rx_id}/pdf", headers=doca_h)
        check("prescribing doctor prescription pdf -> 200", r.status_code == 200)
        r = client.get(f"/prescriptions/{rx_id}/pdf", headers=docb_h)
        check("unrelated doctor prescription pdf -> 404", r.status_code == 404)
        r = client.get(f"/prescriptions/{rx_id}/pdf", headers=rec_h)
        check("receptionist prescription pdf -> 403", r.status_code == 403)
        r = client.get(f"/prescriptions/{rx_id}/pdf")
        check("prescription pdf without token -> 401", r.status_code == 401)
        r = client.get("/prescriptions/99999999/pdf", headers=admin_h)
        check("unknown prescription pdf -> 404", r.status_code == 404)

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            if bill_ids:
                db.query(Payment).filter(
                    Payment.bill_id.in_(bill_ids)
                ).delete(synchronize_session=False)
                db.query(BillItem).filter(
                    BillItem.bill_id.in_(bill_ids)
                ).delete(synchronize_session=False)
                db.query(Bill).filter(
                    Bill.id.in_(bill_ids)
                ).delete(synchronize_session=False)
            if prescription_ids:
                db.query(PrescriptionItem).filter(
                    PrescriptionItem.prescription_id.in_(prescription_ids)
                ).delete(synchronize_session=False)
                db.query(Prescription).filter(
                    Prescription.id.in_(prescription_ids)
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
            for mrn in ("PDFPA", "PDFPB"):
                db.query(Patient).filter(
                    Patient.mrn.like(f"{mrn}%")
                ).delete(synchronize_session=False)
            for lic in ("PDFDA", "PDFDB"):
                db.query(Doctor).filter(
                    Doctor.license_number.like(f"{lic}%")
                ).delete(synchronize_session=False)
            temp_user_ids = db.query(User.id).filter(
                User.email.like("pdf.%@mediflow.local")
            )
            db.query(AuditLog).filter(
                AuditLog.user_id.in_(temp_user_ids)
            ).delete(synchronize_session=False)
            db.query(Notification).filter(
                Notification.user_id.in_(temp_user_ids)
            ).delete(synchronize_session=False)
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id).filter(User.email.like("pdf.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("pdf.%@mediflow.local")
            ).delete(synchronize_session=False)
            db.query(Department).filter(Department.name.like(f"Pdf Dept {suffix}%")).delete(
                synchronize_session=False
            )
            if created_settings:
                db.query(HospitalSettings).filter(
                    HospitalSettings.id == 1
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