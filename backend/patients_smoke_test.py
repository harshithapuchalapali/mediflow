import re
import time
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    Appointment,
    AuditLog,
    Department,
    Doctor,
    Patient,
    PatientAllergy,
    Receptionist,
    RefreshToken,
    User,
)
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time() * 1000))

MRN_RE = re.compile(r"^PT-\d{6}$")


def main():
    db = SessionLocal()
    users = {}
    doctor_id = None
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

    try:
        admin_user = User(
            email=f"pat.admin.{suffix}@mediflow.local",
            password_hash=hash_password("PatientApiPass!42"),
            role="ADMIN",
            status="ACTIVE",
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        users["ADMIN"] = admin_user

        receptionist_user = User(
            email=f"pat.rec.{suffix}@mediflow.local",
            password_hash=hash_password("PatientApiPass!42"),
            role="RECEPTIONIST",
            status="ACTIVE",
        )
        db.add(receptionist_user)
        db.flush()
        users["RECEPTIONIST"] = receptionist_user
        db.add(
            Receptionist(user_id=receptionist_user.id, employee_code=f"PATRE{suffix[-6:]}")
        )

        doctor_user = User(
            email=f"pat.doc.{suffix}@mediflow.local",
            password_hash=hash_password("PatientApiPass!42"),
            role="DOCTOR",
            status="ACTIVE",
        )
        db.add(doctor_user)
        db.flush()
        users["DOCTOR"] = doctor_user
        db.add(Doctor(user_id=doctor_user.id, license_number=f"PATD{suffix[-6:]}"))
        db.commit()
        db.refresh(doctor_user)
        doctor_id = (
            db.query(Doctor).filter(Doctor.user_id == doctor_user.id).first().id
        )

        admin_h = token_for("ADMIN")
        receptionist_h = token_for("RECEPTIONIST")
        doctor_h = token_for("DOCTOR")

        # Department fixture used by the appointment that grants the doctor
        # a relation to patient A.
        dept = Department(name=f"Patient Dept {suffix}", description="Fixture")
        db.add(dept)
        db.commit()
        db.refresh(dept)
        dept_id = dept.id

        # ============ 1. Public self-registration ============
        reg_a = {
            "email": f"pat.a.{suffix}@mediflow.local",
            "password": "PatientPass!42",
            "first_name": "PatientA",
            "last_name": "Alpha",
            "dob": "1990-05-15",
            "gender": "MALE",
            "blood_group": "O+",
            "height_cm": "175.0",
            "weight_kg": "70.5",
            "emergency_contact_name": "ContactA",
            "emergency_contact_phone": "9112345678",
            "address": "1 Main St",
        }
        r = client.post("/auth/register", json=reg_a)
        check("POST /auth/register -> 201", r.status_code == 201)
        patient_a = r.json()
        check("registration assigns PT-%06d MRN",
              MRN_RE.match(patient_a["mrn"]) is not None)
        check("registration echoes profile fields",
              patient_a["email"] == reg_a["email"]
              and patient_a["first_name"] == "PatientA"
              and patient_a["gender"] == "MALE"
              and patient_a["blood_group"] == "O+"
              and patient_a["status"] == "ACTIVE"
              and patient_a["allergies"] == [])
        check("mrn is derived from sequence",
              int(patient_a["mrn"].split("-")[1]) >= 1)

        r = client.post("/auth/register", json=reg_a)
        check("POST register duplicate email -> 409", r.status_code == 409)

        reg_bad_pass = dict(reg_a)
        reg_bad_pass["email"] = f"pat.badpass.{suffix}@mediflow.local"
        reg_bad_pass["password"] = "short"
        r = client.post("/auth/register", json=reg_bad_pass)
        check("POST register short password -> 422", r.status_code == 422)

        reg_bad_dob = dict(reg_a)
        reg_bad_dob["email"] = f"pat.baddob.{suffix}@mediflow.local"
        reg_bad_dob["dob"] = (date.today() + timedelta(days=1)).isoformat()
        r = client.post("/auth/register", json=reg_bad_dob)
        check("POST register future dob -> 422", r.status_code == 422)

        reg_bad_gender = dict(reg_a)
        reg_bad_gender["email"] = f"pat.badgender.{suffix}@mediflow.local"
        reg_bad_gender["gender"] = "UNKNOWN"
        r = client.post("/auth/register", json=reg_bad_gender)
        check("POST register invalid gender -> 422", r.status_code == 422)

        reg_bad_bg = dict(reg_a)
        reg_bad_bg["email"] = f"pat.badbg.{suffix}@mediflow.local"
        reg_bad_bg["blood_group"] = "Z+"
        r = client.post("/auth/register", json=reg_bad_bg)
        check("POST register invalid blood_group -> 422", r.status_code == 422)

        reg_bad_h = dict(reg_a)
        reg_bad_h["email"] = f"pat.badh.{suffix}@mediflow.local"
        reg_bad_h["height_cm"] = "301"
        r = client.post("/auth/register", json=reg_bad_h)
        check("POST register out-of-range height -> 422", r.status_code == 422)

        reg_bad_w = dict(reg_a)
        reg_bad_w["email"] = f"pat.badw.{suffix}@mediflow.local"
        reg_bad_w["weight_kg"] = "600"
        r = client.post("/auth/register", json=reg_bad_w)
        check("POST register out-of-range weight -> 422", r.status_code == 422)

        reg_blank_name = dict(reg_a)
        reg_blank_name["email"] = f"pat.blank.{suffix}@mediflow.local"
        reg_blank_name["first_name"] = "   "
        r = client.post("/auth/register", json=reg_blank_name)
        check("POST register blank first_name -> 422", r.status_code == 422)

        r = client.post("/auth/login", json={
            "email": reg_a["email"], "password": reg_a["password"]})
        check("registered patient can log in -> 200", r.status_code == 200)
        patient_a_token = r.json()["access_token"]
        patient_a_h = {"Authorization": f"Bearer {patient_a_token}"}

        r = client.get("/auth/me", headers=patient_a_h)
        check("/auth/me for registered patient -> 200",
              r.status_code == 200 and r.json()["role"] == "PATIENT")

        # Second patient, no relation to the doctor (used for 404 tests).
        reg_b = {
            "email": f"pat.b.{suffix}@mediflow.local",
            "password": "PatientPass!42",
            "first_name": "PatientB",
            "last_name": "Beta",
            "gender": "FEMALE",
        }
        r = client.post("/auth/register", json=reg_b)
        check("POST register second patient -> 201", r.status_code == 201)
        patient_b = r.json()
        r = client.post("/auth/login", json={
            "email": reg_b["email"], "password": reg_b["password"]})
        patient_b_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # ============ 2. Staff create patient accounts ============
        rec_created = {
            "email": f"pat.crec.{suffix}@mediflow.local",
            "password": "PatientPass!42",
            "first_name": "RecC",
            "last_name": "Made",
        }
        r = client.post("/patients", json=rec_created, headers=receptionist_h)
        check("receptionist POST /patients -> 201", r.status_code == 201)
        patient_rec = r.json()
        check("receptionist-created patient is ACTIVE with MRN",
              MRN_RE.match(patient_rec["mrn"]) is not None
              and patient_rec["status"] == "ACTIVE")

        admin_created = {
            "email": f"pat.cadm.{suffix}@mediflow.local",
            "password": "PatientPass!42",
            "first_name": "AdmC",
            "last_name": "Made",
        }
        r = client.post("/patients", json=admin_created, headers=admin_h)
        check("admin POST /patients -> 201", r.status_code == 201)
        patient_admin = r.json()

        doctor_created = {
            "email": f"pat.cdoc.{suffix}@mediflow.local",
            "password": "PatientPass!42",
            "first_name": "DocC",
            "last_name": "Made",
        }
        r = client.post("/patients", json=doctor_created, headers=doctor_h)
        check("doctor POST /patients -> 201", r.status_code == 201)
        patient_doctor_created = r.json()

        r = client.post("/patients", json=rec_created, headers=patient_a_h)
        check("patient POST /patients -> 403", r.status_code == 403)

        r = client.post("/patients", json=admin_created)
        check("anonymous POST /patients -> 401", r.status_code == 401)

        r = client.post("/patients", json=rec_created, headers=receptionist_h)
        check("staff POST duplicate email -> 409", r.status_code == 409)

        # ============ 3. Search and list ============
        r = client.get("/patients", headers=admin_h)
        listed = r.json()
        check("admin GET /patients -> 200 with created patients",
              r.status_code == 200
              and any(p["id"] == patient_a["id"] for p in listed)
              and any(p["id"] == patient_rec["id"] for p in listed))

        r = client.get("/patients", headers=patient_a_h)
        check("patient GET /patients (search) -> 403", r.status_code == 403)

        r = client.get("/patients")
        check("anonymous GET /patients -> 401", r.status_code == 401)

        r = client.get("/patients?q=%s" % patient_a["mrn"], headers=admin_h)
        check("search by MRN",
              r.status_code == 200
              and len(r.json()) == 1
              and r.json()[0]["id"] == patient_a["id"])

        r = client.get("/patients?q=PatientA", headers=admin_h)
        check("search by name substring",
              r.status_code == 200
              and any(p["id"] == patient_a["id"] for p in r.json()))

        r = client.get("/patients?gender=MALE", headers=admin_h)
        check("list filter by gender",
              r.status_code == 200
              and all(p["gender"] == "MALE" for p in r.json())
              and any(p["id"] == patient_a["id"] for p in r.json()))

        r = client.get("/patients?limit=1", headers=admin_h)
        check("list pagination limit -> 1 result",
              r.status_code == 200 and len(r.json()) == 1)

        r = client.get("/patients", headers=doctor_h)
        check("doctor list is scoped (no relation patients excluded)",
              r.status_code == 200
              and not any(p["id"] == patient_b["id"] for p in r.json()))

        # Doctor relation fixture: an appointment with patient A.
        appt = Appointment(
            patient_id=patient_a["id"],
            doctor_id=doctor_id,
            department_id=dept_id,
            date_time=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=30,
            priority="NORMAL",
            status="PENDING",
            appointment_type="INITIAL_CONSULTATION",
            created_by=users["ADMIN"].id,
        )
        db.add(appt)
        db.commit()

        r = client.get("/patients", headers=doctor_h)
        check("doctor list includes related patient A",
              r.status_code == 200
              and any(p["id"] == patient_a["id"] for p in r.json())
              and not any(p["id"] == patient_b["id"] for p in r.json())
              and not any(p["id"] == patient_doctor_created["id"] for p in r.json()))

        # ============ 4. Profile view / ownership ============
        r = client.get("/patients/%d" % patient_a["id"], headers=patient_a_h)
        check("patient views own profile -> 200", r.status_code == 200)

        r = client.get("/patients/%d" % patient_a["id"], headers=patient_b_h)
        check("patient views another patient -> 404", r.status_code == 404)

        r = client.get("/patients/%d" % patient_a["id"], headers=doctor_h)
        check("doctor with relation views patient A -> 200",
              r.status_code == 200)

        r = client.get("/patients/%d" % patient_b["id"], headers=doctor_h)
        check("doctor without relation views patient B -> 404",
              r.status_code == 404)

        r = client.get("/patients/%d" % patient_b["id"], headers=receptionist_h)
        check("receptionist views any patient -> 200", r.status_code == 200)

        r = client.get("/patients/%d" % patient_b["id"], headers=admin_h)
        check("admin views any patient -> 200", r.status_code == 200)

        r = client.get("/patients/999999", headers=admin_h)
        check("GET unknown patient -> 404", r.status_code == 404)

        # ============ 5. Profile update ============
        r = client.patch("/patients/%d" % patient_a["id"], json={
            "first_name": "PatientARenamed",
            "dob": "1988-01-02",
            "gender": "OTHER",
            "blood_group": "A+",
            "height_cm": "180.0",
            "weight_kg": "75.0",
            "emergency_contact_name": "NewContact",
            "emergency_contact_phone": "9990001111",
            "address": "2 High St",
        }, headers=patient_a_h)
        check("patient self PATCH profile -> 200",
              r.status_code == 200
              and r.json()["first_name"] == "PatientARenamed"
              and r.json()["gender"] == "OTHER"
              and r.json()["blood_group"] == "A+")
        check("MRN immutable after self update",
              r.json()["mrn"] == patient_a["mrn"])

        r = client.patch("/patients/%d" % patient_b["id"], json={
            "first_name": "Hijack"}, headers=patient_a_h)
        check("patient PATCH another's profile -> 404", r.status_code == 404)

        r = client.patch("/patients/%d" % patient_b["id"], json={
            "first_name": "RecEdit"}, headers=receptionist_h)
        check("receptionist PATCH profile -> 403", r.status_code == 403)

        r = client.patch("/patients/%d" % patient_b["id"], json={
            "first_name": "DocEdit"}, headers=doctor_h)
        check("doctor PATCH profile -> 403", r.status_code == 403)

        r = client.patch("/patients/%d" % patient_b["id"], json={
            "last_name": "BetaRenamed"}, headers=admin_h)
        check("admin PATCH profile -> 200",
              r.status_code == 200
              and r.json()["last_name"] == "BetaRenamed")

        r = client.patch("/patients/%d" % patient_b["id"], json={},
                         headers=admin_h)
        check("PATCH empty body -> 422", r.status_code == 422)

        r = client.patch("/patients/%d" % patient_b["id"], json={
            "gender": "MAYBE"}, headers=admin_h)
        check("PATCH invalid gender -> 422", r.status_code == 422)

        r = client.patch("/patients/%d" % patient_b["id"], json={
            "dob": (date.today() + timedelta(days=1)).isoformat()},
            headers=admin_h)
        check("PATCH future dob -> 422", r.status_code == 422)

        r = client.patch("/patients/%d" % patient_b["id"], json={
            "first_name": "X", "unknown_field": "nope"}, headers=admin_h)
        check("PATCH unknown field -> 422", r.status_code == 422)

        # ============ 6. Allergies ============
        r = client.post("/patients/%d/allergies" % patient_a["id"], json={
            "allergen": " Penicillin ",
            "severity": "SEVERE",
            "notes": "hives",
        }, headers=patient_a_h)
        check("patient adds own allergy -> 201",
              r.status_code == 201
              and r.json()["allergen"] == "penicillin"
              and r.json()["severity"] == "SEVERE")
        allergy_pen = r.json()["id"]

        r = client.post("/patients/%d/allergies" % patient_a["id"], json={
            "allergen": "PENICILLIN", "severity": "MILD"},
            headers=patient_a_h)
        check("duplicate normalized allergy -> 409", r.status_code == 409)

        r = client.post("/patients/%d/allergies" % patient_a["id"], json={
            "allergen": "Aspirin", "severity": "WILD"}, headers=patient_a_h)
        check("allergy invalid severity -> 422", r.status_code == 422)

        r = client.post("/patients/%d/allergies" % patient_a["id"], json={
            "allergen": "   ", "severity": "MILD"}, headers=patient_a_h)
        check("allergy blank allergen -> 422", r.status_code == 422)

        r = client.post("/patients/%d/allergies" % patient_a["id"], json={
            "allergen": "Latex", "severity": "MODERATE"}, headers=receptionist_h)
        check("receptionist adds allergy -> 201", r.status_code == 201)

        r = client.post("/patients/%d/allergies" % patient_a["id"], json={
            "allergen": "Dust", "severity": "MILD"}, headers=doctor_h)
        check("doctor (with relation) adds allergy -> 201", r.status_code == 201)

        r = client.post("/patients/%d/allergies" % patient_b["id"], json={
            "allergen": "Pollen", "severity": "MILD"}, headers=doctor_h)
        check("doctor (no relation) adds allergy -> 404", r.status_code == 404)

        r = client.post("/patients/%d/allergies" % patient_a["id"], json={
            "allergen": "Sulfa", "severity": "MILD"}, headers=patient_b_h)
        check("other patient adds allergy -> 404", r.status_code == 404)

        r = client.post("/patients/%d/allergies" % patient_a["id"], json={
            "allergen": "Nuts", "severity": "MILD"}, headers=admin_h)
        check("admin adds allergy -> 201", r.status_code == 201)

        r = client.get("/patients/%d/allergies" % patient_a["id"],
                       headers=patient_a_h)
        check("patient lists own allergies",
              r.status_code == 200
              and len(r.json()) == 4
              and all(a["patient_id"] == patient_a["id"] for a in r.json()))

        r = client.get("/patients/%d" % patient_a["id"], headers=admin_h)
        check("profile includes allergies",
              len(r.json()["allergies"]) == 4)

        r = client.get("/patients/%d/allergies" % patient_a["id"],
                       headers=doctor_h)
        check("doctor (relation) views allergies -> 200",
              r.status_code == 200 and len(r.json()) == 4)

        r = client.get("/patients/%d/allergies" % patient_b["id"],
                       headers=doctor_h)
        check("doctor (no relation) views allergies -> 404",
              r.status_code == 404)

        r = client.delete(
            "/patients/%d/allergies/%d" % (patient_a["id"], allergy_pen),
            headers=patient_a_h)
        check("patient removes own allergy -> 200", r.status_code == 200)

        r = client.delete(
            "/patients/%d/allergies/%d" % (patient_a["id"], allergy_pen),
            headers=patient_a_h)
        check("remove already-removed allergy -> 404", r.status_code == 404)

        r = client.delete(
            "/patients/%d/allergies/%d"
            % (patient_b["id"], allergy_pen),
            headers=patient_a_h)
        check("remove allergy from another patient -> 404", r.status_code == 404)

        r = client.get("/patients/%d/allergies" % patient_a["id"],
                       headers=patient_a_h)
        check("allergy removed persisted",
              r.status_code == 200 and len(r.json()) == 3)

        # ============ 7. Activate / deactivate ============
        r = client.post("/patients/%d/deactivate" % patient_a["id"],
                        headers=receptionist_h)
        check("receptionist deactivate -> 403", r.status_code == 403)

        r = client.post("/patients/%d/deactivate" % patient_a["id"],
                        headers=admin_h)
        check("admin deactivate patient -> 200", r.status_code == 200)

        r = client.post("/auth/login", json={
            "email": reg_a["email"], "password": reg_a["password"]})
        check("deactivated patient login blocked -> 401", r.status_code == 401)

        r = client.get("/patients?is_active=false", headers=admin_h)
        check("deactivated patient in is_active=false filter",
              r.status_code == 200
              and any(p["id"] == patient_a["id"] for p in r.json()))

        r = client.get("/patients?is_active=true", headers=admin_h)
        check("deactivated patient absent from is_active=true filter",
              r.status_code == 200
              and not any(p["id"] == patient_a["id"] for p in r.json()))

        r = client.post("/patients/%d/deactivate" % patient_a["id"],
                        headers=admin_h)
        check("deactivate already-deactivated patient -> 400",
              r.status_code == 400)

        r = client.post("/patients/%d/activate" % patient_a["id"],
                        headers=admin_h)
        check("admin activate patient -> 200", r.status_code == 200)

        r = client.post("/patients/%d/activate" % patient_a["id"],
                        headers=admin_h)
        check("activate already-active patient -> 400", r.status_code == 400)

        r = client.post("/patients/999999/deactivate", headers=admin_h)
        check("deactivate unknown patient -> 404", r.status_code == 404)

        r = client.post("/auth/login", json={
            "email": reg_a["email"], "password": reg_a["password"]})
        check("reactivated patient login -> 200", r.status_code == 200)

        # ============ 8. Audit trail ============
        r = client.get("/admin/audit-logs?action=PATIENT_CREATE", headers=admin_h)
        check("audit action=PATIENT_CREATE",
              r.status_code == 200
              and len(r.json()) >= 5
              and all(e["action"] == "PATIENT_CREATE" for e in r.json())
              and all(e["entity_type"] == "PATIENT" for e in r.json()))

        r = client.get("/admin/audit-logs?action=PATIENT_UPDATE", headers=admin_h)
        check("audit action=PATIENT_UPDATE",
              r.status_code == 200
              and len(r.json()) >= 1
              and all(e["entity_type"] == "PATIENT" for e in r.json()))

        r = client.get("/admin/audit-logs?action=PATIENT_DEACTIVATE", headers=admin_h)
        check("audit action=PATIENT_DEACTIVATE",
              r.status_code == 200
              and len(r.json()) == 1
              and r.json()[0]["entity_type"] == "PATIENT")

        r = client.get("/admin/audit-logs?action=PATIENT_ACTIVATE", headers=admin_h)
        check("audit action=PATIENT_ACTIVATE",
              r.status_code == 200
              and len(r.json()) == 1
              and r.json()[0]["entity_type"] == "PATIENT")

        r = client.get("/admin/audit-logs?action=ALLERGY_ADD", headers=admin_h)
        check("audit action=ALLERGY_ADD",
              r.status_code == 200
              and len(r.json()) >= 4
              and all(e["entity_type"] == "PATIENT" for e in r.json()))

        r = client.get("/admin/audit-logs?action=ALLERGY_REMOVE", headers=admin_h)
        check("audit action=ALLERGY_REMOVE",
              r.status_code == 200
              and len(r.json()) == 1
              and r.json()[0]["entity_type"] == "PATIENT")
    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            user_ids = [u.id for u in db.query(User).filter(
                User.email.like("pat.%@mediflow.local")).all()]
            patient_ids = [p.id for p in db.query(Patient).filter(
                Patient.user_id.in_(user_ids)).all()] if user_ids else []
            doctor_ids = [d.id for d in db.query(Doctor).filter(
                Doctor.user_id.in_(user_ids)).all()] if user_ids else []
            receptionist_ids = [r.id for r in db.query(Receptionist).filter(
                Receptionist.user_id.in_(user_ids)).all()] if user_ids else []
            if user_ids:
                db.query(RefreshToken).filter(
                    RefreshToken.user_id.in_(user_ids)
                ).delete(synchronize_session=False)
            if patient_ids:
                db.query(PatientAllergy).filter(
                    PatientAllergy.patient_id.in_(patient_ids)
                ).delete(synchronize_session=False)
                db.query(Appointment).filter(
                    Appointment.patient_id.in_(patient_ids)
                ).delete(synchronize_session=False)
                db.query(Patient).filter(
                    Patient.id.in_(patient_ids)
                ).delete(synchronize_session=False)
            if doctor_ids:
                db.query(Doctor).filter(
                    Doctor.id.in_(doctor_ids)
                ).delete(synchronize_session=False)
            if receptionist_ids:
                db.query(Receptionist).filter(
                    Receptionist.id.in_(receptionist_ids)
                ).delete(synchronize_session=False)
            if dept_id is not None:
                db.query(Department).filter(
                    Department.id == dept_id
                ).delete(synchronize_session=False)
            if user_ids:
                db.query(AuditLog).filter(
                    AuditLog.user_id.in_(user_ids)
                ).delete(synchronize_session=False)
            db.query(AuditLog).filter(
                AuditLog.action.in_(
                    ["PATIENT_CREATE", "PATIENT_UPDATE",
                     "PATIENT_DEACTIVATE", "PATIENT_ACTIVATE",
                     "ALLERGY_ADD", "ALLERGY_REMOVE"]
                )
            ).delete(synchronize_session=False)
            if user_ids:
                db.query(User).filter(
                    User.id.in_(user_ids)
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
