import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView, FormView

from apps.accounts.permissions import StaffRequiredMixin, AdminOrAccountantMixin
from apps.trust import services
from apps.trust import reports as trust_reports
from .models import (
    TrustAccount, MatterLedger, TrustTransaction, Receipt, Payment,
    MonthlyReconciliation, Irregularity,
)
from .forms import (
    ReceiptForm, PaymentForm, TrustJournalForm, ReconciliationForm,
    IrregularityResolveForm, DateRangeForm, YearForm,
)


class TrustAccountListView(StaffRequiredMixin, ListView):
    model = TrustAccount
    template_name = 'trust/account_list.html'
    context_object_name = 'accounts'

    def get_queryset(self):
        qs = super().get_queryset().select_related('firm')
        user = self.request.user
        if user.role != 'admin' and user.firm:
            qs = qs.filter(firm=user.firm)
        return qs


class TrustAccountDetailView(StaffRequiredMixin, DetailView):
    model = TrustAccount
    template_name = 'trust/account_detail.html'
    context_object_name = 'account'

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
        return get_object_or_404(MatterLedger, pk=self.kwargs['ledger_pk'])

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


class PaymentCreateView(StaffRequiredMixin, View):
    template_name = 'trust/payment_form.html'

    def get_ledger(self):
        return get_object_or_404(MatterLedger, pk=self.kwargs['ledger_pk'])

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
                    second_authoriser=cd.get('second_authoriser'),
                    created_by=request.user,
                )
                messages.success(request, f'Payment #{payment.payment_number} created successfully.')
                return redirect(reverse('trust:account_detail', kwargs={'pk': ledger.trust_account_id}))
            except (ValidationError, Exception) as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'ledger': ledger})


class TrustJournalCreateView(AdminOrAccountantMixin, View):
    template_name = 'trust/journal_form.html'

    def get_trust_account(self):
        ta_pk = self.request.GET.get('trust_account') or self.request.POST.get('trust_account')
        if ta_pk:
            return get_object_or_404(TrustAccount, pk=ta_pk)
        return None

    def get(self, request):
        trust_account = self.get_trust_account()
        form = TrustJournalForm(trust_account=trust_account)
        accounts = TrustAccount.objects.filter(is_active=True)
        return render(request, self.template_name, {'form': form, 'accounts': accounts, 'trust_account': trust_account})

    def post(self, request):
        trust_account = self.get_trust_account()
        form = TrustJournalForm(request.POST, request.FILES, trust_account=trust_account)
        accounts = TrustAccount.objects.filter(is_active=True)
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
        txn = get_object_or_404(TrustTransaction, pk=pk)
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
        qs = super().get_queryset().select_related('trust_account')
        user = self.request.user
        if user.role != 'admin' and user.firm:
            qs = qs.filter(trust_account__firm=user.firm)
        return qs


class ReconciliationCreateView(AdminOrAccountantMixin, CreateView):
    model = MonthlyReconciliation
    form_class = ReconciliationForm
    template_name = 'trust/reconciliation_form.html'

    def get_trust_account(self):
        return get_object_or_404(TrustAccount, pk=self.kwargs['pk'])

    def form_valid(self, form):
        form.instance.trust_account = self.get_trust_account()
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


class IrregularityListView(StaffRequiredMixin, ListView):
    model = Irregularity
    template_name = 'trust/irregularity_list.html'
    context_object_name = 'irregularities'
    ordering = ['-discovered_on']

    def get_queryset(self):
        qs = super().get_queryset().select_related('trust_account')
        user = self.request.user
        if user.role != 'admin' and user.firm:
            qs = qs.filter(trust_account__firm=user.firm)
        return qs


class IrregularityDetailView(StaffRequiredMixin, View):
    template_name = 'trust/irregularity_detail.html'

    def get_irregularity(self, pk):
        return get_object_or_404(Irregularity, pk=pk)

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
        ctx['accounts'] = TrustAccount.objects.filter(is_active=True)
        ctx['date_form'] = DateRangeForm()
        ctx['year_form'] = YearForm()
        return ctx


class ReceiptsJournalPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(TrustAccount, pk=pk)
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
        account = get_object_or_404(TrustAccount, pk=pk)
        form = DateRangeForm(request.GET)
        if form.is_valid():
            date_from = form.cleaned_data.get('date_from') or datetime.date(datetime.date.today().year, 1, 1)
            date_to = form.cleaned_data.get('date_to') or datetime.date.today()
        else:
            date_from = datetime.date(datetime.date.today().year, 1, 1)
            date_to = datetime.date.today()
        return trust_reports.payments_journal_pdf(account, date_from, date_to)


class TrialBalancePDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(TrustAccount, pk=pk)
        as_at = datetime.date.today()
        return trust_reports.trust_trial_balance_pdf(account, as_at)


class ExaminerPackZipView(AdminOrAccountantMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(TrustAccount, pk=pk)
        form = YearForm(request.GET)
        if form.is_valid():
            year = form.cleaned_data['year']
        else:
            year = datetime.date.today().year
        return trust_reports.external_examiner_pack_zip(account, year)


class LedgerStatementPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        ledger = get_object_or_404(MatterLedger, pk=pk)
        return trust_reports.matter_ledger_statement_pdf(ledger)


class ReconciliationPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        recon = get_object_or_404(MonthlyReconciliation, pk=pk)
        return trust_reports.monthly_reconciliation_pdf(recon)


class ReceiptPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        receipt = get_object_or_404(Receipt, pk=pk)
        return trust_reports.receipt_pdf(receipt)
