# MediFlow Hospital Management System

## Project

MediFlow — a single-hospital Hospital Management System (v1).
Roles: Admin, Doctor, Receptionist, Patient.

## Source of truth

- `docs/requirements.md` — approved feature requirements
- `docs/database-design.md` — approved schema, constraints, role permissions

Read both before touching any implementation. Design decisions live there and are authoritative.

## Project Stack

- Frontend: React + Vite + Tailwind CSS
- Backend: Python + FastAPI
- Database: PostgreSQL
- ORM: SQLAlchemy
- Validation: Pydantic
- Authentication: JWT
- Testing: pytest
- Containerization: Docker
- CI/CD: GitHub Actions
- Cloud: AWS

## Development Rules

1. Follow modular architecture.
2. Never put secrets directly in source code.
3. Use environment variables for configuration.
4. Do not modify unrelated files.
5. Write tests for new backend features.
6. Explain significant architectural decisions.
7. Use meaningful names.
8. Follow REST API conventions.
9. Do not add unnecessary dependencies.
10. Ask before making major architectural changes.
11. Implement one feature at a time.
12. Explain unfamiliar code before using it.

## Conventions

- Follow the approved database design exactly (table/column names, enums, constraints).
- Money: `NUMERIC`, never floats. Timestamps: UTC in DB, display Asia/Kolkata (IST).
- Soft-delete only — never hard-delete rows that have history (users, patients, appointments).
- Appointments: the overlap guarantee lives in PostgreSQL (partial exclusion constraint, `btree_gist`)
  in `database/`. Never bypass it in app code.

## User rules (from requirements)

- Only Patients self-register. Doctor/Receptionist/Admin accounts are created by an Admin.
- Receptionists must never modify clinical records or prescriptions.
- No multi-hospital, insurance, pharmacy, SMS, or real payment gateway in v1.

## Commands

- Tests live under `tests/` using pytest. Specific commands will be added when the backend lands.