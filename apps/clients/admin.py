from django.contrib import admin

from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['name', 'firm', 'client_type', 'email']
    list_filter = ['firm', 'client_type']
    search_fields = ['name', 'email', 'abn_acn']
