import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


class TrustAccount(models.Model):
    firm = models.ForeignKey('firms.Firm', on_delete=models.PROTECT, related_name='trust_accounts')
    name = models.CharField(max_length=255)
    bank = models.CharField(max_length=255)
    bsb = models.CharField(max_length=7, validators=[RegexValidator(r'^\d{3}-\d{3}$', 'BSB must be in format 000-000')])
    account_number = models.CharField(max_length=20)
    is_general = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    next_receipt_number = models.PositiveIntegerField(default=1)
    next_payment_number = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = 'Trust Account'
        verbose_name_plural = 'Trust Accounts'

    def __str__(self):
        return f"{self.name} ({self.bsb} {self.account_number})"


class ControlledMoneyAccount(models.Model):
    firm = models.ForeignKey('firms.Firm', on_delete=models.PROTECT, related_name='controlled_money_accounts')
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='controlled_money_accounts')
    matter = models.ForeignKey('matters.Matter', on_delete=models.PROTECT, null=True, blank=True, related_name='controlled_money_accounts')
    bank = models.CharField(max_length=255)
    bsb = models.CharField(max_length=7, validators=[RegexValidator(r'^\d{3}-\d{3}$', 'BSB must be in format 000-000')])
    account_number = models.CharField(max_length=20)
    client_instruction_document = models.FileField(upload_to='controlled_money/instructions/')
    interest_disposition = models.TextField()
    opened_on = models.DateField(default=datetime.date.today)
    closed_on = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = 'Controlled Money Account'
        verbose_name_plural = 'Controlled Money Accounts'

    def __str__(self):
        return f"Controlled Money \u2013 {self.client} ({self.bsb} {self.account_number})"


class MatterLedger(models.Model):
    matter = models.ForeignKey('matters.Matter', on_delete=models.PROTECT, related_name='ledgers')
    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='ledgers')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    opened_on = models.DateTimeField(auto_now_add=True)
    closed_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('matter', 'trust_account')]
        verbose_name = 'Matter Ledger'
        verbose_name_plural = 'Matter Ledgers'
        constraints = [
            models.CheckConstraint(check=models.Q(balance__gte=0), name='matter_ledger_balance_non_negative')
        ]

    def __str__(self):
        return f"Ledger: {self.matter} @ {self.trust_account}"

    def clean(self):
        if self.balance is not None and self.balance < 0:
            raise ValidationError({'balance': 'Ledger balance cannot be negative.'})


class TrustTransaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [
        ('receipt', 'Receipt'),
        ('payment', 'Payment'),
        ('journal_in', 'Journal In'),
        ('journal_out', 'Journal Out'),
        ('transfer_to_office', 'Transfer to Office'),
        ('reversal', 'Reversal'),
    ]

    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    matter_ledger = models.ForeignKey(MatterLedger, on_delete=models.PROTECT, related_name='transactions')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    date_received_or_paid = models.DateField()
    date_banked = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=500)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='trust_transactions')
    created_at = models.DateTimeField(auto_now_add=True)
    is_reversed = models.BooleanField(default=False)
    reverses = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='reversed_by')

    class Meta:
        verbose_name = 'Trust Transaction'
        verbose_name_plural = 'Trust Transactions'

    def __str__(self):
        return f"{self.get_transaction_type_display()} ${self.amount} on {self.date_received_or_paid}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("TrustTransaction is append-only; create a reversal instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("TrustTransaction records cannot be deleted.")


class Receipt(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('eft', 'EFT'),
        ('direct_deposit', 'Direct Deposit'),
    ]

    transaction = models.OneToOneField(TrustTransaction, on_delete=models.PROTECT, related_name='receipt')
    receipt_number = models.PositiveIntegerField()
    payor_name = models.CharField(max_length=255)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    cheque_number = models.CharField(max_length=50, blank=True)
    purpose = models.CharField(max_length=500)
    late_banking = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Receipt'
        verbose_name_plural = 'Receipts'
        unique_together = [('receipt_number', 'transaction')]

    def __str__(self):
        return f"Receipt #{self.receipt_number} \u2013 {self.payor_name} ${self.transaction.amount}"

    def clean(self):
        if self.transaction_id and self.transaction.date_banked and self.transaction.date_received_or_paid:
            delta = (self.transaction.date_banked - self.transaction.date_received_or_paid).days
            if delta > 1:
                self.late_banking = True


class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('cheque', 'Cheque'),
        ('eft', 'EFT'),
    ]
    COSTS_WITHDRAWAL_METHOD_CHOICES = [
        ('method_1_bill_issued', 'Method 1 - Bill issued'),
        ('method_2_authority', 'Method 2 - Authority'),
        ('method_3_reimbursement', 'Method 3 - Reimbursement'),
        ('method_4_commercial_government', 'Method 4 - Commercial/Government client'),
    ]

    transaction = models.OneToOneField(TrustTransaction, on_delete=models.PROTECT, related_name='payment')
    payment_number = models.PositiveIntegerField()
    payee_name = models.CharField(max_length=255)
    payee_bsb = models.CharField(max_length=7, blank=True)
    payee_account = models.CharField(max_length=20, blank=True)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES)
    cheque_number = models.CharField(max_length=50, blank=True)
    purpose = models.CharField(max_length=500)
    authorised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='trust_payments_authorised')
    second_authoriser = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='trust_payments_second_authorised')
    costs_withdrawal_method = models.CharField(max_length=40, choices=COSTS_WITHDRAWAL_METHOD_CHOICES, blank=True, default='')
    key_evidence_date = models.DateField(null=True, blank=True)
    costs_evidence_file = models.FileField(upload_to='trust/costs/evidence/', null=True, blank=True)
    notice_or_request_file = models.FileField(upload_to='trust/costs/notices/', null=True, blank=True)
    authority_or_agreement_file = models.FileField(upload_to='trust/costs/authorities/', null=True, blank=True)
    reimbursement_evidence_file = models.FileField(upload_to='trust/costs/reimbursements/', null=True, blank=True)
    costs_withdrawal_notes = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'

    def __str__(self):
        return f"Payment #{self.payment_number} \u2013 {self.payee_name} ${self.transaction.amount}"

    def clean(self):
        if self.payment_method == 'eft':
            try:
                firm = self.transaction.matter_ledger.trust_account.firm
            except Exception:
                return
            if not firm.is_sole_practitioner:
                if not self.second_authoriser_id:
                    raise ValidationError({'second_authoriser': 'EFT payments require a second authoriser for non-sole-practitioner firms (R44).'})
                if self.second_authoriser_id == self.authorised_by_id:
                    raise ValidationError({'second_authoriser': 'Second authoriser must differ from the authorising person (R44).'})


class TrustJournal(models.Model):
    from_ledger = models.ForeignKey(MatterLedger, on_delete=models.PROTECT, related_name='journals_out')
    to_ledger = models.ForeignKey(MatterLedger, on_delete=models.PROTECT, related_name='journals_in')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    description = models.CharField(max_length=500)
    written_authority = models.FileField(upload_to='trust/authorities/')
    authority_date = models.DateField()
    authority_signed_by = models.CharField(max_length=255)
    journal_out_txn = models.OneToOneField(TrustTransaction, on_delete=models.PROTECT, null=True, blank=True, related_name='journal_as_out')
    journal_in_txn = models.OneToOneField(TrustTransaction, on_delete=models.PROTECT, null=True, blank=True, related_name='journal_as_in')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='trust_journals')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Trust Journal'
        verbose_name_plural = 'Trust Journals'

    def __str__(self):
        return f"Journal ${self.amount}: {self.from_ledger} \u2192 {self.to_ledger}"

    def clean(self):
        if self.from_ledger_id and self.to_ledger_id:
            if self.from_ledger_id == self.to_ledger_id:
                raise ValidationError('From ledger and to ledger must differ.')
            if self.from_ledger.trust_account_id != self.to_ledger.trust_account_id:
                raise ValidationError('Both ledgers must be on the same trust account.')


class WrittenDirection(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='written_directions')
    matter = models.ForeignKey('matters.Matter', on_delete=models.PROTECT, null=True, blank=True, related_name='written_directions')
    direction_text = models.TextField()
    signed_on = models.DateField()
    document = models.FileField(upload_to='trust/directions/')
    linked_transaction = models.ForeignKey(TrustTransaction, on_delete=models.PROTECT, null=True, blank=True, related_name='written_directions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Written Direction'
        verbose_name_plural = 'Written Directions'

    def __str__(self):
        return f"Direction \u2013 {self.client} on {self.signed_on}"


class TransitMoneyEntry(models.Model):
    received_on = models.DateField()
    payor = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    to_be_paid_to = models.CharField(max_length=255)
    paid_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Transit Money Entry'
        verbose_name_plural = 'Transit Money Entries'

    def __str__(self):
        return f"Transit ${self.amount} from {self.payor} to {self.to_be_paid_to}"


class PowerMoneyEntry(models.Model):
    power_instrument = models.FileField(upload_to='trust/power/')
    donor = models.CharField(max_length=255)
    donee = models.CharField(max_length=255)
    amount_held = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Power Money Entry'
        verbose_name_plural = 'Power Money Entries'

    def __str__(self):
        return f"Power Money ${self.amount_held} \u2013 {self.donor} \u2192 {self.donee}"


class MonthlyReconciliation(models.Model):
    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='reconciliations')
    period_end = models.DateField()
    cash_book_balance = models.DecimalField(max_digits=12, decimal_places=2)
    ledger_total_balance = models.DecimalField(max_digits=12, decimal_places=2)
    bank_statement_balance = models.DecimalField(max_digits=12, decimal_places=2)
    unpresented_cheques_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    outstanding_deposits_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    reconciled_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_reconciled = models.BooleanField(default=False)
    signed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='reconciliations_signed')
    signed_on = models.DateTimeField(null=True, blank=True)
    bank_statement_pdf = models.FileField(upload_to='trust/recons/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('trust_account', 'period_end')]
        verbose_name = 'Monthly Reconciliation'
        verbose_name_plural = 'Monthly Reconciliations'

    def __str__(self):
        return f"Reconciliation {self.period_end} \u2013 {self.trust_account}"

    def save(self, *args, **kwargs):
        self.reconciled_balance = (
            self.bank_statement_balance
            - self.unpresented_cheques_total
            + self.outstanding_deposits_total
        )
        self.is_reconciled = (
            self.cash_book_balance == self.ledger_total_balance == self.reconciled_balance
        )
        super().save(*args, **kwargs)
        if not self.is_reconciled:
            discrepancy = self.cash_book_balance - self.reconciled_balance
            Irregularity.objects.get_or_create(
                trust_account=self.trust_account,
                discovered_on=self.period_end,
                defaults={
                    'description': (
                        f'Monthly reconciliation for period ending {self.period_end} failed. '
                        f'Cash book balance {self.cash_book_balance} does not match '
                        f'reconciled balance {self.reconciled_balance}.'
                    ),
                    'amount': abs(discrepancy),
                }
            )


class Irregularity(models.Model):
    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='irregularities')
    discovered_on = models.DateField(default=datetime.date.today)
    description = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reported_to_law_society_on = models.DateField(null=True, blank=True)
    report_document = models.FileField(upload_to='trust/irregularities/', null=True, blank=True)
    resolution = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Irregularity'
        verbose_name_plural = 'Irregularities'

    def __str__(self):
        return f"Irregularity ${self.amount} on {self.discovered_on}"
