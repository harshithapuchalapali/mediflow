from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import Department, HospitalSettings

IST_TZ = ZoneInfo("Asia/Kolkata")

PAGE_W, _ = A4
USABLE_W = PAGE_W - 30 * mm

DEFAULT_HOSPITAL_NAME = "MediFlow Hospital"


def fmt_date(value):
    if value is None:
        return "-"
    return value.strftime("%d %b %Y")


def fmt_ist(value):
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST_TZ).strftime("%d %b %Y, %I:%M %p")


def fmt_money(value):
    return "{:,.2f}".format(Decimal(value or 0))


def styles():
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "Title", parent=base["Title"], fontSize=16, leading=20, spaceAfter=0
        ),
        "SubTitle": ParagraphStyle(
            "SubTitle",
            parent=base["Normal"],
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#555555"),
        ),
        "PageTitle": ParagraphStyle(
            "PageTitle",
            parent=base["Heading2"],
            fontSize=13,
            leading=17,
            spaceBefore=6,
            spaceAfter=6,
        ),
        "Section": ParagraphStyle(
            "Section",
            parent=base["Heading2"],
            fontSize=11,
            leading=14,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "Cell": ParagraphStyle(
            "Cell", parent=base["Normal"], fontSize=8.5, leading=11
        ),
        "CellB": ParagraphStyle(
            "CellB",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            fontName="Helvetica-Bold",
        ),
        "Small": ParagraphStyle(
            "Small", parent=base["Normal"], fontSize=8, leading=10
        ),
        "SmallB": ParagraphStyle(
            "SmallB",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            fontName="Helvetica-Bold",
        ),
        "Amount": ParagraphStyle(
            "Amount",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            alignment=2,
        ),
        "AmountB": ParagraphStyle(
            "AmountB",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            alignment=2,
            fontName="Helvetica-Bold",
        ),
    }


def build_pdf(story, hospital_name=DEFAULT_HOSPITAL_NAME):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=12 * mm,
        bottomMargin=18 * mm,
        pageCompression=0,
    )

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(15 * mm, 10 * mm, (hospital_name or DEFAULT_HOSPITAL_NAME)[:60])
        canvas.drawRightString(PAGE_W - 15 * mm, 10 * mm, "Page %d" % d.page)
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def add_hospital_header(story, settings, title):
    st = styles()
    name = (settings.hospital_name if settings is not None else None) or DEFAULT_HOSPITAL_NAME
    story.append(Paragraph(escape(name), st["Title"]))
    lines = []
    if settings is not None:
        if settings.address:
            lines.append(escape(settings.address))
        contact = ", ".join(escape(x) for x in (settings.phone, settings.email) if x)
        if contact:
            lines.append(contact)
    if lines:
        story.append(Spacer(1, 1))
        story.append(Paragraph("<br/>".join(lines), st["SubTitle"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#888888")))
    story.append(Paragraph(escape(title), st["PageTitle"]))


def key_value_table(story, rows):
    st = styles()
    data = []
    for key, value in rows:
        if value is None or value == "":
            continue
        data.append(
            [
                Paragraph(escape(str(key)), st["SmallB"]),
                Paragraph(escape(str(value)).replace("\n", "<br/>"), st["Small"]),
            ]
        )
    if not data:
        return
    table = Table(data, colWidths=[USABLE_W * 0.32, USABLE_W * 0.68], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f2f2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6))


def data_table(story, headers, rows, col_widths=None):
    st = styles()
    data = [[Paragraph(escape(str(h)), st["CellB"]) for h in headers]]
    for row in rows:
        data.append([Paragraph(escape(str(c)).replace("\n", "<br/>"), st["Cell"]) for c in row])
    widths = col_widths or [USABLE_W / len(headers)] * len(headers)
    table = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#aaaaaa")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6))


def totals_table(story, rows):
    st = styles()
    data = [[Paragraph(escape(str(k)), st["Amount"]), Paragraph(escape(str(v)), st["AmountB"])] for k, v in rows]
    table = Table(data, colWidths=[USABLE_W * 0.68, USABLE_W * 0.32], hAlign="RIGHT")
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#888888")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4))


def add_generated_note(story):
    st = styles()
    now = datetime.now(timezone.utc)
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#aaaaaa")))
    story.append(Spacer(1, 3))
    story.append(
        Paragraph(
            "Generated automatically by MediFlow on %s (IST)." % fmt_ist(now),
            st["Small"],
        )
    )


def department_name(db, department_id):
    if department_id is None:
        return None
    dept = db.get(Department, department_id)
    return dept.name if dept is not None else None