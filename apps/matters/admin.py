from django.contrib import admin

from .models import Matter


@admin.register(Matter)
class MatterAdmin(admin.ModelAdmin):
    list_display = ['file_number', 'description', 'firm', 'client', 'other_party', 'responsible_lawyer', 'status', 'date_instructions_received', 'opened_on', 'closed_on']
    list_filter = ['firm', 'status']
    search_fields = ['file_number', 'description', 'client__name', 'other_party', 'regulated_property_location']
    date_hierarchy = 'opened_on'
