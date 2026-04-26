import datetime
from decimal import Decimal
from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from .models import MatterLedger, MonthlyReconciliation, Irregularity


class ReceiptForm(forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    date_received = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), initial=datetime.date.today)
    date_banked = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), required=False)
    payor_name = forms.CharField(max_length=255)
    payment_method = forms.ChoiceField(choices=[
        ('cash', 'Cash'), ('cheque', 'Cheque'), ('eft', 'EFT'), ('direct_deposit', 'Direct Deposit'),
    ])
    cheque_number = forms.CharField(max_length=50, required=False)
    purpose = forms.CharField(max_length=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Receipt'))


class PaymentForm(forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    date_paid = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), initial=datetime.date.today)
    payee_name = forms.CharField(max_length=255)
    payee_bsb = forms.CharField(max_length=7, required=False)
    payee_account = forms.CharField(max_length=20, required=False)
    payment_method = forms.ChoiceField(choices=[('cheque', 'Cheque'), ('eft', 'EFT')])
    cheque_number = forms.CharField(max_length=50, required=False)
    purpose = forms.CharField(max_length=500)
    second_authoriser = forms.ModelChoiceField(
        queryset=None, required=False, help_text='Required for EFT on non-sole-practitioner firms.'
    )

    def __init__(self, *args, **kwargs):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        super().__init__(*args, **kwargs)
        self.fields['second_authoriser'].queryset = User.objects.filter(
            role__in=['admin', 'solicitor', 'accountant']
        )
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Payment'))


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
    year = forms.IntegerField(initial=datetime.date.today().year, min_value=2000, max_value=2100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'get'
        self.helper.add_input(Submit('submit', 'Download Pack'))
