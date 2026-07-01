from django.contrib import admin

from .models import Firm, FirmAccessRequest


@admin.register(Firm)
class FirmAdmin(admin.ModelAdmin):
    list_display = ['name', 'abn', 'jurisdiction', 'principal_solicitor', 'is_sole_practitioner']
    search_fields = ['name', 'abn']


@admin.register(FirmAccessRequest)
class FirmAccessRequestAdmin(admin.ModelAdmin):
    list_display = ('firm', 'user', 'requested_role', 'status', 'created_at', 'reviewed_by', 'reviewed_at')
    list_filter = ('status', 'requested_role', 'created_at')
    search_fields = ('firm__name', 'user__username', 'user__email', 'request_note', 'review_note')
    readonly_fields = ('created_at',)
