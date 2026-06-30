from decimal import Decimal
from django import forms
from .models import UnclaimedMoneyRecord, AnnualTrustComplianceRecord
from .models import ComplianceReviewLog, Section19ComplianceReview
from django.utils import timezone
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from apps.clients.models import Client
from apps.matters.models import Matter
from .models import MatterLedger, MonthlyReconciliation, DepositRecord, Receipt, Irregularity, Payment, TrustAccount, TrustAccountingPeriod, ControlledMoneyAccount, ControlledMoneyReceipt, ControlledMoneyWithdrawal, ControlledMoneyMonthlyStatement, ControlledMoneySupportingDocument, ReconciliationBankLine, AuthorisedSignatory, WrittenDirection, TransitMoneyEntry, PowerMoneyEntry, PowerMoneyDealing, TrustInvestment, StatutoryDepositRecord


class TrustAccountUpdateForm(forms.ModelForm):
    class Meta:
        model = TrustAccount
        fields = [
            'name', 'bank', 'bsb', 'account_number',
            'opened_on', 'law_society_opening_notice_sent_on',
            'closed_on', 'law_society_closure_notice_sent_on', 'is_active',
        ]
        widgets = {
            'opened_on': forms.DateInput(attrs={'type': 'date'}),
            'law_society_opening_notice_sent_on': forms.DateInput(attrs={'type': 'date'}),
            'closed_on': forms.DateInput(attrs={'type': 'date'}),
            'law_society_closure_notice_sent_on': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'law_society_opening_notice_sent_on': 'Law Society opening notice sent on',
            'law_society_closure_notice_sent_on': 'Law Society closure notice sent on',
        }

        labels = {
            'client_instruction_document': 'Client instruction / authority document',
            'interest_disposition': 'Interest disposition / entitlement notes',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Save Trust Account Details'))


class ReceiptForm(forms.Form):
    amount = forms.DecimalField(label='Amount received', max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    date_received = forms.DateField(
        label='Date received / confirmed in trust account',
        help_text=(
            'For EFT/direct deposit, use the date the solicitor received or accessed confirmation '
            'that funds were in the trust account.'
        ),
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=timezone.localdate
)
    date_banked = forms.DateField(
        label='Date deposited to trust account',
        help_text='Required for cash or cheque when the separate banking/deposit step occurs.',
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False
)
    payor_name = forms.CharField(label='Received from', max_length=255)
    payment_method = forms.ChoiceField(
        label='Form in which money was received',
        help_text='For credit card trust receipts, receipt the full amount credited to trust. Merchant/card fees must not be deducted from trust money.',
        choices=[
            ('cash', 'Cash'),
            ('cheque', 'Cheque'),
            ('eft', 'EFT'),
            ('direct_deposit', 'Direct Deposit'),
            ('credit_card', 'Credit Card'),
        ]
)
    cheque_number = forms.CharField(label='Cheque number, if applicable', max_length=50, required=False)
    purpose = forms.CharField(label='Reason / purpose for which money was received', max_length=500)

    def clean_date_received(self):
        date_received = self.cleaned_data['date_received']
        if date_received > timezone.localdate():
            raise forms.ValidationError('Trust receipt date received / confirmed cannot be future-dated.')
        return date_received

    def clean_date_banked(self):
        date_banked = self.cleaned_data.get('date_banked')
        if date_banked and date_banked > timezone.localdate():
            raise forms.ValidationError('Trust receipt date deposited cannot be future-dated.')
        return date_banked

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('payment_method')
        date_banked = cleaned_data.get('date_banked')
        if method in {'cash', 'cheque'} and not date_banked:
            self.add_error('date_banked', 'Date deposited to trust account is required for cash or cheque receipts.')
        return cleaned_data


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Receipt'))


class PaymentForm(forms.Form):
    amount = forms.DecimalField(
        label='Amount ordered to be paid',
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01')
)
    date_paid = forms.DateField(
        label='Date of cheque / EFT',
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=timezone.localdate
)
    payee_name = forms.CharField(label='Pay to / payee', max_length=255)
    payee_bsb = forms.CharField(label='Payee BSB', max_length=7, required=False)
    payee_account = forms.CharField(label='Payee account number', max_length=20, required=False)
    payment_method = forms.ChoiceField(
        label='Withdrawal method',
        choices=[('cheque', 'Cheque'), ('eft', 'EFT')],
        help_text='Trust withdrawals must be made by cheque or EFT only.'
    )
    payment_reference_override = forms.CharField(
        label='Payment / EFT reference',
        max_length=80,
        required=False,
        help_text='Optional. Leave blank to use the next Matter Funds payment/EFT reference number automatically.'
    )

    cheque_number = forms.CharField(
        label='Cheque number',
        max_length=50,
        required=False,
        help_text='Required for cheque payments only.'
    )
    purpose = forms.CharField(label='Reason / purpose of payment', max_length=500)

    def clean_date_paid(self):
        date_paid = self.cleaned_data['date_paid']
        if date_paid > timezone.localdate():
            raise forms.ValidationError('Trust payment date paid cannot be future-dated.')
        return date_paid

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('payment_method')
        cheque_number = cleaned_data.get('cheque_number')
        payee_bsb = cleaned_data.get('payee_bsb')
        payee_account = cleaned_data.get('payee_account')

        if method == 'cheque' and not cheque_number:
            self.add_error('cheque_number', 'Cheque number is required for cheque trust payments.')

        if method == 'eft':
            if not payee_bsb:
                self.add_error('payee_bsb', 'Payee BSB is required for EFT trust payments.')
            if not payee_account:
                self.add_error('payee_account', 'Payee account number is required for EFT trust payments.')

        return cleaned_data

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Payment'))


class TransferCostsToOfficeForm(forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    date_paid = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), initial=timezone.localdate)
    payee_name = forms.CharField(max_length=255, label='Office account name')
    payee_bsb = forms.CharField(max_length=7, required=False, label='Office account BSB')
    payee_account = forms.CharField(max_length=20, required=False, label='Office account number')
    payment_method = forms.ChoiceField(choices=[('cheque', 'Cheque'), ('eft', 'EFT')])
    cheque_number = forms.CharField(max_length=50, required=False)
    purpose = forms.CharField(max_length=500, initial='Transfer legal costs to office account')
    costs_withdrawal_method = forms.ChoiceField(choices=Payment.COSTS_WITHDRAWAL_METHOD_CHOICES)
    key_evidence_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
        help_text='Optional key date for examiner reference, such as bill, authority, or reimbursement date.'
)
    costs_evidence_file = forms.FileField(required=False, help_text='Optional: upload primary evidence such as bill, authority, agreement, or evidence bundle retained for examiner review.')
    notice_or_request_file = forms.FileField(required=False)
    authority_or_agreement_file = forms.FileField(required=False)
    reimbursement_evidence_file = forms.FileField(required=False)
    costs_withdrawal_notes = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Transfer Costs to Office'))

    def clean_date_paid(self):
        date_paid = self.cleaned_data['date_paid']
        if date_paid > timezone.localdate():
            raise forms.ValidationError('Trust payment date paid cannot be future-dated.')
        return date_paid

    def clean(self):
        cleaned_data = super().clean()
        # Supporting evidence should be retained for examiner review, but the
        # platform should not block the trust transaction solely because the
        # document is not uploaded at the time of entry.
        return cleaned_data


class ReconciliationBankLineForm(forms.ModelForm):
    class Meta:
        model = ReconciliationBankLine
        fields = ['line_date', 'line_type', 'amount', 'description', 'reference', 'adjustment_category', 'carry_forward_until_cleared', 'notes']
        widgets = {
            'line_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'line_date': 'Authorised ADI statement date',
            'line_type': 'Statement line type',
            'amount': 'Statement amount',
            'description': 'Statement description',
            'reference': 'Bank reference',
            'adjustment_category': 'Adjustment category',
            'carry_forward_until_cleared': 'Carry forward until cleared',
            'notes': 'Investigation / correction notes',
        }


class ManualIrregularityForm(forms.ModelForm):
    class Meta:
        model = Irregularity
        fields = [
            'trust_account', 'discovered_on', 'description', 'amount',
            'reported_to_law_society_on', 'report_document', 'resolution',
        ]
        widgets = {
            'discovered_on': forms.DateInput(attrs={'type': 'date'}),
            'reported_to_law_society_on': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user and user.role != 'admin' and user.firm:
            self.fields['trust_account'].queryset = TrustAccount.objects.filter(firm=user.firm)
        else:
            self.fields['trust_account'].queryset = TrustAccount.objects.all()
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Irregularity'))


class MatterLedgerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        matter = obj.matter
        client_name = getattr(matter.client, "name", "")
        return f"{matter.file_number} - {matter.description} - {client_name} - Balance ${obj.balance}"


class TrustJournalForm(forms.Form):
    from_ledger = MatterLedgerChoiceField(
        queryset=MatterLedger.objects.none(),
        label='From matter ledger',
        help_text='The matter ledger losing the trust money.'
    )
    to_ledger = MatterLedgerChoiceField(
        queryset=MatterLedger.objects.none(),
        label='To matter ledger',
        help_text='The matter ledger receiving the trust money. Must be a different matter ledger under the same trust account.'
    )
    amount = forms.DecimalField(
        label='Amount to transfer',
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01')
    )
    description = forms.CharField(
        label='Reason / purpose of transfer',
        max_length=500
    )
    written_authority = forms.FileField(label='Written authority / transfer request document')
    authority_date = forms.DateField(
        label='Authority date',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    authority_signed_by = forms.CharField(label='Authority signed by', max_length=255)

    def __init__(self, *args, **kwargs):
        trust_account = kwargs.pop('trust_account', None)
        super().__init__(*args, **kwargs)
        if trust_account:
            qs = MatterLedger.objects.filter(trust_account=trust_account).select_related('matter', 'matter__client').order_by('matter__file_number', 'pk')
            self.fields['from_ledger'].queryset = qs
            self.fields['to_ledger'].queryset = qs
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Trust Journal Transfer'))


class AuthorisedSignatoryForm(forms.ModelForm):
    class Meta:
        model = AuthorisedSignatory
        fields = [
            'trust_account',
            'name',
            'address',
            'email',
            'role',
            'practising_certificate_number',
            'authorised_trust_cheques',
            'authorised_trust_efts',
            'authorised_controlled_money',
            'authorised_from',
            'authorised_to',
            'is_active',
            'notes',
            'last_reviewed_on',
            'next_review_due_on',
            'review_notes',
        ]
        widgets = {
            'authorised_from': forms.DateInput(attrs={'type': 'date'}),
            'authorised_to': forms.DateInput(attrs={'type': 'date'}),
            'last_reviewed_on': forms.DateInput(attrs={'type': 'date'}),
            'next_review_due_on': forms.DateInput(attrs={'type': 'date'}),
            'reviewed_on': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'review_notes': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'authorised_trust_cheques': 'Authorised to sign trust cheques',
            'authorised_trust_efts': 'Authorised to effect/direct/authorise trust EFTs',
            'authorised_controlled_money': 'Authorised for controlled money withdrawals',
        }


class StatutoryDepositRecordForm(forms.ModelForm):
    class Meta:
        model = StatutoryDepositRecord
        fields = [
            'trust_account', 'applicable_period_end',
            'statutory_deposit_adi', 'statutory_deposit_account_reference',
            'calculated_on', 'required_amount', 'amount_currently_held',
            'adjustment_required', 'adjustment_due_date', 'adjustment_made_on',
            'calculation_notes', 'supporting_document',
            'law_society_determination_document', 'next_review_due_on', 'reviewed_by', 'reviewed_on',
        ]
        widgets = {
            'applicable_period_end': forms.DateInput(attrs={'type': 'date'}),
            'calculated_on': forms.DateInput(attrs={'type': 'date'}),
            'adjustment_due_date': forms.DateInput(attrs={'type': 'date'}),
            'adjustment_made_on': forms.DateInput(attrs={'type': 'date'}),
            'next_review_due_on': forms.DateInput(attrs={'type': 'date'}),
            'calculation_notes': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'statutory_deposit_adi': 'ADI holding statutory deposit',
            'statutory_deposit_account_reference': 'Statutory deposit account reference',
            'required_amount': 'Required statutory deposit amount',
            'amount_currently_held': 'Amount currently held on statutory deposit',
            'adjustment_required': 'Increase / reduction required',
            'supporting_document': 'Supporting document / bank confirmation',
            'law_society_determination_document': 'Law Society determination document',
        }


class TrustInvestmentForm(forms.ModelForm):
    class Meta:
        model = TrustInvestment
        fields = [
            'client',
            'matter',
            'person_on_behalf',
            'person_address',
            'investment_held_name',
            'institution',
            'investment_type',
            'investment_particulars',
            'amount_invested',
            'date_invested',
            'maturity_due_on',
            'source_of_investment',
            'source_reference',
            'trust_ledger_reference',
            'written_direction_reference',
            'written_direction_date',
            'cheque_or_eft_reference',
            'investment_terms',
            'document_identifier',
            'evidence_document',
            'written_direction_document',
            'interest_details',
            'maturity_repayment_details',
            'repaid_on',
            'notes',
        ]
        widgets = {
            'date_invested': forms.DateInput(attrs={'type': 'date'}),
            'maturity_due_on': forms.DateInput(attrs={'type': 'date'}),
            'written_direction_date': forms.DateInput(attrs={'type': 'date'}),
            'repaid_on': forms.DateInput(attrs={'type': 'date'}),
            'person_address': forms.Textarea(attrs={'rows': 2}),
            'investment_particulars': forms.Textarea(attrs={'rows': 3}),
            'investment_terms': forms.Textarea(attrs={'rows': 2}),
            'interest_details': forms.Textarea(attrs={'rows': 2}),
            'maturity_repayment_details': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'person_on_behalf': 'Person on whose behalf investment is made',
            'investment_held_name': 'Name investment held in',
            'source_reference': 'Source reference',
            'trust_ledger_reference': 'Trust ledger reference',
            'written_direction_reference': 'Written instruction / direction reference',
            'cheque_or_eft_reference': 'Cheque / EFT reference',
            'evidence_document': 'Document evidencing investment',
            'maturity_due_on': 'Maturity due date',
            'maturity_repayment_details': 'Maturity / repayment details',
            'written_direction_document': 'Written direction document',
        }


class PowerMoneyEntryForm(forms.ModelForm):
    class Meta:
        model = PowerMoneyEntry
        fields = [
            'entry_type', 'client', 'matter', 'power_instrument',
            'authority_document', 'donor', 'donor_address', 'donee',
            'power_date', 'deceased_name', 'date_of_death',
            'matter_reference', 'description', 'responsible_solicitor',
            'amount_held', 'notes',
        ]
        labels = {
            'amount_held': 'Funds currently held, if applicable',
        }
        widgets = {
            'power_date': forms.DateInput(attrs={'type': 'date'}),
            'date_of_death': forms.DateInput(attrs={'type': 'date'}),
            'donor_address': forms.Textarea(attrs={'rows': 2}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class PowerMoneyDealingForm(forms.ModelForm):
    class Meta:
        model = PowerMoneyDealing
        fields = [
            'dealing_date', 'description', 'deposit', 'withdrawal',
            'payee_or_source', 'supporting_document', 'notes',
        ]
        widgets = {
            'dealing_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class TransitMoneyEntryForm(forms.ModelForm):
    class Meta:
        model = TransitMoneyEntry
        fields = [
            'client',
            'matter',
            'received_on',
            'payor',
            'amount',
            'to_be_paid_to',
            'paid_on',
            'purpose',
            'instructions_document',
            'supporting_document',
            'notes',
        ]
        widgets = {
            'received_on': forms.DateInput(attrs={'type': 'date'}),
            'paid_on': forms.DateInput(attrs={'type': 'date'}),
            'purpose': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'received_on': 'Date transit money received',
            'payor': 'Received from / payor',
            'to_be_paid_to': 'Third party to be paid or delivered to',
            'paid_on': 'Date paid or delivered',
            'purpose': 'Purpose / instructions',
            'instructions_document': 'Written instructions / direction document',
            'supporting_document': 'Supporting document',
        }


class WrittenDirectionForm(forms.ModelForm):
    class Meta:
        model = WrittenDirection
        fields = [
            'client',
            'matter',
            'direction_text',
            'signed_on',
            'document',
            'linked_transaction',
        ]
        widgets = {
            'signed_on': forms.DateInput(attrs={'type': 'date'}),
            'direction_text': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'direction_text': 'Written direction / legal basis',
            'signed_on': 'Date written direction received/signed',
            'document': 'Written direction document',
        }


class DepositRecordForm(forms.Form):
    deposit_type = forms.ChoiceField(
        choices=DepositRecord.DEPOSIT_TYPE_CHOICES,
        label='Deposit record type',
        help_text='Cash and cheque deposits are recorded separately.'
    )
    deposit_date = forms.DateField(
        label='Date deposited to trust account',
        widget=forms.DateInput(attrs={'type': 'date'})
)
    receipts = forms.MultipleChoiceField(
        label='Receipts included in this deposit',
        required=True,
        widget=forms.CheckboxSelectMultiple
)
    notes = forms.CharField(
        label='Notes',
        required=False,
        widget=forms.Textarea(attrs={'rows': 2})
)

    def __init__(self, *args, trust_account=None, deposit_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.trust_account = trust_account
        selected_type = deposit_type or self.data.get('deposit_type') or self.initial.get('deposit_type') or 'cash'
        qs = Receipt.objects.none()
        if trust_account and selected_type in {'cash', 'cheque'}:
            qs = (
                Receipt.objects
                .filter(
                    transaction__matter_ledger__trust_account=trust_account,
                    payment_method=selected_type,
                    deposit_record__isnull=True
)
                .select_related('transaction', 'transaction__matter_ledger__matter')
                .order_by('transaction__date_received_or_paid', 'receipt_number')
            )

        self.fields['receipts'].choices = [
            (
                str(receipt.pk),
                f"R{receipt.receipt_number} | {receipt.transaction.date_received_or_paid} | "
                f"${receipt.transaction.amount} | {receipt.payor_name} | "
                f"{receipt.transaction.matter_ledger.matter.file_number or receipt.transaction.matter_ledger.matter.pk}"
            )
            for receipt in qs
        ]

    def clean(self):
        cleaned = super().clean()
        deposit_type = cleaned.get('deposit_type')
        receipt_ids = cleaned.get('receipts') or []

        if not self.trust_account or not deposit_type or not receipt_ids:
            return cleaned

        receipts = Receipt.objects.filter(pk__in=receipt_ids).select_related('transaction__matter_ledger__trust_account')
        if receipts.count() != len(receipt_ids):
            raise forms.ValidationError('One or more selected receipts could not be found.')

        for receipt in receipts:
            if receipt.deposit_record_id:
                raise forms.ValidationError(f'Receipt R{receipt.receipt_number} is already included in a deposit record.')
            if receipt.payment_method != deposit_type:
                raise forms.ValidationError('Selected receipts must match the deposit record type.')
            if receipt.transaction.matter_ledger.trust_account_id != self.trust_account.pk:
                raise forms.ValidationError('Selected receipts must belong to this trust account.')

        cleaned['receipt_objects'] = list(receipts)
        return cleaned


class ReconciliationForm(forms.ModelForm):
    class Meta:
        model = MonthlyReconciliation
        fields = ['period_end', 'bank_statement_balance', 'bank_statement_pdf']
        widgets = {
            'period_end': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'period_end': 'Bank statement ending date / reconciliation period end',
            'bank_statement_balance': 'Bank statement ending balance',
            'bank_statement_pdf': 'Bank statement PDF',
        }
        help_texts = {
            'period_end': 'Use the month-end date shown on the authorised ADI trust bank statement.',
            'bank_statement_balance': 'Enter the closing balance shown on the authorised ADI trust bank statement.',
            'bank_statement_pdf': 'Optional: upload the bank statement used for this reconciliation.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bank_statement_balance'].widget.attrs.update({
            'placeholder': 'From bank statement',
        })
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Begin Reconciliation'))

    def clean_period_end(self):
        period_end = self.cleaned_data['period_end']
        import calendar
        from django.utils import timezone
        if period_end.day != calendar.monthrange(period_end.year, period_end.month)[1]:
            raise forms.ValidationError('Period end must be the last day of a month.')
        if not period_end < timezone.localdate():
            raise forms.ValidationError('Reconciliation cannot be created until after the period end date.')
        return period_end


class ReconciliationBankStatementForm(forms.ModelForm):
    class Meta:
        model = MonthlyReconciliation
        fields = ['bank_statement_pdf']
        labels = {'bank_statement_pdf': 'Bank statement PDF'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bank_statement_pdf'].required = True
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Save Bank Statement'))


class ReconciliationFinaliseForm(forms.Form):
    confirm = forms.BooleanField(
        required=True,
        label='I confirm this reconciliation is balanced and should be finalised.'
)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Finalise Reconciliation'))


class AccountingPeriodLockForm(forms.Form):
    confirm = forms.BooleanField(
        required=True,
        label='I confirm this accounting period should be locked.'
)

    def __init__(self, *args, **kwargs):
        self.period = kwargs.pop('period', None)
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Lock Period'))

    def clean(self):
        cleaned_data = super().clean()
        if self.period and self.period.status == TrustAccountingPeriod.STATUS_LOCKED:
            raise forms.ValidationError('This accounting period is already locked.')
        return cleaned_data


class IrregularityResolveForm(forms.ModelForm):
    class Meta:
        model = Irregularity
        fields = ['resolution', 'reported_to_law_society_on', 'report_document']
        widgets = {'reported_to_law_society_on': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Save Resolution'))


class DateRangeForm(forms.Form):
    date_from = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), required=False)
    date_to = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'get'
        self.helper.add_input(Submit('submit', 'Download PDF'))


class YearForm(forms.Form):
    year = forms.IntegerField(initial=timezone.localdate().year, min_value=2000, max_value=2100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'get'
        self.helper.add_input(Submit('submit', 'Download Pack'))

class ControlledMoneyAccountForm(forms.ModelForm):
    class Meta:
        model = ControlledMoneyAccount
        fields = ['client', 'matter', 'account_name', 'bank', 'bsb', 'account_number', 'client_instruction_document', 'interest_disposition', 'purpose', 'person_on_behalf', 'person_address', 'matter_reference', 'matter_description', 'opened_on', 'is_active', 'closed_on']
        widgets = {'opened_on': forms.DateInput(attrs={'type': 'date'}), 'closed_on': forms.DateInput(attrs={'type': 'date'}), 'purpose': forms.Textarea(attrs={'rows': 3}), 'interest_disposition': forms.Textarea(attrs={'rows': 3}), 'person_address': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user and self.user.firm_id:
            self.instance.firm = self.user.firm
            self.fields['client'].queryset = Client.objects.filter(firm=self.user.firm)
            self.fields['matter'].queryset = Matter.objects.filter(firm=self.user.firm)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Save Controlled Money Account'))

    def clean(self):
        cleaned_data = super().clean()
        if self.user and self.user.firm_id:
            self.instance.firm = self.user.firm
            account_name = cleaned_data.get('account_name') or ''
            firm_name = self.user.firm.name or ''
            if firm_name and firm_name.lower() not in account_name.lower():
                self.add_error('account_name', f'Controlled money account name must include the law practice name: {firm_name}.')
        return cleaned_data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.user and self.user.firm_id:
            obj.firm = self.user.firm
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class ControlledMoneyReceiptForm(forms.ModelForm):
    class Meta:
        model = ControlledMoneyReceipt
        fields = ['controlled_money_account', 'date_money_received', 'amount', 'payment_method', 'person_from_whom_received', 'person_on_behalf', 'matter_reference', 'matter_description', 'reason']
        widgets = {'date_money_received': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        qs = ControlledMoneyAccount.objects.all()
        if self.user and self.user.firm_id:
            qs = qs.filter(firm=self.user.firm)
        self.fields['controlled_money_account'].queryset = qs.filter(is_active=True)
        self.fields['controlled_money_account'].required = True
        self.fields['controlled_money_account'].label = 'Controlled Money Account credited'
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Controlled Money Receipt'))

    def clean_controlled_money_account(self):
        account = self.cleaned_data.get('controlled_money_account')
        if not account:
            raise forms.ValidationError('Controlled money account is required before issuing a controlled money receipt.')
        if self.user and self.user.firm_id and account.firm_id != self.user.firm_id:
            raise forms.ValidationError('Controlled money account must belong to your firm.')
        return account

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.user and self.user.firm_id:
            obj.firm = self.user.firm
        obj.made_out_by = self.user
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class ControlledMoneyWithdrawalForm(forms.ModelForm):
    class Meta:
        model = ControlledMoneyWithdrawal
        fields = ['controlled_money_account', 'date', 'transaction_number', 'amount', 'withdrawal_method', 'payee', 'destination_account_name', 'destination_bsb', 'destination_account_number', 'person_on_behalf', 'matter_reference', 'reason', 'authorised_by', 'supporting_authority']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        qs = ControlledMoneyAccount.objects.all()
        if self.user and self.user.firm_id:
            qs = qs.filter(firm=self.user.firm)
        self.fields['controlled_money_account'].queryset = qs.filter(is_active=True)
        self.helper = FormHelper(); self.helper.form_tag = False; self.helper.add_input(Submit('submit', 'Create Controlled Money Withdrawal'))


class ControlledMoneySupportingDocumentForm(forms.ModelForm):
    DOCUMENT_TYPE_CHOICES = [
        ('written_direction', 'Written Direction'),
        ('adi_statement', 'ADI Statement'),
        ('interest_notification', 'Interest Notification'),
        ('withdrawal_authority', 'Withdrawal Authority'),
        ('other', 'Other Supporting Record'),
    ]

    document_type = forms.ChoiceField(choices=DOCUMENT_TYPE_CHOICES)

    class Meta:
        model = ControlledMoneySupportingDocument
        fields = ['document_type', 'document', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class ControlledMoneyMonthlyStatementForm(forms.ModelForm):
    class Meta:
        model = ControlledMoneyMonthlyStatement
        fields = ['period_end']
        widgets = {'period_end': forms.DateInput(attrs={'type': 'date'})}
        labels = {'period_end': 'Month end / statement date'}

    def clean_period_end(self):
        period_end = self.cleaned_data['period_end']
        import calendar
        if period_end.day != calendar.monthrange(period_end.year, period_end.month)[1]:
            raise forms.ValidationError('Monthly Controlled Money Statement must be as at month end.')
        if period_end >= timezone.localdate():
            raise forms.ValidationError('Monthly Controlled Money Statement cannot be prepared before the month has ended.')
        return period_end


class ControlledMoneyPrincipalReviewForm(forms.ModelForm):
    confirm = forms.BooleanField(label='I confirm I am authorised as principal/admin to review this Monthly Controlled Money Statement.')
    class Meta:
        model = ControlledMoneyMonthlyStatement
        fields = ['reviewer_role_confirmation', 'review_note']
        widgets = {'review_note': forms.Textarea(attrs={'rows': 3})}


class ComplianceReviewLogForm(forms.ModelForm):
    class Meta:
        model = ComplianceReviewLog
        fields = [
            'severity',
            'category',
            'title',
            'matter',
            'alert_key',
            'source_url',
            'status',
            'review_note',
            'next_review_on',
        ]
        widgets = {
            'review_note': forms.Textarea(attrs={'rows': 5}),
            'next_review_on': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'alert_key': 'Alert reference',
            'source_url': 'Source record URL',
            'next_review_on': 'Next review / follow-up date',
        }


class Section19ComplianceReviewForm(forms.ModelForm):
    class Meta:
        model = Section19ComplianceReview
        fields = [
            'review_period_start',
            'review_period_end',
            'status',
            'debit_balances_reviewed',
            'debit_balances_notes',
            'old_balances_reviewed',
            'old_balances_notes',
            'reconciliations_reviewed',
            'reconciliations_notes',
            'unidentified_money_reviewed',
            'unidentified_money_notes',
            'controlled_money_reviewed',
            'controlled_money_notes',
            'written_directions_reviewed',
            'written_directions_notes',
            'trust_investments_reviewed',
            'trust_investments_notes',
            'statutory_deposits_reviewed',
            'statutory_deposits_notes',
            'source_documents_reviewed',
            'source_documents_notes',
            'corrective_action_summary',
        ]
        widgets = {
            'review_period_start': forms.DateInput(attrs={'type': 'date'}),
            'review_period_end': forms.DateInput(attrs={'type': 'date'}),
            'debit_balances_notes': forms.Textarea(attrs={'rows': 2}),
            'old_balances_notes': forms.Textarea(attrs={'rows': 2}),
            'reconciliations_notes': forms.Textarea(attrs={'rows': 2}),
            'unidentified_money_notes': forms.Textarea(attrs={'rows': 2}),
            'controlled_money_notes': forms.Textarea(attrs={'rows': 2}),
            'written_directions_notes': forms.Textarea(attrs={'rows': 2}),
            'trust_investments_notes': forms.Textarea(attrs={'rows': 2}),
            'statutory_deposits_notes': forms.Textarea(attrs={'rows': 2}),
            'source_documents_notes': forms.Textarea(attrs={'rows': 2}),
            'corrective_action_summary': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'review_period_start': 'Review period start',
            'review_period_end': 'Review period end',
            'debit_balances_reviewed': 'Debit balances reviewed',
            'old_balances_reviewed': 'Old trust balances reviewed',
            'reconciliations_reviewed': 'Monthly reconciliations reviewed',
            'unidentified_money_reviewed': 'Unidentified money / suspense items reviewed',
            'controlled_money_reviewed': 'Controlled money records reviewed',
            'written_directions_reviewed': 'Written directions reviewed',
            'trust_investments_reviewed': 'Trust investments reviewed',
            'statutory_deposits_reviewed': 'Statutory deposit records reviewed',
            'source_documents_reviewed': 'Source documents and supporting evidence reviewed',
            'corrective_action_summary': 'Corrective action summary',
        }


class AnnualTrustComplianceRecordForm(forms.ModelForm):
    class Meta:
        model = AnnualTrustComplianceRecord
        fields = [
            'trust_year_start',
            'trust_year_end',
            'status',
            'part_a_completed_on',
            'part_b_required',
            'part_b_completed_on',
            'external_examiner_required',
            'external_examiner_name',
            'external_examiner_report_lodged_on',
            'bank_reconciliation_31_march',
            'trial_balance_31_march',
            'bank_statement_31_march',
            'overdrawn_ledgers_reviewed',
            'controlled_money_listing_reviewed',
            'investment_money_listing_reviewed',
            'notes',
        ]
        widgets = {
            'trust_year_start': forms.DateInput(attrs={'type': 'date'}),
            'trust_year_end': forms.DateInput(attrs={'type': 'date'}),
            'part_a_completed_on': forms.DateInput(attrs={'type': 'date'}),
            'part_b_completed_on': forms.DateInput(attrs={'type': 'date'}),
            'external_examiner_report_lodged_on': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'trust_year_start': 'Trust year start',
            'trust_year_end': 'Trust year end',
            'part_a_completed_on': 'Annual trust confirmation (Part A) lodged on',
            'part_b_required': 'Statement of Trust Money (Part B) required',
            'part_b_completed_on': 'Statement of Trust Money (Part B) lodged on',
            'external_examiner_required': 'External Examiner Report required',
            'external_examiner_name': 'External examiner name',
            'external_examiner_report_lodged_on': 'External Examiner Report lodged on',
            'bank_reconciliation_31_march': 'Bank reconciliation as at 31 March',
            'trial_balance_31_march': 'Trial balance as at 31 March',
            'bank_statement_31_march': 'Bank statement as at 31 March',
            'overdrawn_ledgers_reviewed': 'Overdrawn ledgers reviewed',
            'controlled_money_listing_reviewed': 'Controlled money listing reviewed',
            'investment_money_listing_reviewed': 'Investment money listing reviewed',
        }

        help_texts = {
            'part_a_completed_on': 'Annual trust confirmation required for the trust year. Record the lodgement/completion date.',
            'part_b_required': 'Use this where a Statement of Trust Money is required for the trust year.',
            'part_b_completed_on': 'Record the date the Statement of Trust Money was completed or lodged.',
            'external_examiner_required': 'Use this where an independent External Examiner Report is required for the trust year.',
            'external_examiner_report_lodged_on': 'Record the date the External Examiner Report was lodged or submitted.',
            'bank_reconciliation_31_march': 'Upload or attach the reconciliation position as at 31 March.',
            'trial_balance_31_march': 'Upload or attach the trust ledger trial balance as at 31 March.',
            'bank_statement_31_march': 'Upload or attach the relevant bank statement as at 31 March.',
        }


class UnclaimedMoneyRecordForm(forms.ModelForm):
    class Meta:
        model = UnclaimedMoneyRecord
        fields = [
            'trust_account',
            'matter_ledger',
            'amount',
            'date_identified',
            'date_last_activity',
            'date_funds_became_potentially_unclaimed',
            'last_client_contact_date',
            'contact_attempts',
            'review_notes',
            'proposed_action',
            'status',
            'supporting_document',
            'reviewed_by',
            'reviewed_on',
            'resolved_on',
            'resolution_notes',
        ]
        widgets = {
            'date_identified': forms.DateInput(attrs={'type': 'date'}),
            'date_last_activity': forms.DateInput(attrs={'type': 'date'}),
            'date_funds_became_potentially_unclaimed': forms.DateInput(attrs={'type': 'date'}),
            'last_client_contact_date': forms.DateInput(attrs={'type': 'date'}),
            'reviewed_on': forms.DateInput(attrs={'type': 'date'}),
            'resolved_on': forms.DateInput(attrs={'type': 'date'}),
            'contact_attempts': forms.Textarea(attrs={'rows': 3}),
            'review_notes': forms.Textarea(attrs={'rows': 3}),
            'proposed_action': forms.Textarea(attrs={'rows': 3}),
            'resolution_notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.firm = kwargs.pop('firm', None)
        super().__init__(*args, **kwargs)
        if self.firm:
            self.fields['trust_account'].queryset = TrustAccount.objects.filter(firm=self.firm).order_by('name')
            self.fields['matter_ledger'].queryset = MatterLedger.objects.filter(trust_account__firm=self.firm).select_related('matter', 'trust_account').order_by('matter__file_number')
