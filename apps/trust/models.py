import datetime
import calendar
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from .compliance_dates import add_nsw_working_days, nsw_working_days_after


def _month_end_for(date_value):
    return datetime.date(
        date_value.year,
        date_value.month,
        calendar.monthrange(date_value.year, date_value.month)[1]
)


def _is_month_end(date_value):
    return date_value == _month_end_for(date_value)


class TrustAccount(models.Model):
    firm = models.ForeignKey('firms.Firm', on_delete=models.PROTECT, related_name='trust_accounts')
    name = models.CharField(max_length=255)
    bank = models.CharField(max_length=255)
    bsb = models.CharField(max_length=7, validators=[RegexValidator(r'^\d{3}-\d{3}$', 'BSB must be in format 000-000')])
    account_number = models.CharField(max_length=20)
    is_general = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    # Section 6A / Rule 35 and Rule 50 basic platform records
    opened_on = models.DateField(default=timezone.localdate)
    closed_on = models.DateField(null=True, blank=True)
    law_society_opening_notice_sent_on = models.DateField(
        null=True,
        blank=True,
        help_text='Optional admin record: Rule 50(1) notice sent within 14 days of opening.'
)
    law_society_closure_notice_sent_on = models.DateField(
        null=True,
        blank=True,
        help_text='Optional admin record: Rule 50(3) notice sent within 14 days of closure.'
)

    next_receipt_number = models.PositiveIntegerField(default=1)
    next_payment_number = models.PositiveIntegerField(default=1)
    next_controlled_money_receipt_number = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = 'Trust Account'
        verbose_name_plural = 'Trust Accounts'

    @property
    def opening_notice_due_on(self):
        if not self.opened_on:
            return None
        return self.opened_on + datetime.timedelta(days=14)

    @property
    def closure_notice_due_on(self):
        if not self.closed_on:
            return None
        return self.closed_on + datetime.timedelta(days=14)

    @property
    def section_6a_warnings(self):
        warnings = []
        if self.is_general:
            name_lower = (self.name or '').lower()
            firm_name = (self.firm.name if self.firm_id else '').lower()

            if firm_name and firm_name not in name_lower:
                warnings.append('Confirm the account name includes the law practice/business name.')

            if 'trust account' not in name_lower and 'trust a/c' not in name_lower:
                warnings.append('Confirm the account name includes “Trust Account” or “Trust A/c”.')

            if not self.opened_on:
                warnings.append('Opening date has not been recorded.')

            if self.closed_on and not self.law_society_closure_notice_sent_on:
                warnings.append('Closure notice date has not been recorded.')

        return warnings

    def clean(self):
        errors = {}
        if self.closed_on and self.opened_on and self.closed_on < self.opened_on:
            errors['closed_on'] = 'Closure date cannot be before opening date.'
        if not self.is_active and not self.closed_on:
            errors['closed_on'] = 'Closed trust accounts should record a closure date.'
        if self.closed_on and self.closed_on > timezone.localdate():
            errors['closed_on'] = 'Closure date cannot be future-dated.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.name} ({self.bsb} {self.account_number})"


class ControlledMoneyAccount(models.Model):
    firm = models.ForeignKey('firms.Firm', on_delete=models.PROTECT, related_name='controlled_money_accounts')
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='controlled_money_accounts')
    matter = models.ForeignKey('matters.Matter', on_delete=models.PROTECT, null=True, blank=True, related_name='controlled_money_accounts')
    account_name = models.CharField(max_length=255, blank=True, default='')
    bank = models.CharField(max_length=255)
    bsb = models.CharField(max_length=7, validators=[RegexValidator(r'^\d{3}-\d{3}$', 'BSB must be in format 000-000')])
    account_number = models.CharField(max_length=20)
    client_instruction_document = models.FileField(upload_to='controlled_money/instructions/', null=True, blank=True)
    interest_disposition = models.TextField(blank=True, default='')
    purpose = models.TextField(blank=True, default='')
    person_on_behalf = models.CharField(max_length=255, blank=True, default='')
    person_address = models.TextField(blank=True, default='')
    matter_reference = models.CharField(max_length=100, blank=True, default='')
    matter_description = models.CharField(max_length=500, blank=True, default='')
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)
    opened_on = models.DateField(default=datetime.date.today)
    closed_on = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = 'Controlled Money Account'
        verbose_name_plural = 'Controlled Money Accounts'

    def __str__(self):
        display_name = self.account_name or "Controlled Money Account"
        account_bits = " ".join(part for part in [self.bsb, self.account_number] if part)
        if account_bits:
            return f"{display_name} ({account_bits})"
        return display_name

    def clean(self):
        errors = {}
        name = (self.account_name or '').lower()
        firm_name = (self.firm.name if self.firm_id else '').lower()
        if firm_name and firm_name not in name:
            errors['account_name'] = 'Controlled money account name must include the law practice/firm name.'
        if not any(term in name for term in ['controlled money account', 'cma', 'cma/c']):
            errors['account_name'] = 'Controlled money account name must include "controlled money account", "CMA", or "CMA/c".'
        if len((self.purpose or '').strip()) < 5 and len((self.matter_description or '').strip()) < 5:
            errors['purpose'] = 'Account name/purpose details must distinguish this CMA from other controlled money accounts.'
        if self.current_balance is not None and self.current_balance < 0:
            errors['current_balance'] = 'Controlled money account balance cannot be negative.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.person_on_behalf and self.client_id:
            self.person_on_behalf = self.client.name
        if not self.person_address and self.client_id:
            self.person_address = self.client.address
        if self.matter_id:
            self.matter_reference = self.matter_reference or self.matter.file_number
            self.matter_description = self.matter_description or self.matter.description
        self.full_clean()
        super().save(*args, **kwargs)


class ControlledMoneyReceipt(models.Model):
    PAYMENT_METHOD_CHOICES = [('cash', 'Cash'), ('cheque', 'Cheque'), ('eft', 'EFT'), ('direct_deposit', 'Direct Deposit')]
    firm = models.ForeignKey('firms.Firm', on_delete=models.PROTECT, related_name='controlled_money_receipts')
    controlled_money_account = models.ForeignKey(ControlledMoneyAccount, on_delete=models.PROTECT, null=True, blank=True, related_name='receipts')
    receipt_number = models.PositiveIntegerField()
    date_made_out = models.DateField(default=timezone.localdate)
    date_money_received = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    person_from_whom_received = models.CharField(max_length=255)
    person_on_behalf = models.CharField(max_length=255)
    matter_description = models.CharField(max_length=500)
    matter_reference = models.CharField(max_length=100, blank=True)
    reason = models.CharField(max_length=500)
    made_out_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='controlled_money_receipts_made')
    is_cancelled = models.BooleanField(default=False)
    not_delivered = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['receipt_number']
        constraints = [models.UniqueConstraint(fields=['firm', 'receipt_number'], name='unique_cma_receipt_number_per_firm')]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('Controlled money receipts are immutable; preserve cancelled/not delivered receipts.')
        if not self.receipt_number:
            from django.db import transaction
            with transaction.atomic():
                account = TrustAccount.objects.select_for_update().filter(firm=self.firm).order_by('pk').first()
                if account:
                    self.receipt_number = account.next_controlled_money_receipt_number
                    account.next_controlled_money_receipt_number += 1
                    account.save(update_fields=['next_controlled_money_receipt_number'])
        self.full_clean()
        super().save(*args, **kwargs)
        if self.controlled_money_account_id and not self.is_cancelled:
            ControlledMoneyAccount.objects.filter(pk=self.controlled_money_account_id).update(current_balance=models.F('current_balance') + self.amount)

    def delete(self, *args, **kwargs):
        raise PermissionError('Controlled money receipts cannot be deleted once issued.')


class ControlledMoneyWithdrawal(models.Model):
    METHOD_CHOICES = [('cheque', 'Cheque'), ('eft', 'EFT')]
    controlled_money_account = models.ForeignKey(ControlledMoneyAccount, on_delete=models.PROTECT, related_name='withdrawals')
    date = models.DateField()
    transaction_number = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    withdrawal_method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    payee = models.CharField(max_length=255, blank=True)
    destination_account_name = models.CharField(max_length=255, blank=True)
    destination_account_number = models.CharField(max_length=20, blank=True)
    destination_bsb = models.CharField(max_length=7, blank=True)
    person_receiving_benefit = models.CharField(max_length=255, blank=True)
    person_on_behalf = models.CharField(max_length=255)
    matter_reference = models.CharField(max_length=100, blank=True)
    reason = models.CharField(max_length=500)
    authorised_by = models.CharField(max_length=500)
    supporting_authority = models.FileField(upload_to='controlled_money/authorities/', null=True, blank=True)
    included_in_monthly_statement = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['controlled_money_account', 'transaction_number'],
                name='unique_cma_withdrawal_transaction_number_per_account'
)
        ]

    def clean(self):
        errors = {}
        if self.withdrawal_method not in {'cheque', 'eft'}:
            errors['withdrawal_method'] = 'Withdrawal method must be cheque or EFT.'
        if self.withdrawal_method == 'cheque' and not (self.payee or (self.destination_bsb and self.person_receiving_benefit)):
            errors['payee'] = 'Cheque withdrawals require a payee or ADI/BSB and person receiving benefit.'
        if self.withdrawal_method == 'eft' and not (self.destination_account_name and self.destination_account_number and self.destination_bsb):
            errors['destination_account_name'] = 'EFT withdrawals require destination account name, number and BSB.'
        if self.controlled_money_account_id and self.amount and self.amount > self.controlled_money_account.current_balance:
            errors['amount'] = 'Withdrawal cannot overdraw the controlled money account.'
        if self.controlled_money_account_id and self.transaction_number:
            duplicate_qs = type(self).objects.filter(
                controlled_money_account_id=self.controlled_money_account_id,
                transaction_number=self.transaction_number
)
            if self.pk:
                duplicate_qs = duplicate_qs.exclude(pk=self.pk)
            if duplicate_qs.exists():
                errors['transaction_number'] = 'This controlled money withdrawal transaction number has already been used for this account.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = type(self).objects.get(pk=self.pk)
            if old.included_in_monthly_statement:
                raise PermissionError('Controlled money withdrawals included in monthly statements cannot be changed.')
        self.full_clean()
        super().save(*args, **kwargs)
        ControlledMoneyAccount.objects.filter(pk=self.controlled_money_account_id).update(current_balance=models.F('current_balance') - self.amount)


class ControlledMoneySupportingDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [('adi_statement', 'ADI statement'), ('interest_notification', 'Interest notification'), ('authority', 'Authority/direction'), ('other', 'Other')]
    controlled_money_account = models.ForeignKey(ControlledMoneyAccount, on_delete=models.PROTECT, related_name='supporting_documents')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    document = models.FileField(upload_to='controlled_money/supporting/')
    description = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class ControlledMoneyMonthlyStatement(models.Model):
    firm = models.ForeignKey('firms.Firm', on_delete=models.PROTECT, related_name='controlled_money_monthly_statements')
    period_end = models.DateField()
    prepared_on = models.DateField(default=timezone.localdate)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='controlled_money_statements_reviewed')
    reviewed_on = models.DateField(null=True, blank=True)
    reviewer_role_confirmation = models.CharField(max_length=255, blank=True)
    review_note = models.TextField(blank=True)
    pdf = models.FileField(upload_to='controlled_money/monthly-statements/', null=True, blank=True)
    sha256_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['firm', 'period_end'], name='unique_cma_monthly_statement_per_firm')]

    @property
    def due_date(self):
        return add_nsw_working_days(self.period_end, 15)


class AnnualTrustComplianceRecord(models.Model):
    STATUS_NOT_STARTED = 'not_started'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_REQUIRES_ACTION = 'requires_action'

    STATUS_CHOICES = [
        (STATUS_NOT_STARTED, 'Not started'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_REQUIRES_ACTION, 'Requires action'),
    ]

    firm = models.ForeignKey(
        'firms.Firm',
        on_delete=models.PROTECT,
        related_name='annual_trust_compliance_records'
)

    trust_year_start = models.DateField()
    trust_year_end = models.DateField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)

    part_a_completed_on = models.DateField(null=True, blank=True)
    part_b_required = models.BooleanField(default=False)
    part_b_completed_on = models.DateField(null=True, blank=True)

    external_examiner_required = models.BooleanField(default=False)
    external_examiner_name = models.CharField(max_length=255, blank=True, default='')
    external_examiner_report_lodged_on = models.DateField(null=True, blank=True)

    bank_reconciliation_31_march = models.FileField(upload_to='annual_trust_compliance/', null=True, blank=True)
    trial_balance_31_march = models.FileField(upload_to='annual_trust_compliance/', null=True, blank=True)
    bank_statement_31_march = models.FileField(upload_to='annual_trust_compliance/', null=True, blank=True)

    overdrawn_ledgers_reviewed = models.BooleanField(default=False)
    controlled_money_listing_reviewed = models.BooleanField(default=False)
    investment_money_listing_reviewed = models.BooleanField(default=False)

    notes = models.TextField(blank=True, default='')

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='annual_trust_compliance_reviews_completed'
)
    reviewed_on = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Annual Trust Compliance Record'
        verbose_name_plural = 'Annual Trust Compliance Records'
        ordering = ['-trust_year_end', '-created_at']
        indexes = [
            models.Index(fields=['firm', 'trust_year_end']),
            models.Index(fields=['firm', 'status']),
        ]

    def __str__(self):
        return f"Annual trust compliance {self.trust_year_start} to {self.trust_year_end}"


class Section19ComplianceReview(models.Model):
    STATUS_NOT_STARTED = 'not_started'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_REQUIRES_ACTION = 'requires_action'

    STATUS_CHOICES = [
        (STATUS_NOT_STARTED, 'Not started'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_REQUIRES_ACTION, 'Requires action'),
    ]

    firm = models.ForeignKey(
        'firms.Firm',
        on_delete=models.PROTECT,
        related_name='section19_reviews'
)

    review_period_start = models.DateField()
    review_period_end = models.DateField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)

    debit_balances_reviewed = models.BooleanField(default=False)
    debit_balances_notes = models.TextField(blank=True, default='')

    old_balances_reviewed = models.BooleanField(default=False)
    old_balances_notes = models.TextField(blank=True, default='')

    reconciliations_reviewed = models.BooleanField(default=False)
    reconciliations_notes = models.TextField(blank=True, default='')

    unidentified_money_reviewed = models.BooleanField(default=False)
    unidentified_money_notes = models.TextField(blank=True, default='')

    controlled_money_reviewed = models.BooleanField(default=False)
    controlled_money_notes = models.TextField(blank=True, default='')

    written_directions_reviewed = models.BooleanField(default=False)
    written_directions_notes = models.TextField(blank=True, default='')

    trust_investments_reviewed = models.BooleanField(default=False)
    trust_investments_notes = models.TextField(blank=True, default='')

    statutory_deposits_reviewed = models.BooleanField(default=False)
    statutory_deposits_notes = models.TextField(blank=True, default='')

    source_documents_reviewed = models.BooleanField(default=False)
    source_documents_notes = models.TextField(blank=True, default='')

    corrective_action_summary = models.TextField(blank=True, default='')

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='section19_reviews_completed'
)
    reviewed_on = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Periodic Trust Compliance Review'
        verbose_name_plural = 'Periodic Trust Compliance Reviews'
        ordering = ['-review_period_end', '-created_at']
        indexes = [
            models.Index(fields=['firm', 'status']),
            models.Index(fields=['firm', 'review_period_end']),
        ]

    def __str__(self):
        return f"Periodic trust compliance review {self.review_period_start} to {self.review_period_end}"


class ComplianceReviewLog(models.Model):
    STATUS_OPEN = 'open'
    STATUS_REVIEWED = 'reviewed'
    STATUS_RESOLVED = 'resolved'
    STATUS_NOT_APPLICABLE = 'not_applicable'
    STATUS_FOLLOW_UP = 'follow_up_required'

    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_REVIEWED, 'Reviewed'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_NOT_APPLICABLE, 'Not applicable'),
        (STATUS_FOLLOW_UP, 'Follow-up required'),
    ]

    SEVERITY_ACTION = 'Action Required'
    SEVERITY_REVIEW = 'Review Required'
    SEVERITY_REMINDER = 'Reminder'
    SEVERITY_INFORMATION = 'Information'

    SEVERITY_CHOICES = [
        (SEVERITY_ACTION, 'Action Required'),
        (SEVERITY_REVIEW, 'Review Required'),
        (SEVERITY_REMINDER, 'Reminder'),
        (SEVERITY_INFORMATION, 'Information'),
    ]

    firm = models.ForeignKey(
        'firms.Firm',
        on_delete=models.PROTECT,
        related_name='compliance_review_logs'
)
    matter = models.ForeignKey(
        'matters.Matter',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='compliance_review_logs'
)

    alert_key = models.CharField(max_length=255, blank=True, default='')
    severity = models.CharField(max_length=30, choices=SEVERITY_CHOICES, default=SEVERITY_REVIEW)
    category = models.CharField(max_length=120)
    title = models.CharField(max_length=255)
    source_url = models.CharField(max_length=500, blank=True, default='')

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_REVIEWED)
    review_note = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='compliance_reviews_completed'
)
    reviewed_on = models.DateTimeField(null=True, blank=True)
    next_review_on = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Compliance Review Log'
        verbose_name_plural = 'Compliance Review Logs'
        ordering = ['-reviewed_on', '-created_at']
        indexes = [
            models.Index(fields=['firm', 'status']),
            models.Index(fields=['firm', 'category']),
            models.Index(fields=['firm', 'next_review_on']),
            models.Index(fields=['alert_key']),
        ]

    def __str__(self):
        return f"{self.category} - {self.title} ({self.get_status_display()})"


class AuthorisedSignatory(models.Model):
    ROLE_PRINCIPAL = 'principal'
    ROLE_SOLICITOR = 'solicitor'
    ROLE_EMPLOYEE = 'employee'
    ROLE_CONSULTANT = 'consultant'
    ROLE_OTHER = 'other'

    ROLE_CHOICES = [
        (ROLE_PRINCIPAL, 'Principal'),
        (ROLE_SOLICITOR, 'Solicitor / legal practitioner associate'),
        (ROLE_EMPLOYEE, 'Employee / associate'),
        (ROLE_CONSULTANT, 'Consultant'),
        (ROLE_OTHER, 'Other authorised associate'),
    ]

    trust_account = models.ForeignKey(
        TrustAccount,
        on_delete=models.CASCADE,
        related_name='authorised_signatories'
)
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True, default='')
    email = models.EmailField(blank=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    practising_certificate_number = models.CharField(max_length=80, blank=True)

    authorised_trust_cheques = models.BooleanField(default=False)
    authorised_trust_efts = models.BooleanField(default=False)
    authorised_controlled_money = models.BooleanField(default=False)

    authorised_from = models.DateField()
    authorised_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    notes = models.TextField(blank=True, default='')

    last_reviewed_on = models.DateField(null=True, blank=True)
    next_review_due_on = models.DateField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='authorised_signatory_reviews')
    reviewed_on = models.DateField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)


    class Meta:
        verbose_name = 'Authorised Signatory'
        verbose_name_plural = 'Authorised Signatories'
        ordering = ['name']
        indexes = [
            models.Index(fields=['trust_account', 'is_active']),
            models.Index(fields=['authorised_from']),
        ]

    def __str__(self):
        return f"{self.name} - {self.trust_account}"

    @property
    def review_status(self):
        from django.utils import timezone
        from datetime import timedelta

        if not self.next_review_due_on:
            return 'Not set'
        today = timezone.localdate()
        if self.next_review_due_on < today:
            return 'Overdue'
        if self.next_review_due_on <= today + timedelta(days=30):
            return 'Due soon'
        return 'Current'

    def clean(self):
        errors = {}
        if self.authorised_to and self.authorised_from and self.authorised_to < self.authorised_from:
            errors['authorised_to'] = 'Authorised to date cannot be before authorised from date.'
        if not any([
            self.authorised_trust_cheques,
            self.authorised_trust_efts,
            self.authorised_controlled_money,
        ]):
            errors['authorised_trust_cheques'] = 'Select at least one authorisation type.'
        if errors:
            raise ValidationError(errors)


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
    created_at = models.DateTimeField(default=timezone.now)
    is_reversed = models.BooleanField(default=False)
    reverses = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='reversed_by')

    class Meta:
        verbose_name = 'Trust Transaction'
        verbose_name_plural = 'Trust Transactions'

    def __str__(self):
        return f"{self.get_transaction_type_display()} ${self.amount} on {self.date_received_or_paid}"

    def clean(self):
        super().clean()
        if (
            self.transaction_type in {'receipt', 'payment', 'transfer_to_office'}
            and self.date_received_or_paid
            and self.date_received_or_paid > timezone.localdate()
        ):
            raise ValidationError({'date_received_or_paid': 'Trust receipts and payments cannot be future-dated.'})
        if (
            self.transaction_type == 'receipt'
            and self.date_banked
            and self.date_banked > timezone.localdate()
        ):
            raise ValidationError({'date_banked': 'Trust receipt deposit date cannot be future-dated.'})

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("TrustTransaction is append-only; create a reversal instead.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("TrustTransaction records cannot be deleted.")


class TrustAccountingPeriod(models.Model):
    STATUS_OPEN = 'open'
    STATUS_LOCKED = 'locked'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_LOCKED, 'Locked'),
    ]

    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='accounting_periods')
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='trust_periods_locked')
    locked_on = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Trust Accounting Period'
        verbose_name_plural = 'Trust Accounting Periods'
        ordering = ['-period_end']
        constraints = [
            models.UniqueConstraint(fields=['trust_account', 'period_start', 'period_end'], name='unique_trust_accounting_period'),
            models.CheckConstraint(check=models.Q(period_start__lte=models.F('period_end')), name='trust_period_start_lte_end'),
        ]
        indexes = [
            models.Index(fields=['trust_account', 'period_start', 'period_end']),
            models.Index(fields=['trust_account', 'status']),
        ]

    def __str__(self):
        return f"{self.trust_account} - {self.period_start} to {self.period_end} ({self.get_status_display()})"

    def clean(self):
        errors = {}
        if self.period_start:
            if self.period_start.day != 1:
                errors['period_start'] = 'Period start must be the first day of a month.'
        if self.period_start and self.period_end:
            expected_end = _month_end_for(self.period_start)
            if self.period_end != expected_end:
                errors['period_end'] = 'Period end must be the last day of the same month as the period start.'
        if self.status == self.STATUS_LOCKED:
            if not self.locked_by_id:
                errors['locked_by'] = 'Locked periods must record who locked them.'
            if not self.locked_on:
                errors['locked_on'] = 'Locked periods must record when they were locked.'
        elif self.status == self.STATUS_OPEN:
            if self.locked_by_id:
                errors['locked_by'] = 'Open periods cannot have locked-by metadata.'
            if self.locked_on:
                errors['locked_on'] = 'Open periods cannot have locked-on metadata.'
        if errors:
            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        if self.status == self.STATUS_LOCKED:
            raise PermissionError('Locked accounting periods cannot be deleted.')
        return super().delete(*args, **kwargs)


class Receipt(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('eft', 'EFT'),
        ('direct_deposit', 'Direct Deposit'),
        ('credit_card', 'Credit Card'),
    ]

    transaction = models.OneToOneField(TrustTransaction, on_delete=models.PROTECT, related_name='receipt')
    receipt_number = models.PositiveIntegerField()
    payor_name = models.CharField(max_length=255)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    cheque_number = models.CharField(max_length=50, blank=True)
    payment_reference_override = models.CharField(max_length=80, blank=True)
    purpose = models.CharField(max_length=500)
    late_banking = models.BooleanField(default=False)
    deposit_record = models.ForeignKey('DepositRecord', on_delete=models.PROTECT, null=True, blank=True, related_name='receipts')

    class Meta:
        verbose_name = 'Receipt'
        verbose_name_plural = 'Receipts'
        unique_together = [('receipt_number', 'transaction')]

    def __str__(self):
        return f"Receipt #{self.receipt_number} \u2013 {self.payor_name} ${self.transaction.amount}"

    @property
    def uses_separate_deposit_date(self):
        """Cash and cheque receipts have a separate physical banking date."""
        return self.payment_method in {'cash', 'cheque'}

    @property
    def date_made_out(self):
        """NSW receipt date made out, derived from the immutable creation timestamp."""
        if not self.transaction_id or not self.transaction.created_at:
            return None
        return timezone.localdate(self.transaction.created_at)

    def clean(self):
        # Deposit delay is calculated in the receipt service as a review indicator.
        # Do not treat any recording deadline as a banking grace period.
        return super().clean()


class DepositRecord(models.Model):
    DEPOSIT_TYPE_CASH = 'cash'
    DEPOSIT_TYPE_CHEQUE = 'cheque'
    DEPOSIT_TYPE_CHOICES = [
        (DEPOSIT_TYPE_CASH, 'Cash Deposit Record'),
        (DEPOSIT_TYPE_CHEQUE, 'Cheque Deposit Record'),
    ]

    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='deposit_records')
    deposit_number = models.PositiveIntegerField()
    deposit_type = models.CharField(max_length=10, choices=DEPOSIT_TYPE_CHOICES)
    deposit_date = models.DateField()
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='deposit_records_prepared')
    prepared_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Deposit Record'
        verbose_name_plural = 'Deposit Records'
        ordering = ['-deposit_date', '-deposit_number']
        unique_together = [('trust_account', 'deposit_number')]
        indexes = [
            models.Index(fields=['trust_account', 'deposit_type']),
            models.Index(fields=['deposit_date']),
        ]

    @property
    def total_amount(self):
        total = Decimal('0.00')
        for receipt in self.receipts.select_related('transaction').all():
            total += receipt.transaction.amount
        return total

    def clean(self):
        errors = {}
        if self.deposit_type not in {'cash', 'cheque'}:
            errors['deposit_type'] = 'Deposit records can only be created for cash or cheque receipts.'
        if self.deposit_date and self.deposit_date > timezone.localdate():
            errors['deposit_date'] = 'Deposit date cannot be future-dated.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.get_deposit_type_display()} #{self.deposit_number} - {self.deposit_date}"


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
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Written Direction'
        verbose_name_plural = 'Written Directions'

    def __str__(self):
        return f"Direction \u2013 {self.client} on {self.signed_on}"


class TransitMoneyEntry(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, null=True, blank=True, related_name='transit_money_entries')
    matter = models.ForeignKey('matters.Matter', on_delete=models.PROTECT, null=True, blank=True, related_name='transit_money_entries')
    received_on = models.DateField()
    payor = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    to_be_paid_to = models.CharField(max_length=255)
    paid_on = models.DateField(null=True, blank=True)
    purpose = models.TextField(blank=True, default='')
    instructions_document = models.FileField(upload_to='trust/transit-money/instructions/', null=True, blank=True)
    supporting_document = models.FileField(upload_to='trust/transit-money/supporting/', null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Transit Money Entry'
        verbose_name_plural = 'Transit Money Entries'
        ordering = ['-received_on']

    @property
    def status(self):
        return 'Completed' if self.paid_on else 'Pending'

    def __str__(self):
        return f"Transit ${self.amount} from {self.payor} to {self.to_be_paid_to}"


class StatutoryDepositRecord(models.Model):
    trust_account = models.ForeignKey('trust.TrustAccount', on_delete=models.PROTECT, related_name='statutory_deposit_records')
    applicable_period_end = models.DateField()
    statutory_deposit_adi = models.CharField(max_length=255, blank=True, default='')
    statutory_deposit_account_reference = models.CharField(max_length=255, blank=True, default='')
    calculated_on = models.DateField(null=True, blank=True)
    required_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_currently_held = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment_required = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment_due_date = models.DateField(null=True, blank=True)
    adjustment_made_on = models.DateField(null=True, blank=True)
    calculation_notes = models.TextField(blank=True, default='')
    supporting_document = models.FileField(upload_to='trust/statutory-deposits/supporting/', null=True, blank=True)
    law_society_determination_document = models.FileField(upload_to='trust/statutory-deposits/law-society/', null=True, blank=True)
    next_review_due_on = models.DateField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='statutory_deposit_record_reviews')
    reviewed_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Statutory Deposit Record'
        verbose_name_plural = 'Statutory Deposit Records'
        ordering = ['-applicable_period_end', 'trust_account']

    @property
    def status_label(self):
        if self.adjustment_required and self.adjustment_required != 0 and not self.adjustment_made_on:
            return 'Adjustment Required'
        if self.next_review_due_on and self.next_review_due_on < timezone.localdate():
            return 'Review Due'
        return 'Up to Date'

    def __str__(self):
        return f"Statutory deposit {self.trust_account} - {self.applicable_period_end}"


class TrustInvestment(models.Model):
    SOURCE_GENERAL_TRUST = 'general_trust'
    SOURCE_CONTROLLED_MONEY = 'controlled_money'
    SOURCE_TRANSIT_MONEY = 'transit_money'
    SOURCE_POWER_MONEY = 'power_money'
    SOURCE_OTHER = 'other'

    SOURCE_CHOICES = [
        (SOURCE_GENERAL_TRUST, 'General Trust Account'),
        (SOURCE_CONTROLLED_MONEY, 'Controlled Money Account'),
        (SOURCE_TRANSIT_MONEY, 'Transit Money'),
        (SOURCE_POWER_MONEY, 'Power Money'),
        (SOURCE_OTHER, 'Other'),
    ]

    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, null=True, blank=True, related_name='trust_investments')
    matter = models.ForeignKey('matters.Matter', on_delete=models.PROTECT, null=True, blank=True, related_name='trust_investments')
    person_on_behalf = models.CharField(max_length=255)
    person_address = models.TextField(blank=True, default='')
    investment_held_name = models.CharField(max_length=255, help_text='Name in which investment is held')
    institution = models.CharField(max_length=255, blank=True, default='')
    investment_type = models.CharField(max_length=255, blank=True, default='')
    investment_particulars = models.TextField(blank=True, default='')
    amount_invested = models.DecimalField(max_digits=12, decimal_places=2)
    date_invested = models.DateField()
    maturity_due_on = models.DateField(null=True, blank=True)
    source_of_investment = models.CharField(max_length=30, choices=SOURCE_CHOICES, default=SOURCE_GENERAL_TRUST)
    source_reference = models.CharField(max_length=255, blank=True, default='')
    trust_ledger_reference = models.CharField(max_length=255, blank=True, default='')
    written_direction_reference = models.CharField(max_length=255, blank=True, default='')
    written_direction_date = models.DateField(null=True, blank=True)
    cheque_or_eft_reference = models.CharField(max_length=255, blank=True, default='')
    investment_terms = models.TextField(blank=True, default='')
    document_identifier = models.CharField(max_length=255, blank=True, default='')
    evidence_document = models.FileField(upload_to='trust/investments/evidence/', null=True, blank=True)
    written_direction_document = models.FileField(upload_to='trust/investments/directions/', null=True, blank=True)
    interest_details = models.TextField(blank=True, default='')
    maturity_repayment_details = models.TextField(blank=True, default='')
    repaid_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Trust Investment'
        verbose_name_plural = 'Trust Investments'
        ordering = ['-date_invested', 'person_on_behalf']

    def __str__(self):
        return f"{self.person_on_behalf} - {self.investment_held_name} - ${self.amount_invested}"


class PowerMoneyEntry(models.Model):
    ENTRY_POWER = 'power'
    ENTRY_ESTATE = 'estate'
    ENTRY_GUARDIANSHIP = 'guardianship'
    ENTRY_PROBATE = 'probate'
    ENTRY_OTHER = 'other'

    ENTRY_TYPE_CHOICES = [
        (ENTRY_POWER, 'Power of attorney / authority'),
        (ENTRY_ESTATE, 'Estate'),
        (ENTRY_GUARDIANSHIP, 'Guardianship order'),
        (ENTRY_PROBATE, 'Probate / administration'),
        (ENTRY_OTHER, 'Other'),
    ]

    entry_type = models.CharField(max_length=30, choices=ENTRY_TYPE_CHOICES, default=ENTRY_POWER)
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, null=True, blank=True, related_name='power_money_entries')
    matter = models.ForeignKey('matters.Matter', on_delete=models.PROTECT, null=True, blank=True, related_name='power_money_entries')
    power_instrument = models.FileField(upload_to='trust/power/', null=True, blank=True)
    authority_document = models.FileField(upload_to='trust/power/authorities/', null=True, blank=True)
    donor = models.CharField(max_length=255, blank=True, default='')
    donor_address = models.TextField(blank=True, default='')
    donee = models.CharField(max_length=255, blank=True, default='')
    power_date = models.DateField(null=True, blank=True)
    deceased_name = models.CharField(max_length=255, blank=True, default='')
    date_of_death = models.DateField(null=True, blank=True)
    matter_reference = models.CharField(max_length=100, blank=True, default='')
    description = models.TextField(blank=True, default='')
    responsible_solicitor = models.CharField(max_length=255, blank=True, default='')
    amount_held = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Power / Estate Register Entry'
        verbose_name_plural = 'Powers & Estates Register'
        ordering = ['-power_date', 'donor', 'deceased_name']

    def __str__(self):
        subject = self.deceased_name or self.donor or self.client or 'Power/Estate'
        return f"{subject} - {self.get_entry_type_display()}"


class PowerMoneyDealing(models.Model):
    power_entry = models.ForeignKey(PowerMoneyEntry, on_delete=models.PROTECT, related_name='dealings')
    dealing_date = models.DateField()
    description = models.TextField()
    deposit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    withdrawal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payee_or_source = models.CharField(max_length=255, blank=True, default='')
    supporting_document = models.FileField(upload_to='trust/power/dealings/', null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Power / Estate Dealing'
        verbose_name_plural = 'Power / Estate Dealings'
        ordering = ['dealing_date', 'id']

    def __str__(self):
        return f"{self.power_entry} - {self.dealing_date}"


class UnclaimedMoneyRecord(models.Model):
    STATUS_UNDER_REVIEW = 'under_review'
    STATUS_CLIENT_CONTACTED = 'client_contacted'
    STATUS_RESOLVED = 'resolved'
    STATUS_PAID_OUT = 'paid_out'
    STATUS_TRANSFERRED = 'transferred'
    STATUS_CLOSED = 'closed'

    STATUS_CHOICES = [
        (STATUS_UNDER_REVIEW, 'Under review'),
        (STATUS_CLIENT_CONTACTED, 'Client contacted'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_PAID_OUT, 'Paid out'),
        (STATUS_TRANSFERRED, 'Transferred / dealt with under statutory process'),
        (STATUS_CLOSED, 'Closed'),
    ]

    firm = models.ForeignKey('firms.Firm', on_delete=models.PROTECT, related_name='unclaimed_money_records')
    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='unclaimed_money_records')
    matter_ledger = models.ForeignKey(MatterLedger, on_delete=models.PROTECT, related_name='unclaimed_money_records')

    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    date_identified = models.DateField(default=timezone.localdate)
    date_last_activity = models.DateField(null=True, blank=True)
    date_funds_became_potentially_unclaimed = models.DateField(null=True, blank=True)

    last_client_contact_date = models.DateField(null=True, blank=True)
    contact_attempts = models.TextField(blank=True)
    review_notes = models.TextField(blank=True)
    proposed_action = models.TextField(blank=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_UNDER_REVIEW)
    supporting_document = models.FileField(upload_to='trust/unclaimed-money/', null=True, blank=True)

    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='unclaimed_money_reviews')
    reviewed_on = models.DateField(null=True, blank=True)
    resolved_on = models.DateField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='unclaimed_money_created')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Unclaimed Money Record'
        verbose_name_plural = 'Unclaimed Money Records'
        ordering = ['-date_identified', '-created_at']
        indexes = [
            models.Index(fields=['firm', 'status']),
            models.Index(fields=['trust_account', 'status']),
            models.Index(fields=['matter_ledger', 'status']),
        ]

    def __str__(self):
        return f"Unclaimed money review - {self.matter_ledger} - ${self.amount}"

    def clean(self):
        errors = {}

        if self.matter_ledger_id and self.trust_account_id:
            if self.matter_ledger.trust_account_id != self.trust_account_id:
                errors['matter_ledger'] = 'Matter ledger must belong to the selected trust account.'

        if self.trust_account_id and self.firm_id:
            if self.trust_account.firm_id != self.firm_id:
                errors['trust_account'] = 'Trust account must belong to the selected firm.'

        if self.amount is not None and self.amount < 0:
            errors['amount'] = 'Amount cannot be negative.'

        if self.resolved_on and self.date_identified and self.resolved_on < self.date_identified:
            errors['resolved_on'] = 'Resolved date cannot be before the date identified.'

        if errors:
            raise ValidationError(errors)

class MonthlyReconciliation(models.Model):
    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='reconciliations')
    accounting_period = models.OneToOneField(TrustAccountingPeriod, on_delete=models.PROTECT, null=True, blank=True, related_name='reconciliation')
    period_end = models.DateField()
    cash_book_balance = models.DecimalField(max_digits=12, decimal_places=2)
    ledger_total_balance = models.DecimalField(max_digits=12, decimal_places=2)
    bank_statement_balance = models.DecimalField(max_digits=12, decimal_places=2)
    unpresented_cheques_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    outstanding_deposits_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    other_payments_not_in_adi_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    credits_not_in_cash_book_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    debits_not_in_cash_book_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    reconciled_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_reconciled = models.BooleanField(default=False)
    is_finalised = models.BooleanField(default=False)
    signed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='reconciliations_signed')
    signed_on = models.DateTimeField(null=True, blank=True)
    finalised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='trust_reconciliations_finalised')
    finalised_on = models.DateTimeField(null=True, blank=True)
    bank_statement_pdf = models.FileField(upload_to='trust/recons/', null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [('trust_account', 'period_end')]
        verbose_name = 'Monthly Reconciliation'
        verbose_name_plural = 'Monthly Reconciliations'

    def __str__(self):
        return f"Reconciliation {self.period_end} \u2013 {self.trust_account}"

    @property
    def reconciliation_due_date(self):
        return add_nsw_working_days(self.period_end, 15)

    @property
    def date_statement_prepared(self):
        if not self.finalised_on:
            return None
        return timezone.localdate(self.finalised_on)

    @property
    def prepared_within_required_period(self):
        prepared_date = self.date_statement_prepared
        if not prepared_date:
            return None
        return prepared_date <= self.reconciliation_due_date

    @property
    def working_days_late(self):
        prepared_date = self.date_statement_prepared
        if not prepared_date or prepared_date <= self.reconciliation_due_date:
            return 0
        return nsw_working_days_after(self.reconciliation_due_date, prepared_date)

    @property
    def preparation_status_label(self):
        if not self.finalised_on:
            return 'Not prepared'
        if self.prepared_within_required_period:
            return 'On time'
        return f'Late ({self.working_days_late} working days)'

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = type(self).objects.get(pk=self.pk)
            if old.is_finalised:
                raise PermissionError('Finalised reconciliations cannot be modified.')
        self.reconciled_balance = (
            self.bank_statement_balance
            - self.unpresented_cheques_total
            - self.other_payments_not_in_adi_total
            + self.outstanding_deposits_total
            - self.credits_not_in_cash_book_total
            + self.debits_not_in_cash_book_total
        )
        self.is_reconciled = (
            self.cash_book_balance == self.ledger_total_balance == self.reconciled_balance
        )
        self.full_clean()
        super().save(*args, **kwargs)
        # A reconciliation timing difference or adjustment is not, by itself,
        # a trust-account irregularity. Irregularities should be recorded
        # deliberately for true trust accounting issues such as deficiencies,
        # unauthorised withdrawals, incorrect disbursements, debit balances,
        # or other reportable receipt/recording/disbursement problems.

    def clean(self):
        errors = {}
        if self.period_end:
            if not _is_month_end(self.period_end):
                errors['period_end'] = 'Period end must be the last day of a month.'
            if self.pk is None and not self.period_end < timezone.localdate():
                errors['period_end'] = 'Reconciliation cannot be created until after the period end date.'
        if self.accounting_period_id:
            if self.accounting_period.trust_account_id != self.trust_account_id:
                errors['accounting_period'] = 'Accounting period must belong to the same trust account.'
            if self.accounting_period.period_end != self.period_end:
                errors['period_end'] = 'Period end must match the linked accounting period.'
        if self.is_finalised:
            if self.period_end and not self.period_end < timezone.localdate():
                errors['is_finalised'] = 'Reconciliation cannot be finalised until after the period end date.'
            if not self.is_reconciled:
                errors['is_finalised'] = 'Only balanced reconciliations can be finalised.'
            if not self.finalised_by_id:
                errors['finalised_by'] = 'Finalised reconciliations must record who finalised them.'
            if not self.finalised_on:
                errors['finalised_on'] = 'Finalised reconciliations must record when they were finalised.'
        if errors:
            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        if self.is_finalised:
            raise PermissionError('Finalised reconciliations cannot be deleted.')
        return super().delete(*args, **kwargs)


class ReconciliationBankLine(models.Model):
    LINE_TYPE_CREDIT = 'credit'
    LINE_TYPE_DEBIT = 'debit'
    LINE_TYPE_CHOICES = [
        (LINE_TYPE_CREDIT, 'Credit in authorised ADI statement'),
        (LINE_TYPE_DEBIT, 'Debit in authorised ADI statement'),
    ]

    ADJUSTMENT_CATEGORY_MATCHED = 'matched_to_cash_book'
    ADJUSTMENT_CATEGORY_RECEIPT_NEXT_MONTH = 'receipt_to_issue_next_month'
    ADJUSTMENT_CATEGORY_UNIDENTIFIED_DEPOSIT = 'unidentified_deposit'
    ADJUSTMENT_CATEGORY_ADI_ERROR = 'adi_error_bank_to_reverse'
    ADJUSTMENT_CATEGORY_INTEREST_ERROR = 'interest_credited_in_error'
    ADJUSTMENT_CATEGORY_BANK_CHARGE_ERROR = 'bank_charge_debited_in_error'
    ADJUSTMENT_CATEGORY_BANK_DEBIT_NOT_CASH_BOOK = 'bank_debit_not_in_cash_book'
    ADJUSTMENT_CATEGORY_UNPRESENTED_CHEQUE = 'unpresented_cheque'
    ADJUSTMENT_CATEGORY_OTHER_PAYMENT_NOT_ADI = 'other_payment_not_in_adi'
    ADJUSTMENT_CATEGORY_OTHER = 'other_adjustment'

    ADJUSTMENT_CATEGORY_CHOICES = [
        ('', 'Unclassified / requires review'),
        (ADJUSTMENT_CATEGORY_MATCHED, 'Matched to cash book'),
        (ADJUSTMENT_CATEGORY_RECEIPT_NEXT_MONTH, 'Direct deposit / receipt to be issued next month'),
        (ADJUSTMENT_CATEGORY_UNIDENTIFIED_DEPOSIT, 'Unidentified deposit'),
        (ADJUSTMENT_CATEGORY_ADI_ERROR, 'Authorised ADI error - bank to reverse'),
        (ADJUSTMENT_CATEGORY_INTEREST_ERROR, 'Interest credited in error - bank to reverse'),
        (ADJUSTMENT_CATEGORY_BANK_CHARGE_ERROR, 'Bank charge debited in error - bank to reverse'),
        (ADJUSTMENT_CATEGORY_BANK_DEBIT_NOT_CASH_BOOK, 'Bank debit not in cash book - investigate/correct'),
        (ADJUSTMENT_CATEGORY_UNPRESENTED_CHEQUE, 'Unpresented cheque'),
        (ADJUSTMENT_CATEGORY_OTHER_PAYMENT_NOT_ADI, 'Other payment in cash book not in authorised ADI statement'),
        (ADJUSTMENT_CATEGORY_OTHER, 'Other reconciliation adjustment'),
    ]

    reconciliation = models.ForeignKey(
        MonthlyReconciliation,
        on_delete=models.CASCADE,
        related_name='bank_lines'
)
    line_date = models.DateField()
    line_type = models.CharField(max_length=10, choices=LINE_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    description = models.CharField(max_length=500)
    reference = models.CharField(max_length=100, blank=True)
    adjustment_category = models.CharField(
        max_length=60,
        choices=ADJUSTMENT_CATEGORY_CHOICES,
        blank=True,
        default=''
)
    carry_forward_until_cleared = models.BooleanField(default=False)
    cleared_by_transaction = models.ForeignKey(
        TrustTransaction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='clears_reconciliation_adjustments'
)
    cleared_in_reconciliation = models.ForeignKey(
        MonthlyReconciliation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='cleared_bank_line_adjustments'
)
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='reconciliation_bank_lines_cleared'
)
    cleared_at = models.DateTimeField(null=True, blank=True)
    cleared_notes = models.TextField(blank=True, default='')
    matched_transaction = models.ForeignKey(
        TrustTransaction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='authorised_adi_matches'
)
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='reconciliation_bank_lines_created')
    matched_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='reconciliation_bank_lines_matched')
    matched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Authorised ADI Statement Line'
        verbose_name_plural = 'Authorised ADI Statement Lines'
        ordering = ['line_date', 'id']
        indexes = [
            models.Index(fields=['reconciliation', 'line_type']),
            models.Index(fields=['reconciliation', 'matched_transaction']),
            models.Index(fields=['line_date']),
        ]

    @property
    def is_matched(self):
        return bool(self.matched_transaction_id)

    def clean(self):
        errors = {}
        if self.reconciliation_id and self.line_date and self.line_date > self.reconciliation.period_end:
            errors['line_date'] = 'Bank statement line date cannot be after the reconciliation period end.'
        if self.reconciliation_id and self.matched_transaction_id:
            if self.matched_transaction.matter_ledger.trust_account_id != self.reconciliation.trust_account_id:
                errors['matched_transaction'] = 'Matched transaction must belong to the same trust account.'
        if self.reconciliation_id and self.cleared_by_transaction_id:
            if self.cleared_by_transaction.matter_ledger.trust_account_id != self.reconciliation.trust_account_id:
                errors['cleared_by_transaction'] = 'Clearing transaction must belong to the same trust account.'
            if self.cleared_by_transaction.date_received_or_paid <= self.reconciliation.period_end:
                errors['cleared_by_transaction'] = 'A carried-forward adjustment should be cleared by a later-period transaction.'
        if self.matched_transaction_id and self.carry_forward_until_cleared:
            errors['carry_forward_until_cleared'] = 'Matched bank lines should not be carried forward.'
        if self.cleared_by_transaction_id and not self.carry_forward_until_cleared:
            errors['carry_forward_until_cleared'] = 'Only carried-forward adjustments can be cleared by a later transaction.'
        if self.reconciliation_id and self.reconciliation.is_finalised:
            errors['reconciliation'] = 'Finalised reconciliations cannot be changed.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_line_type_display()} ${self.amount} on {self.line_date}"


class TrustMonthlyRecord(models.Model):
    RECORD_RECEIPTS_CASH_BOOK = 'receipts_cash_book'
    RECORD_PAYMENTS_CASH_BOOK = 'payments_cash_book'
    RECORD_TRUST_TRANSFER_JOURNAL = 'trust_transfer_journal'
    RECORD_TRIAL_BALANCE = 'trial_balance'
    RECORD_RECONCILIATION_STATEMENT = 'reconciliation_statement'

    RECORD_TYPE_CHOICES = [
        (RECORD_RECEIPTS_CASH_BOOK, 'Receipts Cash Book'),
        (RECORD_PAYMENTS_CASH_BOOK, 'Payments Cash Book'),
        (RECORD_TRUST_TRANSFER_JOURNAL, 'Trust Transfer Journal'),
        (RECORD_TRIAL_BALANCE, 'Ledger Reconciliation / Trial Balance'),
        (RECORD_RECONCILIATION_STATEMENT, 'Reconciliation Statement'),
    ]

    accounting_period = models.ForeignKey(TrustAccountingPeriod, on_delete=models.PROTECT, related_name='monthly_records')
    reconciliation = models.ForeignKey(MonthlyReconciliation, on_delete=models.PROTECT, related_name='monthly_records')
    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='monthly_records')
    record_type = models.CharField(max_length=40, choices=RECORD_TYPE_CHOICES)
    pdf = models.FileField(upload_to='trust/monthly-records/')
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='trust_monthly_records_generated')
    generated_at = models.DateTimeField(auto_now_add=True)
    sha256_hash = models.CharField(max_length=64)

    class Meta:
        verbose_name = 'Trust Monthly Record'
        verbose_name_plural = 'Trust Monthly Records'
        ordering = ['-generated_at']
        constraints = [
            models.UniqueConstraint(fields=['accounting_period', 'record_type'], name='unique_monthly_record_type_per_period'),
        ]
        indexes = [
            models.Index(fields=['trust_account', 'record_type']),
            models.Index(fields=['trust_account', 'generated_at']),
        ]

    def __str__(self):
        return f"{self.get_record_type_display()} - {self.accounting_period.period_end}"

    def clean(self):
        errors = {}
        if self.sha256_hash and len(self.sha256_hash) != 64:
            errors['sha256_hash'] = 'SHA256 hash must be 64 characters.'
        if self.accounting_period_id and self.trust_account_id and self.accounting_period.trust_account_id != self.trust_account_id:
            errors['trust_account'] = 'Monthly record trust account must match the accounting period.'
        if self.reconciliation_id and self.trust_account_id and self.reconciliation.trust_account_id != self.trust_account_id:
            errors['reconciliation'] = 'Monthly record trust account must match the reconciliation.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('Trust monthly records are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Trust monthly records cannot be deleted.')


class Irregularity(models.Model):
    trust_account = models.ForeignKey(TrustAccount, on_delete=models.PROTECT, related_name='irregularities')
    discovered_on = models.DateField(default=datetime.date.today)
    description = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reported_to_law_society_on = models.DateField(null=True, blank=True)
    report_document = models.FileField(upload_to='trust/irregularities/', null=True, blank=True)
    resolution = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Irregularity'
        verbose_name_plural = 'Irregularities'

    def __str__(self):
        return f"Irregularity ${self.amount} on {self.discovered_on}"
