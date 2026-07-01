from django.contrib import admin
from django.utils import timezone

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
    readonly_fields = ('created_at', 'reviewed_at')
    actions = ['approve_access_requests', 'reject_access_requests']

    @admin.action(description='Approve selected firm access requests')
    def approve_access_requests(self, request, queryset):
        approved = 0
        for access_request in queryset.select_related('user', 'firm'):
            if access_request.status != FirmAccessRequest.STATUS_PENDING:
                continue

            user = access_request.user
            user.firm = access_request.firm
            if access_request.requested_role:
                user.role = access_request.requested_role
            user.is_firm_approved = True
            user.mf2fa_required = True
            user.save(update_fields=['firm', 'role', 'is_firm_approved', 'mf2fa_required'])

            access_request.status = FirmAccessRequest.STATUS_APPROVED
            access_request.reviewed_by = request.user
            access_request.reviewed_at = timezone.now()
            access_request.review_note = access_request.review_note or 'Approved via Matter Funds admin.'
            access_request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])

            approved += 1

        self.message_user(request, f'{approved} firm access request(s) approved.')

    @admin.action(description='Reject selected firm access requests')
    def reject_access_requests(self, request, queryset):
        rejected = 0
        for access_request in queryset.select_related('user', 'firm'):
            if access_request.status != FirmAccessRequest.STATUS_PENDING:
                continue

            access_request.status = FirmAccessRequest.STATUS_REJECTED
            access_request.reviewed_by = request.user
            access_request.reviewed_at = timezone.now()
            access_request.review_note = access_request.review_note or 'Rejected via Matter Funds admin.'
            access_request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])

            rejected += 1

        self.message_user(request, f'{rejected} firm access request(s) rejected.')
