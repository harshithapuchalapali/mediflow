from reportlab.lib.units import mm
from reportlab.platypus import Paragraph

from app.models import Prescription
from app.pdf.pdf_common import (
    add_generated_note,
    add_hospital_header,
    build_pdf,
    data_table,
    department_name,
    fmt_date,
    fmt_ist,
    key_value_table,
    styles,
)

DOC_TITLE = "Prescription"


def prescription_pdf_bytes(db, prescription: Prescription, settings=None):
    st = styles()
    story = []
    add_hospital_header(story, settings, DOC_TITLE)

    header_rows = [
        ("Prescription ID", prescription.id),
        ("Prescribed On", fmt_ist(prescription.created_at)),
    ]
    medical_record = prescription.medical_record
    appointment = medical_record.appointment if medical_record is not None else None
    if appointment is not None:
        header_rows.append(("Consultation Date", fmt_ist(appointment.date_time)))
        header_rows.append(("Appointment Status", appointment.status))
        dept = department_name(db, appointment.department_id)
        if dept:
            header_rows.append(("Department", dept))
    key_value_table(story, header_rows)

    patient = prescription.patient
    story.append(Paragraph("Patient Details", st["Section"]))
    key_value_table(
        story,
        [
            ("Patient Name", "%s %s" % (patient.first_name, patient.last_name)),
            ("Email", patient.user.email if patient.user else None),
            ("MRN", patient.mrn),
            ("Date of Birth", fmt_date(patient.dob)),
            ("Gender", patient.gender),
            ("Blood Group", patient.blood_group),
        ],
    )

    doctor = prescription.doctor
    story.append(Paragraph("Doctor", st["Section"]))
    key_value_table(
        story,
        [
            ("Email", doctor.user.email if doctor.user else None),
            ("License Number", doctor.license_number),
        ],
    )

    story.append(Paragraph("Medicines", st["Section"]))
    headers = ["#", "Medicine", "Dosage", "Frequency", "Duration"]
    rows = []
    for index, item in enumerate(prescription.items, start=1):
        rows.append(
            [
                index,
                item.medicine_name,
                item.dosage,
                item.frequency,
                "%d day(s)" % item.duration_in_days,
            ]
        )
    data_table(
        story,
        headers,
        rows,
        col_widths=[9 * mm, 61 * mm, 36 * mm, 49 * mm, 25 * mm],
    )

    add_generated_note(story)
    return build_pdf(story, settings.hospital_name if settings is not None else None)