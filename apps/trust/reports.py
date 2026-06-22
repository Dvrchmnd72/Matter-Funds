import csv
import io
import zipfile
import datetime
from decimal import Decimal

from django.http import HttpResponse
from django.db.models import Q
from django.utils import timezone

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from .models import TrustTransaction, MatterLedger, MonthlyReconciliation, Irregularity, TrustJournal, TrustAccount


FOOTER_TEXT = "Prepared from Matter Funds \u2014 refer to LPUGR Part 4.2"


def _build_header_info(trust_account):
    firm = trust_account.firm
    account_name = getattr(trust_account, "name", None) or getattr(trust_account, "account_name", "")
    account_label = "Controlled Money Account" if hasattr(trust_account, "account_name") else "Trust Account"
    return [
        f"Firm: {firm.name}",
        f"ABN: {firm.abn}",
        f"{account_label}: {account_name}",
        f"BSB: {trust_account.bsb}  Account: {trust_account.account_number}",
    ]


def _make_pdf_response(filename):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _pdf_response_from_bytes(filename, pdf_bytes):
    response = _make_pdf_response(filename)
    response.write(pdf_bytes)
    return response


def _build_pdf_document(buffer, trust_account, title, period_str, rows, col_headers):
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5*cm, rightMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    elements = []

    elements.append(Paragraph(title, styles['Heading1']))
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, styles['Normal']))
    elements.append(Paragraph(f"Period: {period_str}", styles['Normal']))
    elements.append(Spacer(1, 0.5*cm))

    table_data = [col_headers] + rows
    t = Table(table_data, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(FOOTER_TEXT, styles['Italic']))
    doc.build(elements)


def receipts_journal_pdf(trust_account, date_from, date_to):
    return _pdf_response_from_bytes(
        f'receipts_journal_{date_from}_{date_to}.pdf',
        receipts_cash_book_pdf_bytes(trust_account, date_from, date_to),
    )


def receipts_cash_book_pdf_bytes(trust_account, date_from, date_to):
    transactions = (
        TrustTransaction.objects
        .filter(matter_ledger__trust_account=trust_account)
        .filter(
            Q(transaction_type='receipt', created_at__date__range=(date_from, date_to))
            | Q(transaction_type='reversal', reverses__transaction_type='receipt', date_received_or_paid__range=(date_from, date_to))
        )
        .select_related('matter_ledger__matter', 'receipt', 'reverses', 'reverses__receipt')
        .order_by('date_received_or_paid', 'created_at', 'pk')
    )

    buffer = io.BytesIO()
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    normal = styles["Normal"].clone("receipts_cash_book_cell")
    normal.fontSize = 6
    normal.leading = 7

    header_style = styles["Normal"].clone("receipts_cash_book_header")
    header_style.fontName = "Helvetica-Bold"
    header_style.fontSize = 6
    header_style.leading = 7
    header_style.textColor = colors.whitesmoke

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.0 * cm,
        rightMargin=1.0 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    elements = [Paragraph("Trust Receipts Cash Book", title_style)]
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, styles["Normal"]))
    elements.append(Paragraph(f"Period: {date_from} to {date_to}", styles["Normal"]))
    elements.append(Spacer(1, 0.3 * cm))

    col_headers = [
        "Date recorded",
        "Date received if different",
        "Date deposited",
        "Receipt / ref",
        "Matter",
        "Received from / reason",
        "Form",
        "Receipt amt",
        "Deposited amt",
        "Ledger",
    ]

    rows = []
    for txn in transactions:
        if txn.transaction_type == 'reversal' and txn.reverses_id:
            original = txn.reverses
            try:
                receipt = original.receipt
            except Exception:
                receipt = None

            matter = txn.matter_ledger.matter
            rows.append([
                str(txn.date_received_or_paid),
                "",
                "",
                f"Receipt #{receipt.receipt_number} reversal" if receipt else f"Txn #{original.pk} reversal",
                str(matter),
                txn.description,
                receipt.get_payment_method_display() if receipt else "",
                f"-{txn.amount}",
                "",
                str(txn.matter_ledger),
            ])
            continue

        try:
            receipt = txn.receipt
        except Exception:
            receipt = None

        date_made_out = receipt.date_made_out if receipt else timezone.localdate(txn.created_at)
        date_received = txn.date_received_or_paid
        date_received_if_different = str(date_received) if date_received != date_made_out else ""
        date_deposited = str(txn.date_banked or "") if receipt and receipt.uses_separate_deposit_date else ""
        amount_deposited = str(txn.amount) if date_deposited else ""

        rows.append([
            str(date_made_out or ""),
            date_received_if_different,
            date_deposited,
            str(receipt.receipt_number) if receipt else "",
            str(txn.matter_ledger.matter),
            receipt.payor_name if receipt else txn.description,
            receipt.get_payment_method_display() if receipt else "",
            str(txn.amount),
            amount_deposited,
            str(txn.matter_ledger),
        ])

    table_data = [[Paragraph(h, header_style) for h in col_headers]]
    table_data += [
        [Paragraph(str(cell or ""), normal) for cell in row]
        for row in rows
    ]

    table = Table(
        table_data,
        colWidths=[
            1.9 * cm, 2.3 * cm, 2.0 * cm, 2.2 * cm, 3.0 * cm,
            4.0 * cm, 1.5 * cm, 1.9 * cm, 2.0 * cm, 4.9 * cm,
        ],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTSIZE", (0, 0), (-1, -1), 6),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))
    doc.build(elements)

    return buffer.getvalue()


def payments_journal_pdf(trust_account, date_from, date_to):
    return _pdf_response_from_bytes(
        f'payments_journal_{date_from}_{date_to}.pdf',
        payments_cash_book_pdf_bytes(trust_account, date_from, date_to),
    )


def payments_cash_book_pdf_bytes(trust_account, date_from, date_to):
    transactions = (
        TrustTransaction.objects
        .filter(matter_ledger__trust_account=trust_account)
        .filter(
            Q(transaction_type__in=['payment', 'transfer_to_office'], date_received_or_paid__range=(date_from, date_to))
            | Q(transaction_type='reversal', reverses__transaction_type__in=['payment', 'transfer_to_office'], date_received_or_paid__range=(date_from, date_to))
        )
        .select_related('matter_ledger__matter', 'payment', 'reverses', 'reverses__payment')
        .order_by('date_received_or_paid', 'created_at', 'pk')
    )

    buffer = io.BytesIO()
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]

    normal = styles["Normal"].clone("payments_cash_book_cell")
    normal.fontSize = 6
    normal.leading = 7

    header_style = styles["Normal"].clone("payments_cash_book_header")
    header_style.fontName = "Helvetica-Bold"
    header_style.fontSize = 6
    header_style.leading = 7
    header_style.textColor = colors.whitesmoke

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.0 * cm,
        rightMargin=1.0 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    elements = [Paragraph("Trust Payments Cash Book", title_style)]
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, styles["Normal"]))
    elements.append(Paragraph(f"Period: {date_from} to {date_to}", styles["Normal"]))
    elements.append(Spacer(1, 0.3 * cm))

    col_headers = [
        "Date paid",
        "Type",
        "Payment / EFT ref",
        "Cheque #",
        "Matter",
        "Payee",
        "Payee BSB / account",
        "Method",
        "Amount",
        "Reason / purpose",
        "Ledger debited",
    ]

    rows = []
    for txn in transactions:
        if txn.transaction_type == 'reversal' and txn.reverses_id:
            original = txn.reverses
            try:
                payment = original.payment
            except Exception:
                payment = None

            method = payment.get_payment_method_display() if payment else ""
            payee_bsb_account = ""
            if payment and payment.payment_method == "eft" and (payment.payee_bsb or payment.payee_account):
                payee_bsb_account = f"{payment.payee_bsb or ''} / {payment.payee_account or ''}"

            rows.append([
                str(txn.date_received_or_paid),
                "Payment reversal",
                payment.display_payment_reference if payment else f"Transaction #{original.pk}",
                payment.cheque_number if payment and payment.cheque_number else "",
                str(txn.matter_ledger.matter),
                payment.payee_name if payment else "",
                payee_bsb_account,
                method,
                f"-{txn.amount}",
                txn.description,
                str(txn.matter_ledger),
            ])
            continue

        try:
            payment = txn.payment
        except Exception:
            payment = None

        payee_bsb_account = ""
        if payment and payment.payment_method == "eft" and (payment.payee_bsb or payment.payee_account):
            payee_bsb_account = f"{payment.payee_bsb or ''} / {payment.payee_account or ''}"

        rows.append([
            str(txn.date_received_or_paid),
            txn.get_transaction_type_display(),
            payment.display_payment_reference if payment else "",
            payment.cheque_number if payment and payment.cheque_number else "",
            str(txn.matter_ledger.matter),
            payment.payee_name if payment else "",
            payee_bsb_account,
            payment.get_payment_method_display() if payment else "",
            str(txn.amount),
            payment.purpose if payment else txn.description,
            str(txn.matter_ledger),
        ])

    table_data = [[Paragraph(h, header_style) for h in col_headers]]
    table_data += [[Paragraph(str(cell or ""), normal) for cell in row] for row in rows]

    table = Table(
        table_data,
        colWidths=[
            1.7 * cm, 1.7 * cm, 1.9 * cm, 2.5 * cm, 2.6 * cm,
            2.7 * cm, 2.8 * cm, 1.4 * cm, 1.5 * cm, 3.8 * cm, 4.8 * cm,
        ],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTSIZE", (0, 0), (-1, -1), 6),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))
    doc.build(elements)

    return buffer.getvalue()


def _cash_book_amounts_for_period(trust_account, date_from, date_to):
    """Return opening, receipts, payments, and closing cash book balances."""
    def receipt_total(qs):
        total = Decimal("0.00")
        for txn in qs:
            if txn.transaction_type == "receipt":
                total += txn.amount
            elif txn.transaction_type == "reversal" and txn.reverses and txn.reverses.transaction_type == "receipt":
                total -= txn.amount
        return total

    def payment_total(qs):
        total = Decimal("0.00")
        for txn in qs:
            if txn.transaction_type in ("payment", "transfer_to_office"):
                total += txn.amount
            elif txn.transaction_type == "reversal" and txn.reverses and txn.reverses.transaction_type in ("payment", "transfer_to_office"):
                total -= txn.amount
        return total

    before = (
        TrustTransaction.objects
        .filter(matter_ledger__trust_account=trust_account, date_received_or_paid__lt=date_from)
        .select_related("reverses")
        .order_by("date_received_or_paid", "created_at", "pk")
    )
    period = (
        TrustTransaction.objects
        .filter(matter_ledger__trust_account=trust_account, date_received_or_paid__range=(date_from, date_to))
        .select_related("reverses")
        .order_by("date_received_or_paid", "created_at", "pk")
    )

    opening = Decimal("0.00")
    for txn in before:
        if txn.transaction_type in ("receipt",):
            opening += txn.amount
        elif txn.transaction_type in ("payment", "transfer_to_office"):
            opening -= txn.amount
        elif txn.transaction_type == "reversal" and txn.reverses:
            if txn.reverses.transaction_type == "receipt":
                opening -= txn.amount
            elif txn.reverses.transaction_type in ("payment", "transfer_to_office"):
                opening += txn.amount

    receipts = receipt_total(period)
    payments = payment_total(period)
    closing = opening + receipts - payments
    return opening, receipts, payments, closing


def trust_cash_book_summary_pdf_bytes(trust_account, date_from, date_to):
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    opening, receipts, payments, closing = _cash_book_amounts_for_period(trust_account, date_from, date_to)
    subtotal = opening + receipts

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    label_style = styles["Normal"]
    label_style.fontName = "Helvetica-Bold"

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    elements = [Paragraph("Trust Cash Book Summary", styles["Heading1"])]
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, normal))
    elements.append(Paragraph(f"Period: {date_from} to {date_to}", normal))
    elements.append(Spacer(1, 0.4 * cm))

    rows = [
        ["Opening balance", f"As at day before {date_from}", f"${opening}"],
        ["Plus receipts for period", f"{date_from} to {date_to}", f"${receipts}"],
        ["Subtotal", "", f"${subtotal}"],
        ["Less payments for period", f"{date_from} to {date_to}", f"${payments}"],
        ["Closing cash book balance", f"As at {date_to}", f"${closing}"],
    ]

    table_data = [
        [Paragraph("Item", label_style), Paragraph("Reference", label_style), Paragraph("Amount", label_style)]
    ]
    table_data += [[Paragraph(str(c), normal) for c in row] for row in rows]

    table = Table(table_data, colWidths=[6.2 * cm, 6.2 * cm, 4.0 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(
        "Summary derived from the Matter Funds trust receipts cash book and trust payments cash book. "
        "Trust journal transfers do not affect the trust cash book balance.",
        styles["Italic"],
    ))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))
    doc.build(elements)

    return buffer.getvalue()


def trust_cash_book_summary_pdf(trust_account, date_from, date_to):
    return _pdf_response_from_bytes(
        f"trust_cash_book_summary_{date_from}_{date_to}.pdf",
        trust_cash_book_summary_pdf_bytes(trust_account, date_from, date_to),
    )


def trust_transfer_journal_pdf_bytes(trust_account, date_from, date_to):
    journals = (
        TrustJournal.objects
        .filter(
            from_ledger__trust_account=trust_account,
            journal_out_txn__date_received_or_paid__range=(date_from, date_to),
        )
        .select_related(
            'from_ledger__matter__client',
            'to_ledger__matter__client',
            'journal_out_txn',
            'created_by',
        )
        .order_by('journal_out_txn__date_received_or_paid', 'pk')
    )

    buffer = io.BytesIO()
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    styles = getSampleStyleSheet()

    title_style = styles["Heading1"]

    normal = styles["Normal"].clone("transfer_journal_normal")
    normal.fontSize = 6
    normal.leading = 7
    normal.textColor = colors.black

    header_style = styles["Normal"].clone("transfer_journal_header")
    header_style.fontName = "Helvetica-Bold"
    header_style.fontSize = 6
    header_style.leading = 7
    header_style.textColor = colors.whitesmoke

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.0 * cm,
        rightMargin=1.0 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    elements = [Paragraph("Trust Transfer Journal", title_style)]
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, styles["Normal"]))
    elements.append(Paragraph(f"Period: {date_from} to {date_to}", styles["Normal"]))
    elements.append(Spacer(1, 0.3 * cm))

    col_headers = [
        "Date",
        "Journal Ref",
        "From ledger account",
        "To ledger account",
        "Reason",
        "Debit",
        "Credit",
        "Authority date",
        "Authorised by",
    ]

    rows = []
    for journal in journals:
        from_matter = journal.from_ledger.matter
        to_matter = journal.to_ledger.matter

        from_details = (
            f"{from_matter.client.name}\n"
            f"Ref: {from_matter.file_number or journal.from_ledger_id}\n"
            f"{from_matter.description}"
        )
        to_details = (
            f"{to_matter.client.name}\n"
            f"Ref: {to_matter.file_number or journal.to_ledger_id}\n"
            f"{to_matter.description}"
        )

        rows.append([
            str(journal.journal_out_txn.date_received_or_paid) if journal.journal_out_txn else "",
            f"J{journal.pk}",
            from_details,
            to_details,
            journal.description,
            f"${journal.amount}",
            f"${journal.amount}",
            str(journal.authority_date),
            journal.authority_signed_by,
        ])

    if not rows:
        rows.append(["", "", "No trust transfer journal entries for this period", "", "", "", "", "", ""])

    table_data = [[Paragraph(h, header_style) for h in col_headers]]
    table_data += [[Paragraph(str(cell or "").replace("\n", "<br/>"), normal) for cell in row] for row in rows]

    table = Table(
        table_data,
        colWidths=[
            1.8 * cm,
            1.8 * cm,
            4.4 * cm,
            4.4 * cm,
            5.2 * cm,
            1.8 * cm,
            1.8 * cm,
            2.2 * cm,
            3.8 * cm,
        ],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (5, 1), (6, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.35 * cm))
    elements.append(Paragraph(
        "Debit: the trust ledger account from which funds are transferred. "
        "Credit: the trust ledger account to which funds are transferred. "
        "Trust journal transfers do not affect the trust cash book/control account.",
        styles["Italic"],
    ))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(
        "Authority particulars are recorded from the trust journal transfer request / written authority retained with the journal entry.",
        styles["Italic"],
    ))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))

    doc.build(elements)
    return buffer.getvalue()


def trust_transfer_journal_pdf(trust_account, date_from, date_to):
    return _pdf_response_from_bytes(
        f'trust_transfer_journal_{date_from}_{date_to}.pdf',
        trust_transfer_journal_pdf_bytes(trust_account, date_from, date_to),
    )


def matter_ledger_statement_pdf(matter_ledger):
    """Generate a Rule 47-friendly trust ledger account statement."""
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    transactions = (
        TrustTransaction.objects
        .filter(matter_ledger=matter_ledger)
        .select_related(
            "receipt",
            "payment",
            "reverses",
            "reverses__receipt",
            "reverses__payment",
            "journal_as_out__to_ledger__matter__client",
            "journal_as_in__from_ledger__matter__client",
            "matter_ledger__matter__client",
        )
        .order_by("date_received_or_paid", "created_at", "pk")
    )

    trust_account = matter_ledger.trust_account
    matter = matter_ledger.matter
    client = matter.client

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()

    normal = styles["Normal"].clone("trust_ledger_normal")
    normal.fontSize = 6
    normal.leading = 7
    normal.textColor = colors.black

    header_style = styles["Normal"].clone("trust_ledger_header")
    header_style.fontName = "Helvetica-Bold"
    header_style.fontSize = 6
    header_style.leading = 7
    header_style.textColor = colors.whitesmoke

    title_label = styles["Normal"].clone("trust_ledger_title_label")
    title_label.fontName = "Helvetica-Bold"
    title_label.fontSize = 8
    title_label.leading = 10
    title_label.textColor = colors.black

    title_value = styles["Normal"].clone("trust_ledger_title_value")
    title_value.fontSize = 8
    title_value.leading = 10
    title_value.textColor = colors.black

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.0 * cm,
        rightMargin=1.0 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    elements = [Paragraph("Trust Ledger Account", styles["Heading1"])]

    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, title_value))

    elements.append(Spacer(1, 0.25 * cm))

    title_rows = [
        ["Account Name", client.name],
        ["Address", client.address or ""],
        ["Matter Reference", matter.file_number or ""],
        ["Matter Description", matter.description or ""],
        ["Responsible Legal Practitioner", str(matter.responsible_lawyer) if getattr(matter, "responsible_lawyer_id", None) else ""],
        ["Responsible Principal", str(matter.responsible_lawyer) if getattr(matter, "responsible_lawyer_id", None) else ""],
    ]

    title_table = Table(
        [[Paragraph(a, title_label), Paragraph(str(b or ""), title_value)] for a, b in title_rows],
        colWidths=[5.0 * cm, 22.0 * cm],
    )
    title_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(title_table)
    elements.append(Spacer(1, 0.35 * cm))

    def receipt_ref(receipt):
        return f"R{receipt.receipt_number}" if receipt else ""

    def payment_ref(payment):
        return f"P{payment.payment_number}" if payment else ""

    def reference_for(txn):
        try:
            if txn.transaction_type == "receipt":
                return receipt_ref(txn.receipt)
            if txn.transaction_type in ("payment", "transfer_to_office"):
                return payment_ref(txn.payment)
            if txn.transaction_type == "journal_out" and hasattr(txn, "journal_as_out"):
                return f"J{txn.journal_as_out.pk}"
            if txn.transaction_type == "journal_in" and hasattr(txn, "journal_as_in"):
                return f"J{txn.journal_as_in.pk}"
            if txn.transaction_type == "reversal" and txn.reverses_id:
                original = txn.reverses
                if original.transaction_type == "receipt":
                    return f"{receipt_ref(original.receipt)} reversal"
                if original.transaction_type in ("payment", "transfer_to_office"):
                    return f"{payment_ref(original.payment)} reversal"
                return f"Txn {original.pk} reversal"
        except Exception:
            return f"Txn {txn.pk}"
        return f"Txn {txn.pk}"

    def transaction_type_label(txn):
        if txn.transaction_type == "reversal" and txn.reverses_id:
            original = txn.reverses
            if original.transaction_type == "receipt":
                return "Receipt reversal"
            if original.transaction_type in ("payment", "transfer_to_office"):
                return "Payment reversal"
            if original.transaction_type.startswith("journal"):
                return "Journal reversal"
        return txn.get_transaction_type_display()

    def counterparty_for(txn):
        try:
            if txn.transaction_type == "receipt":
                receipt = txn.receipt
                extra = ""
                if txn.date_received_or_paid != receipt.date_made_out:
                    extra = f" | Date received: {txn.date_received_or_paid}"
                return f"{receipt.payor_name}{extra}"

            if txn.transaction_type in ("payment", "transfer_to_office"):
                payment = txn.payment
                details = payment.payee_name
                if payment.payment_method == "eft" and (payment.payee_bsb or payment.payee_account):
                    details += f" | EFT to {payment.payee_bsb or ''} / {payment.payee_account or ''}"
                if payment.payment_method == "cheque" and payment.cheque_number:
                    details += f" | Cheque {payment.cheque_number}"
                return details

            if txn.transaction_type == "journal_out" and hasattr(txn, "journal_as_out"):
                j = txn.journal_as_out
                other = j.to_ledger
                return f"Journal to {other.matter.client.name} | {other.matter.file_number} | {other.matter.description}"

            if txn.transaction_type == "journal_in" and hasattr(txn, "journal_as_in"):
                j = txn.journal_as_in
                other = j.from_ledger
                return f"Journal from {other.matter.client.name} | {other.matter.file_number} | {other.matter.description}"

            if txn.transaction_type == "reversal" and txn.reverses_id:
                original = txn.reverses
                if original.transaction_type == "receipt":
                    return f"Reversal of receipt from {original.receipt.payor_name}"
                if original.transaction_type in ("payment", "transfer_to_office"):
                    return f"Reversal of payment to {original.payment.payee_name}"
                return f"Reversal of transaction #{original.pk}"
        except Exception:
            return txn.description

        return txn.description

    def reason_for(txn):
        try:
            if txn.transaction_type == "receipt":
                return txn.receipt.purpose
            if txn.transaction_type in ("payment", "transfer_to_office"):
                return txn.payment.purpose
            if txn.transaction_type == "journal_out" and hasattr(txn, "journal_as_out"):
                return txn.journal_as_out.description
            if txn.transaction_type == "journal_in" and hasattr(txn, "journal_as_in"):
                return txn.journal_as_in.description
        except Exception:
            pass
        return txn.description

    rows = []
    running = Decimal("0.00")

    for txn in transactions:
        delta = _transaction_delta(txn)
        running += delta

        debit = ""
        credit = ""
        if delta < 0:
            debit = f"${abs(delta)}"
        elif delta > 0:
            credit = f"${delta}"

        rows.append([
            str(txn.date_received_or_paid),
            reference_for(txn),
            transaction_type_label(txn),
            counterparty_for(txn),
            reason_for(txn),
            debit,
            credit,
            f"${running}",
        ])

    if not rows:
        rows.append(["", "", "", "No transactions", "", "", "", "$0.00"])

    table_data = [[
        Paragraph("Date Rec/Rec'd/Paid", header_style),
        Paragraph("Reference Number", header_style),
        Paragraph("Type", header_style),
        Paragraph("Rec'd From / Paid To / Jnl To-From", header_style),
        Paragraph("Reason", header_style),
        Paragraph("Debit Amount", header_style),
        Paragraph("Credit Amount", header_style),
        Paragraph("Balance", header_style),
    ]]
    table_data += [[Paragraph(str(cell or ""), normal) for cell in row] for row in rows]

    table = Table(
        table_data,
        colWidths=[
            2.0 * cm,
            2.5 * cm,
            2.4 * cm,
            6.0 * cm,
            5.7 * cm,
            2.2 * cm,
            2.2 * cm,
            2.2 * cm,
        ],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (5, 1), (7, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.35 * cm))
    elements.append(Paragraph(
        "Debit/credit presentation follows Rule 47 posting: receipts and payment reversals credit the ledger; payments, receipt reversals and journal-outs debit the ledger.",
        styles["Italic"],
    ))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))

    doc.build(elements)

    response = _make_pdf_response(f"ledger_statement_{matter_ledger.pk}.pdf")
    response.write(buffer.getvalue())
    return response


def trust_trial_balance_pdf(trust_account, as_at):
    return _pdf_response_from_bytes(
        f'trial_balance_{as_at}.pdf',
        trial_balance_pdf_bytes(trust_account, as_at),
    )


def _transaction_delta(txn):
    if txn.transaction_type in ('receipt', 'journal_in'):
        return txn.amount
    if txn.transaction_type in ('payment', 'journal_out', 'transfer_to_office'):
        return -txn.amount
    if txn.transaction_type == 'reversal' and txn.reverses:
        return -_transaction_delta(txn.reverses)
    return Decimal('0.00')


def calculate_ledger_balances_as_at(trust_account, as_at):
    balances = {ledger.pk: Decimal('0.00') for ledger in MatterLedger.objects.filter(trust_account=trust_account)}
    transactions = (
        TrustTransaction.objects
        .filter(matter_ledger__trust_account=trust_account, date_received_or_paid__lte=as_at)
        .select_related('matter_ledger', 'reverses')
        .order_by('date_received_or_paid', 'created_at', 'pk')
    )
    for txn in transactions:
        if (
            txn.transaction_type == 'reversal'
            and txn.reverses_id
            and txn.reverses.date_received_or_paid > as_at
        ):
            continue
        balances[txn.matter_ledger_id] = balances.get(txn.matter_ledger_id, Decimal('0.00')) + _transaction_delta(txn)
    return balances


def trial_balance_pdf_bytes(trust_account, as_at):
    reconciliation = MonthlyReconciliation.objects.filter(
        trust_account=trust_account,
        period_end=as_at,
        is_finalised=True,
    ).order_by('-finalised_on').first()

    ledgers = (
        MatterLedger.objects
        .filter(trust_account=trust_account)
        .select_related('matter', 'matter__client')
        .order_by('matter__file_number', 'pk')
    )
    balances = calculate_ledger_balances_as_at(trust_account, as_at)

    if reconciliation:
        reconciled_cash_book_balance = reconciliation.reconciled_balance
        cash_book_balance = reconciliation.cash_book_balance
        prepared_by = str(reconciliation.finalised_by) if getattr(reconciliation, "finalised_by_id", None) else ""
        date_prepared = reconciliation.date_statement_prepared
        due_date = reconciliation.reconciliation_due_date
        preparation_status = reconciliation.preparation_status_label
    else:
        # On-demand/as-at report not linked to a finalised month-end reconciliation.
        reconciled_cash_book_balance = None
        cash_book_balance = None
        prepared_by = ""
        date_prepared = timezone.localdate()
        due_date = ""
        preparation_status = "On-demand / not finalised month-end record"

    buffer = io.BytesIO()
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    styles = getSampleStyleSheet()

    normal = styles["Normal"].clone("trial_balance_normal")
    normal.fontSize = 8
    normal.leading = 10
    normal.textColor = colors.black

    label_style = styles["Normal"].clone("trial_balance_label")
    label_style.fontName = "Helvetica-Bold"
    label_style.fontSize = 8
    label_style.leading = 10
    label_style.textColor = colors.black

    header_style = styles["Normal"].clone("trial_balance_header")
    header_style.fontName = "Helvetica-Bold"
    header_style.fontSize = 8
    header_style.leading = 10
    header_style.textColor = colors.whitesmoke

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    elements = [Paragraph("Trust Trial Balance Statement", styles["Heading1"])]
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, normal))
    elements.append(Paragraph(f"Trust Trial Balance Statement as at: {as_at}", normal))
    elements.append(Spacer(1, 0.4 * cm))

    ledger_rows = []
    total = Decimal("0.00")
    for ledger in ledgers:
        balance = balances.get(ledger.pk, Decimal("0.00"))
        matter = ledger.matter
        # Nil balances may be excluded under the Handbook, but including them assists review.
        ledger_rows.append([
            str(matter.client.name if getattr(matter, "client_id", None) else matter),
            matter.file_number or str(ledger.pk),
            matter.description or "",
            f"${balance}",
        ])
        total += balance

    if not ledger_rows:
        ledger_rows.append(["No trust ledger accounts", "", "", "$0.00"])

    ledger_table_data = [
        [
            Paragraph("Account Name", header_style),
            Paragraph("Matter Reference", header_style),
            Paragraph("Matter Description", header_style),
            Paragraph("Balance", header_style),
        ]
    ]
    ledger_table_data += [
        [Paragraph(str(cell or ""), normal) for cell in row]
        for row in ledger_rows
    ]

    ledger_table = Table(
        ledger_table_data,
        colWidths=[4.8 * cm, 3.2 * cm, 5.8 * cm, 2.8 * cm],
        repeatRows=1,
    )
    ledger_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(ledger_table)
    elements.append(Spacer(1, 0.45 * cm))

    comparison_rows = [
        ["Total Trust Ledger Accounts", f"${total}"],
    ]

    if reconciled_cash_book_balance is not None:
        variance = total - reconciled_cash_book_balance
        comparison_rows.extend([
            ["Reconciled Trust Cash Book Balance", f"${reconciled_cash_book_balance}"],
            ["Variance (should be nil)", f"${variance}"],
            ["Cash Book Balance", f"${cash_book_balance}"],
            ["Balanced?", "Yes" if variance == Decimal("0.00") else "NO - VARIANCE"],
        ])
    else:
        comparison_rows.extend([
            ["Reconciled Trust Cash Book Balance", "No finalised reconciliation for this as-at date"],
            ["Variance (should be nil)", "Not available"],
            ["Balanced?", "Not available"],
        ])

    comparison_table = Table(
        [[Paragraph("Rule 48(2)(b)(i) Comparison", label_style), Paragraph("Amount / Status", label_style)]]
        + [[Paragraph(str(a), normal), Paragraph(str(b), normal)] for a, b in comparison_rows],
        colWidths=[10.8 * cm, 5.8 * cm],
    )
    comparison_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(comparison_table)
    elements.append(Spacer(1, 0.45 * cm))

    prep_rows = [
        ["Month / as-at date", str(as_at)],
        ["Date prepared", str(date_prepared or "")],
        ["Prepared by", prepared_by],
        ["Reconciliation due date", str(due_date or "")],
        ["Preparation status", preparation_status],
        ["Linked finalised reconciliation", "Yes" if reconciliation else "No"],
    ]

    prep_table = Table(
        [[Paragraph("Preparation item", label_style), Paragraph("Value", label_style)]]
        + [[Paragraph(str(a), normal), Paragraph(str(b or ""), normal)] for a, b in prep_rows],
        colWidths=[7.0 * cm, 9.6 * cm],
    )
    prep_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(prep_table)

    elements.append(Spacer(1, 0.35 * cm))
    elements.append(Paragraph(
        "Nil-balance ledger accounts may be excluded under the Handbook; Matter Funds includes them for review transparency.",
        styles["Italic"],
    ))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))

    doc.build(elements)
    return buffer.getvalue()


def monthly_reconciliation_pdf(reconciliation):
    return _pdf_response_from_bytes(
        f'reconciliation_{reconciliation.period_end}.pdf',
        reconciliation_statement_pdf_bytes(reconciliation),
    )


def reconciliation_statement_pdf_bytes(reconciliation):
    trust_account = reconciliation.trust_account
    buffer = io.BytesIO()

    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontSize = 8
    label_style = styles["Normal"]
    label_style.fontName = "Helvetica-Bold"
    label_style.fontSize = 8

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    elements = [Paragraph("Trust Authorised ADI Reconciliation Statement", styles["Heading1"])]
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, normal))

    elements.append(Paragraph(f"Reconciliation statement as at: {reconciliation.period_end}", normal))
    elements.append(Spacer(1, 0.4 * cm))

    rows = [
        ["Authorised ADI statement balance", "Month-end bank statement balance", f"${reconciliation.bank_statement_balance}"],
        ["Add", "Receipts in receipts cash book not in authorised ADI statement / outstanding deposits", f"${reconciliation.outstanding_deposits_total}"],
        ["Add", "Debits in authorised ADI statement not in payments cash book", "$0.00"],
        ["Less", "Cheques in payments cash book not in authorised ADI statement / unpresented cheques", f"${reconciliation.unpresented_cheques_total}"],
        ["Less", "Other payments in payments cash book not in authorised ADI statement", "$0.00"],
        ["Less", "Credits in authorised ADI statement not in receipts cash book", "$0.00"],
        ["Reconciled cash book balance", "Calculated from authorised ADI balance and reconciling items", f"${reconciliation.reconciled_balance}"],
        ["Trust cash book balance", "Closing trust cash book balance", f"${reconciliation.cash_book_balance}"],
        ["Trust ledger total", "Trust ledger control / trial balance total", f"${reconciliation.ledger_total_balance}"],
        ["Balanced?", "Cash book, ledger total and reconciled cash book balance agree", "Yes" if reconciliation.is_reconciled else "NO - DISCREPANCY"],
    ]

    table_data = [
        [Paragraph("Item", label_style), Paragraph("Description", label_style), Paragraph("Amount", label_style)]
    ]
    table_data += [[Paragraph(str(cell or ""), normal) for cell in row] for row in rows]

    t = Table(table_data, colWidths=[4.4 * cm, 8.8 * cm, 3.4 * cm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(t)

    elements.append(Spacer(1, 0.5 * cm))

    metadata_rows = [
        ["Date of preparation", str(reconciliation.date_statement_prepared or "")],
        ["Prepared by", str(reconciliation.finalised_by) if getattr(reconciliation, "finalised_by_id", None) else ""],
        ["Reconciliation due date", str(reconciliation.reconciliation_due_date)],
        ["Prepared within required period", "Yes" if reconciliation.prepared_within_required_period else "No" if reconciliation.finalised_on else ""],
        ["Preparation status", reconciliation.preparation_status_label],
        ["Finalised?", "Yes" if getattr(reconciliation, "is_finalised", False) else "No"],
        ["Finalised on", str(reconciliation.finalised_on) if getattr(reconciliation, "finalised_on", None) else ""],
        ["Accounting period status", reconciliation.accounting_period.get_status_display() if getattr(reconciliation, "accounting_period_id", None) else ""],
    ]

    metadata_table = Table(
        [[Paragraph("Review / preparation item", label_style), Paragraph("Value", label_style)]]
        + [[Paragraph(str(a), normal), Paragraph(str(b or ""), normal)] for a, b in metadata_rows],
        colWidths=[7.0 * cm, 9.6 * cm],
    )
    metadata_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(metadata_table)

    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(
        "Review notes: outstanding deposits should be followed up for banking; unpresented cheques should be reviewed; "
        "authorised ADI errors, interest, charges, unidentified deposits, and other ADI-only items should be investigated and corrected in the appropriate next-period records.",
        styles["Italic"],
    ))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))

    doc.build(elements)
    return buffer.getvalue()


def external_examiner_pack_zip(trust_account, year):
    date_from = datetime.date(year, 1, 1)
    date_to = datetime.date(year, 12, 31)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        r_resp = receipts_journal_pdf(trust_account, date_from, date_to)
        zf.writestr(f'receipts_journal_{year}.pdf', r_resp.content)

        p_resp = payments_journal_pdf(trust_account, date_from, date_to)
        zf.writestr(f'payments_journal_{year}.pdf', p_resp.content)

        tb_resp = trust_trial_balance_pdf(trust_account, date_to)
        zf.writestr(f'trial_balance_{year}.pdf', tb_resp.content)

        recons = MonthlyReconciliation.objects.filter(
            trust_account=trust_account,
            period_end__year=year,
        ).order_by('period_end')
        for recon in recons:
            rr = monthly_reconciliation_pdf(recon)
            zf.writestr(f'reconciliation_{recon.period_end}.pdf', rr.content)

        irr_buf = io.StringIO()
        writer = csv.writer(irr_buf)
        writer.writerow(['Discovered On', 'Description', 'Amount', 'Reported To Law Society', 'Resolution'])
        irregularities = Irregularity.objects.filter(trust_account=trust_account, discovered_on__year=year)
        for irr in irregularities:
            writer.writerow([irr.discovered_on, irr.description, irr.amount, irr.reported_to_law_society_on, irr.resolution])
        zf.writestr(f'irregularities_{year}.csv', irr_buf.getvalue())

        costs_buf = io.StringIO()
        writer = csv.writer(costs_buf)
        writer.writerow([
            'Date', 'Payment #', 'Matter', 'Amount', 'Withdrawal Method', 'Key Evidence Date',
            'Payee', 'Evidence File?', 'Notice/Request File?', 'Authority/Agreement File?',
            'Reimbursement Evidence File?', 'Notes',
        ])
        costs_transfers = (
            TrustTransaction.objects
            .filter(
                transaction_type='transfer_to_office',
                matter_ledger__trust_account=trust_account,
                date_received_or_paid__range=(date_from, date_to),
            )
            .select_related('matter_ledger__matter', 'payment')
            .order_by('date_received_or_paid', 'payment__payment_number')
        )
        for txn in costs_transfers:
            payment = getattr(txn, 'payment', None)
            if not payment:
                continue
            writer.writerow([
                txn.date_received_or_paid,
                payment.payment_number,
                txn.matter_ledger.matter,
                txn.amount,
                payment.get_costs_withdrawal_method_display(),
                payment.key_evidence_date or '',
                payment.payee_name,
                'Yes' if payment.costs_evidence_file else 'No',
                'Yes' if payment.notice_or_request_file else 'No',
                'Yes' if payment.authority_or_agreement_file else 'No',
                'Yes' if payment.reimbursement_evidence_file else 'No',
                payment.costs_withdrawal_notes,
            ])
        zf.writestr(f'costs_transfers_{year}.csv', costs_buf.getvalue())

        if HAS_OPENPYXL:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Ledger Balances'
            ws.append(['Matter', 'Balance'])
            for ledger in MatterLedger.objects.filter(trust_account=trust_account).select_related('matter'):
                ws.append([str(ledger.matter), float(ledger.balance)])
            xl_buf = io.BytesIO()
            wb.save(xl_buf)
            zf.writestr(f'ledger_balances_{year}.xlsx', xl_buf.getvalue())

    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="external_examiner_pack_{year}.zip"'
    return response


def receipt_pdf(receipt):
    """Generate a Rule 36-friendly PDF for a single general trust receipt."""
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    txn = receipt.transaction
    ledger = txn.matter_ledger
    matter = ledger.matter
    trust_account = ledger.trust_account

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    label_style = styles["Normal"]
    label_style.fontName = "Helvetica-Bold"
    label_style.fontSize = 8
    normal.fontSize = 8

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    elements = []

    elements.append(Paragraph("Trust Account Receipt", styles["Heading1"]))
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, normal))
    elements.append(Spacer(1, 0.4 * cm))

    date_made_out = receipt.date_made_out
    date_received = txn.date_received_or_paid
    made_out_by = (
        getattr(txn.created_by, "get_full_name", lambda: "")()
        or getattr(txn.created_by, "email", "")
        or str(txn.created_by)
    )

    details = [
        ["Law practice name", trust_account.firm.name],
        ["Expression", "Trust Account"],
        ["Receipt number", str(receipt.receipt_number)],
        ["Date receipt made out", str(date_made_out or "")],
        ["Date money received, if different", "" if date_received == date_made_out else str(date_received)],
        ["Amount received", f"${txn.amount}"],
        ["Form in which money was received", receipt.get_payment_method_display()],
        ["Received from", receipt.payor_name],
        ["For and on behalf of / client", getattr(matter.client, "name", "")],
        ["Matter reference", matter.file_number or ""],
        ["Matter description", matter.description or ""],
        ["Reason / purpose", receipt.purpose],
        ["Made out by", made_out_by],
    ]

    if receipt.cheque_number:
        details.insert(7, ["Cheque number", receipt.cheque_number])

    if receipt.uses_separate_deposit_date:
        details.insert(5, ["Date deposited to trust account", str(txn.date_banked or "")])

    details.append([
        "Record copy",
        "Generated and retained by Matter Funds. Original receipt available to the person from whom the money was received on request.",
    ])

    wrapped_details = [
        [Paragraph(str(label), label_style), Paragraph(str(value or ""), normal)]
        for label, value in details
    ]

    t = Table(wrapped_details, colWidths=[6.0 * cm, 10.5 * cm], repeatRows=0)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))

    doc.build(elements)

    response = _make_pdf_response(f"receipt_{receipt.receipt_number}.pdf")
    response.write(buffer.getvalue())
    return response


import hashlib
import json
from django.core.files.base import ContentFile
from .models import ControlledMoneyAccount, ControlledMoneyReceipt, ControlledMoneyWithdrawal, ControlledMoneyMonthlyStatement, ControlledMoneySupportingDocument, TrustMonthlyRecord, TrustAccountingPeriod


def _date_range_for_ledger(matter_ledger, date_from=None, date_to=None):
    qs = TrustTransaction.objects.filter(matter_ledger=matter_ledger)
    if date_from is None:
        first = qs.order_by('date_received_or_paid').values_list('date_received_or_paid', flat=True).first()
        date_from = first or datetime.date(timezone.localdate().year if timezone.localdate().month >= 7 else timezone.localdate().year - 1, 7, 1)
    if date_to is None:
        date_to = timezone.localdate()
    return date_from, date_to


def trust_account_statement_rows(matter_ledger, date_from=None, date_to=None):
    date_from, date_to = _date_range_for_ledger(matter_ledger, date_from, date_to)
    all_txns = TrustTransaction.objects.filter(matter_ledger=matter_ledger).select_related('reverses').order_by('date_received_or_paid', 'created_at', 'pk')
    opening = Decimal('0.00')
    for txn in all_txns.filter(date_received_or_paid__lt=date_from):
        opening += _transaction_delta(txn)
    running = opening
    rows = []
    receipts = payments = journals = Decimal('0.00')
    for txn in all_txns.filter(date_received_or_paid__range=(date_from, date_to)):
        delta = _transaction_delta(txn)
        running += delta
        debit = -delta if delta < 0 else Decimal('0.00')
        credit = delta if delta > 0 else Decimal('0.00')
        if txn.transaction_type == 'receipt': receipts += credit
        elif txn.transaction_type in ('payment', 'transfer_to_office'): payments += debit
        elif txn.transaction_type in ('journal_in', 'journal_out'): journals += abs(delta)
        rows.append([str(txn.date_received_or_paid), txn.get_transaction_type_display(), txn.description, str(debit or ''), str(credit or ''), str(running)])
    return date_from, date_to, opening, receipts, payments, journals, running, rows


def trust_account_statement_pdf_bytes(matter_ledger, date_from=None, date_to=None):
    date_from, date_to, opening, receipts, payments, journals, closing, rows = trust_account_statement_rows(matter_ledger, date_from, date_to)
    buffer = io.BytesIO(); styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5*cm, rightMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    matter = matter_ledger.matter; account = matter_ledger.trust_account
    elements = [Paragraph('Trust Account Statement', styles['Heading1'])]
    for line in _build_header_info(account): elements.append(Paragraph(line, styles['Normal']))
    elements += [Paragraph(f'Client/person: {matter.client.name}', styles['Normal']), Paragraph(f'Matter reference: {matter.file_number}', styles['Normal']), Paragraph(f'Matter description: {matter.description}', styles['Normal']), Paragraph(f'Statement period: {date_from} to {date_to}', styles['Normal']), Paragraph(f'Date statement prepared/generated: {timezone.localdate()}', styles['Normal']), Spacer(1, .4*cm)]
    elements.append(Table([['Opening balance', str(opening)], ['Receipts', str(receipts)], ['Payments', str(payments)], ['Transfers/journals affecting ledger', str(journals)], ['Closing balance', str(closing)]], style=[('GRID',(0,0),(-1,-1),.5,colors.black)]))
    elements.append(Spacer(1, .4*cm))
    t = Table([['Date','Type','Description','Debit ($)','Credit ($)','Running balance ($)']] + rows, repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey),('GRID',(0,0),(-1,-1),.5,colors.black),('FONTSIZE',(0,0),(-1,-1),8)]))
    elements.append(t); elements.append(Spacer(1,.4*cm)); elements.append(Paragraph(FOOTER_TEXT, styles['Italic']))
    doc.build(elements); return buffer.getvalue()


def trust_account_statement_pdf(matter_ledger, date_from=None, date_to=None):
    date_from, date_to = _date_range_for_ledger(matter_ledger, date_from, date_to)
    return _pdf_response_from_bytes(f'trust_account_statement_{matter_ledger.pk}_{date_from}_{date_to}.pdf', trust_account_statement_pdf_bytes(matter_ledger, date_from, date_to))


def controlled_money_receipt_pdf_bytes(receipt):
    buffer = io.BytesIO(); rows = [['Expression','controlled money receipt'], ['Law practice name', receipt.firm.name], ['Receipt number', str(receipt.receipt_number)], ['Date made out', str(receipt.date_made_out)], ['Date money received', str(receipt.date_money_received or receipt.date_made_out)], ['Amount', str(receipt.amount)], ['Form/payment method', receipt.get_payment_method_display()], ['From', receipt.person_from_whom_received], ['On behalf of', receipt.person_on_behalf], ['Matter reference', receipt.matter_reference], ['Matter description', receipt.matter_description], ['Reason/purpose', receipt.reason], ['Account credited', str(receipt.controlled_money_account or '')], ['Made out by', str(receipt.made_out_by)]]
    _build_pdf_document(buffer, receipt.controlled_money_account or TrustAccount.objects.filter(firm=receipt.firm).first(), 'Controlled Money Receipt', str(receipt.date_made_out), rows, ['Field','Value'])
    return buffer.getvalue()


def controlled_money_monthly_statement_pdf_bytes(statement):
    accounts = ControlledMoneyAccount.objects.filter(firm=statement.firm, opened_on__lte=statement.period_end).filter(Q(closed_on__isnull=True)|Q(closed_on__gte=statement.period_end)).order_by('account_name')
    rows = [[a.account_name, a.account_number, str(a.current_balance), a.person_on_behalf, a.matter_description] for a in accounts]
    rows += [['Date statement prepared', str(statement.prepared_on), '', '', ''], ['Due date (15 NSW working days)', str(statement.due_date), '', '', ''], ['Reviewed by', str(statement.reviewed_by or ''), str(statement.reviewed_on or ''), statement.reviewer_role_confirmation, statement.review_note]]
    buffer = io.BytesIO(); _build_pdf_document(buffer, accounts.first() or TrustAccount.objects.filter(firm=statement.firm).first(), 'Controlled Money Monthly Statement', f'As at {statement.period_end}', rows, ['Account name','Account number','Register balance','Person on behalf','Matter description'])
    return buffer.getvalue()


def ensure_controlled_money_monthly_statement_pdf(statement):
    if not statement.pdf:
        data = controlled_money_monthly_statement_pdf_bytes(statement); statement.sha256_hash = hashlib.sha256(data).hexdigest(); statement.pdf.save(f'controlled_money_statement_{statement.period_end}.pdf', ContentFile(data), save=False); statement.save()
    return statement.pdf.read()


def trust_records_export_pack_zip(trust_account, date_from=None, date_to=None, year=None, all_data=False, include_technical=False):
    if year and not (date_from or date_to):
        date_from, date_to = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    if all_data:
        date_from, date_to = datetime.date(1900, 1, 1), timezone.localdate()
    date_from = date_from or datetime.date(timezone.localdate().year, 1, 1)
    date_to = date_to or timezone.localdate()
    buf = io.BytesIO()
    manifest = []
    included_files = []

    def add(zf, name, data, source):
        if isinstance(data, str):
            data = data.encode()
        zf.writestr(name, data)
        included_files.append(name)
        if include_technical:
            manifest.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'source': source})

    def csv_export(zf, name, rows, fieldnames):
        csvbuf = io.StringIO()
        writer = csv.DictWriter(csvbuf, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        add(zf, name, csvbuf.getvalue(), 'export')

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        stored_record_types = set()
        retained_records = TrustMonthlyRecord.objects.filter(
            trust_account=trust_account,
            accounting_period__period_end__range=(date_from, date_to),
        ).select_related('accounting_period')
        for rec in retained_records:
            if rec.pdf:
                stored_record_types.add((rec.accounting_period.period_start, rec.accounting_period.period_end, rec.record_type))
                add(zf, f'retained-monthly-records/{rec.accounting_period.period_end}/{rec.record_type}.pdf', rec.pdf.read(), 'retained')

        exact_period_stored_types = {
            record_type for start, end, record_type in stored_record_types
            if start == date_from and end == date_to
        }
        if TrustMonthlyRecord.RECORD_RECEIPTS_CASH_BOOK not in exact_period_stored_types:
            add(zf, 'generated-reports/receipts_cash_book.pdf', receipts_cash_book_pdf_bytes(trust_account, date_from, date_to), 'generated')
        if TrustMonthlyRecord.RECORD_PAYMENTS_CASH_BOOK not in exact_period_stored_types:
            add(zf, 'generated-reports/payments_cash_book.pdf', payments_cash_book_pdf_bytes(trust_account, date_from, date_to), 'generated')
        if TrustMonthlyRecord.RECORD_TRUST_TRANSFER_JOURNAL not in exact_period_stored_types:
            add(zf, 'generated-reports/trust_transfer_journal.pdf', trust_transfer_journal_pdf_bytes(trust_account, date_from, date_to), 'generated')
        if TrustMonthlyRecord.RECORD_TRIAL_BALANCE not in exact_period_stored_types:
            add(zf, 'generated-reports/trial_balance.pdf', trial_balance_pdf_bytes(trust_account, date_to), 'generated')

        for ledger in MatterLedger.objects.filter(trust_account=trust_account).select_related('matter__client', 'trust_account__firm'):
            add(zf, f'statements/matter-ledgers/ledger_{ledger.pk}.pdf', matter_ledger_statement_pdf(ledger).content, 'generated')
            add(zf, f'statements/trust-account-statements/statement_{ledger.pk}.pdf', trust_account_statement_pdf_bytes(ledger, date_from, date_to), 'generated')

        for recon in MonthlyReconciliation.objects.filter(trust_account=trust_account, period_end__range=(date_from, date_to)):
            has_retained_recon = any(
                end == recon.period_end and record_type == TrustMonthlyRecord.RECORD_RECONCILIATION_STATEMENT
                for _start, end, record_type in stored_record_types
            )
            if not has_retained_recon:
                add(zf, f'generated-reports/reconciliations/reconciliation_{recon.period_end}.pdf', reconciliation_statement_pdf_bytes(recon), 'generated')
            if recon.bank_statement_pdf:
                add(zf, f'evidence/bank-statements/{recon.bank_statement_pdf.name.split("/")[-1]}', recon.bank_statement_pdf.read(), 'stored-evidence')

        for st in ControlledMoneyMonthlyStatement.objects.filter(firm=trust_account.firm, period_end__range=(date_from, date_to)):
            add(zf, f'controlled-money/monthly-statements/{st.period_end}.pdf', ensure_controlled_money_monthly_statement_pdf(st), 'controlled-money-record')

        cma_accounts = list(ControlledMoneyAccount.objects.filter(firm=trust_account.firm).values('id', 'account_name', 'bsb', 'account_number', 'person_on_behalf', 'matter_reference', 'matter_description', 'current_balance', 'is_active'))
        csv_export(zf, 'controlled-money/exports/accounts.csv', cma_accounts, ['id', 'account_name', 'bsb', 'account_number', 'person_on_behalf', 'matter_reference', 'matter_description', 'current_balance', 'is_active'])
        cma_receipts = list(ControlledMoneyReceipt.objects.filter(firm=trust_account.firm, date_made_out__range=(date_from, date_to)).values('id', 'controlled_money_account_id', 'receipt_number', 'date_made_out', 'date_money_received', 'amount', 'payment_method', 'person_from_whom_received', 'person_on_behalf', 'matter_reference', 'matter_description', 'reason'))
        csv_export(zf, 'controlled-money/exports/receipts.csv', cma_receipts, ['id', 'controlled_money_account_id', 'receipt_number', 'date_made_out', 'date_money_received', 'amount', 'payment_method', 'person_from_whom_received', 'person_on_behalf', 'matter_reference', 'matter_description', 'reason'])
        cma_withdrawals = list(ControlledMoneyWithdrawal.objects.filter(controlled_money_account__firm=trust_account.firm, date__range=(date_from, date_to)).values('id', 'controlled_money_account_id', 'date', 'transaction_number', 'amount', 'withdrawal_method', 'person_on_behalf', 'matter_reference', 'reason', 'authorised_by'))
        csv_export(zf, 'controlled-money/exports/withdrawals.csv', cma_withdrawals, ['id', 'controlled_money_account_id', 'date', 'transaction_number', 'amount', 'withdrawal_method', 'person_on_behalf', 'matter_reference', 'reason', 'authorised_by'])
        for receipt in ControlledMoneyReceipt.objects.filter(firm=trust_account.firm, date_made_out__range=(date_from, date_to)).select_related('controlled_money_account','made_out_by'):
            add(zf, f'controlled-money/receipts/receipt_{receipt.receipt_number}.pdf', controlled_money_receipt_pdf_bytes(receipt), 'controlled-money-record')
        for doc in ControlledMoneySupportingDocument.objects.filter(controlled_money_account__firm=trust_account.firm):
            if doc.document:
                filename = doc.document.name.rsplit("/", 1)[-1]
                add(
                    zf,
                    f"controlled-money/supporting-documents/{filename}",
                    doc.document.read(),
                    "controlled-money-evidence",
                )

        txns = list(TrustTransaction.objects.filter(matter_ledger__trust_account=trust_account, date_received_or_paid__range=(date_from, date_to)).values('id', 'transaction_type', 'amount', 'date_received_or_paid', 'description', 'matter_ledger_id'))
        csv_export(zf, 'exports/trust_transactions.csv', txns, ['id', 'transaction_type', 'amount', 'date_received_or_paid', 'description', 'matter_ledger_id'])
        ledgers = list(MatterLedger.objects.filter(trust_account=trust_account).values('id', 'matter_id', 'balance'))
        csv_export(zf, 'exports/matter_ledgers.csv', ledgers, ['id', 'matter_id', 'balance'])
        recons = list(MonthlyReconciliation.objects.filter(trust_account=trust_account, period_end__range=(date_from, date_to)).values('id', 'period_end', 'bank_statement_balance', 'cash_book_balance', 'ledger_total_balance', 'reconciled_balance', 'is_reconciled'))
        csv_export(zf, 'exports/reconciliations.csv', recons, ['id', 'period_end', 'bank_statement_balance', 'cash_book_balance', 'ledger_total_balance', 'reconciled_balance', 'is_reconciled'])

        if include_technical:
            add(zf, 'exports/trust_transactions.json', json.dumps(txns, default=str, indent=2), 'export')
            add(zf, 'exports/matter_ledgers.json', json.dumps(ledgers, default=str, indent=2), 'export')
            add(zf, 'exports/reconciliations.json', json.dumps(recons, default=str, indent=2), 'export')
            add(zf, 'manifest.json', json.dumps(manifest, indent=2), 'manifest')
            hash_lines = '\n'.join(f"{m['sha256']}  {m['path']}" for m in manifest)
            add(zf, 'SHA256SUMS.txt', hash_lines, 'manifest')

        readme_lines = [
            'Trust Records Export Pack',
            '',
            f'Firm name: {trust_account.firm.name}',
            f'Trust account name: {trust_account.name}',
            f'Export date: {timezone.localdate()}',
            f'Export period/year: {date_from} to {date_to}',
            '',
            'Retained monthly records are stored records generated at finalisation. Where a retained monthly record exists for a period/report type, this pack includes the stored PDF and omits a duplicate regenerated report for the same purpose.',
            '',
            'Folders/files included:',
        ]
        readme_lines.extend(f'- {name}' for name in sorted(included_files))
        zf.writestr('README.txt', '\n'.join(readme_lines) + '\n')
    return HttpResponse(buf.getvalue(), content_type='application/zip', headers={'Content-Disposition': f'attachment; filename="trust_records_export_pack_{date_from}_{date_to}.zip"'})


def payment_pdf(payment):
    """Generate a Rule 43-friendly PDF for a single general trust payment or costs transfer."""
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    txn = payment.transaction
    ledger = txn.matter_ledger
    matter = ledger.matter
    trust_account = ledger.trust_account
    is_costs_transfer = txn.transaction_type == "transfer_to_office"

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()

    normal = styles["Normal"].clone("payment_pdf_normal")
    normal.fontSize = 8
    normal.leading = 10
    normal.textColor = colors.black

    label_style = styles["Normal"].clone("payment_pdf_label")
    label_style.fontName = "Helvetica-Bold"
    label_style.fontSize = 8
    label_style.leading = 10
    label_style.textColor = colors.black

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    elements = []

    title = "Transfer Costs to Office Source Record" if is_costs_transfer else "Trust Payment Source Record"
    elements.append(Paragraph(title, styles["Heading1"]))

    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, normal))
    elements.append(Spacer(1, 0.4 * cm))

    authorised_by = (
        getattr(payment.authorised_by, "get_full_name", lambda: "")()
        or getattr(payment.authorised_by, "email", "")
        or str(payment.authorised_by or "")
    )
    created_by = (
        getattr(txn.created_by, "get_full_name", lambda: "")()
        or getattr(txn.created_by, "email", "")
        or str(txn.created_by or "")
    )

    details = [
        ["Law practice name", trust_account.firm.name],
        ["Expression", "Law Practice Trust Account"],
        ["Withdrawal type", txn.get_transaction_type_display()],
        ["Withdrawal method", payment.get_payment_method_display()],
        ["Payment / EFT reference", payment.display_payment_reference],
        ["Date of cheque / EFT", str(txn.date_received_or_paid)],
        ["Amount ordered to be paid", f"${txn.amount}"],
        ["Pay to / payee", payment.payee_name],
        ["On behalf of / client", getattr(matter.client, "name", "")],
        ["Matter reference", matter.file_number or ""],
        ["Matter description", matter.description or ""],
        ["Ledger account debited", str(ledger)],
        ["Reason / purpose of payment", payment.purpose],
        ["Authorised by", authorised_by],
        ["Created by", created_by],
    ]

    if payment.cheque_number:
        details.insert(5, ["Cheque number", payment.cheque_number])

    if payment.payee_bsb or payment.payee_account:
        details.insert(9, ["Payee BSB / Account number", f"{payment.payee_bsb or ''} / {payment.payee_account or ''}"])

    if is_costs_transfer:
        details.extend([
            ["", ""],
            ["Costs transfer evidence", ""],
            ["Costs withdrawal method", payment.get_costs_withdrawal_method_display()],
            ["Key evidence date", str(payment.key_evidence_date or "—")],
            ["Costs evidence file", payment.costs_evidence_file.name if payment.costs_evidence_file else "—"],
            ["Notice/request file", payment.notice_or_request_file.name if payment.notice_or_request_file else "—"],
            ["Authority/agreement file", payment.authority_or_agreement_file.name if payment.authority_or_agreement_file else "—"],
            ["Reimbursement evidence file", payment.reimbursement_evidence_file.name if payment.reimbursement_evidence_file else "—"],
            ["Costs withdrawal notes", payment.costs_withdrawal_notes or "—"],
            ["Evidence note", "Uploaded evidence is optional at entry. Supporting evidence should be retained and produced for examiner review if requested."],
        ])

    if payment.payment_method == "cheque":
        details.append([
            "Cheque control note",
            "Trust cheques must be payable to or to the order of a specific person, not to bearer or cash, crossed not negotiable, and signed by an authorised person.",
        ])

    details.append([
        "Record copy",
        "Generated and retained by Matter Funds as the trust payment / costs-transfer source record.",
    ])

    wrapped_details = [
        [Paragraph(str(label), label_style), Paragraph(str(value or ""), normal)]
        for label, value in details
    ]

    t = Table(wrapped_details, colWidths=[6.0 * cm, 10.5 * cm], repeatRows=0)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))

    elements.append(t)
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))

    doc.build(elements)

    response = _make_pdf_response(f"payment_{payment.payment_number}.pdf")
    response.write(buffer.getvalue())
    return response


def reversal_pdf(reversal):
    """Generate a source-record PDF for a trust transaction reversal."""
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")

    original = reversal.reverses
    trust_account = reversal.matter_ledger.trust_account
    matter = reversal.matter_ledger.matter

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()

    normal = styles["Normal"].clone("reversal_normal")
    normal.fontSize = 8
    normal.leading = 10
    normal.textColor = colors.black

    label_style = styles["Normal"].clone("reversal_label")
    label_style.fontName = "Helvetica-Bold"
    label_style.fontSize = 8
    label_style.leading = 10
    label_style.textColor = colors.black

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    elements = [Paragraph("Trust Transaction Reversal Source Record", styles["Heading1"])]
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, normal))
    elements.append(Spacer(1, 0.4 * cm))

    def source_reference(txn):
        try:
            if txn.transaction_type == "receipt":
                return f"Receipt #{txn.receipt.receipt_number}"
            if txn.transaction_type in ("payment", "transfer_to_office"):
                return f"Payment #{txn.payment.payment_number}"
            if txn.transaction_type == "journal_out" and hasattr(txn, "journal_as_out"):
                return f"Journal J{txn.journal_as_out.pk}"
            if txn.transaction_type == "journal_in" and hasattr(txn, "journal_as_in"):
                return f"Journal J{txn.journal_as_in.pk}"
        except Exception:
            pass
        return f"Transaction #{txn.pk}"

    def ledger_effect_text(txn):
        if not original:
            return ""
        if original.transaction_type in ("receipt", "journal_in"):
            return "Debit to ledger / reduction of trust ledger balance"
        if original.transaction_type in ("payment", "transfer_to_office", "journal_out"):
            return "Credit to ledger / restoration of trust ledger balance"
        return ""

    created_by = (
        getattr(reversal.created_by, "get_full_name", lambda: "")()
        or getattr(reversal.created_by, "email", "")
        or str(reversal.created_by or "")
    )

    rows = [
        ["Reversal transaction", f"Transaction #{reversal.pk}"],
        ["Reversal date", str(reversal.date_received_or_paid)],
        ["Amount reversed", f"${reversal.amount}"],
        ["Reversal reason", reversal.description],
        ["Created by", created_by],
        ["Matter / ledger", f"{matter.file_number or reversal.matter_ledger_id} - {matter.description}"],
        ["Client", getattr(matter.client, "name", "")],
        ["Original transaction", source_reference(original) if original else ""],
        ["Original transaction date", str(original.date_received_or_paid) if original else ""],
        ["Original transaction type", original.get_transaction_type_display() if original else ""],
        ["Original description", original.description if original else ""],
        ["Ledger effect", ledger_effect_text(reversal)],
        ["Record treatment", "Original source record remains retained. This reversal is recorded separately and is not a deletion or cancellation of the original record."],
    ]

    table = Table(
        [[Paragraph(a, label_style), Paragraph(str(b or ""), normal)] for a, b in rows],
        colWidths=[6.0 * cm, 10.5 * cm],
    )
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(
        "Generated and retained by Matter Funds as the trust transaction reversal source record.",
        styles["Italic"],
    ))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(FOOTER_TEXT, styles["Italic"]))

    doc.build(elements)

    response = _make_pdf_response(f"reversal_{reversal.pk}.pdf")
    response.write(buffer.getvalue())
    return response

def deposit_record_pdf_bytes(deposit_record):
    receipts = deposit_record.receipts.select_related(
        'transaction',
        'transaction__matter_ledger',
        'transaction__matter_ledger__matter',
    ).order_by('receipt_number')

    rows = []
    for receipt in receipts:
        txn = receipt.transaction
        matter = txn.matter_ledger.matter
        rows.append([
            f"R{receipt.receipt_number}",
            str(txn.date_received_or_paid),
            receipt.payor_name,
            matter.file_number or str(matter.pk),
            matter.description,
            str(txn.amount),
        ])

    rows.append(['', '', '', '', 'Total deposited', str(deposit_record.total_amount)])
    rows.append(['', '', '', '', 'Prepared by', str(deposit_record.prepared_by)])
    rows.append(['', '', '', '', 'Prepared at', timezone.localtime(deposit_record.prepared_at).strftime('%d %b %Y, %I:%M %p %Z')])
    if deposit_record.notes:
        rows.append(['', '', '', '', 'Notes', deposit_record.notes])

    buffer = io.BytesIO()
    _build_pdf_document(
        buffer,
        deposit_record.trust_account,
        deposit_record.get_deposit_type_display(),
        f"Deposit Record #{deposit_record.deposit_number} | Deposited {deposit_record.deposit_date}",
        rows,
        ['Receipt', 'Receipt date', 'Received from', 'Matter', 'Matter description', 'Amount'],
    )
    return buffer.getvalue()
