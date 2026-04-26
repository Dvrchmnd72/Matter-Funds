from django.contrib import admin

from .models import Firm


@admin.register(Firm)
class FirmAdmin(admin.ModelAdmin):
    list_display = ['name', 'abn', 'jurisdiction', 'principal_solicitor', 'is_sole_practitioner']
    search_fields = ['name', 'abn']
