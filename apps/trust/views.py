import datetime
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
    MonthlyReconciliation, Irregularity, TrustAccountingPeriod, TrustMonthlyRecord,
    ControlledMoneyAccount, ControlledMoneyReceipt, ControlledMoneyWithdrawal, ControlledMoneyMonthlyStatement,
)
from .forms import (
    TrustAccountUpdateForm, ReceiptForm, PaymentForm, TransferCostsToOfficeForm, TrustJournalForm, ReconciliationForm,
    ManualIrregularityForm, IrregularityResolveForm, DateRangeForm, YearForm,
    ReconciliationFinaliseForm, AccountingPeriodLockForm, ReconciliationBankStatementForm,
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

    def form_valid(self, form):
        trust_account = self.get_trust_account()
        period = services.get_or_create_accounting_period(trust_account, form.cleaned_data['period_end'])
        if period.status == TrustAccountingPeriod.STATUS_LOCKED:
            form.add_error('period_end', 'This accounting period is locked.')
            return self.form_invalid(form)
        form.instance.trust_account = trust_account
        form.instance.accounting_period = period
        messages.success(self.request, 'Reconciliation saved.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('trust:reconciliation_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['trust_account'] = self.get_trust_account()
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
