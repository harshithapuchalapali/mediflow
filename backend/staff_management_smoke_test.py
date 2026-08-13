import time
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, Department, Doctor, DoctorDepartment, Receptionist, RefreshToken, User
from app.security import create_access_token, hash_password

client = TestClient(app)
suffix = str(int(time.time() * 1000))


def D(value):
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def main():
    db = SessionLocal()
    users = {}
    doctors = []
    receptionists = []
    created_users = []
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
            email=f"stf.admin.{suffix}@mediflow.local",
            password_hash=hash_password("StaffApiPass!42"),
            role="ADMIN",
            status="ACTIVE",
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        users["ADMIN"] = admin_user
        created_users.append(admin_user.id)

        admin_h = token_for("ADMIN")

        for role in ("DOCTOR", "RECEPTIONIST", "PATIENT"):
            u = User(
                email=f"stf.{role.lower()}.{suffix}@mediflow.local",
                password_hash=hash_password("StaffApiPass!42"),
                role=role,
                status="ACTIVE",
            )
            db.add(u)
            db.flush()
            users[role] = u
        db.commit()

        doctor_h = token_for("DOCTOR")
        receptionist_h = token_for("RECEPTIONIST")
        patient_h = token_for("PATIENT")

        # ============ 1. RBAC: ADMIN-only on every staff endpoint ============
        staff_endpoints = [
            ("GET", "/admin/doctors", None),
            ("POST", "/admin/doctors", {"email": "x@y.z", "password": "x" * 9,
                                        "license_number": "L"}),
            ("GET", "/admin/doctors/1", None),
            ("PATCH", "/admin/doctors/1", {"consultation_fee": 1}),
            ("PUT", "/admin/doctors/1/departments", [1, 2]),
            ("GET", "/admin/receptionists", None),
            ("POST", "/admin/receptionists", {"email": "x@y.z", "password": "x" * 9}),
            ("GET", "/admin/receptionists/1", None),
            ("PATCH", "/admin/receptionists/1", {"employee_code": "E"}),
            ("GET", "/admin/users", None),
            ("POST", "/admin/users", {"email": "x@y.z", "password": "x" * 9}),
        ]
        for method, path, body in staff_endpoints:
            for label, headers in (
                ("doctor", doctor_h),
                ("receptionist", receptionist_h),
                ("patient", patient_h),
            ):
                r = client.request(method, path, json=body, headers=headers)
                check(f"{label} {method} {path} -> 403", r.status_code == 403)
            r = client.request(method, path, json=body)
            check(f"anonymous {method} {path} -> 401", r.status_code == 401)

        # ============ 2. Department fixture ============
        r = client.post(
            "/admin/departments",
            json={"name": f"Staff Dept {suffix}", "description": "Staff mgmt dept"},
            headers=admin_h,
        )
        check("create department fixture -> 201", r.status_code == 201)
        dept_id = r.json()["id"]

        # ============ 3. Doctor creation ============
        doctor_info = {
            "email": f"stf.newdoc.{suffix}@mediflow.local",
            "password": "DoctorPass!42",
            "license_number": f"STFDL{suffix[-6:]}",
            "consultation_fee": "1500.00",
        }
        r = client.post("/admin/doctors", json=doctor_info, headers=admin_h)
        check("POST doctor -> 201", r.status_code == 201)
        doc = r.json()
        doctor_id = doc["id"]
        doctors.append(doctor_id)
        created_users.append(doc["user_id"])
        check("created doctor echoes fields and is ACTIVE",
              doc["email"] == doctor_info["email"]
              and doc["license_number"] == doctor_info["license_number"]
              and D(doc["consultation_fee"]) == D("1500.00")
              and doc["status"] == "ACTIVE"
              and doc["department_ids"] == [])

        r = client.post("/admin/doctors", json=doctor_info, headers=admin_h)
        check("POST doctor duplicate email -> 409", r.status_code == 409)

        r = client.post("/admin/doctors", json={
            "email": f"stf.otherdoc.{suffix}@mediflow.local",
            "password": "DoctorPass!42",
            "license_number": doctor_info["license_number"],
        }, headers=admin_h)
        check("POST doctor duplicate license -> 409", r.status_code == 409)

        # A real second doctor, used later as a collision source for updates.
        other_doc_info = {
            "email": f"stf.otherdoc.{suffix}@mediflow.local",
            "password": "DoctorPass!42",
            "license_number": f"STFDO{suffix[-6:]}",
        }
        r = client.post("/admin/doctors", json=other_doc_info, headers=admin_h)
        check("POST second doctor -> 201", r.status_code == 201)
        other_doc_id = r.json()["id"]
        doctors.append(other_doc_id)
        created_users.append(r.json()["user_id"])

        r = client.post("/admin/doctors", json={
            "email": "not-an-email",
            "password": "DoctorPass!42",
            "license_number": f"STFDL2{suffix[-6:]}",
        }, headers=admin_h)
        check("POST doctor invalid email -> 422", r.status_code == 422)

        r = client.post("/admin/doctors", json={
            "email": f"stf.blankdoc.{suffix}@mediflow.local",
            "password": "DoctorPass!42",
            "license_number": "   ",
        }, headers=admin_h)
        check("POST doctor blank license -> 422", r.status_code == 422)

        r = client.post("/admin/doctors", json={
            "email": f"stf.weakpass.{suffix}@mediflow.local",
            "password": "short",
            "license_number": f"STFDL3{suffix[-6:]}",
        }, headers=admin_h)
        check("POST doctor short password -> 422", r.status_code == 422)

        # ============ 4. Doctor retrieval and list ============
        r = client.get("/admin/doctors", headers=admin_h)
        check("list doctors contains created one",
              r.status_code == 200
              and any(d["id"] == doctor_id for d in r.json()))

        r = client.get("/admin/doctors", headers=admin_h)
        check("list doctors returns email + department ids",
              r.status_code == 200
              and all("email" in d and "department_ids" in d for d in r.json()))

        r = client.get("/admin/doctors/%d" % doctor_id, headers=admin_h)
        check("GET doctor -> 200", r.status_code == 200)

        r = client.get("/admin/doctors/999999", headers=admin_h)
        check("GET unknown doctor -> 404", r.status_code == 404)

        # ============ 5. Department assignment (replace-set PUT) ============
        r = client.put("/admin/doctors/%d/departments" % doctor_id,
                       json=[dept_id, dept_id, dept_id], headers=admin_h)
        check("PUT doctor departments -> 200", r.status_code == 200)
        check("PUT dedupes department ids and assigns",
              r.json()["department_ids"] == [dept_id])

        r = client.get("/admin/doctors/%d" % doctor_id, headers=admin_h)
        check("GET doctor reflects assigned department",
              r.json()["department_ids"] == [dept_id])

        r = client.put("/admin/doctors/%d/departments" % doctor_id,
                       json=[999999], headers=admin_h)
        check("PUT unknown department -> 404", r.status_code == 404)

        # Soft-closed department is still assignable (D5)
        r = client.delete("/admin/departments/%d" % dept_id, headers=admin_h)
        check("soft-close department -> 204", r.status_code == 204)
        r = client.put("/admin/doctors/%d/departments" % doctor_id,
                       json=[dept_id], headers=admin_h)
        check("PUT assign soft-closed department -> 200",
              r.status_code == 200 and r.json()["department_ids"] == [dept_id])

        r = client.put("/admin/doctors/%d/departments" % doctor_id,
                       json=[], headers=admin_h)
        check("PUT empty set clears assignments",
              r.status_code == 200 and r.json()["department_ids"] == [])

        r = client.get("/admin/doctors?department_id=%d" % dept_id,
                       headers=admin_h)
        check("list filter department_id matches only assigned doctors",
              r.status_code == 200 and len(r.json()) == 0)

        # Re-open the department for the later assignment test
        r = client.patch("/admin/departments/%d" % dept_id,
                         json={"is_active": True}, headers=admin_h)
        check("re-open department -> 200", r.status_code == 200)

        # ============ 6. Doctor update ============
        r = client.patch("/admin/doctors/%d" % doctor_id, json={}, headers=admin_h)
        check("PATCH doctor empty body -> 422", r.status_code == 422)

        new_email = f"stf.renameddoc.{suffix}@mediflow.local"
        r = client.patch("/admin/doctors/%d" % doctor_id,
                         json={"email": new_email}, headers=admin_h)
        check("PATCH doctor email -> 200",
              r.status_code == 200 and r.json()["email"] == new_email)

        r = client.patch("/admin/doctors/%d" % doctor_id,
                         json={"email": other_doc_info["email"]}, headers=admin_h)
        check("PATCH doctor to existing email -> 409", r.status_code == 409)

        r = client.patch("/admin/doctors/%d" % doctor_id,
                         json={"license_number": f"STFDL4{suffix[-6:]}",
                               "consultation_fee": "2000"},
                         headers=admin_h)
        check("PATCH doctor license + fee -> 200",
              r.status_code == 200
              and r.json()["license_number"] == f"STFDL4{suffix[-6:]}"
              and D(r.json()["consultation_fee"]) == D("2000"))

        r = client.patch("/admin/doctors/%d" % doctor_id,
                         json={"license_number": other_doc_info["license_number"]},
                         headers=admin_h)
        check("PATCH doctor to existing license -> 409", r.status_code == 409)

        r = client.patch("/admin/doctors/%d" % doctor_id,
                         json={"consultation_fee": -5}, headers=admin_h)
        check("PATCH doctor negative fee -> 422", r.status_code == 422)

        r = client.patch("/admin/doctors/999999", json={"email": new_email},
                         headers=admin_h)
        check("PATCH unknown doctor -> 404", r.status_code == 404)

        # ============ 7. Receptionist creation and update ============
        rec_info = {
            "email": f"stf.newrec.{suffix}@mediflow.local",
            "password": "ReceiptPass!42",
            "employee_code": f"STFRE{suffix[-6:]}",
        }
        r = client.post("/admin/receptionists", json=rec_info, headers=admin_h)
        check("POST receptionist -> 201", r.status_code == 201)
        rec = r.json()
        rec_id = rec["id"]
        receptionists.append(rec_id)
        created_users.append(rec["user_id"])
        check("created receptionist echoes fields and is ACTIVE",
              rec["email"] == rec_info["email"]
              and rec["employee_code"] == rec_info["employee_code"]
              and rec["status"] == "ACTIVE")

        r = client.post("/admin/receptionists", json={
            "email": f"stf.otherrec.{suffix}@mediflow.local",
            "password": "ReceiptPass!42",
            "employee_code": rec_info["employee_code"],
        }, headers=admin_h)
        check("POST receptionist duplicate employee_code -> 409",
              r.status_code == 409)

        r = client.post("/admin/receptionists", json={
            "email": rec_info["email"],
            "password": "ReceiptPass!42",
            "employee_code": f"STFRE2{suffix[-6:]}",
        }, headers=admin_h)
        check("POST receptionist duplicate email -> 409", r.status_code == 409)

        r = client.post("/admin/receptionists", json={
            "email": f"stf.nocode.{suffix}@mediflow.local",
            "password": "ReceiptPass!42",
        }, headers=admin_h)
        check("POST receptionist without employee_code -> 201",
              r.status_code == 201 and r.json()["employee_code"] is None)
        no_code_id = r.json()["id"]
        receptionists.append(no_code_id)
        created_users.append(r.json()["user_id"])

        r = client.patch("/admin/doctors/%d" % doctor_id, json={}, headers=admin_h)
        r = client.patch("/admin/receptionists/%d" % rec_id,
                         json={"employee_code": f"STFRE3{suffix[-6:]}"},
                         headers=admin_h)
        check("PATCH receptionist employee_code -> 200",
              r.status_code == 200
              and r.json()["employee_code"] == f"STFRE3{suffix[-6:]}")

        r = client.patch("/admin/receptionists/%d" % rec_id,
                         json={"employee_code": None}, headers=admin_h)
        check("PATCH receptionist clears employee_code -> 200",
              r.status_code == 200 and r.json()["employee_code"] is None)

        r = client.patch("/admin/receptionists/%d" % rec_id,
                         json={"email": f"stf.rec2.{suffix}@mediflow.local"},
                         headers=admin_h)
        check("PATCH receptionist email -> 200",
              r.status_code == 200
              and r.json()["email"] == f"stf.rec2.{suffix}@mediflow.local")

        r = client.get("/admin/receptionists", headers=admin_h)
        check("list receptionists contains created ones",
              r.status_code == 200
              and any(x["id"] == rec_id for x in r.json())
              and any(x["id"] == no_code_id for x in r.json()))

        r = client.get("/admin/receptionists/999999", headers=admin_h)
        check("GET unknown receptionist -> 404", r.status_code == 404)

        # ============ 8. Admin user creation via /admin/users (D2) ============
        new_admin_info = {
            "email": f"stf.newadmin.{suffix}@mediflow.local",
            "password": "NewAdminPass!42",
        }
        r = client.post("/admin/users", json=new_admin_info, headers=admin_h)
        check("POST /admin/users -> 201", r.status_code == 201)
        new_admin_id = r.json()["id"]
        created_users.append(new_admin_id)
        check("created admin user is ADMIN and ACTIVE",
              r.json()["role"] == "ADMIN" and r.json()["status"] == "ACTIVE")

        r = client.post("/admin/users", json=new_admin_info, headers=admin_h)
        check("POST /admin/users duplicate email -> 409", r.status_code == 409)

        r = client.get("/admin/users", headers=admin_h)
        check("list users contains new admin",
              r.status_code == 200
              and any(u["id"] == new_admin_id for u in r.json()))

        r = client.get("/admin/users?role=ADMIN", headers=admin_h)
        check("list users filter by role=ADMIN",
              r.status_code == 200
              and all(u["role"] == "ADMIN" for u in r.json()))

        r = client.get("/admin/users?status=ACTIVE", headers=admin_h)
        check("list users filter by status=ACTIVE",
              r.status_code == 200
              and all(u["status"] == "ACTIVE" for u in r.json()))

        r = client.post("/auth/login", json={
            "email": new_admin_info["email"],
            "password": new_admin_info["password"],
        })
        check("new admin can log in -> 200", r.status_code == 200)

        # ============ 9. User life-cycle: deactivate / activate (with audit) ===
        r = client.get("/admin/doctors/%d" % doctor_id, headers=admin_h)
        doctor_user_id = r.json()["user_id"]

        r = client.get("/admin/users?role=DOCTOR", headers=admin_h)
        check("list_users exposes user_id for doctor",
              r.status_code == 200
              and any(u["id"] == doctor_user_id for u in r.json()))

        r = client.post("/auth/users/%d/deactivate" % doctor_user_id,
                        headers=admin_h)
        check("deactivate doctor user -> 200", r.status_code == 200)

        r = client.get("/admin/doctors/%d" % doctor_id, headers=admin_h)
        check("doctor status is DEACTIVATED after deactivate",
              r.json()["status"] == "DEACTIVATED")

        r = client.get("/admin/doctors?is_active=false", headers=admin_h)
        check("deactivated doctor appears in is_active=false filter",
              r.status_code == 200
              and any(d["id"] == doctor_id for d in r.json()))

        r = client.get("/admin/doctors?is_active=true", headers=admin_h)
        check("deactivated doctor absent from is_active=true filter",
              r.status_code == 200
              and all(d["id"] != doctor_id for d in r.json()))

        r = client.post("/auth/login", json={
            "email": new_email,
            "password": "DoctorPass!42",
        })
        check("deactivated doctor login blocked -> 401", r.status_code == 401)

        r = client.post("/auth/users/%d/activate" % doctor_user_id,
                        headers=admin_h)
        check("activate doctor user -> 200", r.status_code == 200)

        r = client.get("/admin/doctors/%d" % doctor_id, headers=admin_h)
        check("doctor status is ACTIVE again",
              r.json()["status"] == "ACTIVE")

        r = client.post("/auth/users/%d/activate" % doctor_user_id,
                        headers=admin_h)
        check("activate already-active user -> 400", r.status_code == 400)

        r = client.post("/auth/users/%d/deactivate" % users["ADMIN"].id,
                        headers=admin_h)
        check("deactivate own account -> 400", r.status_code == 400)

        r = client.post("/auth/users/999999/deactivate", headers=admin_h)
        check("deactivate unknown user -> 404", r.status_code == 404)

        # ============ 10. Audit trail ============
        r = client.get("/admin/audit-logs", headers=admin_h)
        actions = {e["action"] for e in r.json()}
        check("audit contains staff create/update/assign actions",
              {"DOCTOR_CREATE", "DOCTOR_UPDATE",
               "DOCTOR_DEPARTMENTS_SET",
               "RECEPTIONIST_CREATE", "RECEPTIONIST_UPDATE",
               "ADMIN_CREATE"} <= actions)
        check("audit contains user activate/deactivate actions",
              {"USER_DEACTIVATE", "USER_ACTIVATE"} <= actions)

        r = client.get("/admin/audit-logs?action=DOCTOR_CREATE", headers=admin_h)
        check("filter audit by action=DOCTOR_CREATE",
              r.status_code == 200
              and len(r.json()) >= 2
              and all(e["action"] == "DOCTOR_CREATE" for e in r.json())
              and all(e["entity_type"] == "DOCTOR" for e in r.json()))

        r = client.get("/admin/audit-logs?action=USER_DEACTIVATE", headers=admin_h)
        check("filter audit by action=USER_DEACTIVATE",
              r.status_code == 200
              and len(r.json()) >= 1
              and all(e["action"] == "USER_DEACTIVATE" for e in r.json())
              and all(e["entity_type"] == "USER" for e in r.json()))

        r = client.get("/admin/audit-logs?entity_type=RECEPTIONIST", headers=admin_h)
        check("filter audit by entity_type=RECEPTIONIST",
              r.status_code == 200
              and all(e["entity_type"] == "RECEPTIONIST" for e in r.json())
              and len(r.json()) >= 2)
    except Exception as exc:
        db.rollback()
        print(f"  FAIL | unexpected error: {type(exc).__name__}: {exc}")
        fails += 1

    finally:
        try:
            db.rollback()
            user_ids = [u.id for u in db.query(User).filter(
                User.email.like("stf.%@mediflow.local")).all()]
            doctor_ids = [d.id for d in db.query(Doctor).filter(
                Doctor.user_id.in_(user_ids)).all()] if user_ids else []
            receptionist_ids = [r.id for r in db.query(Receptionist).filter(
                Receptionist.user_id.in_(user_ids)).all()] if user_ids else []
            if user_ids:
                db.query(RefreshToken).filter(
                    RefreshToken.user_id.in_(user_ids)
                ).delete(synchronize_session=False)
                db.query(AuditLog).filter(
                    AuditLog.user_id.in_(user_ids)
                ).delete(synchronize_session=False)
            if doctor_ids:
                db.query(DoctorDepartment).filter(
                    DoctorDepartment.doctor_id.in_(doctor_ids)
                ).delete(synchronize_session=False)
                db.query(Doctor).filter(
                    Doctor.id.in_(doctor_ids)
                ).delete(synchronize_session=False)
            if receptionist_ids:
                db.query(Receptionist).filter(
                    Receptionist.id.in_(receptionist_ids)
                ).delete(synchronize_session=False)
            db.query(Department).filter(
                Department.name.like("Staff Dept %")
            ).delete(synchronize_session=False)
            db.query(AuditLog).filter(
                AuditLog.action.in_(
                    ["DOCTOR_CREATE", "DOCTOR_UPDATE",
                     "DOCTOR_DEPARTMENTS_SET", "RECEPTIONIST_CREATE",
                     "RECEPTIONIST_UPDATE", "ADMIN_CREATE",
                     "USER_DEACTIVATE", "USER_ACTIVATE"]
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