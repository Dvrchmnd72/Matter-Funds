import datetime
import calendar
import hashlib
from decimal import Decimal, ROUND_HALF_EVEN

from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    MatterLedger, TrustAccount, TrustTransaction, Receipt, Payment, TrustJournal,
    TrustAccountingPeriod, MonthlyReconciliation, TrustMonthlyRecord,
)


def _quantize(amount):
    return Decimal(amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)


def get_month_bounds(date_value):
    return (
        datetime.date(date_value.year, date_value.month, 1),
        datetime.date(date_value.year, date_value.month, calendar.monthrange(date_value.year, date_value.month)[1]),
    )


def get_or_create_accounting_period(trust_account, date_value):
    period_start, period_end = get_month_bounds(date_value)
    period, _ = TrustAccountingPeriod.objects.get_or_create(
        trust_account=trust_account,
        period_start=period_start,
        period_end=period_end,
        defaults={'status': TrustAccountingPeriod.STATUS_OPEN},
    )
    return period


def get_accounting_period_for_date(trust_account, date_value):
    return TrustAccountingPeriod.objects.filter(
        trust_account=trust_account,
        period_start__lte=date_value,
        period_end__gte=date_value,
    ).first()


def ensure_period_is_open(trust_account, date_value):
    period = get_or_create_accounting_period(trust_account, date_value)
    if period.status == TrustAccountingPeriod.STATUS_LOCKED:
        raise ValidationError('The accounting period for this transaction date is locked.')
    return period


def required_monthly_record_types():
    return [
        TrustMonthlyRecord.RECORD_RECEIPTS_CASH_BOOK,
        TrustMonthlyRecord.RECORD_PAYMENTS_CASH_BOOK,
        TrustMonthlyRecord.RECORD_TRUST_TRANSFER_JOURNAL,
        TrustMonthlyRecord.RECORD_TRIAL_BALANCE,
        TrustMonthlyRecord.RECORD_RECONCILIATION_STATEMENT,
    ]


def calculate_pdf_sha256(pdf_bytes):
    return hashlib.sha256(pdf_bytes).hexdigest()


def has_all_required_monthly_records(period):
    existing = set(period.monthly_records.values_list('record_type', flat=True))
    return set(required_monthly_record_types()).issubset(existing)


def _monthly_record_filename(reconciliation, record_type):
    return f"{record_type}_{reconciliation.period_end}.pdf"


def generate_monthly_record(reconciliation, record_type, user):
    from . import reports as trust_reports

    if not reconciliation.accounting_period_id:
        raise ValidationError('Reconciliation must be linked to an accounting period before records can be generated.')
    period = reconciliation.accounting_period
    trust_account = reconciliation.trust_account
    if TrustMonthlyRecord.objects.filter(accounting_period=period, record_type=record_type).exists():
        raise ValidationError(f'{dict(TrustMonthlyRecord.RECORD_TYPE_CHOICES).get(record_type, record_type)} already exists for this period.')

    if record_type == TrustMonthlyRecord.RECORD_RECEIPTS_CASH_BOOK:
        pdf_bytes = trust_reports.receipts_cash_book_pdf_bytes(trust_account, period.period_start, period.period_end)
    elif record_type == TrustMonthlyRecord.RECORD_PAYMENTS_CASH_BOOK:
        pdf_bytes = trust_reports.payments_cash_book_pdf_bytes(trust_account, period.period_start, period.period_end)
    elif record_type == TrustMonthlyRecord.RECORD_TRUST_TRANSFER_JOURNAL:
        pdf_bytes = trust_reports.trust_transfer_journal_pdf_bytes(trust_account, period.period_start, period.period_end)
    elif record_type == TrustMonthlyRecord.RECORD_TRIAL_BALANCE:
        pdf_bytes = trust_reports.trial_balance_pdf_bytes(trust_account, period.period_end)
    elif record_type == TrustMonthlyRecord.RECORD_RECONCILIATION_STATEMENT:
        pdf_bytes = trust_reports.reconciliation_statement_pdf_bytes(reconciliation)
    else:
        raise ValidationError('Unknown monthly record type.')

    monthly_record = TrustMonthlyRecord(
        accounting_period=period,
        reconciliation=reconciliation,
        trust_account=trust_account,
        record_type=record_type,
        generated_by=user,
        sha256_hash=calculate_pdf_sha256(pdf_bytes),
    )
    monthly_record.pdf.save(_monthly_record_filename(reconciliation, record_type), ContentFile(pdf_bytes), save=False)
    monthly_record.full_clean()
    monthly_record.save()
    return monthly_record


def generate_monthly_records_for_reconciliation(reconciliation, user):
    records = []
    for record_type in required_monthly_record_types():
        records.append(generate_monthly_record(reconciliation, record_type, user))
    return records


def can_finalise_reconciliation(reconciliation):
    reasons = []
    if reconciliation.is_finalised:
        reasons.append('Reconciliation is already finalised.')
    if not reconciliation.is_reconciled:
        reasons.append('Reconciliation is not balanced.')
    if not reconciliation.bank_statement_pdf:
        reasons.append('Bank statement PDF is required.')
    if not reconciliation.accounting_period_id:
        reasons.append('Reconciliation is not linked to an accounting period.')
    elif reconciliation.accounting_period.status == TrustAccountingPeriod.STATUS_LOCKED:
        reasons.append('Accounting period is locked.')
    return not reasons, reasons


def finalise_reconciliation(reconciliation, user):
    with transaction.atomic():
        recon = MonthlyReconciliation.objects.select_for_update().select_related('accounting_period').get(pk=reconciliation.pk)
        can_finalise, reasons = can_finalise_reconciliation(recon)
        if not can_finalise:
            raise ValidationError(' '.join(reasons))
        period = TrustAccountingPeriod.objects.select_for_update().get(pk=recon.accounting_period_id)
        if period.status == TrustAccountingPeriod.STATUS_LOCKED:
            raise ValidationError('Accounting period is locked.')
        now = timezone.now()
        recon.is_finalised = True
        recon.finalised_by = user
        recon.finalised_on = now
        recon.signed_by = recon.signed_by or user
        recon.signed_on = recon.signed_on or now
        recon.full_clean()
        recon.save()
        generate_monthly_records_for_reconciliation(recon, user)
    return recon


def lock_accounting_period(period, user):
    with transaction.atomic():
        locked_period = TrustAccountingPeriod.objects.select_for_update().get(pk=period.pk)
        if locked_period.status == TrustAccountingPeriod.STATUS_LOCKED:
            raise ValidationError('Accounting period is already locked.')
        reconciliation = getattr(locked_period, 'reconciliation', None)
        if not reconciliation or not reconciliation.is_finalised:
            raise ValidationError('Accounting period requires a finalised reconciliation before locking.')
        if not has_all_required_monthly_records(locked_period):
            raise ValidationError('All required monthly records must be generated before locking.')
        locked_period.status = TrustAccountingPeriod.STATUS_LOCKED
        locked_period.locked_by = user
        locked_period.locked_on = timezone.now()
        locked_period.full_clean()
        locked_period.save(update_fields=['status', 'locked_by', 'locked_on', 'updated_at'])
        return locked_period


def create_receipt(*, matter_ledger, amount, date_received, date_banked=None,
                   payor_name, payment_method, cheque_number='', purpose, created_by):
    amount = _quantize(amount)
    with transaction.atomic():
        ledger = MatterLedger.objects.select_for_update().get(pk=matter_ledger.pk)
        trust_account = TrustAccount.objects.select_for_update().get(pk=ledger.trust_account_id)
        ensure_period_is_open(trust_account, date_received)

        receipt_number = trust_account.next_receipt_number
        trust_account.next_receipt_number += 1
        trust_account.save(update_fields=['next_receipt_number'])

        txn = TrustTransaction(
            transaction_type='receipt',
            matter_ledger=ledger,
            amount=amount,
            date_received_or_paid=date_received,
            date_banked=date_banked,
            description=f"Receipt: {purpose}",
            created_by=created_by,
        )
        txn.save()

        late_banking = False
        if date_banked and date_received:
            delta = (date_banked - date_received).days
            if delta > 1:
                late_banking = True

        receipt = Receipt(
            transaction=txn,
            receipt_number=receipt_number,
            payor_name=payor_name,
            payment_method=payment_method,
            cheque_number=cheque_number,
            purpose=purpose,
            late_banking=late_banking,
        )
        receipt.save()

        ledger.balance = _quantize(ledger.balance + amount)
        ledger.save(update_fields=['balance'])

    return receipt


def create_payment(*, matter_ledger, amount, date_paid, payee_name, payee_bsb='',
                   payee_account='', payment_method, cheque_number='', purpose,
                   authorised_by, second_authoriser=None, created_by):
    amount = _quantize(amount)
    with transaction.atomic():
        ledger = MatterLedger.objects.select_for_update().get(pk=matter_ledger.pk)
        ensure_period_is_open(ledger.trust_account, date_paid)

        if ledger.balance < amount:
            raise ValidationError(f"Insufficient trust funds: balance is {ledger.balance}, payment is {amount}.")

        trust_account = TrustAccount.objects.select_for_update().get(pk=ledger.trust_account_id)
        payment_number = trust_account.next_payment_number
        trust_account.next_payment_number += 1
        trust_account.save(update_fields=['next_payment_number'])

        txn = TrustTransaction(
            transaction_type='payment',
            matter_ledger=ledger,
            amount=amount,
            date_received_or_paid=date_paid,
            description=f"Payment: {purpose}",
            created_by=created_by,
        )
        txn.save()

        payment = Payment(
            transaction=txn,
            payment_number=payment_number,
            payee_name=payee_name,
            payee_bsb=payee_bsb,
            payee_account=payee_account,
            payment_method=payment_method,
            cheque_number=cheque_number,
            purpose=purpose,
            authorised_by=authorised_by,
            second_authoriser=second_authoriser,
        )
        payment.save()

        ledger.balance = _quantize(ledger.balance - amount)
        ledger.save(update_fields=['balance'])

    return payment


def _validate_costs_withdrawal_evidence(*, costs_withdrawal_method, costs_evidence_file=None,
                                        notice_or_request_file=None, authority_or_agreement_file=None,
                                        reimbursement_evidence_file=None):
    if not costs_withdrawal_method:
        raise ValidationError("Costs withdrawal method is required.")
    valid_methods = {choice for choice, _ in Payment.COSTS_WITHDRAWAL_METHOD_CHOICES}
    if costs_withdrawal_method not in valid_methods:
        raise ValidationError("Invalid costs withdrawal method.")
    if not any([costs_evidence_file, notice_or_request_file, authority_or_agreement_file, reimbursement_evidence_file]):
        raise ValidationError("At least one costs withdrawal evidence document is required.")
    if costs_withdrawal_method in ('method_2_authority', 'method_4_commercial_government') and not authority_or_agreement_file:
        raise ValidationError("Authority or agreement evidence is required for this withdrawal method.")
    if costs_withdrawal_method == 'method_3_reimbursement' and not reimbursement_evidence_file:
        raise ValidationError("Reimbursement evidence is required for Method 3 withdrawals.")


def create_transfer_to_office(*, matter_ledger, amount, date_paid, payee_name, payee_bsb='',
                              payee_account='', payment_method, cheque_number='', purpose,
                              authorised_by, second_authoriser=None, created_by,
                              costs_withdrawal_method, key_evidence_date=None,
                              costs_evidence_file=None, notice_or_request_file=None,
                              authority_or_agreement_file=None, reimbursement_evidence_file=None,
                              costs_withdrawal_notes=''):
    _validate_costs_withdrawal_evidence(
        costs_withdrawal_method=costs_withdrawal_method,
        costs_evidence_file=costs_evidence_file,
        notice_or_request_file=notice_or_request_file,
        authority_or_agreement_file=authority_or_agreement_file,
        reimbursement_evidence_file=reimbursement_evidence_file,
    )
    amount = _quantize(amount)
    with transaction.atomic():
        ledger = MatterLedger.objects.select_for_update().get(pk=matter_ledger.pk)
        ensure_period_is_open(ledger.trust_account, date_paid)

        if ledger.balance < amount:
            raise ValidationError(f"Insufficient trust funds: balance is {ledger.balance}, transfer is {amount}.")

        trust_account = TrustAccount.objects.select_for_update().get(pk=ledger.trust_account_id)
        payment_number = trust_account.next_payment_number
        trust_account.next_payment_number += 1
        trust_account.save(update_fields=['next_payment_number'])

        txn = TrustTransaction(
            transaction_type='transfer_to_office',
            matter_ledger=ledger,
            amount=amount,
            date_received_or_paid=date_paid,
            description=f"Transfer to office: {purpose}",
            created_by=created_by,
        )
        txn.save()

        payment = Payment(
            transaction=txn,
            payment_number=payment_number,
            payee_name=payee_name,
            payee_bsb=payee_bsb,
            payee_account=payee_account,
            payment_method=payment_method,
            cheque_number=cheque_number,
            purpose=purpose,
            authorised_by=authorised_by,
            second_authoriser=second_authoriser,
            costs_withdrawal_method=costs_withdrawal_method,
            key_evidence_date=key_evidence_date,
            costs_evidence_file=costs_evidence_file,
            notice_or_request_file=notice_or_request_file,
            authority_or_agreement_file=authority_or_agreement_file,
            reimbursement_evidence_file=reimbursement_evidence_file,
            costs_withdrawal_notes=costs_withdrawal_notes,
        )
        payment.save()

        ledger.balance = _quantize(ledger.balance - amount)
        ledger.save(update_fields=['balance'])

    return payment


def create_trust_journal(*, from_ledger, to_ledger, amount, description,
                         written_authority_file, authority_date, authority_signed_by, created_by):
    amount = _quantize(amount)
    if from_ledger.pk == to_ledger.pk:
        raise ValidationError("From ledger and to ledger must differ.")
    if from_ledger.trust_account_id != to_ledger.trust_account_id:
        raise ValidationError("Both ledgers must be on the same trust account.")

    with transaction.atomic():
        from_l = MatterLedger.objects.select_for_update().get(pk=from_ledger.pk)
        to_l = MatterLedger.objects.select_for_update().get(pk=to_ledger.pk)

        if from_l.balance < amount:
            raise ValidationError(f"Insufficient funds in source ledger: balance {from_l.balance}, journal amount {amount}.")

        today = datetime.date.today()
        ensure_period_is_open(from_l.trust_account, today)

        txn_out = TrustTransaction(
            transaction_type='journal_out',
            matter_ledger=from_l,
            amount=amount,
            date_received_or_paid=today,
            description=description,
            created_by=created_by,
        )
        txn_out.save()

        txn_in = TrustTransaction(
            transaction_type='journal_in',
            matter_ledger=to_l,
            amount=amount,
            date_received_or_paid=today,
            description=description,
            created_by=created_by,
        )
        txn_in.save()

        journal = TrustJournal(
            from_ledger=from_l,
            to_ledger=to_l,
            amount=amount,
            description=description,
            written_authority=written_authority_file,
            authority_date=authority_date,
            authority_signed_by=authority_signed_by,
            journal_out_txn=txn_out,
            journal_in_txn=txn_in,
            created_by=created_by,
        )
        journal.save()

        from_l.balance = _quantize(from_l.balance - amount)
        from_l.save(update_fields=['balance'])

        to_l.balance = _quantize(to_l.balance + amount)
        to_l.save(update_fields=['balance'])

    return journal


def reverse_transaction(*, transaction_obj, reason, created_by):
    with transaction.atomic():
        if transaction_obj.is_reversed:
            raise ValidationError("This transaction has already been reversed.")

        ledger = MatterLedger.objects.select_for_update().get(pk=transaction_obj.matter_ledger_id)
        ensure_period_is_open(ledger.trust_account, datetime.date.today())

        txn_type = transaction_obj.transaction_type
        if txn_type in ('receipt', 'journal_in'):
            if ledger.balance < transaction_obj.amount:
                raise ValidationError("Cannot reverse: reversal would cause ledger to go negative.")
            balance_delta = -transaction_obj.amount
        elif txn_type in ('payment', 'journal_out', 'transfer_to_office'):
            balance_delta = transaction_obj.amount
        else:
            raise ValidationError(f"Cannot reverse a transaction of type '{txn_type}'.")

        reversal = TrustTransaction(
            transaction_type='reversal',
            matter_ledger=ledger,
            amount=transaction_obj.amount,
            date_received_or_paid=datetime.date.today(),
            description=f"Reversal of transaction #{transaction_obj.pk}: {reason}",
            created_by=created_by,
            reverses=transaction_obj,
        )
        reversal.save()

        ledger.balance = _quantize(ledger.balance + balance_delta)
        ledger.save(update_fields=['balance'])

        TrustTransaction.objects.filter(pk=transaction_obj.pk).update(is_reversed=True)
        transaction_obj.is_reversed = True

    return reversal
