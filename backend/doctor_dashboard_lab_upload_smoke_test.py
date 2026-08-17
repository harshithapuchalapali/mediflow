import os

# Keep the oversize-file check cheap: configure the upload limit before the
# app (and thereby report_files.py) is imported. setdefault lets a real
# environment variable still override this.
os.environ.setdefault("LAB_REPORT_MAX_SIZE_MB", "1")

import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.lab_requests import report_files
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
    Prescription,
    PrescriptionItem,
    Receptionist,
    User,
)
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time()))

IST = ZoneInfo("Asia/Kolkata")
today_ist = datetime.now(timezone.utc).astimezone(IST).date()


def iso(dt):
    return dt.isoformat()


def ist_utc(day, hour, minute=0):
    """UTC datetime for an IST wall-clock time on ``day``."""
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)
    return local.astimezone(timezone.utc)


def pdf_bytes(tag):
    return b"%PDF-1.4\n" + tag + b"\n%%EOF\n"


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

    def upload_report(request_id, filename, data, headers):
        return client.post(
            f"/lab-requests/{request_id}/report",
            files={"file": (filename, data, "application/octet-stream")},
            headers=headers or {},
        )

    try:
        dept = Department(name=f"Phase3 Dept {suffix}")
        db.add(dept)
        db.flush()

        for role in (
            "ADMIN",
            "DOCTOR_A",
            "DOCTOR_B",
            "DOCTOR_C",
            "RECEPTIONIST",
            "PATIENT_A",
            "PATIENT_B",
        ):
            u = User(
                email=f"p3.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("Phase3Pass!42"),
                role="ADMIN" if role == "ADMIN"
                else ("DOCTOR" if role.startswith("DOCTOR")
                      else ("RECEPTIONIST" if role == "RECEPTIONIST" else "PATIENT")),
                status="ACTIVE" if role != "DOCTOR_C" else "DEACTIVATED",
                deactivated_at=None if role != "DOCTOR_C"
                else datetime.now(timezone.utc),
            )
            db.add(u)
            db.flush()
            users[role] = u

        da = Doctor(
            user_id=users["DOCTOR_A"].id, license_number=f"P3DA{suffix[:6]}"
        )
        dbb = Doctor(
            user_id=users["DOCTOR_B"].id, license_number=f"P3DB{suffix[:6]}"
        )
        db.add_all([da, dbb])
        db.flush()
        doctors["A"] = da
        doctors["B"] = dbb

        pa = Patient(
            user_id=users["PATIENT_A"].id,
            mrn=f"P3PA{suffix[:6]}",
            first_name="Alice",
            last_name="Phase3",
        )
        pb = Patient(
            user_id=users["PATIENT_B"].id,
            mrn=f"P3PB{suffix[:6]}",
            first_name="Bob",
            last_name="Phase3",
        )
        patients["A"] = pa
        patients["B"] = pb

        receptionist = Receptionist(user_id=users["RECEPTIONIST"].id)
        db.add_all([pa, pb, receptionist])
        db.commit()
        for obj in (da, dbb, pa, pb, receptionist, dept):
            db.refresh(obj)

        admin_h = token_for("ADMIN")
        doca_h = token_for("DOCTOR_A")
        docb_h = token_for("DOCTOR_B")
        docc_h = token_for("DOCTOR_C")
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

        yesterday = today_ist - timedelta(days=1)
        day2 = today_ist - timedelta(days=2)
        day3 = today_ist - timedelta(days=3)

        # ---- Dashboard fixture: doctor A = 5 appointments across 4 IST days ----
        a1 = create_appointment(doctors["A"], patients["A"], ist_utc(today_ist, 10, 0))
        a2 = create_appointment(doctors["A"], patients["A"], ist_utc(today_ist, 11, 0))
        a3 = create_appointment(doctors["A"], patients["B"], ist_utc(yesterday, 10, 0))
        a4 = create_appointment(doctors["A"], patients["A"], ist_utc(day3, 10, 0))
        a5 = create_appointment(doctors["A"], patients["B"], ist_utc(day2, 10, 0))
        # Doctor B = 2 appointments (isolation fixture)
        b1 = create_appointment(doctors["B"], patients["B"], ist_utc(today_ist, 12, 0))
        b2 = create_appointment(doctors["B"], patients["A"], ist_utc(yesterday, 12, 0))
        for label, r in (("a1", a1), ("a2", a2), ("a3", a3), ("a4", a4),
                         ("a5", a5), ("b1", b1), ("b2", b2)):
            check(f"setup: appointment {label} (201)", r.status_code == 201)
        a1_id, a2_id, a3_id, a4_id, a5_id = (r.json()["id"] for r in (a1, a2, a3, a4, a5))
        b1_id = b1.json()["id"]

        # ---- Statuses via admin (PENDING -> ... ) ----
        for appt_id, path in (
            (a1_id, ["CONFIRMED", "CHECKED_IN", "COMPLETED"]),
            (a2_id, ["CONFIRMED"]),
            (a3_id, ["CANCELLED"]),
            (a4_id, ["CONFIRMED", "CHECKED_IN", "NO_SHOW"]),
        ):
            for target in path:
                r = client.patch(
                    f"/appointments/{appt_id}",
                    json={"status": target},
                    headers=admin_h,
                )
                check(f"setup: appt {appt_id} -> {target} (200)", r.status_code == 200)

        # ---- Consultation fixture: one medical record + one prescription ----
        r = client.post(
            "/medical-records",
            json={"appointment_id": a1_id, "diagnosis": "Phase3 dashboard test"},
            headers=doca_h,
        )
        check("setup: medical record (201)", r.status_code == 201)
        record_id = r.json()["id"]

        r = client.post(
            "/prescriptions",
            json={
                "medical_record_id": record_id,
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

        # ================= DOCTOR DASHBOARD =================
        r = client.get("/doctor/dashboard")
        check("dashboard without token -> 401", r.status_code == 401)
        r = client.get("/doctor/dashboard", headers=pata_h)
        check("dashboard as patient -> 403", r.status_code == 403)
        r = client.get("/doctor/dashboard", headers=rec_h)
        check("dashboard as receptionist -> 403", r.status_code == 403)
        r = client.get("/doctor/dashboard", headers=docc_h)
        check("dashboard as deactivated doctor -> 401", r.status_code == 401)

        r = client.get("/doctor/dashboard", headers=doca_h)
        body = r.json()
        check("doctor A dashboard -> 200", r.status_code == 200)
        check("dashboard scoped to doctor A id", body["doctor_id"] == doctors["A"].id)
        check("dashboard total appointments = 5", body["appointments"]["total"] == 5)
        check("dashboard today appointments = 2", body["appointments"]["today"] == 2)
        check("dashboard completed = 1", body["appointments"]["completed"] == 1)
        check("dashboard confirmed = 1", body["appointments"]["confirmed"] == 1)
        check("dashboard cancelled = 1", body["appointments"]["cancelled"] == 1)
        check("dashboard no_show = 1", body["appointments"]["no_show"] == 1)
        check("dashboard unique patients = 2", body["patients"]["total"] == 2)
        check("dashboard unique patients today = 1", body["patients"]["today"] == 1)
        check("dashboard total records = 1", body["consultations"]["total_records"] == 1)
        check("dashboard records today = 1", body["consultations"]["records_today"] == 1)
        check("dashboard total prescriptions = 1",
              body["consultations"]["total_prescriptions"] == 1)
        check("dashboard prescriptions today = 1",
              body["consultations"]["prescriptions_today"] == 1)
        check("dashboard reports date 'today'", body["today"] == today_ist.isoformat())

        # Doctor B cannot see doctor A's data (derived identity isolation).
        r = client.get("/doctor/dashboard", headers=docb_h)
        body_b = r.json()
        check("doctor B dashboard scoped to B id", body_b["doctor_id"] == doctors["B"].id)
        check("doctor B total appointments = 2", body_b["appointments"]["total"] == 2)

        # ---- Date-range statistics ----
        r = client.get(
            "/doctor/dashboard",
            params={"start_date": day3.isoformat(), "end_date": today_ist.isoformat()},
            headers=doca_h,
        )
        body = r.json()
        by_day = {p["date"]: p["total"] for p in body["appointment_by_day"]}
        check("range request -> 200", r.status_code == 200)
        check("range date_from/date_to echoed",
              body["date_from"] == day3.isoformat() and body["date_to"] == today_ist.isoformat())
        check("by_day has 4 points", len(by_day) == 4)
        check("by_day counts [1,1,1,2]",
              by_day == {
                  day3.isoformat(): 1,
                  day2.isoformat(): 1,
                  yesterday.isoformat(): 1,
                  today_ist.isoformat(): 2,
              })
        check("by_day totals to 5", sum(by_day.values()) == 5)

        # ---- Date boundary handling: single-day window ----
        r = client.get(
            "/doctor/dashboard",
            params={"start_date": today_ist.isoformat(), "end_date": today_ist.isoformat()},
            headers=doca_h,
        )
        body = r.json()
        check("single-day range -> 200", r.status_code == 200)
        check("single-day by_day = today:2",
              body["appointment_by_day"] ==
              [{"date": today_ist.isoformat(), "total": 2}])

        # ---- Invalid date range ----
        r = client.get(
            "/doctor/dashboard",
            params={"start_date": today_ist.isoformat(), "end_date": yesterday.isoformat()},
            headers=doca_h,
        )
        check("invalid date range -> 422", r.status_code == 422)

        # ================= LAB REPORT UPLOAD =================
        r = client.post(
            "/lab-requests",
            json={"appointment_id": a1_id, "test_name": "Complete Blood Count"},
            headers=doca_h,
        )
        check("setup: lab request lab1 (201)", r.status_code == 201)
        lab1 = r.json()["id"]
        lab_ids.append(lab1)

        r = client.post(
            "/lab-requests",
            json={"appointment_id": a1_id, "test_name": "PNG Report"},
            headers=doca_h,
        )
        lab2 = r.json()["id"]
        lab_ids.append(lab2)

        r = client.post(
            "/lab-requests",
            json={"appointment_id": a1_id, "test_name": "Traversal Check"},
            headers=doca_h,
        )
        lab3 = r.json()["id"]
        lab_ids.append(lab3)

        r = client.post(
            "/lab-requests",
            json={"appointment_id": a1_id, "test_name": "No report attached"},
            headers=doca_h,
        )
        lab4 = r.json()["id"]
        lab_ids.append(lab4)

        r = upload_report(lab1, "report.pdf", pdf_bytes(b"first"), None)
        check("upload without token -> 401", r.status_code == 401)

        r = upload_report(lab1, "report.pdf", pdf_bytes(b"x"), pata_h)
        check("patient upload -> 403", r.status_code == 403)

        r = upload_report(lab1, "report.pdf", pdf_bytes(b"x"), rec_h)
        check("receptionist upload -> 403", r.status_code == 403)

        r = upload_report(99999999, "report.pdf", pdf_bytes(b"x"), doca_h)
        check("unknown lab request upload -> 404", r.status_code == 404)

        r = upload_report(lab1, "report.pdf", pdf_bytes(b"x"), docb_h)
        check("other doctor upload -> 404", r.status_code == 404)

        r = upload_report(lab1, "report.pdf", pdf_bytes(b"first"), doca_h)
        check("valid PDF upload -> 200", r.status_code == 200)
        check("upload response has_report", r.json().get("has_report") is True)
        check("upload response hides report_file_path", "report_file_path" not in r.text)

        # Patient cannot download a non-verified report yet.
        r = client.get(f"/lab-requests/{lab1}/report", headers=pata_h)
        check("patient download before verify -> 404", r.status_code == 404)

        # ---- Replacement: second PDF supersedes the first ----
        lab1_row_path1 = db.get(LabRequest, lab1).report_file_path
        r = upload_report(lab1, "report-v2.pdf", pdf_bytes(b"second"), doca_h)
        check("replacement PDF upload -> 200", r.status_code == 200)
        lab1_row_path2 = db.get(LabRequest, lab1).report_file_path
        check("replacement changed stored path",
              lab1_row_path2 is not None and lab1_row_path2 != lab1_row_path1)
        check("replacement removed old file",
              report_files.resolve_report_path(lab1_row_path1) is None)
        second_pdf = pdf_bytes(b"second")

        # ---- Admin may upload too (existing admin clinical access rules) ----
        r = upload_report(lab1, "report-admin.pdf", pdf_bytes(b"admin"), admin_h)
        check("admin upload -> 200", r.status_code == 200)
        lab1_row_path3 = db.get(LabRequest, lab1).report_file_path
        check("admin replacement removed predecessor",
              report_files.resolve_report_path(lab1_row_path2) is None)
        final_pdf = pdf_bytes(b"admin")

        # ---- Invalid files -> 422 ----
        r = upload_report(lab2, "empty.pdf", b"", doca_h)
        check("empty file rejected -> 422", r.status_code == 422)

        r = upload_report(lab2, "notes.txt", b"hello world", doca_h)
        check("unsupported text file rejected -> 422", r.status_code == 422)

        r = upload_report(lab2, "tool.exe", b"MZ\x90\x00\x03\x00", doca_h)
        check("executable header rejected -> 422", r.status_code == 422)

        r = upload_report(lab2, "fake.pdf", b"PK\x03\x04 fake zip", doca_h)
        check("zip named .pdf rejected (content authoritative) -> 422",
              r.status_code == 422)

        big = b"a" * (report_files.MAX_REPORT_BYTES + 1)
        r = upload_report(lab2, "big.pdf", big, doca_h)
        check("oversized file rejected -> 422", r.status_code == 422)

        # ---- Authorized image uploads (PNG + JPG) ----
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 24
        r = upload_report(lab2, "report.png", png, doca_h)
        check("valid PNG upload -> 200", r.status_code == 200)
        r = upload_report(lab2, "report.jpg", jpg, doca_h)
        check("valid JPEG upload -> 200", r.status_code == 200)

        # ---- Path-traversal filename handled safely ----
        r = upload_report(lab3, "../../escape/report.pdf", pdf_bytes(b"trav"), doca_h)
        check("path-traversal filename upload -> 200", r.status_code == 200)
        stored3 = db.get(LabRequest, lab3).report_file_path
        prefix = str(report_files.UPLOAD_REL)
        check("stored path is relative/controlled",
              stored3 is not None
              and not os.path.isabs(stored3)
              and "../" not in stored3.replace("\\", "/"))
        check("stored path lives under upload dir", stored3.startswith(prefix + "/"))
        check("stored filename is server-generated",
              re.fullmatch(r"[0-9a-f]{32}\.pdf", os.path.basename(stored3)) is not None)
        check("resolved path exists on disk",
              report_files.resolve_report_path(stored3) is not None)

        # Lab detail does not leak paths and reports has_report.
        r = client.get(f"/lab-requests/{lab1}", headers=admin_h)
        check("lab detail has_report true", r.json().get("has_report") is True)
        check("lab detail hides filesystem paths",
              "uploads" not in r.text and "report_file_path" not in r.text)
        r = client.get(f"/lab-requests/{lab4}", headers=admin_h)
        check("lab detail (no report) has_report false",
              r.json().get("has_report") is False)

        # ================= LAB REPORT DOWNLOAD =================
        r = client.get(f"/lab-requests/{lab1}/report")
        check("download without token -> 401", r.status_code == 401)

        r = client.get(f"/lab-requests/{lab1}/report", headers=rec_h)
        check("receptionist download -> 403", r.status_code == 403)

        r = client.get(f"/lab-requests/{lab1}/report", headers=docb_h)
        check("other doctor download -> 404", r.status_code == 404)

        r = client.get(f"/lab-requests/{lab1}/report", headers=patb_h)
        check("other patient download -> 404", r.status_code == 404)

        r = client.get(f"/lab-requests/{lab1}/report", headers=doca_h)
        check("doctor download own report -> 200", r.status_code == 200)
        check("download content type pdf",
              r.headers.get("content-type", "").split(";")[0].strip() == "application/pdf")
        check("download content matches file",
              r.content == final_pdf)
        check("download content-disposition attachment",
              "attachment" in r.headers.get("content-disposition", "")
              and f'filename="lab-report-{lab1}.pdf"' in r.headers.get("content-disposition", ""))

        r = client.get(f"/lab-requests/{lab1}/report", headers=admin_h)
        check("admin download -> 200", r.status_code == 200 and r.content == final_pdf)

        # Verify lab1 so the OWN patient can download it.
        for target, payload in (
            ("IN_PROGRESS", {"target_status": "IN_PROGRESS"}),
            ("RESULT_READY", {"target_status": "RESULT_READY",
                              "result_details": "Hb 12.8, WBC 6.1K"}),
            ("VERIFIED", {"target_status": "VERIFIED"}),
        ):
            r = client.patch(
                f"/lab-requests/{lab1}", json=payload, headers=doca_h
            )
            check(f"setup: lab1 -> {target}", r.status_code == 200)

        r = client.get(f"/lab-requests/{lab1}/report", headers=pata_h)
        check("own patient download verified report -> 200",
              r.status_code == 200 and r.content == final_pdf)

        r = client.get(f"/lab-requests/{lab2}/report", headers=doca_h)
        check("image download content type jpeg",
              r.status_code == 200
              and r.headers.get("content-type", "").split(";")[0].strip() == "image/jpeg"
              and r.content == jpg)

        r = client.get(f"/lab-requests/{lab3}/report", headers=doca_h)
        check("traversal-upload download content intact",
              r.status_code == 200 and r.content == pdf_bytes(b"trav"))

        r = client.get("/lab-requests/99999999/report", headers=admin_h)
        check("unknown lab download -> 404", r.status_code == 404)

        r = client.get(f"/lab-requests/{lab4}/report", headers=doca_h)
        check("missing report download -> 404", r.status_code == 404)

        # No absolute filesystem path anywhere in the API surface we touch.
        for endpoint in (
            f"/lab-requests/{lab1}/report",
        ):
            r = client.get(endpoint, headers=doca_h)
            check("download body has no path leakage",
                  b"uploads" not in r.content and b"lab_reports" not in r.content)

    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()

            # ---- Remove stored files before deleting their rows ----
            for (path,) in db.query(LabRequest.report_file_path).filter(
                LabRequest.id.in_(lab_ids)
            ).all():
                report_files.delete_report(path)

            if lab_ids:
                db.query(LabRequest).filter(LabRequest.id.in_(lab_ids)).delete(
                    synchronize_session=False
                )

            if appointment_ids:
                record_ids = [
                    row[0]
                    for row in db.query(MedicalRecord.id)
                    .filter(MedicalRecord.appointment_id.in_(appointment_ids))
                    .all()
                ]
                if record_ids:
                    db.query(PrescriptionItem).filter(
                        PrescriptionItem.prescription_id.in_(
                            db.query(Prescription.id).filter(
                                Prescription.medical_record_id.in_(record_ids)
                            )
                        )
                    ).delete(synchronize_session=False)
                    db.query(Prescription).filter(
                        Prescription.medical_record_id.in_(record_ids)
                    ).delete(synchronize_session=False)
                    db.query(MedicalRecordVersion).filter(
                        MedicalRecordVersion.record_id.in_(record_ids)
                    ).delete(synchronize_session=False)
                    db.query(MedicalRecord).filter(
                        MedicalRecord.id.in_(record_ids)
                    ).delete(synchronize_session=False)
                db.query(Appointment).filter(
                    Appointment.id.in_(appointment_ids)
                ).delete(synchronize_session=False)

            for mrn in ("P3PA", "P3PB"):
                db.query(Patient).filter(Patient.mrn.like(f"{mrn}%")).delete(
                    synchronize_session=False
                )
            for lic in ("P3DA", "P3DB"):
                db.query(Doctor).filter(Doctor.license_number.like(f"{lic}%")).delete(
                    synchronize_session=False
                )

            temp_user_ids = db.query(User.id).filter(
                User.email.like(f"p3.%@mediflow.local")
            )
            db.query(AuditLog).filter(AuditLog.user_id.in_(temp_user_ids)).delete(
                synchronize_session=False
            )
            db.query(Notification).filter(Notification.user_id.in_(temp_user_ids)).delete(
                synchronize_session=False
            )
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id).filter(User.email.like(f"p3.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like(f"p3.%@mediflow.local")
            ).delete(synchronize_session=False)
            db.query(Department).filter(
                Department.name.like(f"Phase3 Dept {suffix}%")
            ).delete(synchronize_session=False)
            db.commit()

            remaining = list(report_files._upload_root().glob("*"))
            check("cleanup: no leftover files in upload dir", len(remaining) == 0)
            check("cleanup: no leftover temp rows",
                  db.query(User).filter(User.email.like(f"p3.%@mediflow.local")).count() == 0)
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