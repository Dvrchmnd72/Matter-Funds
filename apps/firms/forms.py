from django import forms

from .models import Firm


class FirmForm(forms.ModelForm):
    principal_first_name = forms.CharField(
        required=False,
        label='Principal first name',
        help_text='Used as the display name on firm and matter records.'
    )
    principal_last_name = forms.CharField(
        required=False,
        label='Principal last name',
        help_text='Used as the display name on firm and matter records.'
    )

    class Meta:
        model = Firm
        fields = [
            'name',
            'abn',
            'address',
            'principal_first_name',
            'principal_last_name',
            'is_sole_practitioner',
            'jurisdiction',
        ]
        labels = {
            'principal_solicitor': 'Principal user account',
        }
        help_texts = {
            'principal_solicitor': 'Linked login account for the principal solicitor.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        principal = getattr(self.instance, 'principal_solicitor', None)
        if principal:
            self.fields['principal_first_name'].initial = principal.first_name
            self.fields['principal_last_name'].initial = principal.last_name

    def save(self, commit=True):
        firm = super().save(commit=commit)

        principal = getattr(firm, 'principal_solicitor', None)
        if principal:
            principal.first_name = self.cleaned_data.get('principal_first_name', '')
            principal.last_name = self.cleaned_data.get('principal_last_name', '')
            if commit:
                principal.save(update_fields=['first_name', 'last_name'])

        return firm
