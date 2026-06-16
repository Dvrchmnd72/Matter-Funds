import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView, FormView

from apps.accounts.permissions import StaffRequiredMixin, AdminOrAccountantMixin
from apps.trust import services
from apps.trust import reports as trust_reports
from .models import (
    TrustAccount, MatterLedger, TrustTransaction, Receipt, Payment,
    MonthlyReconciliation, Irregularity, TrustAccountingPeriod, TrustMonthlyRecord,
)
from .forms import (
    ReceiptForm, PaymentForm, TransferCostsToOfficeForm, TrustJournalForm, ReconciliationForm,
    ManualIrregularityForm, IrregularityResolveForm, DateRangeForm, YearForm,
    ReconciliationFinaliseForm, AccountingPeriodLockForm, ReconciliationBankStatementForm,
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
        ctx['ledgers'] = self.object.ledgers.select_related('matter').order_by('matter__file_number')
        ctx['recent_transactions'] = (
            TrustTransaction.objects
            .filter(matter_ledger__trust_account=self.object)
            .select_related('matter_ledger__matter')
            .order_by('-created_at')[:20]
        )
        return ctx


class ReceiptCreateView(StaffRequiredMixin, View):
    template_name = 'trust/receipt_form.html'

    def get_ledger(self):
        queryset = scope_trust_queryset_for_user(
            MatterLedger.objects.select_related('trust_account', 'matter'),
            self.request.user,
        )
        return get_object_or_404(queryset, pk=self.kwargs['ledger_pk'])

    def get(self, request, ledger_pk):
        form = ReceiptForm()
        return render(request, self.template_name, {'form': form, 'ledger': self.get_ledger()})

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
        return render(request, self.template_name, {'form': form, 'ledger': ledger})


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
                return redirect(reverse('trust:account_detail', kwargs={'pk': ledger.trust_account_id}))
            except (ValidationError, Exception) as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'ledger': ledger})


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
                return redirect(reverse('trust:account_detail', kwargs={'pk': ledger.trust_account_id}))
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

class ReportsLandingView(StaffRequiredMixin, TemplateView):
    template_name = 'trust/reports.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['accounts'] = scope_trust_queryset_for_user(
            TrustAccount.objects.filter(is_active=True),
            self.request.user,
            firm_lookup='firm',
        )
        ctx['date_form'] = DateRangeForm()
        ctx['year_form'] = YearForm()
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
        as_at = datetime.date.today()
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


class LedgerStatementPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        ledger = get_object_or_404(
            scope_trust_queryset_for_user(MatterLedger.objects.select_related('trust_account'), request.user),
            pk=pk,
        )
        return trust_reports.matter_ledger_statement_pdf(ledger)


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
