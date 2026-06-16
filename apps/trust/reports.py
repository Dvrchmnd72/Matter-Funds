import csv
import io
import zipfile
import datetime
from decimal import Decimal

from django.http import HttpResponse
from django.db.models import Q
from django.utils import timezone

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

from .models import TrustTransaction, MatterLedger, MonthlyReconciliation, Irregularity, TrustJournal, TrustAccount


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
        .filter(
            transaction_type='receipt',
            matter_ledger__trust_account=trust_account,
            created_at__date__range=(date_from, date_to),
        )
        .select_related('matter_ledger__matter', 'receipt')
        .order_by('created_at', 'receipt__receipt_number', 'pk')
    )

    buffer = io.BytesIO()
    col_headers = [
        'Date receipt made out', 'Date received / confirmed in trust account (if different)',
        'Date deposited to trust account', 'Receipt #', 'Matter', 'Payor', 'Method', 'Amount ($)', 'Reason', 'Ledger credited'
    ]
    rows = []
    for txn in transactions:
        r = getattr(txn, 'receipt', None)
        date_made_out = r.date_made_out if r else None
        rows.append([
            str(date_made_out or ''),
            str(txn.date_received_or_paid) if txn.date_received_or_paid != date_made_out else '',
            str(txn.date_banked or ''),
            str(r.receipt_number) if r else '',
            str(txn.matter_ledger.matter),
            r.payor_name if r else '',
            r.get_payment_method_display() if r else '',
            str(txn.amount),
            r.purpose if r else txn.description,
            str(txn.matter_ledger),
        ])

    _build_pdf_document(buffer, trust_account, 'Trust Receipts Cash Book',
                        f"{date_from} to {date_to}", rows, col_headers)
    return buffer.getvalue()


def payments_journal_pdf(trust_account, date_from, date_to):
    return _pdf_response_from_bytes(
        f'payments_journal_{date_from}_{date_to}.pdf',
        payments_cash_book_pdf_bytes(trust_account, date_from, date_to),
    )


def payments_cash_book_pdf_bytes(trust_account, date_from, date_to):
    transactions = (
        TrustTransaction.objects
        .filter(
            transaction_type__in=['payment', 'transfer_to_office'],
            matter_ledger__trust_account=trust_account,
            date_received_or_paid__range=(date_from, date_to),
        )
        .select_related('matter_ledger__matter', 'payment')
        .order_by('date_received_or_paid', 'payment__payment_number')
    )

    buffer = io.BytesIO()
    col_headers = ['Date', 'Type', 'Payment #', 'Matter', 'Payee', 'Method', 'Amount ($)']
    rows = []
    for txn in transactions:
        p = getattr(txn, 'payment', None)
        rows.append([
            str(txn.date_received_or_paid),
            txn.get_transaction_type_display(),
            str(p.payment_number) if p else '',
            str(txn.matter_ledger.matter),
            p.payee_name if p else '',
            p.get_payment_method_display() if p else '',
            str(txn.amount),
        ])

    _build_pdf_document(buffer, trust_account, 'Trust Payments Cash Book',
                        f"{date_from} to {date_to}", rows, col_headers)
    return buffer.getvalue()


def trust_transfer_journal_pdf_bytes(trust_account, date_from, date_to):
    journals = (
        TrustJournal.objects
        .filter(
            from_ledger__trust_account=trust_account,
            journal_out_txn__date_received_or_paid__range=(date_from, date_to),
        )
        .select_related('from_ledger__matter', 'to_ledger__matter', 'journal_out_txn')
        .order_by('journal_out_txn__date_received_or_paid', 'pk')
    )
    buffer = io.BytesIO()
    col_headers = ['Date', 'From Matter', 'To Matter', 'Amount ($)', 'Description', 'Authority Date', 'Authority Signed By']
    rows = []
    for journal in journals:
        rows.append([
            str(journal.journal_out_txn.date_received_or_paid) if journal.journal_out_txn else '',
            str(journal.from_ledger.matter),
            str(journal.to_ledger.matter),
            str(journal.amount),
            journal.description,
            str(journal.authority_date),
            journal.authority_signed_by,
        ])
    _build_pdf_document(buffer, trust_account, 'Trust Transfer Journal', f"{date_from} to {date_to}", rows, col_headers)
    return buffer.getvalue()


def trust_transfer_journal_pdf(trust_account, date_from, date_to):
    return _pdf_response_from_bytes(
        f'trust_transfer_journal_{date_from}_{date_to}.pdf',
        trust_transfer_journal_pdf_bytes(trust_account, date_from, date_to),
    )


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
        .select_related('matter')
        .order_by('matter__file_number')
    )
    balances = calculate_ledger_balances_as_at(trust_account, as_at)

    buffer = io.BytesIO()
    col_headers = ['Ledger name', 'Identifying reference', 'Matter description', 'Balance ($)']
    rows = []
    total = Decimal('0.00')
    for ledger in ledgers:
        balance = balances.get(ledger.pk, Decimal('0.00'))
        matter = ledger.matter
        rows.append([str(matter), matter.file_number or str(ledger.pk), matter.description, str(balance)])
        total += balance
    rows.append(['TOTAL', '', '', str(total)])
    rows.append(['Date generated / prepared', '', '', str(timezone.localdate())])
    if reconciliation:
        rows.extend([
            ['Date statement prepared', '', '', str(reconciliation.date_statement_prepared or '')],
            ['Reconciliation due date', '', '', str(reconciliation.reconciliation_due_date)],
            ['Prepared within required period', '', '', 'Yes' if reconciliation.prepared_within_required_period else 'No'],
            ['Preparation status', '', '', reconciliation.preparation_status_label],
        ])

    _build_pdf_document(buffer, trust_account, 'Trust Trial Balance Statement / Ledger Reconciliation – Rule 48(2)(b)',
                        f"As at {as_at}", rows, col_headers)
    return buffer.getvalue()


def monthly_reconciliation_pdf(reconciliation):
    return _pdf_response_from_bytes(
        f'reconciliation_{reconciliation.period_end}.pdf',
        reconciliation_statement_pdf_bytes(reconciliation),
    )


def reconciliation_statement_pdf_bytes(reconciliation):
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
        ['Reconciled?', 'Yes' if reconciliation.is_reconciled else 'NO - DISCREPANCY'],
        ['Finalised?', 'Yes' if getattr(reconciliation, 'is_finalised', False) else 'No'],
        ['Finalised By', str(reconciliation.finalised_by) if getattr(reconciliation, 'finalised_by_id', None) else ''],
        ['Finalised On', str(reconciliation.finalised_on) if getattr(reconciliation, 'finalised_on', None) else ''],
        ['Date statement prepared', str(reconciliation.date_statement_prepared or '')],
        ['Reconciliation due date', str(reconciliation.reconciliation_due_date)],
        ['Prepared within required period', 'Yes' if reconciliation.prepared_within_required_period else 'No' if reconciliation.finalised_on else ''],
        ['Preparation status', reconciliation.preparation_status_label],
        ['Period Status', reconciliation.accounting_period.get_status_display() if getattr(reconciliation, 'accounting_period_id', None) else ''],
    ]
    _build_pdf_document(buffer, trust_account, 'Monthly Trust Reconciliation',
                        str(reconciliation.period_end), rows, col_headers)
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
    """Generate a PDF for a single trust receipt."""
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required for PDF generation")
    trust_account = receipt.transaction.matter_ledger.trust_account
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5*cm, rightMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    elements = []
    elements.append(Paragraph(f"Trust Receipt #{receipt.receipt_number}", styles['Heading1']))
    for line in _build_header_info(trust_account):
        elements.append(Paragraph(line, styles['Normal']))
    elements.append(Spacer(1, 0.5*cm))
    details = [
        ['Receipt Number', str(receipt.receipt_number)],
        ['Date receipt made out', str(receipt.date_made_out or '')],
        ['Date received / confirmed in trust account', str(receipt.transaction.date_received_or_paid)],
        ['Payor', receipt.payor_name],
        ['Payment Method', receipt.get_payment_method_display()],
        ['Cheque Number', receipt.cheque_number],
        ['Purpose', receipt.purpose],
        ['Amount', f"${receipt.transaction.amount}"],
        ['Matter', str(receipt.transaction.matter_ledger.matter)],
        ['Deposit delay — review if not deposited as soon as practicable', 'Yes' if receipt.late_banking else 'No'],
    ]
    if receipt.uses_separate_deposit_date:
        details.insert(3, ['Date deposited to trust account', str(receipt.transaction.date_banked or '')])
    t = Table(details)
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(FOOTER_TEXT, styles['Italic']))
    doc.build(elements)
    response = _make_pdf_response(f'receipt_{receipt.receipt_number}.pdf')
    response.write(buffer.getvalue())
    return response

import hashlib
import json
from django.core.files.base import ContentFile
from .models import ControlledMoneyAccount, ControlledMoneyReceipt, ControlledMoneyWithdrawal, ControlledMoneyMonthlyStatement, TrustMonthlyRecord, TrustAccountingPeriod


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
    buffer = io.BytesIO(); _build_pdf_document(buffer, accounts.first() or TrustAccount.objects.filter(firm=statement.firm).first(), 'Controlled Money Monthly Statement – in progress', f'As at {statement.period_end}', rows, ['Account name','Account number','Register balance','Person on behalf','Matter description'])
    return buffer.getvalue()


def ensure_controlled_money_monthly_statement_pdf(statement):
    if not statement.pdf:
        data = controlled_money_monthly_statement_pdf_bytes(statement); statement.sha256_hash = hashlib.sha256(data).hexdigest(); statement.pdf.save(f'controlled_money_statement_{statement.period_end}.pdf', ContentFile(data), save=False); statement.save()
    return statement.pdf.read()


def trust_records_export_pack_zip(trust_account, date_from=None, date_to=None, year=None, all_data=False):
    if year and not (date_from or date_to): date_from, date_to = datetime.date(year,1,1), datetime.date(year,12,31)
    if all_data: date_from, date_to = datetime.date(1900,1,1), timezone.localdate()
    date_from = date_from or datetime.date(timezone.localdate().year,1,1); date_to = date_to or timezone.localdate()
    buf=io.BytesIO(); manifest=[]
    def add(zf, name, data, source):
        if isinstance(data, str):
            data = data.encode()
        h = hashlib.sha256(data).hexdigest()
        zf.writestr(name, data)
        manifest.append({'path': name, 'sha256': h, 'source': source})
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as zf:
        for rec in TrustMonthlyRecord.objects.filter(trust_account=trust_account, accounting_period__period_end__range=(date_from,date_to)):
            if rec.pdf: add(zf, f'retained-monthly-records/{rec.accounting_period.period_end}/{rec.record_type}.pdf', rec.pdf.read(), 'retained')
        add(zf,'live-generated/receipts_cash_book.pdf',receipts_cash_book_pdf_bytes(trust_account,date_from,date_to),'live-generated')
        add(zf,'live-generated/payments_cash_book.pdf',payments_cash_book_pdf_bytes(trust_account,date_from,date_to),'live-generated')
        add(zf,'live-generated/trust_transfer_journal.pdf',trust_transfer_journal_pdf_bytes(trust_account,date_from,date_to),'live-generated')
        add(zf,'live-generated/trial_balance.pdf',trial_balance_pdf_bytes(trust_account,date_to),'live-generated')
        for ledger in MatterLedger.objects.filter(trust_account=trust_account).select_related('matter__client','trust_account__firm'):
            add(zf,f'live-generated/matter-ledgers/ledger_{ledger.pk}.pdf', matter_ledger_statement_pdf(ledger).content, 'live-generated')
            add(zf,f'live-generated/trust-account-statements/statement_{ledger.pk}.pdf', trust_account_statement_pdf_bytes(ledger,date_from,date_to),'live-generated')
        for recon in MonthlyReconciliation.objects.filter(trust_account=trust_account, period_end__range=(date_from,date_to)):
            add(zf,f'live-generated/reconciliations/reconciliation_{recon.period_end}.pdf',reconciliation_statement_pdf_bytes(recon),'live-generated')
            if recon.bank_statement_pdf: add(zf,f'evidence/bank-statements/{recon.bank_statement_pdf.name.split("/")[-1]}',recon.bank_statement_pdf.read(),'stored-evidence')
        for st in ControlledMoneyMonthlyStatement.objects.filter(firm=trust_account.firm, period_end__range=(date_from,date_to)):
            add(zf,f'controlled-money/monthly-statements/{st.period_end}.pdf',ensure_controlled_money_monthly_statement_pdf(st),'permanent-controlled-money-record')
        txns=list(TrustTransaction.objects.filter(matter_ledger__trust_account=trust_account, date_received_or_paid__range=(date_from,date_to)).values('id','transaction_type','amount','date_received_or_paid','description','matter_ledger_id'))
        add(zf,'exports/trust_transactions.json',json.dumps(txns,default=str,indent=2),'export')
        csvbuf=io.StringIO(); w=csv.DictWriter(csvbuf, fieldnames=['id','transaction_type','amount','date_received_or_paid','description','matter_ledger_id']); w.writeheader(); [w.writerow(t) for t in txns]; add(zf,'exports/trust_transactions.csv',csvbuf.getvalue(),'export')
        ledgers=list(MatterLedger.objects.filter(trust_account=trust_account).values('id','matter_id','balance')); add(zf,'exports/matter_ledgers.json',json.dumps(ledgers,default=str,indent=2),'export')
        add(zf,'exports/reconciliations.json',json.dumps(list(MonthlyReconciliation.objects.filter(trust_account=trust_account).values()),default=str,indent=2),'export')
        add(zf,'exports/monthly_records.json',json.dumps(list(TrustMonthlyRecord.objects.filter(trust_account=trust_account).values('id','record_type','sha256_hash','generated_at')),default=str,indent=2),'export')
        add(zf,'exports/accounting_periods.json',json.dumps(list(TrustAccountingPeriod.objects.filter(trust_account=trust_account).values()),default=str,indent=2),'export')
        add(zf,'exports/irregularities.json',json.dumps(list(Irregularity.objects.filter(trust_account=trust_account).values()),default=str,indent=2),'export')
        add(zf,'manifest.json',json.dumps(manifest,indent=2),'manifest')
        hash_lines='\n'.join(f"{m['sha256']}  {m['path']}" for m in manifest); add(zf,'SHA256SUMS.txt',hash_lines,'manifest')
    return HttpResponse(buf.getvalue(), content_type='application/zip', headers={'Content-Disposition': f'attachment; filename="trust_records_export_pack_{date_from}_{date_to}.zip"'})
