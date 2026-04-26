from django.contrib import admin

from .models import Matter


@admin.register(Matter)
class MatterAdmin(admin.ModelAdmin):
    list_display = ['file_number', 'description', 'firm', 'client', 'responsible_lawyer', 'status', 'opened_on']
    list_filter = ['firm', 'status']
    search_fields = ['file_number', 'description']
    date_hierarchy = 'opened_on'
