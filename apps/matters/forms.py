from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from .models import Matter
from apps.trust.models import MatterLedger


class MatterForm(forms.ModelForm):
    class Meta:
        model = Matter
        fields = ['firm', 'file_number', 'description', 'client', 'responsible_lawyer', 'status', 'opened_on', 'closed_on']
        widgets = {
            'opened_on': forms.DateInput(attrs={'type': 'date'}),
            'closed_on': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Save'))


class MatterLedgerForm(forms.ModelForm):
    class Meta:
        model = MatterLedger
        fields = ['trust_account']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Create Ledger'))
