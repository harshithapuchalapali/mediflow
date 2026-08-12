# MediFlow Database Design (v1)

> Single-hospital scope. No multi-tenant columns. PostgreSQL only.
> v1 timezone: **Asia/Kolkata (IST)** for display; store everything as `TIMESTAMPTZ` (UTC internally).

---

## 1. Conventions

| Concern            | Convention |
| ------------------ | ---------- |
| Primary keys       | `BIGINT GENERATED ALWAYS AS IDENTITY` (no UUIDs in v1 — simpler) |
| Timestamps         | `TIMESTAMPTZ` (store UTC, display in IST) |
| Money              | `NUMERIC(12,2)` — exact decimal, never `FLOAT` |
| Text                | `VARCHAR(n)` for short values, `TEXT` for long free text |
| Enums              | Implemented as `TEXT` columns + `CHECK` constraints (easier to extend than native PG enums) |
| Deletion           | **Soft deletion only** (`status` / `deactivated_at`). Historic rows are never hard-deleted. |
| Emails             | Normalized to lowercase before insert; unique constraint on the column |
| Auto-created fields| `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at` maintained by the app |

---

## 2. Enum Values (as CHECK constraints)

| Column / ENUM          | Allowed values |
| ---------------------- | -------------- |
| `users.role`           | `ADMIN`, `DOCTOR`, `RECEPTIONIST`, `PATIENT` |
| `users.status`         | `ACTIVE`, `DEACTIVATED` |
| `patients.gender`      | `MALE`, `FEMALE`, `OTHER` |
| `patients.blood_group` | `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`, `UNKNOWN` |
| `patient_allergies.severity` | `MILD`, `MODERATE`, `SEVERE` |
| `appointments.status`  | `PENDING`, `CONFIRMED`, `CHECKED_IN`, `COMPLETED`, `CANCELLED`, `NO_SHOW` |
| `appointments.priority`| `NORMAL`, `URGENT`, `EMERGENCY` *(separate from status)* |
| `appointments.appointment_type` | `INITIAL_CONSULTATION`, `FOLLOW_UP` |
| `lab_requests.status`  | `REQUESTED`, `IN_PROGRESS`, `RESULT_READY`, `VERIFIED` |
| `bills.status`         | `PENDING`, `PARTIALLY_PAID`, `PAID`, `OVERDUE`, `REFUNDED` |
| `bill_items.category`  | `CONSULTATION`, `LAB_TEST`, `PROCEDURE`, `SERVICE` |
| `payments.method`      | `CASH`, `CARD`, `UPI`, `BANK_TRANSFER`, `OTHER` |

---

## 3. Tables, Columns, Constraints

### 3.1 `hospital_settings`
Single-row table. `id` is locked to `1` by CHECK to guarantee one row.

| Column        | Type                | Constraints |
| ------------- | ------------------- | ----------- |
| id            | SMALLINT            | **PK**, CHECK `id = 1` |
| hospital_name | VARCHAR(150)        | NOT NULL |
| address       | TEXT                | |
| phone         | VARCHAR(30)         | |
| email         | VARCHAR(255)        | CHECK `email ~ '^.+@.+$'` |
| timezone      | VARCHAR(50)         | NOT NULL DEFAULT `'Asia/Kolkata'` |
| logo_path     | VARCHAR(500)        | |

> No `hospital_id` anywhere in the schema. Adding multi-hospital later → add `hospital_id` FK here and re-use it.

### 3.2 `users`
One row per login account; holds the credentials and role.

| Column           | Type          | Constraints |
| ---------------- | ------------- | ----------- |
| id               | BIGINT        | **PK** |
| email            | VARCHAR(255)  | NOT NULL, **UNIQUE** (stored lowercase) |
| password_hash    | VARCHAR(255)  | NOT NULL (bcrypt) |
| role             | TEXT          | NOT NULL, CHECK in (`ADMIN`,`DOCTOR`,`RECEPTIONIST`,`PATIENT`) |
| status           | TEXT          | NOT NULL DEFAULT `'ACTIVE'`, CHECK in (`ACTIVE`,`DEACTIVATED`) |
| failed_attempts  | SMALLINT      | NOT NULL DEFAULT 0 |
| locked_until     | TIMESTAMPTZ   | NULL = not locked |
| deactivated_at   | TIMESTAMPTZ   | NULL until deactivated (soft delete) |
| last_login_at    | TIMESTAMPTZ   | |
| created_at       | TIMESTAMPTZ   | NOT NULL DEFAULT now() |
| updated_at       | TIMESTAMPTZ   | NOT NULL DEFAULT now() |

**Constraints:**
- UNIQUE (`email`)
- CHECK `failed_attempts BETWEEN 0 AND 5`

**Indexes:** idx_users_role (`role`)

### 3.3 `patients`

| Column                  | Type          | Constraints |
| ----------------------- | ------------- | ----------- |
| id                      | BIGINT        | **PK** |
| user_id                 | BIGINT        | NOT NULL, **FK → `users.id`**, **UNIQUE** (1:1) |
| mrn                     | VARCHAR(20)   | NOT NULL, **UNIQUE** — e.g. `PT-000001` |
| first_name              | VARCHAR(100)  | NOT NULL |
| last_name               | VARCHAR(100)  | NOT NULL |
| dob                     | DATE          | CHECK `dob <= CURRENT_DATE` |
| gender                  | TEXT          | CHECK in (`MALE`,`FEMALE`,`OTHER`) |
| blood_group             | TEXT          | CHECK in (`A+`,`A-`,`B+`,`B-`,`AB+`,`AB-`,`O+`,`O-`,`UNKNOWN`) |
| height_cm               | NUMERIC(5,1)  | CHECK `height_cm > 0 AND height_cm < 300` |
| weight_kg               | NUMERIC(5,1)  | CHECK `weight_kg > 0 AND weight_kg < 500` |
| emergency_contact_name  | VARCHAR(150)  | |
| emergency_contact_phone | VARCHAR(30)   | |
| address                 | TEXT          | |
| created_at              | TIMESTAMPTZ   | NOT NULL DEFAULT now() |
| updated_at              | TIMESTAMPTZ   | NOT NULL DEFAULT now() |

**Indexes:** unique on `mrn` (automatic); idx_patients_name (`last_name`, `first_name`) for name search. Optional later: `pg_trgm` for fuzzy name search.

### 3.4 `doctors`

| Column            | Type         | Constraints |
| ----------------- | ------------ | ----------- |
| id                | BIGINT       | **PK** |
| user_id           | BIGINT       | NOT NULL, **FK → `users.id`**, **UNIQUE** (1:1) |
| license_number    | VARCHAR(50)  | **UNIQUE** |
| consultation_fee  | NUMERIC(12,2)| NOT NULL DEFAULT 0, CHECK `>= 0` |
| created_at        | TIMESTAMPTZ  | NOT NULL DEFAULT now() |
| updated_at        | TIMESTAMPTZ  | NOT NULL DEFAULT now() |

### 3.5 `receptionists`

| Column         | Type         | Constraints |
| -------------- | ------------ | ----------- |
| id             | BIGINT       | **PK** |
| user_id        | BIGINT       | NOT NULL, **FK → `users.id`**, **UNIQUE** (1:1) |
| employee_code  | VARCHAR(50)  | **UNIQUE** |
| created_at     | TIMESTAMPTZ  | NOT NULL DEFAULT now() |
| updated_at     | TIMESTAMPTZ  | NOT NULL DEFAULT now() |

### 3.6 `patient_allergies`
Enables the recorded-allergy match at prescription time.

| Column      | Type        | Constraints |
| ----------- | ----------- | ----------- |
| id          | BIGINT      | **PK** |
| patient_id  | BIGINT      | NOT NULL, **FK → `patients.id`** |
| allergen    | VARCHAR(150)| NOT NULL (normalized: trimmed, lowercased) |
| severity    | TEXT        | CHECK in (`MILD`,`MODERATE`,`SEVERE`) |
| notes       | TEXT        | |
| created_by  | BIGINT      | **FK → `users.id`** |
| created_at  | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:** idx_patient_allergies_patient (`patient_id`)

### 3.7 `departments`

| Column      | Type         | Constraints |
| ----------- | ------------ | ----------- |
| id          | BIGINT       | **PK** |
| name        | VARCHAR(150) | NOT NULL, **UNIQUE** |
| description | TEXT         | |
| is_active   | BOOLEAN      | NOT NULL DEFAULT true (soft-close instead of DELETE) |
| created_at  | TIMESTAMPTZ  | NOT NULL DEFAULT now() |

### 3.8 `doctor_departments`
Many-to-many join between doctors and departments.

| Column         | Type   | Constraints |
| -------------- | ------ | ----------- |
| doctor_id      | BIGINT | **FK → `doctors.id`**, part of composite **PK** |
| department_id  | BIGINT | **FK → `departments.id`**, part of composite **PK** |

**PK:** (`doctor_id`, `department_id`)

### 3.9 `doctor_schedules`
Recurring weekly working schedule per doctor.

| Column      | Type     | Constraints |
| ----------- | -------- | ----------- |
| id          | BIGINT   | **PK** |
| doctor_id   | BIGINT   | NOT NULL, **FK → `doctors.id`** |
| day_of_week | SMALLINT | NOT NULL, CHECK `0 (Sun) … 6 (Sat)` |
| start_time  | TIME     | NOT NULL |
| end_time    | TIME     | NOT NULL, CHECK `end_time > start_time` |

**Unique:** (`doctor_id`, `day_of_week`, `start_time`)

### 3.10 `doctor_unavailable`
One-off blocked dates (holidays, leave), set by doctor or admin.

| Column      | Type        | Constraints |
| ----------- | ----------- | ----------- |
| id          | BIGINT      | **PK** |
| doctor_id   | BIGINT      | NOT NULL, **FK → `doctors.id`** |
| from_date   | DATE        | NOT NULL |
| to_date     | DATE        | NOT NULL, CHECK `to_date >= from_date` |
| reason      | VARCHAR(200)| |
| created_by  | BIGINT      | **FK → `users.id`** |
| created_at  | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:** idx_doc_unavail_doctor (`doctor_id`, `from_date`, `to_date`)

### 3.11 `appointments`
The core scheduling table.

| Column            | Type        | Constraints |
| ----------------- | ----------- | ----------- |
| id                | BIGINT      | **PK** |
| patient_id        | BIGINT      | NOT NULL, **FK → `patients.id`** |
| doctor_id         | BIGINT      | NOT NULL, **FK → `doctors.id`** |
| department_id     | BIGINT      | NOT NULL, **FK → `departments.id`** (denormalized for reporting) |
| date_time         | TIMESTAMPTZ | NOT NULL |
| duration_minutes  | SMALLINT    | NOT NULL DEFAULT 30, CHECK `BETWEEN 5 AND 480` |
| priority          | TEXT        | NOT NULL DEFAULT `'NORMAL'`, CHECK in (`NORMAL`,`URGENT`,`EMERGENCY`) |
| status            | TEXT        | NOT NULL DEFAULT `'PENDING'`, CHECK in (`PENDING`,`CONFIRMED`,`CHECKED_IN`,`COMPLETED`,`CANCELLED`,`NO_SHOW`) |
| appointment_type  | TEXT        | NOT NULL DEFAULT `'INITIAL_CONSULTATION'`, CHECK in (`INITIAL_CONSULTATION`,`FOLLOW_UP`) |
| reason            | TEXT        | |
| created_by        | BIGINT      | NOT NULL, **FK → `users.id`** (patient, receptionist, or admin) |
| created_at        | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at        | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:**
- idx_appt_doctor_time (`doctor_id`, `date_time`)
- idx_appt_patient (`patient_id`, `date_time`)
- idx_appt_status_date (`status`, `date_time`) — for today lists & dashboards

**Overlap protection → see Section 6.**

> The 24-hour cancel/reschedule rule and admin override are **application policy**, enforced in service code, not the DB.

### 3.12 `medical_records`
Immutable anchor row. Always created first; **never updated or deleted**.

| Column          | Type        | Constraints |
| --------------- | ----------- | ----------- |
| id              | BIGINT      | **PK** |
| appointment_id  | BIGINT      | NOT NULL, **FK → `appointments.id`** |
| patient_id      | BIGINT      | NOT NULL, **FK → `patients.id`** |
| doctor_id       | BIGINT      | NOT NULL, **FK → `doctors.id`** |
| latest_version  | INTEGER     | NOT NULL DEFAULT 1 |
| created_at      | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Unique:** (`appointment_id`) — one record per appointment.

### 3.13 `medical_record_versions`
Append-only version history. One row per edit → satisfies "no silent overwrite" + audit (who / when).

| Column         | Type        | Constraints |
| -------------- | ----------- | ----------- |
| id             | BIGINT      | **PK** |
| record_id      | BIGINT      | NOT NULL, **FK → `medical_records.id`** |
| version_number | INTEGER     | NOT NULL, CHECK `>= 1` |
| symptoms       | TEXT        | |
| diagnosis      | TEXT        | |
| vitals_json    | JSONB       | e.g. `{"bp":"120/80","pulse":"72"}` |
| notes          | TEXT        | |
| changed_by     | BIGINT      | NOT NULL, **FK → `users.id`** (only DOCTOR) |
| changed_at     | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Unique:** (`record_id`, `version_number`)

### 3.14 `prescriptions`

| Column           | Type        | Constraints |
| ---------------- | ----------- | ----------- |
| id               | BIGINT      | **PK** |
| medical_record_id| BIGINT      | NOT NULL, **FK → `medical_records.id`** |
| doctor_id        | BIGINT      | NOT NULL, **FK → `doctors.id`** |
| patient_id       | BIGINT      | NOT NULL, **FK → `patients.id`** |
| created_at       | TIMESTAMPTZ | NOT NULL DEFAULT now() |

> Allergy warning is computed **at creation time** by the app: match `prescription_items.medicine_name` against `patient_allergies.allergen` and return an **informational warning** in the API response. This is NOT a clinical decision-support system — it never blocks a prescription.

### 3.15 `prescription_items`

| Column            | Type        | Constraints |
| ----------------- | ----------- | ----------- |
| id                | BIGINT      | **PK** |
| prescription_id   | BIGINT      | NOT NULL, **FK → `prescriptions.id`** |
| medicine_name     | VARCHAR(200)| NOT NULL (lowercased for matching) |
| dosage            | VARCHAR(100)| NOT NULL |
| frequency         | VARCHAR(100)| NOT NULL |
| duration_in_days  | SMALLINT    | CHECK `> 0` |

### 3.16 `lab_requests`

| Column        | Type        | Constraints |
| ------------- | ----------- | ----------- |
| id            | BIGINT      | **PK** |
| appointment_id| BIGINT      | NOT NULL, **FK → `appointments.id`** |
| patient_id    | BIGINT      | NOT NULL, **FK → `patients.id`** |
| doctor_id     | BIGINT      | NOT NULL, **FK → `doctors.id`** |
| test_name     | VARCHAR(200)| NOT NULL |
| notes         | TEXT        | |
| status        | TEXT        | NOT NULL DEFAULT `'REQUESTED'`, CHECK in (`REQUESTED`,`IN_PROGRESS`,`RESULT_READY`,`VERIFIED`) |
| result_details| TEXT        | |
| report_file_path | VARCHAR(500) | (Multer upload; random filename, no leaks) |
| requested_at  | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| verified_by   | BIGINT      | NULL, **FK → `doctors.id`** (only set when `STATUS = VERIFIED`) |
| verified_at   | TIMESTAMPTZ | NULL |

**Indexes:** idx_lab_patient (`patient_id`, `status`)

### 3.17 `bills`

| Column         | Type        | Constraints |
| -------------- | ----------- | ----------- |
| id             | BIGINT      | **PK** |
| bill_number    | VARCHAR(20) | NOT NULL, **UNIQUE** — e.g. `INV-000001` (used on PDF) |
| patient_id     | BIGINT      | NOT NULL, **FK → `patients.id`** |
| appointment_id | BIGINT      | NOT NULL, **FK → `appointments.id`** |
| status         | TEXT        | NOT NULL DEFAULT `'PENDING'`, CHECK in (`PENDING`,`PARTIALLY_PAID`,`PAID`,`OVERDUE`,`REFUNDED`) |
| due_date       | DATE        | |
| created_at     | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at     | TIMESTAMPTZ | NOT NULL DEFAULT now() |

> `total` is **computed** as `SUM(bill_items.quantity * unit_price)` whenever needed — never stored.

### 3.18 `bill_items`

| Column      | Type         | Constraints |
| ----------- | ------------ | ----------- |
| id          | BIGINT       | **PK** |
| bill_id     | BIGINT       | NOT NULL, **FK → `bills.id`** |
| description | VARCHAR(200) | NOT NULL |
| category    | TEXT         | NOT NULL, CHECK in (`CONSULTATION`,`LAB_TEST`,`PROCEDURE`,`SERVICE`) |
| quantity    | SMALLINT     | NOT NULL DEFAULT 1, CHECK `> 0` |
| unit_price  | NUMERIC(12,2)| NOT NULL, CHECK `>= 0` |

### 3.19 `payments`

| Column               | Type         | Constraints |
| -------------------- | ------------ | ----------- |
| id                   | BIGINT       | **PK** |
| bill_id              | BIGINT       | NOT NULL, **FK → `bills.id`** |
| amount               | NUMERIC(12,2)| NOT NULL, CHECK `> 0` |
| method               | TEXT         | NOT NULL, CHECK in (`CASH`,`CARD`,`UPI`,`BANK_TRANSFER`,`OTHER`) |
| transaction_reference| VARCHAR(255) | NULL (manual entry in v1 — no real gateway) |
| paid_at              | TIMESTAMPTZ  | NOT NULL DEFAULT now() |
| recorded_by          | BIGINT       | **FK → `users.id`** (admin/receptionist) |

**Partial unique index:** `UNIQUE WHERE transaction_reference IS NOT NULL` (if provided, must be unique).

### 3.20 `notifications`

| Column     | Type        | Constraints |
| ---------- | ----------- | ----------- |
| id         | BIGINT      | **PK** |
| user_id    | BIGINT      | NOT NULL, **FK → `users.id`** |
| type       | VARCHAR(50) | NOT NULL (e.g. `APPOINTMENT_REMINDER`, `APPOINTMENT_CONFIRMED`, `LAB_READY`, `BILL_CREATED`) |
| message    | TEXT        | NOT NULL |
| channel    | TEXT        | NOT NULL, CHECK in (`IN_APP`,`EMAIL`) |
| is_read    | BOOLEAN     | NOT NULL DEFAULT false |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:** idx_notif_user (`user_id`, `is_read`)

### 3.21 `refresh_tokens`

| Column      | Type        | Constraints |
| ----------- | ----------- | ----------- |
| id          | BIGINT      | **PK** |
| user_id     | BIGINT      | NOT NULL, **FK → `users.id`** |
| token_hash  | VARCHAR(255)| NOT NULL, **UNIQUE** (never store raw tokens) |
| expires_at  | TIMESTAMPTZ | NOT NULL |
| revoked_at  | TIMESTAMPTZ | NULL |

**Indexes:** idx_refresh_user (`user_id`)

### 3.22 `audit_logs`
Append-only. Every sensitive read/write is logged.

| Column       | Type        | Constraints |
| ------------ | ----------- | ----------- |
| id           | BIGINT      | **PK** |
| user_id      | BIGINT      | NULL, **FK → `users.id`** (NULL = system) |
| action       | VARCHAR(50) | NOT NULL (e.g. `RECORD_VIEW`, `RECORD_UPDATE`, `LOGIN`) |
| entity_type  | VARCHAR(50) | NOT NULL (e.g. `APPOINTMENT`, `MEDICAL_RECORD`) |
| entity_id    | BIGINT      | |
| ip_address   | VARCHAR(45) | |
| created_at   | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:** idx_audit_entity (`entity_type`, `entity_id`), idx_audit_time (`created_at`)

---

## 4. Relationships Summary

```
users ──1:1── patients        users ──1:1── doctors      users ──1:1── receptionists
patients ──1:N── patient_allergies
doctors ──N:M── departments   (via doctor_departments)
doctors ──1:N── doctor_schedules
doctors ──1:N── doctor_unavailable
patients ──1:N── appointments ◄──N:1── doctors
appointments ──1:1── bills          appointments ──1:1── medical_records
appointments ──1:N── lab_requests
bills ──1:N── bill_items            bills ──1:N── payments
medical_records ──1:N── medical_record_versions
medical_records ──1:N── prescriptions ◄──1:N── prescription_items
users ──1:N── notifications          users ──1:N── refresh_tokens      users ──1:N── audit_logs
```

- **1:1** — `users` → profile tables (a user is exactly one of patient/doctor/receptionist; enforced by app + unique FKs).
- **N:M** — doctors ↔ departments.
- Everything historical references `users.id`, so deactivated/deleted users keep records intact.

---

## 5. MRN / Bill Number Generation

- `PT-000001` style → app allocates next value from a database **sequence**, formats with zero-padding, retries on the rare unique-collision. The `UNIQUE` index is the safety net.

---

## 6. Appointment Concurrency / Double-Booking Strategy

Target: **no overlapping *active* appointments per doctor, per minute**, while CANCELLED / NO_SHOW slots are immediately reusable without deleting rows.

### 6.1 Database-level guarantee (the hard floor)

Requires the `btree_gist` extension (combines b-tree search on one column with range overlap on another):

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Exact same start time AND any overlap are blocked by the same rule:
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE appointments
  ADD CONSTRAINT no_overlapping_active_appointments
  EXCLUDE USING gist (
    doctor_id                      WITH =,
    tstzrange(
      date_time,
      date_time + (duration_minutes || ' minutes')::interval
    )                              WITH &&
  )
  WHERE (status NOT IN ('CANCELLED', 'NO_SHOW'))
  DEFERRABLE INITIALLY IMMEDIATE;
```

How it behaves:
- **Booking a slot** → the range `[start, start + duration)` must NOT overlap any other *active* appointment of the same doctor. Overlap → the INSERT fails at the DB level.
- **Cancelling** → status becomes `CANCELLED` → row drops out of the guarded set → slot reusable immediately.
- Uses `duration_minutes` → catches both identical start times **and** true overlaps (e.g. 09:00 + 45 min vs 09:30 + 45 min).
- `DEFERRABLE INITIALLY IMMEDIATE` keeps it checked normally, but allows a reschedule to flip status/rebook inside one transaction if needed.

> Simpler alternative if you want to avoid the extension: a **partial unique index** `UNIQUE(doctor_id, date_time) WHERE status NOT IN ('CANCELLED','NO_SHOW')`. Downside: it only blocks the *exact same start time*, not partial overlaps — acceptable only if you enforce fixed-length slots in the app.

### 6.2 Backend layer (friendly errors)

1. Service validates against `doctor_schedules` + `doctor_unavailable` + the 24h-policy before INSERT.
2. On a constraint violation (`23505` / exclusion error) the API maps it to a readable `409 CONFLICT` "doctor unavailable at this time" response.
3. Concurrency: two simultaneous overlapping bookings are safe — Postgres lets one proceed and rejects the second (constraint enforced at insert/commit; app should catch and retry-with-clear-message if desired).

### 6.3 What the DB does NOT enforce (application policy only)

- The **24-hour cancel/reschedule deadline** and **admin override** — service code.
- That a booking falls inside working hours — service code (schedule tables exist for that check).

---

## 7. Role Permissions (feature matrix)

| Capability                              | PATIENT | DOCTOR | RECEPTIONIST | ADMIN |
| --------------------------------------- | :-----: | :----: | :----------: | :---: |
| Self-register                          | ✅      | ❌     | ❌           | ❌    |
| Create doctor/receptionist accounts     | ❌      | ❌     | ❌           | ✅    |
| Create patient accounts                 | ✅ self | ✅     | ✅           | ✅    |
| View own profile                        | ✅      | ✅     | ✅           | ✅    |
| Update own profile                      | ✅      | ✅     | ✅           | ✅    |
| Search patients (name / MRN)            | ❌      | 🚧     | ✅           | ✅    |
| Book / reschedule / cancel appointment  | ✅ self | 🚧 assigned | ✅ on behalf | ✅ all |
| Override appointment restrictions       | ❌      | ❌     | ❌           | ✅    |
| Check-in appointments                   | ❌      | ❌     | ✅           | ✅    |
| View patient's medical records          | own     | own consults | ❌     | ✅    |
| Create / update medical records         | ❌      | ✅     | ❌           | ❌    |
| Create prescriptions                    | ❌      | ✅     | ❌           | ❌    |
| Request lab tests                       | ❌      | ✅     | ❌           | ❌    |
| Verify lab results                      | ❌      | ✅     | ❌           | ✅    |
| View verified lab results               | own     | own consults | ❌     | ✅    |
| View bills                              | own     | consultations | ❌   | ✅    |
| Record payments                         | ❌      | ❌     | ✅           | ✅    |
| Manage departments / hospital settings  | ❌      | ❌     | ❌           | ✅    |
| View dashboard statistics               | ❌ own data | ✅ own | 🚧 today list | ✅ all |
| View audit log                          | ❌      | ❌     | ❌           | ✅    |

- 🚧 = with restriction: DOCTOR only for assigned/consulted patients; RECEPTIONIST only today's appointment list, never clinical data.
- **Enforcement must happen server-side** on every endpoint (IDOR protection), never only in the UI.

---

## 8. Open Items (before implementation)

- Confirm whether `NO_SHOW` should also auto-free the slot (yes, per this design) and whether it requires explicit action by the doctor/admin afterward.
- Reaction to a `no_overlapping_active_appointments` reject should read "no free slot" — decide the exact 409 body during API design.
- `vitals_json` key naming convention (store keys like `bp`, `pulse`, `temp_c`, `spO2`) to keep records consistent across doctors.