from django.contrib import admin

from .models import AnnualTrustComplianceRecord
from .models import (
    Section19ComplianceReview,
    ComplianceReviewLog,
    TrustAccount, ControlledMoneyAccount, MatterLedger, TrustTransaction,
    Receipt, Payment, TrustJournal, WrittenDirection, TransitMoneyEntry,
    PowerMoneyEntry, TrustInvestment, MonthlyReconciliation, Irregularity, TrustAccountingPeriod,
    TrustMonthlyRecord, ControlledMoneyReceipt, ControlledMoneyWithdrawal,
    ControlledMoneySupportingDocument, ControlledMoneyMonthlyStatement,
)
from .services import create_receipt, create_payment


@admin.register(TrustAccount)
class TrustAccountAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'firm', 'bank', 'bsb', 'account_number',
        'opened_on', 'closed_on', 'law_society_opening_notice_sent_on',
        'law_society_closure_notice_sent_on', 'is_general', 'is_active',
    ]
    list_filter = ['firm', 'is_general', 'is_active']
    search_fields = ['name', 'bank', 'bsb', 'account_number']
    fieldsets = (
        (None, {
            'fields': (
                'firm', 'name', 'bank', 'bsb', 'account_number',
                'is_general', 'is_active',
            )
        }),
        ('Section 6A — General trust account record', {
            'fields': (
                'opened_on', 'law_society_opening_notice_sent_on',
                'closed_on', 'law_society_closure_notice_sent_on',
            )
        }),
        ('Sequencing', {
            'fields': (
                'next_receipt_number', 'next_payment_number',
                'next_controlled_money_receipt_number',
            )
        }),
    )


@admin.register(ControlledMoneyAccount)
class ControlledMoneyAccountAdmin(admin.ModelAdmin):
    list_display = ['account_name', 'client', 'firm', 'bank', 'bsb', 'account_number', 'current_balance', 'is_active', 'opened_on']
    list_filter = ['firm', 'is_active']
    search_fields = ['account_name', 'client__name', 'account_number', 'matter_reference']


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
                       'date_banked', 'description', 'created_by', 'is_reversed', 'reverses']

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


@admin.register(ControlledMoneyReceipt)
class ControlledMoneyReceiptAdmin(_ReadOnlyAppendMixin, admin.ModelAdmin):
    list_display = ['receipt_number', 'firm', 'controlled_money_account', 'date_made_out', 'amount', 'person_on_behalf', 'is_cancelled']
    list_filter = ['firm', 'is_cancelled', 'not_delivered']
    search_fields = ['receipt_number', 'person_from_whom_received', 'person_on_behalf', 'matter_reference', 'reason']


@admin.register(ControlledMoneyWithdrawal)
class ControlledMoneyWithdrawalAdmin(admin.ModelAdmin):
    list_display = ['transaction_number', 'controlled_money_account', 'date', 'amount', 'withdrawal_method', 'person_on_behalf']
    list_filter = ['withdrawal_method', 'controlled_money_account__firm']
    search_fields = ['transaction_number', 'payee', 'destination_account_name', 'matter_reference', 'reason']


@admin.register(ControlledMoneySupportingDocument)
class ControlledMoneySupportingDocumentAdmin(admin.ModelAdmin):
    list_display = ['controlled_money_account', 'document_type', 'description', 'uploaded_at']
    list_filter = ['document_type', 'controlled_money_account__firm']


@admin.register(ControlledMoneyMonthlyStatement)
class ControlledMoneyMonthlyStatementAdmin(admin.ModelAdmin):
    list_display = ['firm', 'period_end', 'prepared_on', 'due_date', 'reviewed_by', 'reviewed_on']
    list_filter = ['firm']


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
    list_display = ['payment_number', 'transaction_type', 'payee_name', 'payment_method', 'purpose', 'authorised_by', 'costs_withdrawal_method']
    search_fields = ['payee_name', 'purpose', 'costs_withdrawal_notes']
    readonly_fields = ['payment_number', 'transaction']
    exclude = ['second_authoriser']

    def transaction_type(self, obj):
        return obj.transaction.get_transaction_type_display()

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
            created_by=request.user,
        )


@admin.register(TrustJournal)
class TrustJournalAdmin(_ReadOnlyAppendMixin, admin.ModelAdmin):
    list_display = ['from_ledger', 'to_ledger', 'amount', 'authority_date', 'created_by']
    search_fields = ['description', 'authority_signed_by']
    readonly_fields = ['journal_out_txn', 'journal_in_txn', 'created_by']


@admin.register(WrittenDirection)
class WrittenDirectionAdmin(admin.ModelAdmin):
    list_display = ['client', 'matter', 'signed_on']
    list_filter = ['client']
    search_fields = ['client__name', 'direction_text']


@admin.register(TransitMoneyEntry)
class TransitMoneyEntryAdmin(admin.ModelAdmin):
    list_display = ['payor', 'amount', 'to_be_paid_to', 'received_on', 'paid_on']
    search_fields = ['payor', 'to_be_paid_to']


@admin.register(TrustInvestment)
class TrustInvestmentAdmin(admin.ModelAdmin):
    list_display = [
        'person_on_behalf',
        'investment_held_name',
        'institution',
        'amount_invested',
        'date_invested',
        'maturity_due_on',
        'source_of_investment',
        'repaid_on',
    ]
    list_filter = ['source_of_investment', 'date_invested', 'maturity_due_on', 'repaid_on']
    search_fields = [
        'person_on_behalf',
        'investment_held_name',
        'institution',
        'investment_type',
        'source_reference',
        'trust_ledger_reference',
        'document_identifier',
    ]


@admin.register(PowerMoneyEntry)
class PowerMoneyEntryAdmin(admin.ModelAdmin):
    list_display = ['donor', 'donee', 'amount_held']
    search_fields = ['donor', 'donee']


@admin.register(MonthlyReconciliation)
class MonthlyReconciliationAdmin(_ReadOnlyAppendMixin, admin.ModelAdmin):
    list_display = ['trust_account', 'period_end', 'cash_book_balance', 'reconciled_balance', 'is_reconciled', 'is_finalised']
    list_filter = ['trust_account', 'is_reconciled', 'is_finalised']
    readonly_fields = ['reconciled_balance', 'is_reconciled', 'is_finalised', 'finalised_by', 'finalised_on']


@admin.register(TrustAccountingPeriod)
class TrustAccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ['trust_account', 'period_start', 'period_end', 'status', 'locked_by', 'locked_on']
    list_filter = ['trust_account', 'status']
    readonly_fields = ['updated_at', 'locked_by', 'locked_on']

    def has_change_permission(self, request, obj=None):
        if obj and obj.status == TrustAccountingPeriod.STATUS_LOCKED:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status == TrustAccountingPeriod.STATUS_LOCKED:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(TrustMonthlyRecord)
class TrustMonthlyRecordAdmin(admin.ModelAdmin):
    list_display = ['accounting_period', 'record_type', 'generated_by', 'generated_at', 'sha256_hash']
    list_filter = ['trust_account', 'record_type']
    search_fields = ['sha256_hash']
    readonly_fields = ['accounting_period', 'reconciliation', 'trust_account', 'record_type', 'pdf', 'generated_by', 'generated_at', 'sha256_hash']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Irregularity)
class IrregularityAdmin(admin.ModelAdmin):
    list_display = ['trust_account', 'discovered_on', 'amount', 'reported_to_law_society_on']
    list_filter = ['trust_account']
    search_fields = ['description']


@admin.register(ComplianceReviewLog)
class ComplianceReviewLogAdmin(admin.ModelAdmin):
    list_display = ['firm', 'severity', 'category', 'title', 'status', 'reviewed_by', 'reviewed_on', 'next_review_on']
    list_filter = ['firm', 'severity', 'category', 'status', 'next_review_on']
    search_fields = ['category', 'title', 'review_note', 'alert_key']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Section19ComplianceReview)
class Section19ComplianceReviewAdmin(admin.ModelAdmin):
    list_display = ['firm', 'review_period_start', 'review_period_end', 'status', 'reviewed_by', 'reviewed_on']
    list_filter = ['firm', 'status', 'review_period_end']
    search_fields = ['corrective_action_summary']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(AnnualTrustComplianceRecord)
class AnnualTrustComplianceRecordAdmin(admin.ModelAdmin):
    list_display = ['firm', 'trust_year_start', 'trust_year_end', 'status', 'part_a_completed_on', 'external_examiner_required', 'external_examiner_report_lodged_on']
    list_filter = ['firm', 'status', 'trust_year_end', 'external_examiner_required']
    search_fields = ['external_examiner_name', 'notes']
    readonly_fields = ['created_at', 'updated_at']
