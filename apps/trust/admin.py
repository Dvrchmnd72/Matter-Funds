from django.contrib import admin

from .models import (
    TrustAccount, ControlledMoneyAccount, MatterLedger, TrustTransaction,
    Receipt, Payment, TrustJournal, WrittenDirection, TransitMoneyEntry,
    PowerMoneyEntry, MonthlyReconciliation, Irregularity,
)
from .services import create_receipt, create_payment


@admin.register(TrustAccount)
class TrustAccountAdmin(admin.ModelAdmin):
    list_display = ['name', 'firm', 'bank', 'bsb', 'account_number', 'is_general', 'is_active']
    list_filter = ['firm', 'is_general', 'is_active']
    search_fields = ['name', 'bsb', 'account_number']


@admin.register(ControlledMoneyAccount)
class ControlledMoneyAccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'firm', 'bank', 'bsb', 'account_number', 'opened_on']
    list_filter = ['firm']
    search_fields = ['client__name', 'account_number']


@admin.register(MatterLedger)
class MatterLedgerAdmin(admin.ModelAdmin):
    list_display = ['matter', 'trust_account', 'balance', 'opened_on']
    list_filter = ['trust_account']
    search_fields = ['matter__file_number', 'matter__description']
    readonly_fields = ['balance', 'opened_on']


@admin.register(TrustTransaction)
class TrustTransactionAdmin(admin.ModelAdmin):
    list_display = ['transaction_type', 'matter_ledger', 'amount', 'date_received_or_paid', 'created_by', 'is_reversed']
    list_filter = ['transaction_type', 'is_reversed']
    search_fields = ['description']
    readonly_fields = ['transaction_type', 'matter_ledger', 'amount', 'date_received_or_paid',
                       'date_banked', 'description', 'created_by', 'created_at', 'is_reversed', 'reverses']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _ReadOnlyAppendMixin:
    """Admin mixin: existing records are read-only; deletions are always prohibited."""

    def has_change_permission(self, request, obj=None):
        if obj is not None:
            return False
        return super().has_change_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Receipt)
class ReceiptAdmin(_ReadOnlyAppendMixin, admin.ModelAdmin):
    list_display = ['receipt_number', 'payor_name', 'payment_method', 'purpose', 'late_banking']
    search_fields = ['payor_name', 'purpose']
    readonly_fields = ['receipt_number', 'transaction', 'late_banking']

    def save_model(self, request, obj, form, change):
        # Receipts must be created via the service layer; this path is for new objects only.
        create_receipt(
            matter_ledger=obj.transaction.matter_ledger,
            amount=obj.transaction.amount,
            date_received=obj.transaction.date_received_or_paid,
            date_banked=obj.transaction.date_banked,
            payor_name=obj.payor_name,
            payment_method=obj.payment_method,
            cheque_number=obj.cheque_number,
            purpose=obj.purpose,
            created_by=request.user,
        )


@admin.register(Payment)
class PaymentAdmin(_ReadOnlyAppendMixin, admin.ModelAdmin):
    list_display = ['payment_number', 'payee_name', 'payment_method', 'purpose', 'authorised_by']
    search_fields = ['payee_name', 'purpose']
    readonly_fields = ['payment_number', 'transaction']

    def save_model(self, request, obj, form, change):
        create_payment(
            matter_ledger=obj.transaction.matter_ledger,
            amount=obj.transaction.amount,
            date_paid=obj.transaction.date_received_or_paid,
            payee_name=obj.payee_name,
            payee_bsb=obj.payee_bsb,
            payee_account=obj.payee_account,
            payment_method=obj.payment_method,
            cheque_number=obj.cheque_number,
            purpose=obj.purpose,
            authorised_by=obj.authorised_by,
            second_authoriser=obj.second_authoriser,
            created_by=request.user,
        )


@admin.register(TrustJournal)
class TrustJournalAdmin(_ReadOnlyAppendMixin, admin.ModelAdmin):
    list_display = ['from_ledger', 'to_ledger', 'amount', 'authority_date', 'created_by']
    search_fields = ['description', 'authority_signed_by']
    readonly_fields = ['journal_out_txn', 'journal_in_txn', 'created_by', 'created_at']


@admin.register(WrittenDirection)
class WrittenDirectionAdmin(admin.ModelAdmin):
    list_display = ['client', 'matter', 'signed_on', 'created_at']
    list_filter = ['client']
    search_fields = ['client__name', 'direction_text']


@admin.register(TransitMoneyEntry)
class TransitMoneyEntryAdmin(admin.ModelAdmin):
    list_display = ['payor', 'amount', 'to_be_paid_to', 'received_on', 'paid_on']
    search_fields = ['payor', 'to_be_paid_to']


@admin.register(PowerMoneyEntry)
class PowerMoneyEntryAdmin(admin.ModelAdmin):
    list_display = ['donor', 'donee', 'amount_held']
    search_fields = ['donor', 'donee']


@admin.register(MonthlyReconciliation)
class MonthlyReconciliationAdmin(_ReadOnlyAppendMixin, admin.ModelAdmin):
    list_display = ['trust_account', 'period_end', 'cash_book_balance', 'reconciled_balance', 'is_reconciled']
    list_filter = ['trust_account', 'is_reconciled']
    readonly_fields = ['reconciled_balance', 'is_reconciled', 'created_at']


@admin.register(Irregularity)
class IrregularityAdmin(admin.ModelAdmin):
    list_display = ['trust_account', 'discovered_on', 'amount', 'reported_to_law_society_on']
    list_filter = ['trust_account']
    search_fields = ['description']
