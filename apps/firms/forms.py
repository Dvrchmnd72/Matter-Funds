from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from .models import Firm


class FirmForm(forms.ModelForm):
    class Meta:
        model = Firm
        fields = ['name', 'abn', 'address', 'principal_solicitor', 'is_sole_practitioner', 'jurisdiction']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Save'))
