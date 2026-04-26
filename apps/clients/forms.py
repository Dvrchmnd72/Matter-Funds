from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from .models import Client


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['firm', 'client_type', 'name', 'email', 'phone', 'address', 'abn_acn']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.add_input(Submit('submit', 'Save'))
