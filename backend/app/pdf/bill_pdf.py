from reportlab.lib.units import mm
from reportlab.platypus import Paragraph

from app.billing.service import bill_totals
from app.models import Bill
from app.pdf.pdf_common import (
    add_generated_note,
    add_hospital_header,
    build_pdf,
    data_table,
    department_name,
    fmt_date,
    fmt_ist,
    fmt_money,
    key_value_table,
    styles,
    totals_table,
)

DOC_TITLE = "Hospital Bill / Invoice"


def bill_pdf_bytes(db, bill: Bill, settings=None):
    st = styles()
    story = []
    add_hospital_header(story, settings, DOC_TITLE)

    appointment = bill.appointment
    header_rows = [
        ("Bill Number", bill.bill_number),
        ("Status", bill.status),
        ("Bill Date", fmt_ist(bill.created_at)),
        ("Due Date", fmt_date(bill.due_date)),
        ("Last Updated", fmt_ist(bill.updated_at)),
    ]
    if appointment is not None:
        header_rows.append(("Appointment Date", fmt_ist(appointment.date_time)))
        header_rows.append(("Appointment Status", appointment.status))
        dept = department_name(db, appointment.department_id)
        if dept:
            header_rows.append(("Department", dept))
    key_value_table(story, header_rows)

    patient = bill.patient
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
            ("Address", patient.address),
            ("Emergency Contact", patient.emergency_contact_name),
            ("Emergency Phone", patient.emergency_contact_phone),
        ],
    )

    if appointment is not None and appointment.doctor is not None:
        doctor = appointment.doctor
        story.append(Paragraph("Doctor", st["Section"]))
        key_value_table(
            story,
            [
                ("Email", doctor.user.email if doctor.user else None),
                ("License Number", doctor.license_number),
                ("Consultation Fee", fmt_money(doctor.consultation_fee)),
            ],
        )

    story.append(Paragraph("Bill Items", st["Section"]))
    headers = ["#", "Description", "Category", "Qty", "Unit Price", "Amount"]
    rows = []
    for index, item in enumerate(bill.items, start=1):
        rows.append(
            [
                index,
                item.description,
                item.category,
                item.quantity,
                fmt_money(item.unit_price),
                fmt_money(item.quantity * item.unit_price),
            ]
        )
    data_table(
        story,
        headers,
        rows,
        col_widths=[9 * mm, 60 * mm, 30 * mm, 12 * mm, 28 * mm, 41 * mm],
    )

    total, paid = bill_totals(bill)
    totals_table(
        story,
        [
            ("Total Amount", "INR %s" % fmt_money(total)),
            ("Amount Paid", "INR %s" % fmt_money(paid)),
            ("Balance Due", "INR %s" % fmt_money(total - paid)),
        ],
    )

    if bill.payments:
        story.append(Paragraph("Payments", st["Section"]))
        pay_rows = [
            [
                "INR %s" % fmt_money(p.amount),
                p.method,
                p.transaction_reference or "-",
                fmt_ist(p.paid_at),
            ]
            for p in bill.payments
        ]
        data_table(
            story,
            ["Amount", "Method", "Transaction Reference", "Paid At"],
            pay_rows,
        )

    add_generated_note(story)
    return build_pdf(story, settings.hospital_name if settings is not None else None)