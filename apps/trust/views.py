import datetime
from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q, Count
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView, FormView

from apps.accounts.permissions import StaffRequiredMixin, AdminOrAccountantMixin
from apps.trust import services
from apps.trust import reports as trust_reports
from .models import (
    TrustAccount, MatterLedger, TrustTransaction, Receipt, Payment, TrustJournal,
    MonthlyReconciliation, DepositRecord, ReconciliationBankLine, Irregularity, TrustAccountingPeriod, TrustMonthlyRecord,
    ControlledMoneyAccount, ControlledMoneyReceipt, ControlledMoneyWithdrawal, ControlledMoneyMonthlyStatement,
)
from .forms import (
    TrustAccountUpdateForm, ReceiptForm, PaymentForm, TransferCostsToOfficeForm, TrustJournalForm, ReconciliationForm, DepositRecordForm,
    ManualIrregularityForm, IrregularityResolveForm, DateRangeForm, YearForm,
    ReconciliationFinaliseForm, AccountingPeriodLockForm, ReconciliationBankStatementForm, ReconciliationBankLineForm,
    ControlledMoneyAccountForm, ControlledMoneyReceiptForm, ControlledMoneyWithdrawalForm,
    ControlledMoneyMonthlyStatementForm, ControlledMoneyPrincipalReviewForm,
)


def user_has_global_trust_access(user):
    return getattr(user, 'is_superuser', False) or (
        getattr(user, 'is_staff', False) and getattr(user, 'role', None) == 'admin'
    )


def scope_trust_queryset_for_user(queryset, user, firm_lookup='trust_account__firm'):
    if user_has_global_trust_access(user):
        return queryset
    if getattr(user, 'firm_id', None):
        return queryset.filter(**{firm_lookup: user.firm})
    return queryset.none()


class TrustAccountListView(StaffRequiredMixin, ListView):
    model = TrustAccount
    template_name = 'trust/account_list.html'
    context_object_name = 'accounts'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('firm'),
            self.request.user,
            firm_lookup='firm',
        )


class TrustAccountDetailView(StaffRequiredMixin, DetailView):
    model = TrustAccount
    template_name = 'trust/account_detail.html'
    context_object_name = 'account'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('firm'),
            self.request.user,
            firm_lookup='firm',
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        show_all_ledgers = self.request.GET.get('show_all_ledgers') in {'1', 'true', 'yes'}

        all_ledgers = (
            self.object.ledgers
            .select_related('matter', 'matter__client')
            .annotate(transaction_count=Count('transactions'))
            .order_by('matter__file_number', 'pk')
        )

        if show_all_ledgers:
            ledgers = all_ledgers
        else:
            ledgers = all_ledgers.filter(Q(transaction_count__gt=0) | ~Q(balance=0))

        total_count = all_ledgers.count()
        visible_count = ledgers.count()

        ctx['ledgers'] = ledgers
        ctx['show_all_ledgers'] = show_all_ledgers
        ctx['ledger_total_count'] = total_count
        ctx['ledger_visible_count'] = visible_count
        ctx['ledger_hidden_count'] = max(total_count - visible_count, 0)
        ctx['recent_transactions'] = (
            TrustTransaction.objects
            .filter(matter_ledger__trust_account=self.object)
            .select_related(
                'matter_ledger__matter',
                'receipt',
                'payment',
                'reverses',
                'journal_as_out',
                'journal_as_in',
            )
            .order_by('-created_at')[:20]
        )
        return ctx


class TrustAccountUpdateView(AdminOrAccountantMixin, UpdateView):
    model = TrustAccount
    form_class = TrustAccountUpdateForm
    template_name = 'trust/account_form.html'
    context_object_name = 'account'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('firm'),
            self.request.user,
            firm_lookup='firm',
        )

    def get_success_url(self):
        return reverse('trust:account_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Trust account details updated.')
        return super().form_valid(form)


class ReceiptCreateView(StaffRequiredMixin, View):
    template_name = 'trust/receipt_form.html'

    def get_ledger(self):
        queryset = scope_trust_queryset_for_user(
            MatterLedger.objects.select_related('trust_account', 'matter'),
            self.request.user,
        )
        return get_object_or_404(queryset, pk=self.kwargs['ledger_pk'])

    def get_context_data(self, form, ledger):
        return {
            'form': form,
            'ledger': ledger,
            'date_receipt_made_out': timezone.localdate(),
        }

    def get(self, request, ledger_pk):
        form = ReceiptForm()
        ledger = self.get_ledger()
        return render(request, self.template_name, self.get_context_data(form, ledger))

    def post(self, request, ledger_pk):
        ledger = self.get_ledger()
        form = ReceiptForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                receipt = services.create_receipt(
                    matter_ledger=ledger,
                    amount=cd['amount'],
                    date_received=cd['date_received'],
                    date_banked=cd.get('date_banked'),
                    payor_name=cd['payor_name'],
                    payment_method=cd['payment_method'],
                    cheque_number=cd.get('cheque_number', ''),
                    purpose=cd['purpose'],
                    created_by=request.user,
                )
                messages.success(request, f'Receipt #{receipt.receipt_number} created successfully.')
                return redirect(reverse('trust:receipt_detail', kwargs={'pk': receipt.pk}))
            except (ValidationError, Exception) as e:
                messages.error(request, str(e))
        return render(request, self.template_name, self.get_context_data(form, ledger))


class ReceiptDetailView(StaffRequiredMixin, DetailView):
    model = Receipt
    template_name = 'trust/receipt_detail.html'
    context_object_name = 'receipt'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('transaction__matter_ledger__trust_account'),
            self.request.user,
            firm_lookup='transaction__matter_ledger__trust_account__firm',
        )


class PaymentCreateView(StaffRequiredMixin, View):
    template_name = 'trust/payment_form.html'

    def get_ledger(self):
        queryset = scope_trust_queryset_for_user(
            MatterLedger.objects.select_related('trust_account', 'matter'),
            self.request.user,
        )
        return get_object_or_404(queryset, pk=self.kwargs['ledger_pk'])

    def get(self, request, ledger_pk):
        form = PaymentForm()
        return render(request, self.template_name, {'form': form, 'ledger': self.get_ledger()})

    def post(self, request, ledger_pk):
        ledger = self.get_ledger()
        form = PaymentForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                payment = services.create_payment(
                    matter_ledger=ledger,
                    amount=cd['amount'],
                    date_paid=cd['date_paid'],
                    payee_name=cd['payee_name'],
                    payee_bsb=cd.get('payee_bsb', ''),
                    payee_account=cd.get('payee_account', ''),
                    payment_method=cd['payment_method'],
                    cheque_number=cd.get('cheque_number', ''),
                    purpose=cd['purpose'],
                    authorised_by=request.user,
                    created_by=request.user,
                )
                messages.success(request, f'Payment #{payment.payment_number} created successfully.')
                return redirect(reverse('trust:payment_detail', kwargs={'pk': payment.pk}))
            except (ValidationError, Exception) as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'ledger': ledger})



class PaymentDetailView(StaffRequiredMixin, DetailView):
    model = Payment
    template_name = 'trust/payment_detail.html'
    context_object_name = 'payment'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related(
                'transaction__matter_ledger__trust_account__firm',
                'transaction__matter_ledger__matter__client',
                'authorised_by',
            ),
            self.request.user,
            firm_lookup='transaction__matter_ledger__trust_account__firm',
        )


class TransferCostsToOfficeCreateView(AdminOrAccountantMixin, View):
    template_name = 'trust/transfer_costs_to_office_form.html'

    def get_ledger(self):
        queryset = scope_trust_queryset_for_user(
            MatterLedger.objects.select_related('trust_account', 'matter'),
            self.request.user,
        )
        return get_object_or_404(queryset, pk=self.kwargs['ledger_pk'])

    def get(self, request, ledger_pk):
        form = TransferCostsToOfficeForm()
        return render(request, self.template_name, {'form': form, 'ledger': self.get_ledger()})

    def post(self, request, ledger_pk):
        ledger = self.get_ledger()
        form = TransferCostsToOfficeForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                payment = services.create_transfer_to_office(
                    matter_ledger=ledger,
                    amount=cd['amount'],
                    date_paid=cd['date_paid'],
                    payee_name=cd['payee_name'],
                    payee_bsb=cd.get('payee_bsb', ''),
                    payee_account=cd.get('payee_account', ''),
                    payment_method=cd['payment_method'],
                    cheque_number=cd.get('cheque_number', ''),
                    purpose=cd['purpose'],
                    authorised_by=request.user,
                    created_by=request.user,
                    costs_withdrawal_method=cd['costs_withdrawal_method'],
                    key_evidence_date=cd.get('key_evidence_date'),
                    costs_evidence_file=cd.get('costs_evidence_file'),
                    notice_or_request_file=cd.get('notice_or_request_file'),
                    authority_or_agreement_file=cd.get('authority_or_agreement_file'),
                    reimbursement_evidence_file=cd.get('reimbursement_evidence_file'),
                    costs_withdrawal_notes=cd.get('costs_withdrawal_notes', ''),
                )
                messages.success(request, f'Transfer to office #{payment.payment_number} created successfully.')
                return redirect(reverse('trust:payment_detail', kwargs={'pk': payment.pk}))
            except (ValidationError, Exception) as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'ledger': ledger})


class TrustJournalCreateView(AdminOrAccountantMixin, View):
    template_name = 'trust/journal_form.html'

    def get_trust_account(self):
        ta_pk = self.request.GET.get('trust_account') or self.request.POST.get('trust_account')
        if ta_pk:
            queryset = scope_trust_queryset_for_user(
                TrustAccount.objects.all(),
                self.request.user,
                firm_lookup='firm',
            )
            return get_object_or_404(queryset, pk=ta_pk)
        return None

    def get(self, request):
        trust_account = self.get_trust_account()
        form = TrustJournalForm(trust_account=trust_account)
        accounts = scope_trust_queryset_for_user(
            TrustAccount.objects.filter(is_active=True),
            request.user,
            firm_lookup='firm',
        )
        return render(request, self.template_name, {'form': form, 'accounts': accounts, 'trust_account': trust_account})

    def post(self, request):
        trust_account = self.get_trust_account()
        form = TrustJournalForm(request.POST, request.FILES, trust_account=trust_account)
        accounts = scope_trust_queryset_for_user(
            TrustAccount.objects.filter(is_active=True),
            request.user,
            firm_lookup='firm',
        )
        if form.is_valid():
            cd = form.cleaned_data
            try:
                journal = services.create_trust_journal(
                    from_ledger=cd['from_ledger'],
                    to_ledger=cd['to_ledger'],
                    amount=cd['amount'],
                    description=cd['description'],
                    written_authority_file=cd['written_authority'],
                    authority_date=cd['authority_date'],
                    authority_signed_by=cd['authority_signed_by'],
                    created_by=request.user,
                )
                messages.success(request, f'Journal #{journal.pk} created successfully.')
                if trust_account:
                    return redirect(reverse('trust:account_detail', kwargs={'pk': trust_account.pk}))
                return redirect(reverse('trust:account_list'))
            except (ValidationError, Exception) as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'accounts': accounts, 'trust_account': trust_account})


class ReverseTransactionView(AdminOrAccountantMixin, View):
    def post(self, request, pk):
        queryset = scope_trust_queryset_for_user(
            TrustTransaction.objects.select_related('matter_ledger__trust_account'),
            request.user,
            firm_lookup='matter_ledger__trust_account__firm',
        )
        txn = get_object_or_404(queryset, pk=pk)
        reason = request.POST.get('reason', 'Manual reversal')
        try:
            services.reverse_transaction(transaction_obj=txn, reason=reason, created_by=request.user)
            messages.success(request, 'Transaction reversed successfully.')
        except (ValidationError, Exception) as e:
            messages.error(request, str(e))
        ledger = txn.matter_ledger
        return redirect(reverse('trust:account_detail', kwargs={'pk': ledger.trust_account_id}))


class DepositRecordListView(AdminOrAccountantMixin, ListView):
    model = DepositRecord
    template_name = 'trust/deposit_record_list.html'
    context_object_name = 'deposit_records'

    def get_queryset(self):
        return (
            scope_trust_queryset_for_user(
                DepositRecord.objects.select_related('trust_account', 'prepared_by'),
                self.request.user,
                firm_lookup='trust_account__firm',
            )
            .order_by('-deposit_date', '-deposit_number')
        )


class DepositRecordCreateView(AdminOrAccountantMixin, FormView):
    form_class = DepositRecordForm
    template_name = 'trust/deposit_record_form.html'

    def get_trust_account(self):
        queryset = scope_trust_queryset_for_user(TrustAccount.objects.all(), self.request.user, firm_lookup='firm')
        return get_object_or_404(queryset, pk=self.kwargs['pk'])

    def get_initial(self):
        initial = super().get_initial()
        deposit_type = self.request.GET.get('type')
        if deposit_type in {'cash', 'cheque'}:
            initial['deposit_type'] = deposit_type
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['trust_account'] = self.get_trust_account()
        kwargs['deposit_type'] = self.request.POST.get('deposit_type') or self.request.GET.get('type')
        return kwargs

    def form_valid(self, form):
        trust_account = self.get_trust_account()
        last = DepositRecord.objects.filter(trust_account=trust_account).order_by('-deposit_number').first()
        next_number = (last.deposit_number + 1) if last else 1

        with transaction.atomic():
            deposit = DepositRecord.objects.create(
                trust_account=trust_account,
                deposit_number=next_number,
                deposit_type=form.cleaned_data['deposit_type'],
                deposit_date=form.cleaned_data['deposit_date'],
                prepared_by=self.request.user,
                notes=form.cleaned_data.get('notes', ''),
            )
            for receipt in form.cleaned_data['receipt_objects']:
                receipt.deposit_record = deposit
                receipt.transaction.date_banked = deposit.deposit_date
                receipt.transaction.save(update_fields=['date_banked'])
                receipt.save(update_fields=['deposit_record'])

        messages.success(self.request, f'{deposit.get_deposit_type_display()} #{deposit.deposit_number} created.')
        return redirect(reverse('trust:deposit_record_detail', kwargs={'pk': deposit.pk}))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        trust_account = self.get_trust_account()
        ctx['trust_account'] = trust_account
        ctx['cash_count'] = Receipt.objects.filter(transaction__matter_ledger__trust_account=trust_account, payment_method='cash', deposit_record__isnull=True).count()
        ctx['cheque_count'] = Receipt.objects.filter(transaction__matter_ledger__trust_account=trust_account, payment_method='cheque', deposit_record__isnull=True).count()
        return ctx


class DepositRecordDetailView(AdminOrAccountantMixin, DetailView):
    model = DepositRecord
    template_name = 'trust/deposit_record_detail.html'
    context_object_name = 'deposit_record'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            DepositRecord.objects.select_related('trust_account', 'prepared_by'),
            self.request.user,
            firm_lookup='trust_account__firm',
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['receipts'] = self.object.receipts.select_related(
            'transaction',
            'transaction__matter_ledger',
            'transaction__matter_ledger__matter',
        ).order_by('receipt_number')
        return ctx


class DepositRecordPDFView(AdminOrAccountantMixin, DetailView):
    model = DepositRecord

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            DepositRecord.objects.select_related('trust_account', 'prepared_by'),
            self.request.user,
            firm_lookup='trust_account__firm',
        )

    def get(self, request, *args, **kwargs):
        deposit_record = self.get_object()
        pdf = trust_reports.deposit_record_pdf_bytes(deposit_record)
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="deposit-record-{deposit_record.deposit_number}.pdf"'
        return response


class ReconciliationListView(StaffRequiredMixin, ListView):
    model = MonthlyReconciliation
    template_name = 'trust/reconciliation_list.html'
    context_object_name = 'reconciliations'
    ordering = ['-period_end']

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'accounting_period', 'finalised_by'),
            self.request.user,
        )



class ReconciliationCreateView(AdminOrAccountantMixin, CreateView):
    model = MonthlyReconciliation
    form_class = ReconciliationForm
    template_name = 'trust/reconciliation_form.html'

    def get_trust_account(self):
        queryset = scope_trust_queryset_for_user(TrustAccount.objects.all(), self.request.user, firm_lookup='firm')
        return get_object_or_404(queryset, pk=self.kwargs['pk'])

    def _last_reconciliation(self, trust_account):
        return (
            MonthlyReconciliation.objects
            .filter(trust_account=trust_account)
            .order_by('-period_end')
            .first()
        )

    def _suggested_period_end(self, trust_account):
        import calendar

        last = self._last_reconciliation(trust_account)
        if last:
            year = last.period_end.year
            month = last.period_end.month + 1
            if month == 13:
                year += 1
                month = 1
            day = calendar.monthrange(year, month)[1]
            return datetime.date(year, month, day)

        today = timezone.localdate()
        first_day_this_month = today.replace(day=1)
        return first_day_this_month - datetime.timedelta(days=1)

    def _balance_preview(self, trust_account, period_end):
        if not period_end:
            return None

        period_start = period_end.replace(day=1)
        opening, receipts, payments, closing = trust_reports._cash_book_amounts_for_period(
            trust_account,
            period_start,
            period_end,
        )
        ledger_balances = trust_reports.calculate_ledger_balances_as_at(trust_account, period_end)
        ledger_total = sum(ledger_balances.values(), Decimal('0.00'))

        return {
            'period_start': period_start,
            'period_end': period_end,
            'opening_balance': opening,
            'receipts_total': receipts,
            'payments_total': payments,
            'cash_book_balance': closing,
            'ledger_total_balance': ledger_total,
            'variance': closing - ledger_total,
        }

    def get_initial(self):
        initial = super().get_initial()
        trust_account = self.get_trust_account()
        initial['period_end'] = self._suggested_period_end(trust_account)
        return initial

    def form_valid(self, form):
        trust_account = self.get_trust_account()
        period_end = form.cleaned_data['period_end']
        period = services.get_or_create_accounting_period(trust_account, period_end)

        if period.status == TrustAccountingPeriod.STATUS_LOCKED:
            form.add_error('period_end', 'This accounting period is locked.')
            return self.form_invalid(form)

        preview = self._balance_preview(trust_account, period_end)

        form.instance.trust_account = trust_account
        form.instance.accounting_period = period
        form.instance.cash_book_balance = preview['cash_book_balance']
        form.instance.ledger_total_balance = preview['ledger_total_balance']

        form.instance.unpresented_cheques_total = Decimal('0.00')
        form.instance.outstanding_deposits_total = Decimal('0.00')

        for field_name in [
            'other_payments_not_in_adi_total',
            'credits_not_in_cash_book_total',
            'debits_not_in_cash_book_total',
        ]:
            if hasattr(form.instance, field_name):
                setattr(form.instance, field_name, Decimal('0.00'))

        messages.success(
            self.request,
            f'Reconciliation started. Matter Funds calculated cash book balance ${preview["cash_book_balance"]} '
            f'and ledger total ${preview["ledger_total_balance"]}. Complete the ADI matching worksheet next.'
        )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('trust:reconciliation_worksheet', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        trust_account = self.get_trust_account()
        suggested_period_end = self.get_initial().get('period_end')
        ctx['trust_account'] = trust_account
        ctx['last_reconciliation'] = self._last_reconciliation(trust_account)
        ctx['balance_preview'] = self._balance_preview(trust_account, suggested_period_end)
        return ctx


class ReconciliationDetailView(StaffRequiredMixin, DetailView):
    model = MonthlyReconciliation
    template_name = 'trust/reconciliation_detail.html'
    context_object_name = 'reconciliation'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'accounting_period', 'finalised_by'),
            self.request.user,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        can_finalise, blockers = services.can_finalise_reconciliation(self.object)
        ctx['can_finalise'] = can_finalise and self.request.user.role in ('admin', 'accountant')
        ctx['finalise_blockers'] = blockers
        ctx['monthly_records'] = self.object.monthly_records.all().order_by('record_type')
        period = self.object.accounting_period
        ctx['accounting_period'] = period
        ctx['can_lock_period'] = (
            period
            and period.status == TrustAccountingPeriod.STATUS_OPEN
            and self.object.is_finalised
            and services.has_all_required_monthly_records(period)
            and self.request.user.role in ('admin', 'accountant')
        )
        return ctx



def _cash_book_direction(txn):
    if txn.transaction_type == 'receipt':
        return 'credit'
    if txn.transaction_type in {'payment', 'transfer_to_office'}:
        return 'debit'
    if txn.transaction_type == 'reversal' and txn.reverses_id:
        if txn.reverses.transaction_type in {'payment', 'transfer_to_office'}:
            return 'credit'
        if txn.reverses.transaction_type == 'receipt':
            return 'debit'
    return None


def _cash_book_match_label(txn):
    matter = txn.matter_ledger.matter
    bits = [
        str(txn.date_received_or_paid),
        txn.get_transaction_type_display(),
        f"${txn.amount}",
        matter.file_number or f"Matter {matter.pk}",
        txn.description,
    ]
    return " | ".join(str(bit) for bit in bits if bit)


def _money_sum(items):
    total = Decimal('0.00')
    for item in items:
        total += item.amount
    return total


class ReconciliationWorksheetView(AdminOrAccountantMixin, TemplateView):
    template_name = 'trust/reconciliation_worksheet.html'

    def get_reconciliation(self):
        queryset = scope_trust_queryset_for_user(
            MonthlyReconciliation.objects.select_related('trust_account', 'accounting_period'),
            self.request.user,
        )
        return get_object_or_404(queryset, pk=self.kwargs['pk'])

    def _period_start(self, reconciliation):
        return reconciliation.period_end.replace(day=1)

    def _internal_transactions(self, reconciliation):
        period_start = self._period_start(reconciliation)
        return (
            TrustTransaction.objects
            .filter(
                matter_ledger__trust_account=reconciliation.trust_account,
                date_received_or_paid__gte=period_start,
                date_received_or_paid__lte=reconciliation.period_end,
                transaction_type__in=['receipt', 'payment', 'transfer_to_office', 'reversal'],
            )
            .select_related(
                'matter_ledger__matter',
                'matter_ledger__matter__client',
                'receipt',
                'payment',
                'reverses',
            )
            .order_by('date_received_or_paid', 'pk')
        )

    def _prior_uncleared_adjustments(self, reconciliation):
        return (
            ReconciliationBankLine.objects
            .filter(
                reconciliation__trust_account=reconciliation.trust_account,
                reconciliation__period_end__lt=reconciliation.period_end,
                carry_forward_until_cleared=True,
                cleared_by_transaction__isnull=True,
            )
            .select_related('reconciliation', 'matched_transaction')
            .order_by('reconciliation__period_end', 'line_date', 'pk')
        )

    def _worksheet_buckets(self, reconciliation, internal_transactions, bank_lines):
        matched_ids = {
            line.matched_transaction_id
            for line in bank_lines
            if line.matched_transaction_id
        }

        credit_transactions = [txn for txn in internal_transactions if _cash_book_direction(txn) == 'credit']
        debit_transactions = [txn for txn in internal_transactions if _cash_book_direction(txn) == 'debit']

        outstanding_deposits = [txn for txn in credit_transactions if txn.pk not in matched_ids]
        unmatched_debits = [txn for txn in debit_transactions if txn.pk not in matched_ids]

        unpresented_cheques = [
            txn for txn in unmatched_debits
            if hasattr(txn, 'payment') and txn.payment.payment_method == 'cheque'
        ]
        other_payments_not_in_adi = [
            txn for txn in unmatched_debits
            if txn not in unpresented_cheques
        ]

        unmatched_bank_credits = [
            line for line in bank_lines
            if line.line_type == ReconciliationBankLine.LINE_TYPE_CREDIT
            and not line.matched_transaction_id
            and not line.cleared_by_transaction_id
        ]
        unmatched_bank_debits = [
            line for line in bank_lines
            if line.line_type == ReconciliationBankLine.LINE_TYPE_DEBIT
            and not line.matched_transaction_id
            and not line.cleared_by_transaction_id
        ]

        return {
            'matched_ids': matched_ids,
            'outstanding_deposits': outstanding_deposits,
            'unpresented_cheques': unpresented_cheques,
            'other_payments_not_in_adi': other_payments_not_in_adi,
            'unmatched_bank_credits': unmatched_bank_credits,
            'unmatched_bank_debits': unmatched_bank_debits,
        }

    def _update_totals_from_worksheet(self, reconciliation):
        internal_transactions = list(self._internal_transactions(reconciliation))
        bank_lines = list(reconciliation.bank_lines.all())
        buckets = self._worksheet_buckets(reconciliation, internal_transactions, bank_lines)

        reconciliation.outstanding_deposits_total = _money_sum(buckets['outstanding_deposits'])
        reconciliation.unpresented_cheques_total = _money_sum(buckets['unpresented_cheques'])
        reconciliation.other_payments_not_in_adi_total = _money_sum(buckets['other_payments_not_in_adi'])
        reconciliation.credits_not_in_cash_book_total = _money_sum(buckets['unmatched_bank_credits'])
        reconciliation.debits_not_in_cash_book_total = _money_sum(buckets['unmatched_bank_debits'])
        reconciliation.save()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        reconciliation = self.get_reconciliation()
        internal_transactions = list(self._internal_transactions(reconciliation))
        bank_lines = list(
            reconciliation.bank_lines
            .select_related(
                'matched_transaction',
                'matched_transaction__matter_ledger__matter',
                'cleared_by_transaction',
                'cleared_by_transaction__matter_ledger__matter',
                'cleared_in_reconciliation',
            )
            .order_by('line_date', 'pk')
        )
        buckets = self._worksheet_buckets(reconciliation, internal_transactions, bank_lines)

        matched_line_by_txn = {
            line.matched_transaction_id: line
            for line in bank_lines
            if line.matched_transaction_id
        }

        cash_book_rows = []
        for txn in internal_transactions:
            direction = _cash_book_direction(txn)
            if not direction:
                continue

            source_ref = f"Txn {txn.pk}"
            source_name = txn.get_transaction_type_display()
            try:
                if txn.transaction_type == 'receipt':
                    source_ref = f"R{txn.receipt.receipt_number}"
                    source_name = "Receipt"
                elif txn.transaction_type in {'payment', 'transfer_to_office'}:
                    source_ref = f"P{txn.payment.payment_number}"
                    source_name = "Payment" if txn.transaction_type == 'payment' else "Transfer to office"
                elif txn.transaction_type == 'reversal' and txn.reverses_id:
                    source_name = "Reversal"
                    source_ref = f"Txn {txn.reverses_id} reversal"
            except Exception:
                pass

            matched_line = matched_line_by_txn.get(txn.pk)
            cash_book_rows.append({
                'id': txn.pk,
                'date': txn.date_received_or_paid,
                'source': source_name,
                'source_ref': source_ref,
                'matter': txn.matter_ledger.matter,
                'description': txn.description,
                'debit': txn.amount if direction == 'debit' else '',
                'credit': txn.amount if direction == 'credit' else '',
                'direction': direction,
                'matched_line': matched_line,
                'status': 'Matched' if matched_line else 'Unmatched',
            })

        outstanding_deposits_total = _money_sum(buckets['outstanding_deposits'])
        unpresented_cheques_total = _money_sum(buckets['unpresented_cheques'])
        other_payments_not_in_adi_total = _money_sum(buckets['other_payments_not_in_adi'])
        credits_not_in_cash_book_total = _money_sum(buckets['unmatched_bank_credits'])
        debits_not_in_cash_book_total = _money_sum(buckets['unmatched_bank_debits'])
        total_adjustments = -credits_not_in_cash_book_total + debits_not_in_cash_book_total
        reconciled_bank_balance_preview = (
            reconciliation.bank_statement_balance
            + outstanding_deposits_total
            - unpresented_cheques_total
            - other_payments_not_in_adi_total
            + total_adjustments
        )
        difference_preview = reconciled_bank_balance_preview - reconciliation.cash_book_balance

        bank_cash_book_difference_preview = reconciliation.bank_statement_balance - reconciliation.cash_book_balance
        recorded_adjustments_total_preview = credits_not_in_cash_book_total - debits_not_in_cash_book_total
        remaining_difference_preview = bank_cash_book_difference_preview - recorded_adjustments_total_preview

        ctx.update({
            'reconciliation': reconciliation,
            'period_start': self._period_start(reconciliation),
            'line_form': ReconciliationBankLineForm(),
            'bank_lines': bank_lines,
            'candidate_transactions': [
                {'id': txn.pk, 'label': _cash_book_match_label(txn), 'direction': _cash_book_direction(txn)}
                for txn in internal_transactions
            ],
            'prior_uncleared_adjustments': list(self._prior_uncleared_adjustments(reconciliation)),
            'cash_book_rows': cash_book_rows,
            'outstanding_deposits_total_preview': outstanding_deposits_total,
            'unpresented_cheques_total_preview': unpresented_cheques_total,
            'other_payments_not_in_adi_total_preview': other_payments_not_in_adi_total,
            'credits_not_in_cash_book_total_preview': credits_not_in_cash_book_total,
            'debits_not_in_cash_book_total_preview': debits_not_in_cash_book_total,
            'total_adjustments_preview': total_adjustments,
            'reconciled_bank_balance_preview': reconciled_bank_balance_preview,
            'difference_preview': difference_preview,
            'bank_cash_book_difference_preview': bank_cash_book_difference_preview,
            'recorded_adjustments_total_preview': recorded_adjustments_total_preview,
            'remaining_difference_preview': remaining_difference_preview,
            'outstanding_deposits': buckets['outstanding_deposits'],
            'unpresented_cheques': buckets['unpresented_cheques'],
            'other_payments_not_in_adi': buckets['other_payments_not_in_adi'],
            'unmatched_bank_credits': buckets['unmatched_bank_credits'],
            'unmatched_bank_debits': buckets['unmatched_bank_debits'],
            'matched_count': len(buckets['matched_ids']),
            'bank_line_count': len(bank_lines),
            'can_edit_worksheet': not reconciliation.is_finalised,
            'adjustment_category_choices': ReconciliationBankLine.ADJUSTMENT_CATEGORY_CHOICES,
        })
        return ctx

    def post(self, request, *args, **kwargs):
        reconciliation = self.get_reconciliation()
        if reconciliation.is_finalised:
            messages.error(request, 'Finalised reconciliations cannot be changed.')
            return redirect(reverse('trust:reconciliation_worksheet', kwargs={'pk': reconciliation.pk}))

        action = request.POST.get('action')

        if action == 'confirm_transaction':
            txn = get_object_or_404(
                self._internal_transactions(reconciliation),
                pk=request.POST.get('transaction_id'),
            )

            direction = _cash_book_direction(txn)
            if direction not in {'credit', 'debit'}:
                messages.error(request, 'Only cash book receipt/payment entries can be confirmed against the bank statement.')
                return redirect(reverse('trust:reconciliation_worksheet', kwargs={'pk': reconciliation.pk}))

            existing = reconciliation.bank_lines.filter(matched_transaction=txn).first()
            if existing:
                messages.info(request, 'This cash book entry is already confirmed on the bank statement.')
                return redirect(reverse('trust:reconciliation_worksheet', kwargs={'pk': reconciliation.pk}))

            ReconciliationBankLine.objects.create(
                reconciliation=reconciliation,
                line_date=request.POST.get('statement_date') or txn.date_received_or_paid,
                line_type=direction,
                amount=txn.amount,
                description=request.POST.get('statement_description') or txn.description,
                reference=request.POST.get('statement_reference', ''),
                adjustment_category=ReconciliationBankLine.ADJUSTMENT_CATEGORY_MATCHED,
                matched_transaction=txn,
                created_by=request.user,
                matched_by=request.user,
                matched_at=timezone.now(),
            )
            self._update_totals_from_worksheet(reconciliation)
            messages.success(request, 'Cash book entry confirmed on authorised ADI bank statement.')
            return redirect(reverse('trust:reconciliation_worksheet', kwargs={'pk': reconciliation.pk}))

        if action == 'add_line':
            form = ReconciliationBankLineForm(request.POST)
            if form.is_valid():
                line = form.save(commit=False)
                line.reconciliation = reconciliation
                line.created_by = request.user
                if not line.adjustment_category:
                    line.adjustment_category = ReconciliationBankLine.ADJUSTMENT_CATEGORY_OTHER
                line.carry_forward_until_cleared = True
                try:
                    line.save()
                except ValidationError as exc:
                    messages.error(request, exc.messages[0] if hasattr(exc, 'messages') and exc.messages else exc)
                    return redirect(reverse('trust:reconciliation_worksheet', kwargs={'pk': reconciliation.pk}))
                self._update_totals_from_worksheet(reconciliation)
                messages.success(request, 'Reconciliation adjustment recorded.')
            else:
                messages.error(request, form.errors.as_text())

        elif action == 'match_line':
            line = get_object_or_404(reconciliation.bank_lines.all(), pk=request.POST.get('line_id'))
            txn_id = request.POST.get('matched_transaction') or None
            line.notes = request.POST.get('notes', '')
            line.adjustment_category = request.POST.get('adjustment_category', '')
            line.carry_forward_until_cleared = bool(request.POST.get('carry_forward_until_cleared'))

            if txn_id:
                txn = get_object_or_404(self._internal_transactions(reconciliation), pk=txn_id)
                expected_direction = _cash_book_direction(txn)
                if expected_direction != line.line_type:
                    messages.error(request, 'Bank line type does not match the selected cash book transaction direction.')
                    return redirect(reverse('trust:reconciliation_worksheet', kwargs={'pk': reconciliation.pk}))
                line.matched_transaction = txn
                line.matched_by = request.user
                line.matched_at = timezone.now()
                line.adjustment_category = ReconciliationBankLine.ADJUSTMENT_CATEGORY_MATCHED
                line.carry_forward_until_cleared = False
                messages.success(request, 'Bank line matched to cash book transaction.')
            else:
                line.matched_transaction = None
                line.matched_by = None
                line.matched_at = None
                messages.success(request, 'Bank line saved as unmatched / adjustment item.')

            line.save()

        elif action == 'clear_adjustment':
            line = get_object_or_404(
                self._prior_uncleared_adjustments(reconciliation),
                pk=request.POST.get('line_id'),
            )
            txn = get_object_or_404(
                self._internal_transactions(reconciliation),
                pk=request.POST.get('cleared_by_transaction'),
            )
            line.cleared_by_transaction = txn
            line.cleared_in_reconciliation = reconciliation
            line.cleared_by = request.user
            line.cleared_at = timezone.now()
            line.cleared_notes = request.POST.get('cleared_notes', '')
            line.save()
            messages.success(request, 'Prior reconciliation adjustment cleared by this period transaction.')

        elif action == 'update_totals':
            self._update_totals_from_worksheet(reconciliation)
            messages.success(request, 'Reconciliation adjustment totals updated from worksheet.')

        elif action == 'delete_line':
            line = get_object_or_404(reconciliation.bank_lines.all(), pk=request.POST.get('line_id'))
            line.delete()
            self._update_totals_from_worksheet(reconciliation)
            messages.success(request, 'Reconciliation adjustment removed.')

        else:
            messages.error(request, 'Unknown worksheet action.')

        return redirect(reverse('trust:reconciliation_worksheet', kwargs={'pk': reconciliation.pk}))



class ReconciliationBankStatementView(AdminOrAccountantMixin, UpdateView):
    model = MonthlyReconciliation
    form_class = ReconciliationBankStatementForm
    template_name = 'trust/reconciliation_bank_statement_form.html'
    context_object_name = 'reconciliation'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'accounting_period', 'finalised_by'),
            self.request.user,
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get('download'):
            if not self.object.bank_statement_pdf:
                raise Http404('Bank statement PDF not found.')
            return FileResponse(
                self.object.bank_statement_pdf.open('rb'),
                as_attachment=True,
                filename=self.object.bank_statement_pdf.name.split('/')[-1],
            )
        if self.object.is_finalised:
            messages.warning(request, 'Finalised reconciliations cannot have bank statement evidence replaced.')
            return redirect(self.get_success_url())
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.is_finalised:
            messages.error(request, 'Finalised reconciliations cannot have bank statement evidence replaced.')
            return redirect(self.get_success_url())
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, 'Bank statement evidence saved.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('trust:reconciliation_detail', kwargs={'pk': self.object.pk})


class ReconciliationFinaliseView(AdminOrAccountantMixin, FormView):
    form_class = ReconciliationFinaliseForm
    template_name = 'trust/reconciliation_finalise.html'

    def get_reconciliation(self):
        queryset = scope_trust_queryset_for_user(
            MonthlyReconciliation.objects.select_related('trust_account', 'accounting_period'),
            self.request.user,
        )
        return get_object_or_404(queryset, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        reconciliation = self.get_reconciliation()
        ctx['reconciliation'] = reconciliation
        ctx['can_finalise'], ctx['finalise_blockers'] = services.can_finalise_reconciliation(reconciliation)
        return ctx

    def form_valid(self, form):
        reconciliation = self.get_reconciliation()
        try:
            services.finalise_reconciliation(reconciliation, self.request.user)
            messages.success(self.request, 'Reconciliation finalised and monthly records generated.')
            return redirect(reverse('trust:reconciliation_detail', kwargs={'pk': reconciliation.pk}))
        except ValidationError as e:
            form.add_error(None, e)
            return self.form_invalid(form)


class AccountingPeriodListView(StaffRequiredMixin, ListView):
    model = TrustAccountingPeriod
    template_name = 'trust/period_list.html'
    context_object_name = 'periods'
    ordering = ['-period_end']

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'locked_by'),
            self.request.user,
        )


class AccountingPeriodDetailView(StaffRequiredMixin, DetailView):
    model = TrustAccountingPeriod
    template_name = 'trust/period_detail.html'
    context_object_name = 'period'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'locked_by').prefetch_related('monthly_records'),
            self.request.user,
        )


class AccountingPeriodLockView(AdminOrAccountantMixin, FormView):
    form_class = AccountingPeriodLockForm
    template_name = 'trust/period_lock.html'

    def get_period(self):
        queryset = scope_trust_queryset_for_user(
            TrustAccountingPeriod.objects.select_related('trust_account'),
            self.request.user,
        )
        return get_object_or_404(queryset, pk=self.kwargs['pk'])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['period'] = self.get_period()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['period'] = self.get_period()
        return ctx

    def form_valid(self, form):
        period = self.get_period()
        try:
            services.lock_accounting_period(period, self.request.user)
            messages.success(self.request, 'Accounting period locked.')
            return redirect(reverse('trust:period_detail', kwargs={'pk': period.pk}))
        except ValidationError as e:
            form.add_error(None, e)
            return self.form_invalid(form)


class MonthlyRecordListView(StaffRequiredMixin, ListView):
    model = TrustMonthlyRecord
    template_name = 'trust/monthly_record_list.html'
    context_object_name = 'monthly_records'
    ordering = ['-generated_at']

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'accounting_period', 'generated_by'),
            self.request.user,
        )


class MonthlyRecordDetailView(StaffRequiredMixin, DetailView):
    model = TrustMonthlyRecord
    template_name = 'trust/monthly_record_detail.html'
    context_object_name = 'monthly_record'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'accounting_period', 'generated_by'),
            self.request.user,
        )


class MonthlyRecordDownloadView(StaffRequiredMixin, View):
    def get(self, request, pk):
        queryset = scope_trust_queryset_for_user(
            TrustMonthlyRecord.objects.select_related('trust_account', 'accounting_period'),
            request.user,
        )
        record = get_object_or_404(queryset, pk=pk)
        if not record.pdf:
            raise Http404('Monthly record PDF not found.')
        filename = f'{record.record_type}_{record.accounting_period.period_end}.pdf'
        return FileResponse(record.pdf.open('rb'), as_attachment=True, filename=filename, content_type='application/pdf')


class IrregularityListView(StaffRequiredMixin, ListView):
    model = Irregularity
    template_name = 'trust/irregularity_list.html'
    context_object_name = 'irregularities'
    ordering = ['-discovered_on']

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account'),
            self.request.user,
        )


class IrregularityCreateView(AdminOrAccountantMixin, CreateView):
    model = Irregularity
    form_class = ManualIrregularityForm
    template_name = 'trust/irregularity_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Irregularity created successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('trust:irregularity_detail', kwargs={'pk': self.object.pk})


class IrregularityDetailView(StaffRequiredMixin, View):
    template_name = 'trust/irregularity_detail.html'

    def get_irregularity(self, pk):
        queryset = scope_trust_queryset_for_user(
            Irregularity.objects.select_related('trust_account'),
            self.request.user,
        )
        return get_object_or_404(queryset, pk=pk)

    def get(self, request, pk):
        irr = self.get_irregularity(pk)
        can_resolve = request.user.role in ('admin', 'accountant')
        form = IrregularityResolveForm(instance=irr) if can_resolve else None
        return render(request, self.template_name, {'irregularity': irr, 'form': form, 'can_resolve': can_resolve})

    def post(self, request, pk):
        irr = self.get_irregularity(pk)
        can_resolve = request.user.role in ('admin', 'accountant')
        if not can_resolve:
            messages.error(request, 'You do not have permission to resolve irregularities.')
            return redirect(reverse('trust:irregularity_detail', kwargs={'pk': pk}))
        form = IrregularityResolveForm(request.POST, request.FILES, instance=irr)
        if form.is_valid():
            form.save()
            messages.success(request, 'Irregularity updated.')
            return redirect(reverse('trust:irregularity_list'))
        return render(request, self.template_name, {'irregularity': irr, 'form': form, 'can_resolve': can_resolve})

def build_reports_context(request, trial_balance_account_id=None, trial_balance_as_at='', trial_balance_error=''):
    accounts = list(scope_trust_queryset_for_user(
        TrustAccount.objects.filter(is_active=True),
        request.user,
        firm_lookup='firm',
    ))
    for account in accounts:
        account.trial_balance_as_at_value = ''
        account.trial_balance_error = ''
        if account.pk == trial_balance_account_id:
            account.trial_balance_as_at_value = trial_balance_as_at
            account.trial_balance_error = trial_balance_error
    return {
        'accounts': accounts,
        'date_form': DateRangeForm(),
        'year_form': YearForm(),
    }


class ReportsLandingView(StaffRequiredMixin, TemplateView):
    template_name = 'trust/reports.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(build_reports_context(self.request))
        return ctx


class ReceiptsJournalPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(
            scope_trust_queryset_for_user(TrustAccount.objects.all(), request.user, firm_lookup='firm'),
            pk=pk,
        )
        form = DateRangeForm(request.GET)
        if form.is_valid():
            date_from = form.cleaned_data.get('date_from') or datetime.date(datetime.date.today().year, 1, 1)
            date_to = form.cleaned_data.get('date_to') or datetime.date.today()
        else:
            date_from = datetime.date(datetime.date.today().year, 1, 1)
            date_to = datetime.date.today()
        return trust_reports.receipts_journal_pdf(account, date_from, date_to)


class PaymentsJournalPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(
            scope_trust_queryset_for_user(TrustAccount.objects.all(), request.user, firm_lookup='firm'),
            pk=pk,
        )
        form = DateRangeForm(request.GET)
        if form.is_valid():
            date_from = form.cleaned_data.get('date_from') or datetime.date(datetime.date.today().year, 1, 1)
            date_to = form.cleaned_data.get('date_to') or datetime.date.today()
        else:
            date_from = datetime.date(datetime.date.today().year, 1, 1)
            date_to = datetime.date.today()
        return trust_reports.payments_journal_pdf(account, date_from, date_to)



class TrustCashBookSummaryPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(
            scope_trust_queryset_for_user(TrustAccount.objects.all(), request.user, firm_lookup='firm'),
            pk=pk,
        )
        form = DateRangeForm(request.GET)
        if form.is_valid():
            date_from = form.cleaned_data.get('date_from') or datetime.date(datetime.date.today().year, 1, 1)
            date_to = form.cleaned_data.get('date_to') or datetime.date.today()
        else:
            date_from = datetime.date(datetime.date.today().year, 1, 1)
            date_to = datetime.date.today()
        return trust_reports.trust_cash_book_summary_pdf(account, date_from, date_to)


class TrustTransferJournalPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(
            scope_trust_queryset_for_user(TrustAccount.objects.all(), request.user, firm_lookup='firm'),
            pk=pk,
        )
        form = DateRangeForm(request.GET)
        if form.is_valid():
            date_from = form.cleaned_data.get('date_from') or datetime.date(datetime.date.today().year, 1, 1)
            date_to = form.cleaned_data.get('date_to') or datetime.date.today()
        else:
            date_from = datetime.date(datetime.date.today().year, 1, 1)
            date_to = datetime.date.today()
        return trust_reports.trust_transfer_journal_pdf(account, date_from, date_to)


class TrialBalancePDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(
            scope_trust_queryset_for_user(TrustAccount.objects.all(), request.user, firm_lookup='firm'),
            pk=pk,
        )
        as_at_param = request.GET.get('as_at')
        if as_at_param:
            as_at = parse_date(as_at_param)
            if as_at is None:
                return HttpResponseBadRequest('Invalid as_at date. Use YYYY-MM-DD.')
        else:
            as_at = timezone.localdate()
        if as_at > timezone.localdate():
            context = build_reports_context(
                request,
                trial_balance_account_id=account.pk,
                trial_balance_as_at=as_at_param or as_at.isoformat(),
                trial_balance_error='As at date cannot be in the future.',
            )
            return render(request, 'trust/reports.html', context, status=400)
        return trust_reports.trust_trial_balance_pdf(account, as_at)


class ExaminerPackZipView(AdminOrAccountantMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(
            scope_trust_queryset_for_user(TrustAccount.objects.all(), request.user, firm_lookup='firm'),
            pk=pk,
        )
        form = YearForm(request.GET)
        if form.is_valid():
            year = form.cleaned_data['year']
        else:
            year = datetime.date.today().year
        return trust_reports.external_examiner_pack_zip(account, year)


class TrustRecordsExportPackZipView(AdminOrAccountantMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(
            scope_trust_queryset_for_user(TrustAccount.objects.all(), request.user, firm_lookup='firm'),
            pk=pk,
        )
        date_from = parse_date(request.GET.get('date_from') or '') if request.GET.get('date_from') else None
        date_to = parse_date(request.GET.get('date_to') or '') if request.GET.get('date_to') else None
        year = None
        if request.GET.get('year'):
            try:
                year = int(request.GET['year'])
            except ValueError:
                return HttpResponseBadRequest('Invalid year.')
        return trust_reports.trust_records_export_pack_zip(
            account,
            date_from=date_from,
            date_to=date_to,
            year=year,
            all_data=request.GET.get('all') in {'1', 'true', 'yes'},
            include_technical=request.GET.get('include_technical') in {'1', 'true', 'yes'},
        )


class LedgerStatementPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        ledger = get_object_or_404(
            scope_trust_queryset_for_user(MatterLedger.objects.select_related('trust_account'), request.user),
            pk=pk,
        )
        return trust_reports.matter_ledger_statement_pdf(ledger)


class TrustAccountStatementPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        ledger = get_object_or_404(
            scope_trust_queryset_for_user(
                MatterLedger.objects.select_related('trust_account__firm', 'matter__client'),
                request.user,
            ),
            pk=pk,
        )
        date_from = parse_date(request.GET.get('date_from') or '') if request.GET.get('date_from') else None
        date_to = parse_date(request.GET.get('date_to') or '') if request.GET.get('date_to') else None
        return trust_reports.trust_account_statement_pdf(ledger, date_from, date_to)


class ReconciliationPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        recon = get_object_or_404(
            scope_trust_queryset_for_user(MonthlyReconciliation.objects.select_related('trust_account'), request.user),
            pk=pk,
        )
        return trust_reports.monthly_reconciliation_pdf(recon)


class ReceiptPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        receipt = get_object_or_404(
            scope_trust_queryset_for_user(
                Receipt.objects.select_related('transaction__matter_ledger__trust_account'),
                request.user,
                firm_lookup='transaction__matter_ledger__trust_account__firm',
            ),
            pk=pk,
        )
        return trust_reports.receipt_pdf(receipt)


class PaymentPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        payment = get_object_or_404(
            scope_trust_queryset_for_user(
                Payment.objects.select_related(
                    'transaction__matter_ledger__trust_account__firm',
                    'transaction__matter_ledger__matter__client',
                    'authorised_by',
                ),
                request.user,
                firm_lookup='transaction__matter_ledger__trust_account__firm',
            ),
            pk=pk,
        )
        return trust_reports.payment_pdf(payment)



class TrustJournalDetailView(StaffRequiredMixin, DetailView):
    model = TrustJournal
    template_name = 'trust/journal_detail.html'
    context_object_name = 'journal'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related(
                'from_ledger__trust_account__firm',
                'from_ledger__matter__client',
                'to_ledger__matter__client',
                'created_by',
                'journal_out_txn',
                'journal_in_txn',
            ),
            self.request.user,
            firm_lookup='from_ledger__trust_account__firm',
        )


class TrustJournalPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        journal = get_object_or_404(
            scope_trust_queryset_for_user(
                TrustJournal.objects.select_related(
                    'from_ledger__trust_account__firm',
                    'from_ledger__matter__client',
                    'to_ledger__matter__client',
                    'created_by',
                    'journal_out_txn',
                    'journal_in_txn',
                ),
                request.user,
                firm_lookup='from_ledger__trust_account__firm',
            ),
            pk=pk,
        )
        return trust_reports.trust_journal_pdf(journal)


class ControlledMoneyAccountListView(AdminOrAccountantMixin, ListView):
    model = ControlledMoneyAccount
    template_name = 'trust/controlled_money/account_list.html'
    context_object_name = 'accounts'
    def get_queryset(self):
        return scope_trust_queryset_for_user(ControlledMoneyAccount.objects.select_related('firm','client','matter'), self.request.user, firm_lookup='firm').order_by('account_name')

class ControlledMoneyAccountCreateView(AdminOrAccountantMixin, CreateView):
    model = ControlledMoneyAccount
    form_class = ControlledMoneyAccountForm
    template_name = 'trust/controlled_money/form.html'
    def get_form_kwargs(self):
        kw=super().get_form_kwargs(); kw['user']=self.request.user; return kw
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form_title'] = 'New Controlled Money Account'
        return ctx
    def get_success_url(self): return reverse('trust:controlled_money_detail', kwargs={'pk': self.object.pk})

class ControlledMoneyAccountDetailView(AdminOrAccountantMixin, DetailView):
    model = ControlledMoneyAccount
    template_name = 'trust/controlled_money/detail.html'
    context_object_name = 'account'
    def get_queryset(self):
        return scope_trust_queryset_for_user(ControlledMoneyAccount.objects.select_related('firm','client','matter'), self.request.user, firm_lookup='firm')
    def get_context_data(self, **kwargs):
        ctx=super().get_context_data(**kwargs); a=self.object
        receipts=list(a.receipts.order_by('date_made_out','receipt_number')); withdrawals=list(a.withdrawals.order_by('date','created_at'))
        movements=[]
        for r in receipts: movements.append((r.date_money_received or r.date_made_out, f'Receipt #{r.receipt_number}', r.amount, None, r.reason))
        for w in withdrawals: movements.append((w.date, f'Withdrawal {w.transaction_number}', None, w.amount, w.reason))
        bal=0; rows=[]
        for d,label,credit,debit,reason in sorted(movements, key=lambda x:(x[0], x[1])):
            bal += credit or 0; bal -= debit or 0; rows.append({'date':d,'label':label,'credit':credit,'debit':debit,'balance':bal,'reason':reason})
        ctx.update(receipts=receipts, withdrawals=withdrawals, movements=rows, documents=a.supporting_documents.all())
        return ctx

class ControlledMoneyReceiptCreateView(AdminOrAccountantMixin, CreateView):
    model = ControlledMoneyReceipt; form_class = ControlledMoneyReceiptForm; template_name='trust/controlled_money/form.html'
    def get_form_kwargs(self): kw=super().get_form_kwargs(); kw['user']=self.request.user; return kw
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form_title'] = 'New Controlled Money Receipt'
        return ctx
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Controlled Money Receipt #{self.object.receipt_number} created. Download the PDF from the register below.')
        return response
    def get_success_url(self):
        return reverse('trust:controlled_money_detail', kwargs={'pk': self.object.controlled_money_account_id})

class ControlledMoneyWithdrawalCreateView(AdminOrAccountantMixin, CreateView):
    model = ControlledMoneyWithdrawal; form_class = ControlledMoneyWithdrawalForm; template_name='trust/controlled_money/form.html'
    def get_form_kwargs(self): kw=super().get_form_kwargs(); kw['user']=self.request.user; return kw
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form_title'] = 'New Controlled Money Withdrawal'
        return ctx
    def get_success_url(self): return reverse('trust:controlled_money_detail', kwargs={'pk': self.object.controlled_money_account_id})

class ControlledMoneyReceiptPDFView(AdminOrAccountantMixin, View):
    def get(self, request, pk):
        receipt=get_object_or_404(scope_trust_queryset_for_user(ControlledMoneyReceipt.objects.select_related('firm','controlled_money_account','made_out_by'), request.user, firm_lookup='firm'), pk=pk)
        return trust_reports._pdf_response_from_bytes(f'controlled_money_receipt_{receipt.receipt_number}.pdf', trust_reports.controlled_money_receipt_pdf_bytes(receipt))

class ControlledMoneyMonthlyStatementListView(AdminOrAccountantMixin, ListView):
    model=ControlledMoneyMonthlyStatement; template_name='trust/controlled_money/statements.html'; context_object_name='statements'
    def get_queryset(self): return scope_trust_queryset_for_user(ControlledMoneyMonthlyStatement.objects.select_related('firm','reviewed_by'), self.request.user, firm_lookup='firm').order_by('-period_end')
    def get_context_data(self, **kwargs): ctx=super().get_context_data(**kwargs); ctx['form']=ControlledMoneyMonthlyStatementForm(); return ctx
    def post(self, request):
        form=ControlledMoneyMonthlyStatementForm(request.POST)
        if form.is_valid():
            st,created=ControlledMoneyMonthlyStatement.objects.get_or_create(firm=request.user.firm, period_end=form.cleaned_data['period_end'], defaults={'prepared_on': timezone.localdate()})
            trust_reports.ensure_controlled_money_monthly_statement_pdf(st)
            return redirect('trust:controlled_money_statement_detail', pk=st.pk)
        return render(request, self.template_name, {'form':form, 'statements': self.get_queryset()})

class ControlledMoneyMonthlyStatementDetailView(AdminOrAccountantMixin, DetailView):
    model=ControlledMoneyMonthlyStatement; template_name='trust/controlled_money/statement_detail.html'; context_object_name='statement'
    def get_queryset(self): return scope_trust_queryset_for_user(ControlledMoneyMonthlyStatement.objects.select_related('firm','reviewed_by'), self.request.user, firm_lookup='firm')
    def get_context_data(self, **kwargs):
        ctx=super().get_context_data(**kwargs); ctx['accounts']=ControlledMoneyAccount.objects.filter(firm=self.object.firm, opened_on__lte=self.object.period_end).filter(Q(closed_on__isnull=True)|Q(closed_on__gte=self.object.period_end)).order_by('account_name'); ctx['review_form']=ControlledMoneyPrincipalReviewForm(instance=self.object); return ctx
    def post(self, request, pk):
        self.object=self.get_object(); form=ControlledMoneyPrincipalReviewForm(request.POST, instance=self.object)
        if form.is_valid():
            st=form.save(commit=False); st.reviewed_by=request.user; st.reviewed_on=timezone.localdate(); st.pdf.delete(save=False); st.save(); trust_reports.ensure_controlled_money_monthly_statement_pdf(st); return redirect('trust:controlled_money_statement_detail', pk=st.pk)
        return render(request, self.template_name, self.get_context_data(review_form=form))

class ControlledMoneyMonthlyStatementPDFView(AdminOrAccountantMixin, View):
    def get(self, request, pk):
        st=get_object_or_404(scope_trust_queryset_for_user(ControlledMoneyMonthlyStatement.objects.select_related('firm'), request.user, firm_lookup='firm'), pk=pk)
        return trust_reports._pdf_response_from_bytes(f'controlled_money_statement_{st.period_end}.pdf', trust_reports.ensure_controlled_money_monthly_statement_pdf(st))


class ReversalDetailView(StaffRequiredMixin, DetailView):
    model = TrustTransaction
    template_name = 'trust/reversal_detail.html'
    context_object_name = 'reversal'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset()
            .filter(transaction_type='reversal')
            .select_related(
                'matter_ledger__trust_account__firm',
                'matter_ledger__matter__client',
                'created_by',
                'reverses',
                'reverses__matter_ledger__matter__client',
                'reverses__receipt',
                'reverses__payment',
            ),
            self.request.user,
            firm_lookup='matter_ledger__trust_account__firm',
        )


class ReversalPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        reversal = get_object_or_404(
            scope_trust_queryset_for_user(
                TrustTransaction.objects
                .filter(transaction_type='reversal')
                .select_related(
                    'matter_ledger__trust_account__firm',
                    'matter_ledger__matter__client',
                    'created_by',
                    'reverses',
                    'reverses__matter_ledger__matter__client',
                    'reverses__receipt',
                    'reverses__payment',
                ),
                request.user,
                firm_lookup='matter_ledger__trust_account__firm',
            ),
            pk=pk,
        )
        return trust_reports.reversal_pdf(reversal)
