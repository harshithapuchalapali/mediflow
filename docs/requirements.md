# MediFlow Requirements (v1)

## Overview

MediFlow is a full-stack Hospital Management System that digitizes and automates core hospital operations. It provides four roles (Admin, Doctor, Receptionist, Patient) with role-based dashboards, appointment booking, scheduling, medical records, prescriptions, laboratory workflow, billing, search, notifications, and administrative management.

**Scope (v1):**
- Single hospital only. No multi-hospital / multi-tenant functionality in v1.
- The schema and code architecture must stay modular so future features (multi-hospital, insurance, pharmacy, SMS, real payment gateways, advanced clinical decision support) can be added later without a rewrite.

## Roles & Registration

| Role         | Description                                              |
| ------------ | -------------------------------------------------------- |
| Admin        | Manages the whole hospital system.                       |
| Doctor       | Manages patients, appointments, records, prescriptions, labs. |
| Receptionist | Front-desk staff who views/books appointments on behalf of patients. |
| Patient      | Uses the system to book/view healthcare.                 |

**Registration rules (v1):**
- Only **Patients** can self-register (public signup).
- **Doctors, Admins, and Receptionists** cannot self-register — their accounts are created by an existing Admin.

## Tech Stack (planned)

| Layer       | Technology                  |
| ----------- | --------------------------- |
| Frontend    | React (Vite) + Tailwind     |
| Backend     | Node.js + Express (or NestJS) |
| Database    | PostgreSQL                  |
| Auth        | JWT + refresh token         |
| File upload | Multer (lab reports)        |

_Final choices to be confirmed during architecture/design phase._

## Authentication & Authorization

### Users (all roles)
- [ ] Login with email and password
- [ ] Logout (invalidate session/token)
- [ ] Role-based access control (RBAC) on all routes and UI
- [ ] JWT-based authentication with refresh token support
- [ ] Password hashing (bcrypt)
- [ ] Account lockout after **3 failed login attempts for 15 minutes**
- [ ] Password reset via **expiring email token**
- [ ] Profile update (name, email, phone, password)
- [ ] User deactivation / **soft deletion**, so historical records (appointments, records, bills) remain intact
- [ ] All login attempts and locks are tracked (3 failed attempts → locked 15 minutes)

### Public
- [ ] Patient self-registration only (creates role = patient)

## Patients

- [ ] Every patient receives a unique **MRN** (e.g., `PT-000001`)
- [ ] Profile includes: DOB, gender, blood group, height, weight, allergies, emergency contact
- [ ] View own profile
- [ ] Book appointment (choose department, doctor, date/time)
- [ ] Cancel/reschedule appointment — allowed up to **24 hours before** the appointment
- [ ] View list of appointments (upcoming + past)
- [ ] View medical records (diagnosis, vitals, notes)
- [ ] View prescriptions (medications, dosage, duration)
- [ ] View verified lab results
- [ ] View/download bill PDF
- [ ] View/download prescription PDF
- [ ] Receive notifications (in-app + email): appointment confirmations, reminders, status updates

## Doctors

- [ ] View their assigned appointments (daily/upcoming schedule)
- [ ] Manage appointment status (confirmed, completed, cancelled)
- [ ] View patient information (only for assigned/consulted patients)
- [ ] Create/update medical records (symptoms, diagnosis, vitals, notes)
- [ ] Create prescriptions (medicine name, dosage, frequency, duration)
- [ ] On prescription creation, system performs a **basic recorded-allergy match** and shows an **informational warning** if a potential match exists (NOT a clinical decision system)
- [ ] Request lab tests
- [ ] Verify lab results (Requested → In Progress → Result Ready → Verified)
- [ ] View bill summary for their consultations
- [ ] View dashboard statistics (appointments per day, patients seen)
- [ ] Set individual working schedule (days/hours)
- [ ] Mark specific dates as unavailable

## Receptionists

- [ ] Search patients by name or MRN
- [ ] View patient profile
- [ ] Register patients (create patient accounts on their behalf)
- [ ] Book appointments on behalf of patients
- [ ] Cancel/reschedule appointments (subject to same rules, or admin override)
- [ ] View today's appointment list
- [ ] Mark appointments as checked-in (front desk)
- [ ] Must NOT modify clinical records or prescriptions

## Admins

- [ ] Manage doctors (add, edit, deactivate, assign departments, set working schedule)
- [ ] Manage receptionists (add, edit, deactivate)
- [ ] Manage patients (view, edit, activate/deactivate)
- [ ] Manage departments (add, edit, delete)
- [ ] Manage all appointments (view, assign, cancel)
- [ ] **Override appointment restrictions** (e.g., allow a late reschedule)
- [ ] Manage user accounts and roles
- [ ] View key statistics: total patients, total doctors, appointment trends, revenue/bills overview, lab reports per department
- [ ] Manage hospital settings (working hours, consultation fee)
- [ ] Hospital profile via a **single-row `hospital_settings` table** (hospital name, address, contact details, timezone, logo) — no multi-hospital support
- [ ] View audit log (who created/updated what and when)

## Appointments & Scheduling

- [ ] Prevent **doctor double-booking** with a PostgreSQL **partial exclusion constraint** plus backend validation — no overlapping **active** (non-cancelled, non-no-show) appointments for the same doctor; cancelled slots are reusable
- [ ] Appointment **duration** stored as `duration_minutes` so overlap checks are exact
- [ ] Appointment **type**: **INITIAL_CONSULTATION** or **FOLLOW_UP** (separate from priority and status)
- [ ] Priority: **NORMAL**, **URGENT**, **EMERGENCY** — kept separate from status
- [ ] Doctors have **individual working schedules**
- [ ] Doctors and Admins can mark **specific dates as unavailable**
- [ ] Patients can cancel/reschedule **up to 24 hours before** the appointment
- [ ] Admin can override appointment restrictions
- [ ] Status workflow: pending → confirmed → checked-in → completed | cancelled | no-show

## Medical Records

- [ ] Medical records must **not** be silently deleted or overwritten
- [ ] Maintain **basic version history / audit info**: who created/updated a record and when

## Laboratory

- [ ] Workflow: **Requested → In Progress → Result Ready → Verified**
- [ ] Doctor can request tests and verify results
- [ ] Patient can view verified results only

## Search

- [ ] Patient search by name and MRN
- [ ] Filtering and pagination for large datasets

## Billing

- [ ] Covers: consultation fees, lab tests, procedures, and other hospital service charges
- [ ] Pharmacy and insurance are out of scope for v1
- [ ] Payment states: **Pending, Partially Paid, Paid, Overdue, Refunded**
- [ ] No real payment gateway integration in v1 — payments recorded manually, each with an optional **transaction_reference**
- [ ] Invoice totals are always recomputable from line items
- [ ] PDF bill generation

## Documents

- [ ] Generate PDF prescriptions (v1)
- [ ] Generate PDF bills (v1)
- [ ] Lab report PDF (later)

## Notifications

- [ ] In-app notifications
- [ ] Email notifications
- [ ] No SMS in v1

## Infrastructure / Non-Functional

- [ ] PostgreSQL backup/restore procedure
- [ ] v1 timezone: **Asia/Kolkata (IST)**
- [ ] Secure auth: password hashing, token expiry, input validation, rate limiting on login/reset
- [ ] Responsive UI (mobile + desktop)
- [ ] RESTful API with consistent error handling
- [ ] `GET /health` API health-check endpoint
- [ ] Data validation on client and server
- [ ] Database schema with relations
- [ ] Seed script for demo data (admin, sample doctors/receptionists/patients)
- [ ] Basic tests for core backend flows (auth, appointments)

## Out of Scope (v1)

- [ ] Multi-hospital / multi-tenant support
- [ ] Insurance claims
- [ ] Pharmacy / inventory management
- [ ] SMS notifications
- [ ] Online / real payment gateway integration
- [ ] Real-time chat/video consultations
- [ ] Advanced clinical decision support (allergy warning is informational only)