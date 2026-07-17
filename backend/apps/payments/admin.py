from django.contrib import admin

from apps.payments.models import BankAccount


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("country", "currency", "bank_name", "account_number", "is_active")
    list_filter = ("is_active", "country")
