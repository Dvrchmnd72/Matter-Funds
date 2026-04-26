import datetime
from decimal import Decimal, ROUND_HALF_EVEN

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    MatterLedger, TrustAccount, TrustTransaction, Receipt, Payment, TrustJournal,
)


def _quantize(amount):
    return Decimal(amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)


def create_receipt(*, matter_ledger, amount, date_received, date_banked=None,
                   payor_name, payment_method, cheque_number='', purpose, created_by):
    amount = _quantize(amount)
    with transaction.atomic():
        ledger = MatterLedger.objects.select_for_update().get(pk=matter_ledger.pk)
        trust_account = TrustAccount.objects.select_for_update().get(pk=ledger.trust_account_id)

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

        if ledger.balance < amount:
            raise ValidationError(f"Insufficient trust funds: balance is {ledger.balance}, payment is {amount}.")

        firm = ledger.trust_account.firm
        if payment_method == 'eft' and not firm.is_sole_practitioner:
            if not second_authoriser:
                raise ValidationError("EFT payments require a second authoriser for non-sole-practitioner firms (R44).")
            if second_authoriser.pk == authorised_by.pk:
                raise ValidationError("Second authoriser must differ from the authorising person (R44).")

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
