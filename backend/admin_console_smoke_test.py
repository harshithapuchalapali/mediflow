import time
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

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
    LabRequest,
    Patient,
    Payment,
    Receptionist,
    User,
)
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time() * 1000))

CLINIC_TZ = ZoneInfo("Asia/Kolkata")

BASE_DT = datetime.now(CLINIC_TZ).replace(
    hour=10, minute=0, second=0, microsecond=0
)
TODAY = BASE_DT.date()


def D(value):
    return Decimal(str(value))


def main():
    db = SessionLocal()
    users = {}
    doctors = {}
    patients = {}
    dept_id = None
    created = {"appointments": [], "bills": [], "labs": [], "departments": []}
    baseline = None
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
        admin_user = User(
            email=f"adm.admin.{suffix}@mediflow.local",
            password_hash=hash_password("AdminApiPass!42"),
            role="ADMIN",
            status="ACTIVE",
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        users["ADMIN"] = admin_user

        admin_h = token_for("ADMIN")

        # Baseline BEFORE the other accounts / any data exist: totals and
        # bills deltas are then computed against a DB holding just the admin.
        r = client.get("/admin/dashboard", headers=admin_h)
        check("baseline dashboard fetch -> 200", r.status_code == 200)
        baseline = r.json()

        # Make the single-row settings resource deterministic for this run.
        db.query(HospitalSettings).filter(HospitalSettings.id == 1).delete(
            synchronize_session=False)
        db.commit()

        for role in ("DOCTOR_A", "DOCTOR_B", "RECEPTIONIST",
                     "PATIENT_A", "PATIENT_B"):
            u = User(
                email=f"adm.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("AdminApiPass!42"),
                role="DOCTOR" if role.startswith("DOCTOR") else (
                    "RECEPTIONIST" if role == "RECEPTIONIST" else "PATIENT"
                ),
                status="ACTIVE",
            )
            db.add(u)
            db.flush()
            users[role] = u

        da = Doctor(
            user_id=users["DOCTOR_A"].id, license_number=f"ADMDA{suffix[:6]}"
        )
        dbb = Doctor(
            user_id=users["DOCTOR_B"].id, license_number=f"ADMDB{suffix[:6]}"
        )
        db.add_all([da, dbb])
        db.flush()
        doctors["A"] = da
        doctors["B"] = dbb

        pa = Patient(
            user_id=users["PATIENT_A"].id,
            mrn=f"ADMPA{suffix[:6]}",
            first_name="Adm",
            last_name="PatientA",
        )
        pb = Patient(
            user_id=users["PATIENT_B"].id,
            mrn=f"ADMPB{suffix[:6]}",
            first_name="Adm",
            last_name="PatientB",
        )
        db.add_all([pa, pb])
        db.flush()
        patients["A"] = pa
        patients["B"] = pb

        rec = Receptionist(user_id=users["RECEPTIONIST"].id)
        db.add(rec)
        db.commit()

        doctor_h = token_for("DOCTOR_A")
        receptionist_h = token_for("RECEPTIONIST")
        patient_h = token_for("PATIENT_A")

        # ============ 1. RBAC: ADMIN-only enforcement ============
        for method, path, body in (
            ("GET", "/admin/hospital-settings", None),
            ("POST", "/admin/hospital-settings",
             {"hospital_name": "x"}),
            ("PATCH", "/admin/hospital-settings", {"phone": "x"}),
            ("GET", "/admin/departments", None),
            ("POST", "/admin/departments", {"name": "x"}),
            ("GET", "/admin/departments/1", None),
            ("PATCH", "/admin/departments/1", {"name": "x"}),
            ("DELETE", "/admin/departments/1", None),
            ("GET", "/admin/audit-logs", None),
            ("GET", "/admin/dashboard", None),
        ):
            for label, headers in (
                ("doctor", doctor_h),
                ("receptionist", receptionist_h),
                ("patient", patient_h),
            ):
                r = client.request(method, path, json=body, headers=headers)
                check(f"{label} {method} {path} -> 403", r.status_code == 403)
            r = client.request(method, path, json=body)
            check(f"anonymous {method} {path} -> 401", r.status_code == 401)

        # ============ 2. Hospital settings (single-row, id=1) ============
        r = client.get("/admin/hospital-settings", headers=admin_h)
        check("GET settings before create -> 404", r.status_code == 404)

        body = {
            "hospital_name": "MediFlow Memorial",
            "address": "123 Heal St",
            "phone": "+91-1234567890",
            "email": "care@mediflow.example",
            "timezone": "Asia/Kolkata",
            "logo_path": "/logos/hospital.png",
        }
        r = client.post("/admin/hospital-settings", json=body, headers=admin_h)
        check("POST settings -> 201", r.status_code == 201)
        settings = r.json()
        check("settings echoes fields and id=1",
              settings["id"] == 1
              and settings["hospital_name"] == "MediFlow Memorial"
              and settings["timezone"] == "Asia/Kolkata")

        r = client.post("/admin/hospital-settings", json=body, headers=admin_h)
        check("POST again (single row) -> 409", r.status_code == 409)

        r = client.post(
            "/admin/hospital-settings", json={"hospital_name": "   "},
            headers=admin_h)
        check("POST blank hospital_name -> 422", r.status_code == 422)

        r = client.post("/admin/hospital-settings", json={
            "hospital_name": "X", "email": "not-an-email",
        }, headers=admin_h)
        check("POST invalid email -> 422", r.status_code == 422)

        r = client.patch("/admin/hospital-settings", json={
            "hospital_name": "MediFlow General",
            "phone": "+91-9999999999",
        }, headers=admin_h)
        check("PATCH settings -> 200", r.status_code == 200)
        check("PATCH persists updates",
              r.json()["hospital_name"] == "MediFlow General"
              and r.json()["phone"] == "+91-9999999999"
              and r.json()["email"] == "care@mediflow.example")

        r = client.patch("/admin/hospital-settings", json={}, headers=admin_h)
        check("PATCH empty body -> 422", r.status_code == 422)

        r = client.patch("/admin/hospital-settings", json={"hospital_name": None},
                         headers=admin_h)
        check("PATCH hospital_name null -> 422", r.status_code == 422)

        r = client.patch("/admin/hospital-settings", json={"email": "bad"},
                         headers=admin_h)
        check("PATCH invalid email -> 422", r.status_code == 422)

        r = client.get("/admin/hospital-settings", headers=admin_h)
        check("GET settings returns updated value -> 200",
              r.status_code == 200
              and r.json()["hospital_name"] == "MediFlow General")

        # ============ 3. Departments CRUD (soft-close) ============
        dept_body = {"name": f"Admin Console Dept {suffix}", "description": "Test dept"}
        r = client.post("/admin/departments", json=dept_body, headers=admin_h)
        check("POST department -> 201", r.status_code == 201)
        dept_id = r.json()["id"]
        created["departments"].append(dept_id)
        check("created department is active",
              r.json()["is_active"] is True and r.json()["name"] == dept_body["name"])

        r = client.post("/admin/departments", json=dept_body, headers=admin_h)
        check("POST duplicate department name -> 409", r.status_code == 409)

        r = client.post("/admin/departments", json={"name": "  "}, headers=admin_h)
        check("POST blank department name -> 422", r.status_code == 422)

        r = client.get("/admin/departments", headers=admin_h)
        listed = r.json()
        check("list departments contains created one",
              r.status_code == 200
              and any(d["id"] == dept_id for d in listed))

        r = client.get("/admin/departments?is_active=true", headers=admin_h)
        check("list filter is_active=true",
              r.status_code == 200
              and all(d["is_active"] for d in r.json())
              and any(d["id"] == dept_id for d in r.json()))

        r = client.get("/admin/departments/%d" % dept_id, headers=admin_h)
        check("GET department -> 200", r.status_code == 200)

        r = client.get("/admin/departments/999999", headers=admin_h)
        check("GET unknown department -> 404", r.status_code == 404)

        r = client.patch(
            "/admin/departments/%d" % dept_id,
            json={"description": "Updated dept description"},
            headers=admin_h,
        )
        check("PATCH department -> 200",
              r.status_code == 200
              and r.json()["description"] == "Updated dept description")

        r = client.patch("/admin/departments/999999", json={"name": "Y"},
                         headers=admin_h)
        check("PATCH unknown department -> 404", r.status_code == 404)

        # Soft-close: DELETE flips is_active, row survives
        r = client.delete("/admin/departments/%d" % dept_id, headers=admin_h)
        check("DELETE (soft-close) department -> 204", r.status_code == 204)

        r = client.get("/admin/departments/%d" % dept_id, headers=admin_h)
        check("department still present after soft-close",
              r.status_code == 200 and r.json()["is_active"] is False)

        r = client.get("/admin/departments?is_active=false", headers=admin_h)
        check("soft-closed department appears in is_active=false filter",
              r.status_code == 200 and any(d["id"] == dept_id for d in r.json()))

        # Re-open for use by the dashboard fixtures below
        r = client.patch("/admin/departments/%d" % dept_id,
                         json={"is_active": True}, headers=admin_h)
        check("re-activate department -> 200", r.status_code == 200)

        # ============ 4. Audit log (append-only, ADMIN view) ============
        r = client.get("/admin/audit-logs", headers=admin_h)
        logs = r.json()
        check("GET audit log -> 200 and non-empty", r.status_code == 200 and logs)

        actions = {entry["action"] for entry in logs}
        check("audit contains settings/department actions",
              {"SETTINGS_CREATE", "SETTINGS_UPDATE",
               "DEPARTMENT_CREATE", "DEPARTMENT_UPDATE",
               "DEPARTMENT_DEACTIVATE"} <= actions)

        r = client.get("/admin/audit-logs?action=SETTINGS_CREATE", headers=admin_h)
        check("filter by action",
              r.status_code == 200
              and len(r.json()) == 1
              and r.json()[0]["action"] == "SETTINGS_CREATE")

        r = client.get("/admin/audit-logs?entity_type=DEPARTMENT", headers=admin_h)
        check("filter by entity_type",
              r.status_code == 200
              and all(e["entity_type"] == "DEPARTMENT" for e in r.json()))

        r = client.get("/admin/audit-logs?user_id=%d" % users["ADMIN"].id,
                       headers=admin_h)
        check("filter by user_id",
              r.status_code == 200
              and all(e["user_id"] == users["ADMIN"].id for e in r.json()))

        r = client.get("/admin/audit-logs?date_from=%s&date_to=%s"
                       % (datetime.now(CLINIC_TZ).date().isoformat(),
                          (datetime.now(CLINIC_TZ) + timedelta(days=1)).date().isoformat()),
                       headers=admin_h)
        check("filter by date range", r.status_code == 200 and len(r.json()) >= 1)

        r = client.get("/admin/audit-logs?limit=1", headers=admin_h)
        check("pagination limit", r.status_code == 200 and len(r.json()) == 1)

        r = client.get("/admin/audit-logs?limit=0", headers=admin_h)
        check("limit out of range -> 422", r.status_code == 422)

        all_logs = client.get("/admin/audit-logs", headers=admin_h).json()
        r = client.get("/admin/audit-logs?offset=1", headers=admin_h)
        check("pagination offset advances",
              r.status_code == 200
              and r.json()[0]["id"] != all_logs[0]["id"])

        # ============ 5. Dashboard statistics ============
        dash_url = "/admin/dashboard"

        # Fixtures: two appointments, two bills, one payment, two lab requests
        appt_dt = BASE_DT
        appt1 = Appointment(
            patient_id=patients["A"].id,
            doctor_id=doctors["A"].id,
            department_id=dept_id,
            date_time=appt_dt,
            duration_minutes=30,
            priority="NORMAL",
            status="CONFIRMED",
            appointment_type="INITIAL_CONSULTATION",
            created_by=users["ADMIN"].id,
        )
        appt2 = Appointment(
            patient_id=patients["B"].id,
            doctor_id=doctors["B"].id,
            department_id=dept_id,
            date_time=appt_dt + timedelta(hours=1),
            duration_minutes=30,
            priority="NORMAL",
            status="COMPLETED",
            appointment_type="FOLLOW_UP",
            created_by=users["ADMIN"].id,
        )
        db.add_all([appt1, appt2])
        db.flush()
        created["appointments"] = [appt1.id, appt2.id]

        bill1 = Bill(
            bill_number=f"ADMB1{suffix[:8]}",
            patient_id=patients["A"].id,
            appointment_id=appt1.id,
            status="PENDING",
        )
        bill2 = Bill(
            bill_number=f"ADMB2{suffix[:8]}",
            patient_id=patients["B"].id,
            appointment_id=appt2.id,
            status="PAID",
        )
        db.add_all([bill1, bill2])
        db.flush()

        db.add_all([
            BillItem(bill_id=bill1.id, description="Consultation fee",
                     category="CONSULTATION", quantity=1, unit_price=500.00),
            BillItem(bill_id=bill1.id, description="Dressing service",
                     category="SERVICE", quantity=2, unit_price=100.00),
            BillItem(bill_id=bill2.id, description="Consultation fee",
                     category="CONSULTATION", quantity=1, unit_price=600.00),
        ])
        db.add(Payment(
            bill_id=bill2.id, amount=600.00, method="CASH",
            recorded_by=users["ADMIN"].id,
        ))
        db.flush()
        created["bills"] = [bill1.id, bill2.id]

        db.add_all([
            LabRequest(appointment_id=appt1.id, patient_id=patients["A"].id,
                       doctor_id=doctors["A"].id, test_name="CBC",
                       status="VERIFIED"),
            LabRequest(appointment_id=appt2.id, patient_id=patients["B"].id,
                       doctor_id=doctors["B"].id, test_name="LFT",
                       status="REQUESTED"),
        ])
        db.flush()
        db.commit()

        r = client.get(dash_url, headers=admin_h)
        check("GET dashboard -> 200", r.status_code == 200)
        dash = r.json()

        def delta(key):
            return dash["totals"][key]["active"] - baseline["totals"][key]["active"]

        check("dashboard patients active delta == 2", delta("patients") == 2)
        check("dashboard doctors active delta == 2", delta("doctors") == 2)
        check("dashboard receptionists active delta == 1",
              delta("receptionists") == 1)
        check("dashboard admins active >= 1",
              dash["totals"]["admins"]["active"] >= 1)

        trend = dash["appointment_trends"]
        check("appointment trend includes today",
              any(p["date"] == TODAY.isoformat() and p["total"] >= 2
                  for p in trend))

        check("appointment trend summary totals",
              dash["appointment_trend_summary"].get("CONFIRMED", 0) >= 1
              and dash["appointment_trend_summary"].get("COMPLETED", 0) >= 1)

        bio = dash["bills_overview"]
        check("bills overview count delta == 2",
              bio["bills_count"] == baseline["bills_overview"]["bills_count"] + 2)
        check("billed total delta == 1300.00",
              D(str(D(bio["billed_total"]) - D(str(baseline["bills_overview"]["billed_total"]))))
              == D("1300.00"))
        check("collected total delta == 600.00",
              D(str(D(bio["collected_total"]) - D(str(baseline["bills_overview"]["collected_total"]))))
              == D("600.00"))
        check("outstanding delta == 700.00",
              D(str(D(bio["outstanding"]) - D(str(baseline["bills_overview"]["outstanding"]))))
              == D("700.00"))

        labs = {l["department_id"]: l for l in dash["labs_per_department"]}
        check("lab reports list our department",
              dept_id in labs
              and labs[dept_id]["department_name"] == dept_body["name"])
        check("lab reports counts per status",
              labs[dept_id]["total"] == 2
              and labs[dept_id]["by_status"].get("VERIFIED") == 1
              and labs[dept_id]["by_status"].get("REQUESTED") == 1)

        # Dashboard supports explicit date ranges
        r = client.get(
            "%s?date_from=2030-01-01&date_to=2030-01-31" % dash_url,
            headers=admin_h)
        check("dashboard empty for future date range",
              r.status_code == 200 and r.json()["appointment_trends"] == [])
    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            handled_doc_ids = db.query(Doctor.id).filter(
                Doctor.license_number.like("ADMD%")
            ).all()
            handled_doc_ids = [d[0] for d in handled_doc_ids]
            handled_patient_ids = db.query(Patient.id).filter(
                Patient.mrn.like("ADMP%")
            ).all()
            handled_patient_ids = [p[0] for p in handled_patient_ids]

            db.query(LabRequest).filter(
                LabRequest.patient_id.in_(handled_patient_ids)
            ).delete(synchronize_session=False)
            db.query(Payment).filter(
                Payment.bill_id.in_(
                    db.query(Bill.id).filter(Bill.bill_number.like("ADMB%"))
                )
            ).delete(synchronize_session=False)
            db.query(BillItem).filter(
                BillItem.bill_id.in_(
                    db.query(Bill.id).filter(Bill.bill_number.like("ADMB%"))
                )
            ).delete(synchronize_session=False)
            db.query(Bill).filter(
                Bill.bill_number.like("ADMB%")
            ).delete(synchronize_session=False)
            if created["appointments"]:
                db.query(Appointment).filter(
                    Appointment.id.in_(created["appointments"])
                ).delete(synchronize_session=False)
            if created["departments"]:
                db.query(Department).filter(
                    Department.id.in_(created["departments"])
                ).delete(synchronize_session=False)
            if handled_doc_ids:
                db.query(Doctor).filter(
                    Doctor.id.in_(handled_doc_ids)
                ).delete(synchronize_session=False)
            db.query(Patient).filter(
                Patient.mrn.like("ADMP%")
            ).delete(synchronize_session=False)
            db.query(Receptionist).filter(
                Receptionist.user_id.in_(
                    db.query(User.id).filter(
                        User.email.like("adm.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(AuditLog).filter(
                AuditLog.user_id.in_(
                    db.query(User.id).filter(
                        User.email.like("adm.%@mediflow.local"))
                )
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("adm.%@mediflow.local")
            ).delete(synchronize_session=False)
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