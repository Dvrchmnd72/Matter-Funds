from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'action', 'user', 'object_repr', 'ip_address']
    list_filter = ['action', 'content_type']
    search_fields = ['object_repr']
    readonly_fields = ['user', 'ip_address', 'timestamp', 'action', 'content_type',
                       'object_id', 'object_repr', 'before_json', 'after_json']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
