from decimal import Decimal
from django import forms
from django.utils import timezone
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from .models import MatterLedger, MonthlyReconciliation, Irregularity, Payment, TrustAccount, TrustAccountingPeriod


class ReceiptForm(forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    date_received = forms.DateField(
        label='Date received / confirmed in trust account',
        help_text=(
            'For EFT/direct deposit, use the date the solicitor received or accessed confirmation '
            'that funds were in the trust account.'
        ),
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=timezone.localdate,
    )
    date_banked = forms.DateField(
        label='Date deposited to trust account',
        help_text='Required for cash or cheque when the separate banking/deposit step occurs.',
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
    )
    payor_name = forms.CharField(max_length=255)
    payment_method = forms.ChoiceField(choices=[
        ('cash', 'Cash'), ('cheque', 'Cheque'), ('eft', 'EFT'), ('direct_deposit', 'Direct Deposit'),
    ])
    cheque_number = forms.CharField(max_length=50, required=False)
    purpose = forms.CharField(max_length=500)

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
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    date_paid = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), initial=timezone.localdate)
    payee_name = forms.CharField(max_length=255)
    payee_bsb = forms.CharField(max_length=7, required=False)
    payee_account = forms.CharField(max_length=20, required=False)
    payment_method = forms.ChoiceField(choices=[('cheque', 'Cheque'), ('eft', 'EFT')])
    cheque_number = forms.CharField(max_length=50, required=False)
    purpose = forms.CharField(max_length=500)

    def clean_date_paid(self):
        date_paid = self.cleaned_data['date_paid']
        if date_paid > timezone.localdate():
            raise forms.ValidationError('Trust payment date paid cannot be future-dated.')
        return date_paid

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
        help_text='Optional key date for examiner reference, such as bill, authority, or reimbursement date.',
    )
    costs_evidence_file = forms.FileField(required=False, help_text='Primary evidence, such as bill, authority, agreement, or evidence bundle.')
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
        method = cleaned_data.get('costs_withdrawal_method')
        evidence_fields = [
            'costs_evidence_file',
            'notice_or_request_file',
            'authority_or_agreement_file',
            'reimbursement_evidence_file',
        ]
        if not any(cleaned_data.get(field) for field in evidence_fields):
            raise forms.ValidationError('At least one costs withdrawal evidence document is required.')
        if method in ('method_2_authority', 'method_4_commercial_government') and not cleaned_data.get('authority_or_agreement_file'):
            self.add_error('authority_or_agreement_file', 'Authority or agreement evidence is required for this withdrawal method.')
        if method == 'method_3_reimbursement' and not cleaned_data.get('reimbursement_evidence_file'):
            self.add_error('reimbursement_evidence_file', 'Reimbursement evidence is required for Method 3 withdrawals.')
        return cleaned_data


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


class TrustJournalForm(forms.Form):
    from_ledger = forms.ModelChoiceField(queryset=MatterLedger.objects.none(), label='From Ledger')
    to_ledger = forms.ModelChoiceField(queryset=MatterLedger.objects.none(), label='To Ledger')
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    description = forms.CharField(max_length=500)
    written_authority = forms.FileField(label='Written Authority Document')
    authority_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    authority_signed_by = forms.CharField(max_length=255)

    def __init__(self, *args, **kwargs):
        trust_account = kwargs.pop('trust_account', None)
        super().__init__(*args, **kwargs)
        if trust_account:
            qs = MatterLedger.objects.filter(trust_account=trust_account).select_related('matter')
            self.fields['from_ledger'].queryset = qs
            self.fields['to_ledger'].queryset = qs
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Journal'))


class ReconciliationForm(forms.ModelForm):
    class Meta:
        model = MonthlyReconciliation
        fields = [
            'period_end', 'cash_book_balance', 'ledger_total_balance',
            'bank_statement_balance', 'unpresented_cheques_total',
            'outstanding_deposits_total', 'bank_statement_pdf',
        ]
        widgets = {'period_end': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Save Reconciliation'))

    def clean_period_end(self):
        period_end = self.cleaned_data['period_end']
        import calendar
        if period_end.day != calendar.monthrange(period_end.year, period_end.month)[1]:
            raise forms.ValidationError('Period end must be the last day of a month.')
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
        label='I confirm this reconciliation is balanced and should be finalised.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Finalise Reconciliation'))


class AccountingPeriodLockForm(forms.Form):
    confirm = forms.BooleanField(
        required=True,
        label='I confirm this accounting period should be locked.',
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
