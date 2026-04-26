import csv
import io
import zipfile
import datetime
from decimal import Decimal

from django.http import HttpResponse

try:
    from reportlab.lib.pagesizes import A4
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

from .models import TrustTransaction, MatterLedger, MonthlyReconciliation, Irregularity


FOOTER_TEXT = "Prepared from Matter Funds \u2014 refer to LPUGR Part 4.2"


def _build_header_info(trust_account):
    firm = trust_account.firm
    return [
        f"Firm: {firm.name}",
        f"ABN: {firm.abn}",
        f"Trust Account: {trust_account.name}",
        f"BSB: {trust_account.bsb}  Account: {trust_account.account_number}",
    ]


def _make_pdf_response(filename):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
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
    transactions = (
        TrustTransaction.objects
        .filter(
            transaction_type='receipt',
            matter_ledger__trust_account=trust_account,
            date_received_or_paid__range=(date_from, date_to),
        )
        .select_related('matter_ledger__matter', 'receipt')
        .order_by('date_received_or_paid', 'receipt__receipt_number')
    )

    buffer = io.BytesIO()
    col_headers = ['Date', 'Receipt #', 'Matter', 'Payor', 'Method', 'Amount ($)']
    rows = []
    for txn in transactions:
        r = getattr(txn, 'receipt', None)
        rows.append([
            str(txn.date_received_or_paid),
            str(r.receipt_number) if r else '',
            str(txn.matter_ledger.matter),
            r.payor_name if r else '',
            r.get_payment_method_display() if r else '',
            str(txn.amount),
        ])

    _build_pdf_document(buffer, trust_account, 'Trust Receipts Journal',
                        f"{date_from} to {date_to}", rows, col_headers)
    response = _make_pdf_response(f'receipts_journal_{date_from}_{date_to}.pdf')
    response.write(buffer.getvalue())
    return response


def payments_journal_pdf(trust_account, date_from, date_to):
    transactions = (
        TrustTransaction.objects
        .filter(
            transaction_type='payment',
            matter_ledger__trust_account=trust_account,
            date_received_or_paid__range=(date_from, date_to),
        )
        .select_related('matter_ledger__matter', 'payment')
        .order_by('date_received_or_paid', 'payment__payment_number')
    )

    buffer = io.BytesIO()
    col_headers = ['Date', 'Payment #', 'Matter', 'Payee', 'Method', 'Amount ($)']
    rows = []
    for txn in transactions:
        p = getattr(txn, 'payment', None)
        rows.append([
            str(txn.date_received_or_paid),
            str(p.payment_number) if p else '',
            str(txn.matter_ledger.matter),
            p.payee_name if p else '',
            p.get_payment_method_display() if p else '',
            str(txn.amount),
        ])

    _build_pdf_document(buffer, trust_account, 'Trust Payments Journal',
                        f"{date_from} to {date_to}", rows, col_headers)
    response = _make_pdf_response(f'payments_journal_{date_from}_{date_to}.pdf')
    response.write(buffer.getvalue())
    return response


def matter_ledger_statement_pdf(matter_ledger):
    transactions = (
        TrustTransaction.objects
        .filter(matter_ledger=matter_ledger)
        .order_by('date_received_or_paid', 'created_at')
    )

    buffer = io.BytesIO()
    trust_account = matter_ledger.trust_account
    col_headers = ['Date', 'Type', 'Description', 'Debit ($)', 'Credit ($)', 'Balance ($)']
    rows = []
    running = Decimal('0.00')
    for txn in transactions:
        if txn.transaction_type in ('receipt', 'journal_in'):
            debit, credit = '', str(txn.amount)
            running += txn.amount
        else:
            debit, credit = str(txn.amount), ''
            running -= txn.amount
        rows.append([
            str(txn.date_received_or_paid),
            txn.get_transaction_type_display(),
            txn.description,
            debit,
            credit,
            str(running),
        ])

    _build_pdf_document(buffer, trust_account, f'Matter Ledger Statement \u2013 {matter_ledger.matter}',
                        f"As at {datetime.date.today()}", rows, col_headers)
    response = _make_pdf_response(f'ledger_statement_{matter_ledger.pk}.pdf')
    response.write(buffer.getvalue())
    return response


def trust_trial_balance_pdf(trust_account, as_at):
    ledgers = (
        MatterLedger.objects
        .filter(trust_account=trust_account)
        .select_related('matter')
        .order_by('matter__file_number')
    )

    buffer = io.BytesIO()
    col_headers = ['Matter', 'Balance ($)']
    rows = []
    total = Decimal('0.00')
    for ledger in ledgers:
        rows.append([str(ledger.matter), str(ledger.balance)])
        total += ledger.balance
    rows.append(['TOTAL', str(total)])

    _build_pdf_document(buffer, trust_account, 'Trust Trial Balance',
                        f"As at {as_at}", rows, col_headers)
    response = _make_pdf_response(f'trial_balance_{as_at}.pdf')
    response.write(buffer.getvalue())
    return response


def monthly_reconciliation_pdf(reconciliation):
    trust_account = reconciliation.trust_account
    buffer = io.BytesIO()
    col_headers = ['Item', 'Amount ($)']
    rows = [
        ['Cash Book Balance', str(reconciliation.cash_book_balance)],
        ['Ledger Total Balance', str(reconciliation.ledger_total_balance)],
        ['Bank Statement Balance', str(reconciliation.bank_statement_balance)],
        ['Less: Unpresented Cheques', str(reconciliation.unpresented_cheques_total)],
        ['Add: Outstanding Deposits', str(reconciliation.outstanding_deposits_total)],
        ['Reconciled Balance', str(reconciliation.reconciled_balance)],
        ['Reconciled?', 'Yes' if reconciliation.is_reconciled else 'NO \u2013 DISCREPANCY'],
    ]
    _build_pdf_document(buffer, trust_account, 'Monthly Trust Reconciliation',
                        str(reconciliation.period_end), rows, col_headers)
    response = _make_pdf_response(f'reconciliation_{reconciliation.period_end}.pdf')
    response.write(buffer.getvalue())
    return response


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
