import datetime
from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Count
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from apps.trust.compliance import ComplianceService
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView, FormView

from apps.accounts.permissions import StaffRequiredMixin, AdminOrAccountantMixin
from apps.trust import services
from apps.trust import reports as trust_reports
from .models import (
    Section19ComplianceReview,
    ComplianceReviewLog,
    TrustAccount, MatterLedger, TrustTransaction, Receipt, Payment, TrustJournal,
    MonthlyReconciliation, DepositRecord, ReconciliationBankLine, Irregularity, TrustAccountingPeriod, TrustMonthlyRecord,
    ControlledMoneyAccount, ControlledMoneyReceipt, ControlledMoneyWithdrawal, ControlledMoneyMonthlyStatement, ControlledMoneySupportingDocument, AuthorisedSignatory, WrittenDirection, TransitMoneyEntry, PowerMoneyEntry, PowerMoneyDealing, TrustInvestment, StatutoryDepositRecord,
    UnclaimedMoneyRecord
)
from .models import AnnualTrustComplianceRecord
from .forms import AnnualTrustComplianceRecordForm
from .forms import (
    Section19ComplianceReviewForm,
    ComplianceReviewLogForm,
    TrustAccountUpdateForm, ReceiptForm, PaymentForm, TransferCostsToOfficeForm, TrustJournalForm, ReconciliationForm, DepositRecordForm,
    ManualIrregularityForm, IrregularityResolveForm, DateRangeForm, YearForm,
    ReconciliationFinaliseForm, AccountingPeriodLockForm, ReconciliationBankStatementForm, ReconciliationBankLineForm,
    ControlledMoneyAccountForm, ControlledMoneyReceiptForm, ControlledMoneyWithdrawalForm,
    ControlledMoneyMonthlyStatementForm, ControlledMoneyPrincipalReviewForm, ControlledMoneySupportingDocumentForm, AuthorisedSignatoryForm, WrittenDirectionForm, TransitMoneyEntryForm, PowerMoneyEntryForm, PowerMoneyDealingForm, TrustInvestmentForm, StatutoryDepositRecordForm,
    AnnualTrustComplianceRecordForm,
    UnclaimedMoneyRecordForm
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
            firm_lookup='firm'
)


class TrustAccountDetailView(StaffRequiredMixin, DetailView):
    model = TrustAccount
    template_name = 'trust/account_detail.html'
    context_object_name = 'account'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('firm'),
            self.request.user,
            firm_lookup='firm'
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
                'journal_as_in'
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
            firm_lookup='firm'
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
            self.request.user
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
                    created_by=request.user
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
            firm_lookup='transaction__matter_ledger__trust_account__firm'
)


class PaymentCreateView(StaffRequiredMixin, View):
    template_name = 'trust/payment_form.html'

    def get_ledger(self):
        queryset = scope_trust_queryset_for_user(
            MatterLedger.objects.select_related('trust_account', 'matter'),
            self.request.user
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
                    created_by=request.user
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
                'authorised_by'
),
            self.request.user,
            firm_lookup='transaction__matter_ledger__trust_account__firm'
)


class TransferCostsToOfficeCreateView(AdminOrAccountantMixin, View):
    template_name = 'trust/transfer_costs_to_office_form.html'

    def get_ledger(self):
        queryset = scope_trust_queryset_for_user(
            MatterLedger.objects.select_related('trust_account', 'matter'),
            self.request.user
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
                    costs_withdrawal_notes=cd.get('costs_withdrawal_notes', '')
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
                firm_lookup='firm'
)
            return get_object_or_404(queryset, pk=ta_pk)
        return None

    def get(self, request):
        trust_account = self.get_trust_account()
        form = TrustJournalForm(trust_account=trust_account)
        accounts = scope_trust_queryset_for_user(
            TrustAccount.objects.filter(is_active=True),
            request.user,
            firm_lookup='firm'
)
        return render(request, self.template_name, {'form': form, 'accounts': accounts, 'trust_account': trust_account})

    def post(self, request):
        trust_account = self.get_trust_account()
        form = TrustJournalForm(request.POST, request.FILES, trust_account=trust_account)
        accounts = scope_trust_queryset_for_user(
            TrustAccount.objects.filter(is_active=True),
            request.user,
            firm_lookup='firm'
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
                    created_by=request.user
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
            firm_lookup='matter_ledger__trust_account__firm'
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


class AuthorisedSignatoryListView(AdminOrAccountantMixin, ListView):
    model = AuthorisedSignatory
    template_name = 'trust/authorised_signatory_list.html'
    context_object_name = 'signatories'

    def get_queryset(self):
        queryset = scope_trust_queryset_for_user(
            AuthorisedSignatory.objects.select_related('trust_account'),
            self.request.user,
            firm_lookup='trust_account__firm'
)
        status = self.request.GET.get('status', 'active')
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        elif status == 'inactive':
            queryset = queryset.filter(is_active=False)
        return queryset.order_by('trust_account__name', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        scoped = scope_trust_queryset_for_user(
            AuthorisedSignatory.objects.all(),
            self.request.user,
            firm_lookup='trust_account__firm'
)
        ctx['active_count'] = scoped.filter(is_active=True).count()
        ctx['status_filter'] = self.request.GET.get('status', 'active')
        return ctx


class AuthorisedSignatoryPDFView(AdminOrAccountantMixin, View):
    def get(self, request, *args, **kwargs):
        signatories = (
            scope_trust_queryset_for_user(
                AuthorisedSignatory.objects.select_related('trust_account'),
                request.user,
                firm_lookup='trust_account__firm'
)
            .order_by('trust_account__name', '-is_active', 'name')
        )
        return trust_reports.authorised_signatory_register_pdf(signatories)


class AuthorisedSignatoryCreateView(AdminOrAccountantMixin, CreateView):
    model = AuthorisedSignatory
    form_class = AuthorisedSignatoryForm
    template_name = 'trust/authorised_signatory_form.html'

    def get_initial(self):
        initial = super().get_initial()
        trust_account_id = self.request.GET.get('trust_account')
        if trust_account_id:
            initial['trust_account'] = trust_account_id
        initial.setdefault('is_active', True)
        return initial

    def get_success_url(self):
        messages.success(self.request, 'Authorised signatory created.')
        return reverse('trust:authorised_signatory_list')


class AuthorisedSignatoryUpdateView(AdminOrAccountantMixin, UpdateView):
    model = AuthorisedSignatory
    form_class = AuthorisedSignatoryForm
    template_name = 'trust/authorised_signatory_form.html'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            AuthorisedSignatory.objects.select_related('trust_account'),
            self.request.user,
            firm_lookup='trust_account__firm'
)

    def get_success_url(self):
        messages.success(self.request, 'Authorised signatory updated.')
        return reverse('trust:authorised_signatory_list')


class StatutoryDepositListView(AdminOrAccountantMixin, ListView):
    model = StatutoryDepositRecord
    template_name = 'trust/statutory_deposit_list.html'
    context_object_name = 'records'

    def get_queryset(self):
        qs = StatutoryDepositRecord.objects.select_related('trust_account')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(trust_account__firm=self.request.user.firm)
        return qs.order_by('-applicable_period_end', 'trust_account__name')


class StatutoryDepositCreateView(AdminOrAccountantMixin, CreateView):
    model = StatutoryDepositRecord
    form_class = StatutoryDepositRecordForm
    template_name = 'trust/statutory_deposit_form.html'

    def get_success_url(self):
        messages.success(self.request, 'Statutory deposit record created.')
        return reverse('trust:statutory_deposit_list')


class StatutoryDepositUpdateView(AdminOrAccountantMixin, UpdateView):
    model = StatutoryDepositRecord
    form_class = StatutoryDepositRecordForm
    template_name = 'trust/statutory_deposit_form.html'

    def get_queryset(self):
        qs = StatutoryDepositRecord.objects.select_related('trust_account')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(trust_account__firm=self.request.user.firm)
        return qs

    def get_success_url(self):
        messages.success(self.request, 'Statutory deposit record updated.')
        return reverse('trust:statutory_deposit_list')


class StatutoryDepositPDFView(AdminOrAccountantMixin, View):
    def get(self, request, *args, **kwargs):
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        qs = StatutoryDepositRecord.objects.select_related('trust_account')
        if hasattr(request.user, 'firm') and request.user.firm_id:
            qs = qs.filter(trust_account__firm=request.user.firm)
        qs = qs.order_by('-applicable_period_end', 'trust_account__name')

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        normal = styles['Normal'].clone('sd_cell')
        normal.fontSize = 7
        normal.leading = 8
        header = styles['Normal'].clone('sd_header')
        header.fontName = 'Helvetica-Bold'
        header.fontSize = 7
        header.leading = 8

        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1*cm, rightMargin=1*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
        generated_at = timezone.localtime(timezone.now()).strftime('%d %b %Y %I:%M %p %Z')

        elements = [
            Paragraph('Statutory Deposit Register', styles['Heading1']),
            Paragraph(f'Generated: {generated_at}', styles['Normal']),
            Spacer(1, 0.25*cm),
            Paragraph('Record of statutory deposit reviews and supporting documents. Calculations should be checked against authorised ADI statement balances and the Law Society statutory deposit calculator.', styles['Normal']),
            Spacer(1, 0.25*cm),
        ]

        data = [[
            Paragraph('Trust Account', header),
            Paragraph('Period End', header),
            Paragraph('ADI / Account Ref', header),
            Paragraph('Calculated', header),
            Paragraph('Required', header),
            Paragraph('Currently Held', header),
            Paragraph('Adjustment', header),
            Paragraph('Due', header),
            Paragraph('Made', header),
            Paragraph('Next Review', header),
            Paragraph('Reviewed', header),
            Paragraph('Docs', header),
        ]]

        for r in qs:
            docs = []
            if r.supporting_document:
                docs.append('support')
            if r.law_society_determination_document:
                docs.append('determination')
            data.append([
                Paragraph(str(r.trust_account), normal),
                Paragraph(str(r.applicable_period_end), normal),
                Paragraph(f'{r.statutory_deposit_adi or "-"} {r.statutory_deposit_account_reference or ""}', normal),
                Paragraph(str(r.calculated_on) if r.calculated_on else '-', normal),
                Paragraph(f'${r.required_amount}', normal),
                Paragraph(f'${r.amount_currently_held}', normal),
                Paragraph(f'${r.adjustment_required}', normal),
                Paragraph(str(r.adjustment_due_date) if r.adjustment_due_date else '-', normal),
                Paragraph(str(r.adjustment_made_on) if r.adjustment_made_on else '-', normal),
                Paragraph(str(r.next_review_due_on) if r.next_review_due_on else '-', normal),
                Paragraph(str(r.reviewed_on) if r.reviewed_on else '-', normal),
                Paragraph(', '.join(docs) if docs else '-', normal),
            ])

        if len(data) == 1:
            data.append([Paragraph('-', normal)] * 11)

        table = Table(data, colWidths=[3.5*cm, 1.8*cm, 3.5*cm, 1.8*cm, 1.8*cm, 2.0*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.8*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 0.35, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.25*cm))
        elements.append(Paragraph('Statutory Deposit Register - generated by Matter Funds.', styles['Normal']))
        doc.build(elements)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="statutory_deposit_register.pdf"'
        return response


class TrustInvestmentListView(AdminOrAccountantMixin, ListView):
    model = TrustInvestment
    template_name = 'trust/investment_list.html'
    context_object_name = 'investments'

    def get_queryset(self):
        qs = TrustInvestment.objects.select_related('client', 'matter')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(Q(matter__firm=self.request.user.firm) | Q(matter__isnull=True))
        return qs.order_by('-date_invested', 'person_on_behalf')


class TrustInvestmentCreateView(AdminOrAccountantMixin, CreateView):
    model = TrustInvestment
    form_class = TrustInvestmentForm
    template_name = 'trust/investment_form.html'

    def get_success_url(self):
        messages.success(self.request, 'Trust investment record created.')
        return reverse('trust:investment_list')


class TrustInvestmentUpdateView(AdminOrAccountantMixin, UpdateView):
    model = TrustInvestment
    form_class = TrustInvestmentForm
    template_name = 'trust/investment_form.html'

    def get_queryset(self):
        qs = TrustInvestment.objects.select_related('client', 'matter')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(Q(matter__firm=self.request.user.firm) | Q(matter__isnull=True))
        return qs

    def get_success_url(self):
        messages.success(self.request, 'Trust investment record updated.')
        return reverse('trust:investment_list')


class TrustInvestmentDetailView(AdminOrAccountantMixin, DetailView):
    model = TrustInvestment
    template_name = 'trust/investment_detail.html'
    context_object_name = 'investment'

    def get_queryset(self):
        qs = TrustInvestment.objects.select_related('client', 'matter')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(Q(matter__firm=self.request.user.firm) | Q(matter__isnull=True))
        return qs


class TrustInvestmentPDFView(AdminOrAccountantMixin, View):
    def get(self, request, *args, **kwargs):
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        qs = TrustInvestment.objects.select_related('client', 'matter')
        if hasattr(request.user, 'firm') and request.user.firm_id:
            qs = qs.filter(Q(matter__firm=request.user.firm) | Q(matter__isnull=True))
        qs = qs.order_by('-date_invested', 'person_on_behalf')

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        normal = styles['Normal'].clone('investment_cell')
        normal.fontSize = 6
        normal.leading = 7
        header = styles['Normal'].clone('investment_header')
        header.fontName = 'Helvetica-Bold'
        header.fontSize = 6
        header.leading = 7

        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=0.8*cm, rightMargin=0.8*cm, topMargin=1.0*cm, bottomMargin=1.0*cm)
        generated_at = timezone.localtime(timezone.now()).strftime('%d %b %Y %I:%M %p %Z')

        elements = [
            Paragraph('Register of Investments of Trust Money', styles['Heading1']),
            Paragraph(f'Generated: {generated_at}', styles['Normal']),
            Spacer(1, 0.25*cm),
        ]

        data = [[
            Paragraph('Person', header),
            Paragraph('Address', header),
            Paragraph('Matter', header),
            Paragraph('Name Investment Held In', header),
            Paragraph('Institution', header),
            Paragraph('Investment', header),
            Paragraph('Amount', header),
            Paragraph('Date', header),
            Paragraph('Source', header),
            Paragraph('Instruction', header),
            Paragraph('Evidence', header),
            Paragraph('Interest / Repayment', header),
        ]]

        for i in qs:
            data.append([
                Paragraph(i.person_on_behalf or '-', normal),
                Paragraph(i.person_address or '-', normal),
                Paragraph(str(i.matter or '-'), normal),
                Paragraph(i.investment_held_name or '-', normal),
                Paragraph(i.institution or '-', normal),
                Paragraph((i.investment_type or i.investment_particulars or '-')[:250], normal),
                Paragraph(f'${i.amount_invested}', normal),
                Paragraph(str(i.date_invested), normal),
                Paragraph(f'{i.get_source_of_investment_display()} {i.source_reference or ""}', normal),
                Paragraph(i.written_direction_reference or ('Attached' if i.written_direction_document else '-'), normal),
                Paragraph(i.document_identifier or ('Attached' if i.evidence_document else '-'), normal),
                Paragraph((i.interest_details or i.maturity_repayment_details or '-')[:250], normal),
            ])

        if len(data) == 1:
            data.append([Paragraph('-', normal)] * 12)

        table = Table(data, colWidths=[2.3*cm, 2.8*cm, 2.8*cm, 2.7*cm, 2.5*cm, 3.0*cm, 1.5*cm, 1.5*cm, 2.7*cm, 2.1*cm, 1.8*cm, 3.0*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 0.35, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.25*cm))
        elements.append(Paragraph('Register of Investments of Trust Money — generated by Matter Funds.', styles['Normal']))
        doc.build(elements)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="trust_investments_register.pdf"'
        return response


class PowerMoneyEntryListView(AdminOrAccountantMixin, ListView):
    model = PowerMoneyEntry
    template_name = 'trust/power_money_list.html'
    context_object_name = 'power_entries'

    def get_queryset(self):
        qs = PowerMoneyEntry.objects.select_related('client', 'matter')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(Q(matter__firm=self.request.user.firm) | Q(matter__isnull=True))
        return qs.order_by('-power_date', 'donor', 'deceased_name')


class PowerMoneyEntryCreateView(AdminOrAccountantMixin, CreateView):
    model = PowerMoneyEntry
    form_class = PowerMoneyEntryForm
    template_name = 'trust/power_money_form.html'

    def get_success_url(self):
        messages.success(self.request, 'Power / estate register entry created.')
        return reverse('trust:power_money_list')


class PowerMoneyEntryUpdateView(AdminOrAccountantMixin, UpdateView):
    model = PowerMoneyEntry
    form_class = PowerMoneyEntryForm
    template_name = 'trust/power_money_form.html'

    def get_queryset(self):
        qs = PowerMoneyEntry.objects.select_related('client', 'matter')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(Q(matter__firm=self.request.user.firm) | Q(matter__isnull=True))
        return qs

    def get_success_url(self):
        messages.success(self.request, 'Power / estate register entry updated.')
        return reverse('trust:power_money_list')


class PowerMoneyEntryDetailView(AdminOrAccountantMixin, DetailView):
    model = PowerMoneyEntry
    template_name = 'trust/power_money_detail.html'
    context_object_name = 'entry'

    def get_queryset(self):
        qs = PowerMoneyEntry.objects.select_related('client', 'matter').prefetch_related('dealings')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(Q(matter__firm=self.request.user.firm) | Q(matter__isnull=True))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        balance = self.object.amount_held or 0
        dealing_rows = []
        for dealing in self.object.dealings.all().order_by('dealing_date', 'id'):
            balance = balance + dealing.deposit - dealing.withdrawal
            dealing_rows.append({
                'dealing': dealing,
                'balance': balance,
            })
        ctx['dealing_rows'] = dealing_rows
        return ctx


class PowerMoneyDealingCreateView(AdminOrAccountantMixin, CreateView):
    model = PowerMoneyDealing
    form_class = PowerMoneyDealingForm
    template_name = 'trust/power_money_dealing_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.power_entry = get_object_or_404(PowerMoneyEntry, pk=kwargs['entry_pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.power_entry = self.power_entry
        messages.success(self.request, 'Power / estate dealing recorded.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['entry'] = self.power_entry
        return ctx

    def get_success_url(self):
        return reverse('trust:power_money_detail', kwargs={'pk': self.power_entry.pk})


class PowerMoneyPDFView(AdminOrAccountantMixin, View):
    def get(self, request, *args, **kwargs):
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        qs = PowerMoneyEntry.objects.select_related('client', 'matter')
        if hasattr(request.user, 'firm') and request.user.firm_id:
            qs = qs.filter(Q(matter__firm=request.user.firm) | Q(matter__isnull=True))
        qs = qs.order_by('-power_date', 'donor', 'deceased_name')

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        normal = styles['Normal'].clone('pe_cell')
        normal.fontSize = 7
        normal.leading = 8
        header = styles['Normal'].clone('pe_header')
        header.fontName = 'Helvetica-Bold'
        header.fontSize = 7
        header.leading = 8

        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1*cm, rightMargin=1*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
        generated_at = timezone.localtime(timezone.now()).strftime('%d %b %Y %I:%M %p %Z')

        elements = [
            Paragraph('Register of Powers and Estates', styles['Heading1']),
            Paragraph(f'Generated: {generated_at}', styles['Normal']),
            Spacer(1, 0.3*cm),
        ]

        data = [[
            Paragraph('Date of Power', header),
            Paragraph('Donor / Deceased', header),
            Paragraph('Address', header),
            Paragraph('Matter Reference', header),
            Paragraph('Description of Power', header),
            Paragraph('Date of Death', header),
            Paragraph('Responsible Solicitor', header),
            Paragraph('Authority Doc', header),
        ]]

        for e in qs:
            data.append([
                Paragraph(str(e.power_date) if e.power_date else '-', normal),
                Paragraph(e.deceased_name or e.donor or str(e.client or '-'), normal),
                Paragraph(e.donor_address or '-', normal),
                Paragraph(e.matter_reference or str(e.matter or '-'), normal),
                Paragraph(e.description or e.get_entry_type_display(), normal),
                Paragraph(str(e.date_of_death) if e.date_of_death else '-', normal),
                Paragraph(e.responsible_solicitor or '-', normal),
                Paragraph('Attached' if e.power_instrument or e.authority_document else 'None', normal),
            ])

        if len(data) == 1:
            data.append([Paragraph('-', normal)] * 8)

        table = Table(data, colWidths=[2.0*cm, 4.0*cm, 4.5*cm, 3.0*cm, 6.0*cm, 2.0*cm, 3.5*cm, 1.7*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 0.35, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="powers_estates_register.pdf"'
        return response


class TransitMoneyEntryListView(AdminOrAccountantMixin, ListView):
    model = TransitMoneyEntry
    template_name = 'trust/transit_money_list.html'
    context_object_name = 'transit_entries'

    def get_queryset(self):
        qs = TransitMoneyEntry.objects.select_related('client', 'matter')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(Q(matter__firm=self.request.user.firm) | Q(matter__isnull=True))
        status = self.request.GET.get('status', 'all')
        if status == 'pending':
            qs = qs.filter(paid_on__isnull=True)
        elif status == 'completed':
            qs = qs.filter(paid_on__isnull=False)
        return qs.order_by('-received_on')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        scoped = self.get_queryset()
        ctx['pending_count'] = scoped.filter(paid_on__isnull=True).count()
        ctx['status_filter'] = self.request.GET.get('status', 'all')
        return ctx


class TransitMoneyEntryCreateView(AdminOrAccountantMixin, CreateView):
    model = TransitMoneyEntry
    form_class = TransitMoneyEntryForm
    template_name = 'trust/transit_money_form.html'

    def get_success_url(self):
        messages.success(self.request, 'Transit money entry created.')
        return reverse('trust:transit_money_list')


class TransitMoneyEntryUpdateView(AdminOrAccountantMixin, UpdateView):
    model = TransitMoneyEntry
    form_class = TransitMoneyEntryForm
    template_name = 'trust/transit_money_form.html'

    def get_queryset(self):
        qs = TransitMoneyEntry.objects.select_related('client', 'matter')
        if hasattr(self.request.user, 'firm') and self.request.user.firm_id:
            qs = qs.filter(Q(matter__firm=self.request.user.firm) | Q(matter__isnull=True))
        return qs

    def get_success_url(self):
        messages.success(self.request, 'Transit money entry updated.')
        return reverse('trust:transit_money_list')


class TransitMoneyPDFView(AdminOrAccountantMixin, View):
    def get(self, request, *args, **kwargs):
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        qs = TransitMoneyEntry.objects.select_related('client', 'matter')
        if hasattr(request.user, 'firm') and request.user.firm_id:
            qs = qs.filter(Q(matter__firm=request.user.firm) | Q(matter__isnull=True))
        qs = qs.order_by('-received_on')

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        normal = styles['Normal'].clone('tm_cell')
        normal.fontSize = 7
        normal.leading = 8
        header = styles['Normal'].clone('tm_header')
        header.fontName = 'Helvetica-Bold'
        header.fontSize = 7
        header.leading = 8

        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            leftMargin=1 * cm,
            rightMargin=1 * cm,
            topMargin=1.2 * cm,
            bottomMargin=1.2 * cm
)

        generated_at = timezone.localtime(timezone.now()).strftime('%d %b %Y %I:%M %p %Z')
        elements = [
            Paragraph('Transit Money Register', styles['Heading1']),
            Paragraph(f'Generated: {generated_at}', styles['Normal']),
            Spacer(1, 0.3 * cm),
            Paragraph('Register of brief particulars and retained supporting records for transit money under Section 140.', styles['Normal']),
            Spacer(1, 0.3 * cm),
        ]

        data = [[
            Paragraph('Received', header),
            Paragraph('Client', header),
            Paragraph('Matter', header),
            Paragraph('Payor', header),
            Paragraph('Amount', header),
            Paragraph('To be paid/delivered to', header),
            Paragraph('Paid/Delivered', header),
            Paragraph('Purpose / Instructions', header),
            Paragraph('Instructions Doc', header),
            Paragraph('Supporting Doc', header),
            Paragraph('Status', header),
        ]]

        for e in qs:
            data.append([
                Paragraph(str(e.received_on), normal),
                Paragraph(str(e.client) if e.client else '-', normal),
                Paragraph(str(e.matter) if e.matter else '-', normal),
                Paragraph(e.payor or '-', normal),
                Paragraph(f'${e.amount}', normal),
                Paragraph(e.to_be_paid_to or '-', normal),
                Paragraph(str(e.paid_on) if e.paid_on else '-', normal),
                Paragraph((e.purpose or e.notes or '-')[:400], normal),
                Paragraph('Yes' if e.instructions_document else 'No', normal),
                Paragraph('Yes' if e.supporting_document else 'No', normal),
                Paragraph(e.status, normal),
            ])

        if len(data) == 1:
            data.append([Paragraph('-', normal)] * 11)

        table = Table(
            data,
            colWidths=[1.8*cm, 2.8*cm, 3.2*cm, 2.8*cm, 1.7*cm, 3.2*cm, 1.8*cm, 6.0*cm, 1.6*cm, 1.6*cm, 1.5*cm],
            repeatRows=1
)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 0.35, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="transit_money_register.pdf"'
        return response


class WrittenDirectionListView(AdminOrAccountantMixin, ListView):
    model = WrittenDirection
    template_name = 'trust/written_direction_list.html'
    context_object_name = 'written_directions'

    def get_queryset(self):
        return (
            scope_trust_queryset_for_user(
                WrittenDirection.objects.select_related('client', 'matter', 'linked_transaction'),
                self.request.user,
                firm_lookup='matter__firm'
)
            .order_by('-signed_on', 'client__name')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['active_count'] = self.get_queryset().count()
        return ctx


class WrittenDirectionCreateView(AdminOrAccountantMixin, CreateView):
    model = WrittenDirection
    form_class = WrittenDirectionForm
    template_name = 'trust/written_direction_form.html'

    def get_success_url(self):
        messages.success(self.request, 'Written direction created.')
        return reverse('trust:written_direction_list')


class WrittenDirectionUpdateView(AdminOrAccountantMixin, UpdateView):
    model = WrittenDirection
    form_class = WrittenDirectionForm
    template_name = 'trust/written_direction_form.html'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            WrittenDirection.objects.select_related('client', 'matter', 'linked_transaction'),
            self.request.user,
            firm_lookup='matter__firm'
)

    def get_success_url(self):
        messages.success(self.request, 'Written direction updated.')
        return reverse('trust:written_direction_list')


class WrittenDirectionPDFView(AdminOrAccountantMixin, View):
    def get(self, request, *args, **kwargs):
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        qs = (
            scope_trust_queryset_for_user(
                WrittenDirection.objects.select_related('client', 'matter', 'linked_transaction'),
                request.user,
                firm_lookup='matter__firm'
)
            .order_by('-signed_on', 'client__name')
        )

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        normal = styles['Normal'].clone('wd_cell')
        normal.fontSize = 7
        normal.leading = 8
        header = styles['Normal'].clone('wd_header')
        header.fontName = 'Helvetica-Bold'
        header.fontSize = 7
        header.leading = 8

        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            leftMargin=1 * cm,
            rightMargin=1 * cm,
            topMargin=1.2 * cm,
            bottomMargin=1.2 * cm
)

        generated_at = timezone.localtime(timezone.now()).strftime('%d %b %Y %I:%M %p %Z')
        elements = [
            Paragraph('Written Direction Register', styles['Heading1']),
            Paragraph(f'Generated: {generated_at}', styles['Normal']),
            Spacer(1, 0.3 * cm),
            Paragraph('Register of written direction money records retained for Section 137(a) / Rule 34 compliance.', styles['Normal']),
            Spacer(1, 0.3 * cm),
        ]

        data = [[
            Paragraph('Client', header),
            Paragraph('Matter', header),
            Paragraph('Date', header),
            Paragraph('Direction / Legal Basis', header),
            Paragraph('Linked Transaction', header),
            Paragraph('Document', header),
        ]]

        for wd in qs:
            data.append([
                Paragraph(str(wd.client), normal),
                Paragraph(str(wd.matter) if wd.matter else '-', normal),
                Paragraph(wd.signed_on.strftime('%d %b %Y') if wd.signed_on else '-', normal),
                Paragraph((wd.direction_text or '-')[:500], normal),
                Paragraph(str(wd.linked_transaction) if wd.linked_transaction else '-', normal),
                Paragraph('Yes' if wd.document else 'No', normal),
            ])

        table = Table(
            data,
            colWidths=[3.2*cm, 4.2*cm, 2.0*cm, 10.0*cm, 4.0*cm, 1.7*cm],
            repeatRows=1
)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 0.35, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="written_direction_register.pdf"'
        return response


class DepositRecordListView(AdminOrAccountantMixin, ListView):
    model = DepositRecord
    template_name = 'trust/deposit_record_list.html'
    context_object_name = 'deposit_records'

    def get_queryset(self):
        return (
            scope_trust_queryset_for_user(
                DepositRecord.objects.select_related('trust_account', 'prepared_by'),
                self.request.user,
                firm_lookup='trust_account__firm'
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
                notes=form.cleaned_data.get('notes', '')
)
            for receipt in form.cleaned_data['receipt_objects']:
                receipt.deposit_record = deposit
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
            firm_lookup='trust_account__firm'
)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['receipts'] = self.object.receipts.select_related(
            'transaction',
            'transaction__matter_ledger',
            'transaction__matter_ledger__matter'
).order_by('receipt_number')
        return ctx


class DepositRecordPDFView(AdminOrAccountantMixin, DetailView):
    model = DepositRecord

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            DepositRecord.objects.select_related('trust_account', 'prepared_by'),
            self.request.user,
            firm_lookup='trust_account__firm'
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
            self.request.user
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
            period_end
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
            self.request.user
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
            self.request.user
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
                transaction_type__in=['receipt', 'payment', 'transfer_to_office', 'reversal']
)
            .select_related(
                'matter_ledger__matter',
                'matter_ledger__matter__client',
                'receipt',
                'payment',
                'reverses'
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
                cleared_by_transaction__isnull=True
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
                'cleared_in_reconciliation'
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
                pk=request.POST.get('transaction_id')
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
                matched_at=timezone.now()
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
                pk=request.POST.get('line_id')
)
            txn = get_object_or_404(
                self._internal_transactions(reconciliation),
                pk=request.POST.get('cleared_by_transaction')
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
            self.request.user
)

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get('download'):
            if not self.object.bank_statement_pdf:
                raise Http404('Bank statement PDF not found.')
            return FileResponse(
                self.object.bank_statement_pdf.open('rb'),
                as_attachment=True,
                filename=self.object.bank_statement_pdf.name.split('/')[-1]
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
            self.request.user
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
            self.request.user
)


class AccountingPeriodDetailView(StaffRequiredMixin, DetailView):
    model = TrustAccountingPeriod
    template_name = 'trust/period_detail.html'
    context_object_name = 'period'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'locked_by').prefetch_related('monthly_records'),
            self.request.user
)


class AccountingPeriodLockView(AdminOrAccountantMixin, FormView):
    form_class = AccountingPeriodLockForm
    template_name = 'trust/period_lock.html'

    def get_period(self):
        queryset = scope_trust_queryset_for_user(
            TrustAccountingPeriod.objects.select_related('trust_account'),
            self.request.user
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
            self.request.user
)


class MonthlyRecordDetailView(StaffRequiredMixin, DetailView):
    model = TrustMonthlyRecord
    template_name = 'trust/monthly_record_detail.html'
    context_object_name = 'monthly_record'

    def get_queryset(self):
        return scope_trust_queryset_for_user(
            super().get_queryset().select_related('trust_account', 'accounting_period', 'generated_by'),
            self.request.user
)


class MonthlyRecordDownloadView(StaffRequiredMixin, View):
    def get(self, request, pk):
        queryset = scope_trust_queryset_for_user(
            TrustMonthlyRecord.objects.select_related('trust_account', 'accounting_period'),
            request.user
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
            self.request.user
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
            self.request.user
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
        firm_lookup='firm'
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


def _outstanding_cheque_rows(trust_account, age_filter='all'):
    today = timezone.localdate()
    payments = (
        Payment.objects
        .filter(
            transaction__matter_ledger__trust_account=trust_account,
            payment_method='cheque',
            transaction__is_reversed=False
)
        .select_related(
            'transaction',
            'transaction__matter_ledger',
            'transaction__matter_ledger__matter',
            'transaction__matter_ledger__matter__client'
)
        .order_by('transaction__date_received_or_paid', 'payment_number')
    )

    rows = []
    totals = {
        'current_total': Decimal('0.00'),
        'review_total': Decimal('0.00'),
        'stale_total': Decimal('0.00'),
        'grand_total': Decimal('0.00'),
    }

    for payment in payments:
        issued = payment.transaction.date_received_or_paid
        days = max((today - issued).days, 0)

        if days >= 180:
            band_key = 'stale'
            band_label = 'Stale cheque'
        elif days >= 90:
            band_key = 'review'
            band_label = 'Review required'
        else:
            band_key = 'current'
            band_label = 'Current'

        if age_filter != 'all' and age_filter != band_key:
            continue

        amount = payment.transaction.amount
        totals[f'{band_key}_total'] += amount
        totals['grand_total'] += amount

        matter = payment.transaction.matter_ledger.matter
        rows.append({
            'payment_number': getattr(payment, 'payment_reference_override', '') or str(payment.payment_number),
            'cheque_number': payment.cheque_number or '-',
            'date_issued': issued,
            'matter': f"{matter.file_number or matter.pk} - {matter.description}",
            'payee': payment.payee_name,
            'amount': amount,
            'days_outstanding': days,
            'age_band_key': band_key,
            'age_band': band_label,
        })

    return rows, totals


class OutstandingChequesReportView(AdminOrAccountantMixin, TemplateView):
    template_name = 'trust/outstanding_cheques_report.html'

    def get_trust_account(self):
        queryset = scope_trust_queryset_for_user(TrustAccount.objects.all(), self.request.user, firm_lookup='firm')
        return get_object_or_404(queryset, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        trust_account = self.get_trust_account()
        age_filter = self.request.GET.get('age', 'all')
        if age_filter not in {'all', 'current', 'review', 'stale'}:
            age_filter = 'all'

        rows, totals = _outstanding_cheque_rows(trust_account, age_filter)
        ctx.update({
            'trust_account': trust_account,
            'rows': rows,
            'totals': totals,
            'age_filter': age_filter,
            'report_date': timezone.localdate(),
        })
        return ctx


class OutstandingChequesPDFView(AdminOrAccountantMixin, View):
    def get_trust_account(self):
        queryset = scope_trust_queryset_for_user(TrustAccount.objects.all(), self.request.user, firm_lookup='firm')
        return get_object_or_404(queryset, pk=self.kwargs['pk'])

    def get(self, request, *args, **kwargs):
        trust_account = self.get_trust_account()
        age_filter = request.GET.get('age', 'all')
        if age_filter not in {'all', 'current', 'review', 'stale'}:
            age_filter = 'all'
        rows, totals = _outstanding_cheque_rows(trust_account, age_filter)
        pdf = trust_reports.outstanding_cheques_pdf_bytes(trust_account, rows, totals)
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="outstanding-cheques.pdf"'
        return response


class UnclaimedMoneyRecordListView(StaffRequiredMixin, ListView):
    model = UnclaimedMoneyRecord
    template_name = 'trust/unclaimed_money_list.html'
    context_object_name = 'records'

    def get_queryset(self):
        qs = UnclaimedMoneyRecord.objects.select_related(
            'firm',
            'trust_account',
            'matter_ledger',
            'matter_ledger__matter',
            'matter_ledger__matter__client',
            'reviewed_by'
)
        firm = getattr(self.request.user, 'firm', None)
        if firm:
            qs = qs.filter(firm=firm)
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs.order_by('-date_identified', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = UnclaimedMoneyRecord.STATUS_CHOICES
        ctx['selected_status'] = self.request.GET.get('status', '')
        return ctx


class UnclaimedMoneyRecordCreateView(StaffRequiredMixin, CreateView):
    model = UnclaimedMoneyRecord
    form_class = UnclaimedMoneyRecordForm
    template_name = 'trust/unclaimed_money_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['firm'] = getattr(self.request.user, 'firm', None)
        return kwargs

    def form_valid(self, form):
        firm = getattr(self.request.user, 'firm', None)
        if firm:
            form.instance.firm = firm
        if not form.instance.amount and form.instance.matter_ledger_id:
            form.instance.amount = form.instance.matter_ledger.balance
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Unclaimed money review record created.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('trust:unclaimed_money_list')


class UnclaimedMoneyRecordUpdateView(StaffRequiredMixin, UpdateView):
    model = UnclaimedMoneyRecord
    form_class = UnclaimedMoneyRecordForm
    template_name = 'trust/unclaimed_money_form.html'

    def get_queryset(self):
        qs = UnclaimedMoneyRecord.objects.select_related('firm', 'trust_account', 'matter_ledger')
        firm = getattr(self.request.user, 'firm', None)
        if firm:
            qs = qs.filter(firm=firm)
        return qs

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['firm'] = getattr(self.request.user, 'firm', None)
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Unclaimed money review record updated.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('trust:unclaimed_money_list')

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
            pk=pk
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
            pk=pk
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
            pk=pk
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
            pk=pk
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
            pk=pk
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
                trial_balance_error='As at date cannot be in the future.'
)
            return render(request, 'trust/reports.html', context, status=400)
        return trust_reports.trust_trial_balance_pdf(account, as_at)


class ExaminerPackZipView(AdminOrAccountantMixin, View):
    def get(self, request, pk):
        account = get_object_or_404(
            scope_trust_queryset_for_user(TrustAccount.objects.all(), request.user, firm_lookup='firm'),
            pk=pk
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
            pk=pk
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
            include_technical=request.GET.get('include_technical') in {'1', 'true', 'yes'}
)


class LedgerStatementPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        ledger = get_object_or_404(
            scope_trust_queryset_for_user(MatterLedger.objects.select_related('trust_account'), request.user),
            pk=pk
)
        return trust_reports.matter_ledger_statement_pdf(ledger)


class TrustAccountStatementPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        ledger = get_object_or_404(
            scope_trust_queryset_for_user(
                MatterLedger.objects.select_related('trust_account__firm', 'matter__client'),
                request.user
),
            pk=pk
)
        date_from = parse_date(request.GET.get('date_from') or '') if request.GET.get('date_from') else None
        date_to = parse_date(request.GET.get('date_to') or '') if request.GET.get('date_to') else None
        return trust_reports.trust_account_statement_pdf(ledger, date_from, date_to)


class ReconciliationPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        recon = get_object_or_404(
            scope_trust_queryset_for_user(MonthlyReconciliation.objects.select_related('trust_account'), request.user),
            pk=pk
)
        return trust_reports.monthly_reconciliation_pdf(recon)


class ReceiptPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        receipt = get_object_or_404(
            scope_trust_queryset_for_user(
                Receipt.objects.select_related('transaction__matter_ledger__trust_account'),
                request.user,
                firm_lookup='transaction__matter_ledger__trust_account__firm'
),
            pk=pk
)
        return trust_reports.receipt_pdf(receipt)


class PaymentPDFView(StaffRequiredMixin, View):
    def get(self, request, pk):
        payment = get_object_or_404(
            scope_trust_queryset_for_user(
                Payment.objects.select_related(
                    'transaction__matter_ledger__trust_account__firm',
                    'transaction__matter_ledger__matter__client',
                    'authorised_by'
),
                request.user,
                firm_lookup='transaction__matter_ledger__trust_account__firm'
),
            pk=pk
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
                'journal_in_txn'
),
            self.request.user,
            firm_lookup='from_ledger__trust_account__firm'
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
                    'journal_in_txn'
),
                request.user,
                firm_lookup='from_ledger__trust_account__firm'
),
            pk=pk
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

class ControlledMoneyWithdrawalPDFView(AdminOrAccountantMixin, View):
    def get(self, request, pk, *args, **kwargs):
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        withdrawal = get_object_or_404(
            scope_trust_queryset_for_user(
                ControlledMoneyWithdrawal.objects.select_related('controlled_money_account', 'controlled_money_account__firm', 'controlled_money_account__client', 'controlled_money_account__matter'),
                request.user,
                firm_lookup='controlled_money_account__firm'
),
            pk=pk
)
        account = withdrawal.controlled_money_account

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        normal = styles['Normal'].clone('cmw_cell')
        normal.fontSize = 8
        normal.leading = 10
        header = styles['Normal'].clone('cmw_header')
        header.fontName = 'Helvetica-Bold'
        header.fontSize = 8
        header.leading = 10

        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.4*cm, rightMargin=1.4*cm, topMargin=1.4*cm, bottomMargin=1.4*cm)
        generated_at = timezone.localtime(timezone.now()).strftime('%d %b %Y %I:%M %p %Z')

        destination = '-'
        if withdrawal.withdrawal_method == 'eft':
            destination = f"{withdrawal.destination_account_name or ''} BSB {withdrawal.destination_bsb or ''} Account {withdrawal.destination_account_number or ''}".strip()

        authority_attached = 'Yes' if withdrawal.supporting_authority else 'No'

        rows = [
            ['Reference Number', withdrawal.transaction_number or '-'],
            ['Generated', generated_at],
            ['Controlled Money Account', account.account_name],
            ['ADI / BSB / Account', f"{account.bank} / {account.bsb} / {account.account_number}"],
            ['Withdrawal Date', str(withdrawal.date)],
            ['Matter Reference', withdrawal.matter_reference or account.matter_reference or '-'],
            ['Client / Person Name', withdrawal.person_on_behalf or account.person_on_behalf or '-'],
            ['Matter Description', account.matter_description or '-'],
            ['Amount', f"${withdrawal.amount}"],
            ['Balance Before Withdrawal', f"${account.current_balance + withdrawal.amount}"],
            ['Balance After Withdrawal', f"${account.current_balance}"],
            ['Withdrawal Method', withdrawal.get_withdrawal_method_display()],
            ['Payee', withdrawal.payee or '-'],
            ['EFT Destination', destination],
            ['Person Receiving Benefit', withdrawal.person_receiving_benefit or '-'],
            ['Reason / Purpose of Payment', withdrawal.reason or '-'],
            ['Authority Document',
              withdrawal.supporting_authority.name if withdrawal.supporting_authority else 'Not Attached'],
            ['Authorised By', withdrawal.authorised_by or '-'],
        ]

        data = [[Paragraph('Field', header), Paragraph('Value', header)]]
        for label, value in rows:
            data.append([Paragraph(str(label), header), Paragraph(str(value), normal)])

        elements = [
            Paragraph('Controlled Money Payment / Withdrawal Record', styles['Heading1']),
            Spacer(1, 0.25*cm),
            Paragraph('Record of withdrawal of controlled money by cheque or electronic funds transfer.', styles['Normal']),
            Spacer(1, 0.35*cm),
        ]

        table = Table(data, colWidths=[6.0*cm, 11.5*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 0.35, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="controlled_money_withdrawal_{withdrawal.transaction_number or withdrawal.pk}.pdf"'
        return response


class ControlledMoneyReceiptPDFView(AdminOrAccountantMixin, View):
    def get(self, request, pk):
        receipt=get_object_or_404(scope_trust_queryset_for_user(ControlledMoneyReceipt.objects.select_related('firm','controlled_money_account','made_out_by'), request.user, firm_lookup='firm'), pk=pk)
        return trust_reports._pdf_response_from_bytes(f'controlled_money_receipt_{receipt.receipt_number}.pdf', trust_reports.controlled_money_receipt_pdf_bytes(receipt))

class ControlledMoneySupportingDocumentCreateView(AdminOrAccountantMixin, CreateView):
    model = ControlledMoneySupportingDocument
    form_class = ControlledMoneySupportingDocumentForm
    template_name = 'trust/controlled_money/supporting_document_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.controlled_money_account = get_object_or_404(
            scope_trust_queryset_for_user(
                ControlledMoneyAccount.objects.select_related('firm', 'client', 'matter'),
                request.user,
                firm_lookup='firm'
),
            pk=kwargs['account_pk']
)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.controlled_money_account = self.controlled_money_account
        messages.success(self.request, 'Supporting document uploaded.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['controlled_money_account'] = self.controlled_money_account
        return ctx

    def get_success_url(self):
        return reverse('trust:controlled_money_detail', kwargs={'pk': self.controlled_money_account.pk})


class ControlledMoneyRegisterPDFView(AdminOrAccountantMixin, View):
    def get(self, request, pk, *args, **kwargs):
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        account = get_object_or_404(
            scope_trust_queryset_for_user(
                ControlledMoneyAccount.objects.select_related('firm', 'client', 'matter'),
                request.user,
                firm_lookup='firm'
),
            pk=pk
)
        receipts = account.receipts.all().order_by('date_made_out', 'receipt_number')
        withdrawals = account.withdrawals.all().order_by('date', 'transaction_number')
        docs = account.supporting_documents.all().order_by('uploaded_at')

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        normal = styles['Normal'].clone('cm_cell')
        normal.fontSize = 7
        normal.leading = 8
        header = styles['Normal'].clone('cm_header')
        header.fontName = 'Helvetica-Bold'
        header.fontSize = 7
        header.leading = 8

        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1*cm, rightMargin=1*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
        generated_at = timezone.localtime(timezone.now()).strftime('%d %b %Y %I:%M %p %Z')

        elements = [
            Paragraph('Controlled Money Register', styles['Heading1']),
            Paragraph(f'Generated: {generated_at}', styles['Normal']),
            Spacer(1, 0.25*cm),
            Paragraph(f'Account: {account.account_name}', styles['Normal']),
            Paragraph(f'Client/person: {account.person_on_behalf}', styles['Normal']),
            Paragraph(f'Address: {account.person_address or "-"}', styles['Normal']),
            Paragraph(f'Matter: {account.matter_reference} {account.matter_description}', styles['Normal']),
            Paragraph(f'ADI/account: {account.bank} BSB {account.bsb} Account {account.account_number}', styles['Normal']),
            Paragraph(f'Purpose: {account.purpose or "-"}', styles['Normal']),
            Paragraph(f'Opened: {account.opened_on or "-"}', styles['Normal']),
            Paragraph(f'Closed: {account.closed_on or "-"}', styles['Normal']),
            Paragraph(f'Interest disposition: {account.interest_disposition or "-"}', styles['Normal']),
            Paragraph(f'Written direction attached: {"Yes" if account.client_instruction_document else "No"}', styles['Normal']),
            Paragraph(f'Current balance: ${account.current_balance}', styles['Normal']),
            Spacer(1, 0.35*cm),
            Paragraph('Receipts', styles['Heading2']),
        ]

        receipt_rows = [[Paragraph('No.', header), Paragraph('Date Made Out', header), Paragraph('Date Received', header), Paragraph('From', header), Paragraph('Amount', header), Paragraph('Reason', header)]]
        for r in receipts:
            receipt_rows.append([
                Paragraph(str(r.receipt_number), normal),
                Paragraph(str(r.date_made_out), normal),
                Paragraph(str(r.date_money_received or r.date_made_out), normal),
                Paragraph(r.person_from_whom_received or '-', normal),
                Paragraph(f'${r.amount}', normal),
                Paragraph(r.reason or '-', normal),
            ])
        if len(receipt_rows) == 1:
            receipt_rows.append([Paragraph('-', normal)] * 6)

        t = Table(receipt_rows, colWidths=[1.2*cm, 2.1*cm, 2.1*cm, 4.0*cm, 2.0*cm, 12.0*cm], repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey),('GRID',(0,0),(-1,-1),0.35,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),3)]))
        elements.append(t)

        elements += [Spacer(1, 0.35*cm), Paragraph('Withdrawals', styles['Heading2'])]
        withdrawal_rows = [[Paragraph('Txn No.', header), Paragraph('Date', header), Paragraph('Method', header), Paragraph('Payee', header), Paragraph('Amount', header), Paragraph('Reason', header), Paragraph('Authorised By', header)]]
        for w in withdrawals:
            withdrawal_rows.append([
                Paragraph(w.transaction_number or '-', normal),
                Paragraph(str(w.date), normal),
                Paragraph(w.get_withdrawal_method_display(), normal),
                Paragraph(w.payee or '-', normal),
                Paragraph(f'${w.amount}', normal),
                Paragraph(w.reason or '-', normal),
                Paragraph(w.authorised_by or '-', normal),
            ])
        if len(withdrawal_rows) == 1:
            withdrawal_rows.append([Paragraph('-', normal)] * 7)

        t = Table(withdrawal_rows, colWidths=[1.8*cm, 2.0*cm, 2.0*cm, 4.0*cm, 2.0*cm, 9.0*cm, 4.0*cm], repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey),('GRID',(0,0),(-1,-1),0.35,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),3)]))
        elements.append(t)

        elements += [Spacer(1, 0.35*cm), Paragraph('Supporting Documents', styles['Heading2'])]
        doc_rows = [[Paragraph('Type', header), Paragraph('Description', header), Paragraph('Uploaded', header)]]
        for d in docs:
            doc_rows.append([
                Paragraph(d.document_type or '-', normal),
                Paragraph(d.description or '-', normal),
                Paragraph(str(d.uploaded_at), normal),
            ])
        if len(doc_rows) == 1:
            doc_rows.append([Paragraph('-', normal)] * 3)

        t = Table(doc_rows, colWidths=[4.0*cm, 14.0*cm, 5.0*cm], repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey),('GRID',(0,0),(-1,-1),0.35,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),3)]))
        elements.append(t)

        doc.build(elements)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="controlled_money_register_{account.pk}.pdf"'
        return response


class ControlledMoneyMovementPDFView(AdminOrAccountantMixin, View):
    def get(self, request, pk, *args, **kwargs):
        import io
        from decimal import Decimal
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        account = get_object_or_404(
            scope_trust_queryset_for_user(
                ControlledMoneyAccount.objects.select_related('firm', 'client', 'matter'),
                request.user,
                firm_lookup='firm'
),
            pk=pk
)

        movements = []
        for r in account.receipts.all():
            movements.append((r.date_money_received or r.date_made_out, f'Receipt {r.receipt_number}', r.person_from_whom_received, Decimal('0.00'), r.amount, r.reason))
        for w in account.withdrawals.all():
            movements.append((w.date, f'Withdrawal {w.transaction_number}', w.payee, w.amount, Decimal('0.00'), w.reason))
        movements.sort(key=lambda x: (x[0], x[1]))

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        normal = styles['Normal'].clone('cmm_cell')
        normal.fontSize = 7
        normal.leading = 8
        header = styles['Normal'].clone('cmm_header')
        header.fontName = 'Helvetica-Bold'
        header.fontSize = 7
        header.leading = 8

        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1*cm, rightMargin=1*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
        generated_at = timezone.localtime(timezone.now()).strftime('%d %b %Y %I:%M %p %Z')
        elements = [
            Paragraph('Controlled Money Movement Record', styles['Heading1']),
            Paragraph(f'Generated: {generated_at}', styles['Normal']),
            Spacer(1, 0.25*cm),
            Paragraph(f'Account: {account.account_name}', styles['Normal']),
            Paragraph(f'Person: {account.person_on_behalf}', styles['Normal']),
            Paragraph(f'Address: {account.person_address or "-"}', styles['Normal']),
            Paragraph(f'Matter: {account.matter_reference} {account.matter_description}', styles['Normal']),
            Paragraph(f'ADI: {account.bank}', styles['Normal']),
            Paragraph(f'BSB / Account Number: {account.bsb} / {account.account_number}', styles['Normal']),
            Paragraph(f'Purpose: {account.purpose or "-"}', styles['Normal']),
            Paragraph(f'Opened: {account.opened_on or "-"}', styles['Normal']),
            Paragraph(f'Interest disposition: {account.interest_disposition or "-"}', styles['Normal']),
            Spacer(1, 0.35*cm),
        ]

        rows = [[Paragraph('Date', header), Paragraph('Reference', header), Paragraph('Paid To / Received From', header), Paragraph('Reason', header), Paragraph('Debit', header), Paragraph('Credit', header), Paragraph('Balance', header)]]
        balance = Decimal('0.00')
        for date, ref, party, debit, credit, reason in movements:
            balance = balance + credit - debit
            rows.append([
                Paragraph(str(date), normal),
                Paragraph(str(ref), normal),
                Paragraph(party or '-', normal),
                Paragraph(reason or '-', normal),
                Paragraph(f'${debit}' if debit else '-', normal),
                Paragraph(f'${credit}' if credit else '-', normal),
                Paragraph(f'${balance}', normal),
            ])

        if len(rows) == 1:
            rows.append([Paragraph('-', normal)] * 7)

        t = Table(rows, colWidths=[2.0*cm, 3.0*cm, 5.0*cm, 8.0*cm, 2.0*cm, 2.0*cm, 2.0*cm], repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey),('GRID',(0,0),(-1,-1),0.35,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),3)]))
        elements.append(t)
        doc.build(elements)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="controlled_money_movements_{account.pk}.pdf"'
        return response


class ControlledMoneyAccountStatementPDFView(AdminOrAccountantMixin, View):
    def get(self, request, pk, *args, **kwargs):
        return ControlledMoneyMovementPDFView().get(request, pk, *args, **kwargs)


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
                'reverses__payment'
),
            self.request.user,
            firm_lookup='matter_ledger__trust_account__firm'
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
                    'reverses__payment'
),
                request.user,
                firm_lookup='matter_ledger__trust_account__firm'
),
            pk=pk
)
        return trust_reports.reversal_pdf(reversal)


class ComplianceReviewLogListView(StaffRequiredMixin, ListView):
    model = ComplianceReviewLog
    template_name = "trust/compliance_review_log.html"
    context_object_name = "review_logs"
    paginate_by = 25

    def get_queryset(self):
        return (
            ComplianceReviewLog.objects
            .filter(firm=self.request.user.firm)
            .select_related("matter", "reviewed_by")
            .order_by("-reviewed_on", "-created_at")
        )


class ComplianceReviewLogCreateView(StaffRequiredMixin, CreateView):
    model = ComplianceReviewLog
    form_class = ComplianceReviewLogForm
    template_name = "trust/compliance_review_form.html"
    success_url = reverse_lazy("trust:compliance_review_log")

    def get_initial(self):
        initial = super().get_initial()
        for field in ["severity", "category", "title", "alert_key", "source_url"]:
            value = self.request.GET.get(field)
            if value:
                initial[field] = value
        matter_id = self.request.GET.get("matter")
        if matter_id:
            initial["matter"] = matter_id
        return initial

    def form_valid(self, form):
        form.instance.firm = self.request.user.firm
        form.instance.reviewed_by = self.request.user
        form.instance.reviewed_on = timezone.now()
        return super().form_valid(form)


class ComplianceReviewLogUpdateView(StaffRequiredMixin, UpdateView):
    model = ComplianceReviewLog
    form_class = ComplianceReviewLogForm
    template_name = "trust/compliance_review_form.html"
    success_url = reverse_lazy("trust:compliance_review_log")

    def get_queryset(self):
        return ComplianceReviewLog.objects.filter(firm=self.request.user.firm)

    def form_valid(self, form):
        form.instance.reviewed_by = self.request.user
        form.instance.reviewed_on = timezone.now()
        return super().form_valid(form)


class Section19ComplianceReviewListView(StaffRequiredMixin, ListView):
    model = Section19ComplianceReview
    template_name = "trust/section19_review_list.html"
    context_object_name = "section19_reviews"
    paginate_by = 25

    def get_queryset(self):
        return (
            Section19ComplianceReview.objects
            .filter(firm=self.request.user.firm)
            .select_related("reviewed_by")
            .order_by("-review_period_end", "-created_at")
        )


class Section19ComplianceReviewCreateView(StaffRequiredMixin, CreateView):
    model = Section19ComplianceReview
    form_class = Section19ComplianceReviewForm
    template_name = "trust/section19_review_form.html"
    success_url = reverse_lazy("trust:periodic_compliance_review_list")

    def get_initial(self):
        initial = super().get_initial()
        today = timezone.localdate()

        if today.month >= 4:
            trust_year_start = today.replace(month=4, day=1)
            trust_year_end = today.replace(year=today.year + 1, month=3, day=31)
        else:
            trust_year_start = today.replace(year=today.year - 1, month=4, day=1)
            trust_year_end = today.replace(month=3, day=31)

        initial["review_period_start"] = trust_year_start
        initial["review_period_end"] = trust_year_end
        return initial

    def form_valid(self, form):
        form.instance.firm = self.request.user.firm
        form.instance.reviewed_by = self.request.user
        form.instance.reviewed_on = timezone.now()
        return super().form_valid(form)


class Section19ComplianceReviewUpdateView(StaffRequiredMixin, UpdateView):
    model = Section19ComplianceReview
    form_class = Section19ComplianceReviewForm
    template_name = "trust/section19_review_form.html"
    success_url = reverse_lazy("trust:periodic_compliance_review_list")

    def get_queryset(self):
        return Section19ComplianceReview.objects.filter(firm=self.request.user.firm)

    def form_valid(self, form):
        form.instance.reviewed_by = self.request.user
        form.instance.reviewed_on = timezone.now()
        return super().form_valid(form)


class AnnualTrustComplianceRecordListView(StaffRequiredMixin, ListView):
    model = AnnualTrustComplianceRecord
    template_name = "trust/annual_trust_compliance_list.html"
    context_object_name = "annual_records"
    paginate_by = 25

    def get_queryset(self):
        return (
            AnnualTrustComplianceRecord.objects
            .filter(firm=self.request.user.firm)
            .select_related("reviewed_by")
            .order_by("-trust_year_end", "-created_at")
        )


class AnnualTrustComplianceRecordCreateView(StaffRequiredMixin, CreateView):
    model = AnnualTrustComplianceRecord
    form_class = AnnualTrustComplianceRecordForm
    template_name = "trust/annual_trust_compliance_form.html"
    success_url = reverse_lazy("trust:annual_compliance_list")

    def get_initial(self):
        initial = super().get_initial()
        today = timezone.localdate()

        if today.month >= 4:
            trust_year_end = today.replace(month=3, day=31)
        else:
            trust_year_end = today.replace(year=today.year - 1, month=3, day=31)

        trust_year_start = trust_year_end.replace(year=trust_year_end.year - 1) + timezone.timedelta(days=1)

        initial["trust_year_start"] = trust_year_start
        initial["trust_year_end"] = trust_year_end
        return initial

    def form_valid(self, form):
        form.instance.firm = self.request.user.firm
        form.instance.reviewed_by = self.request.user
        form.instance.reviewed_on = timezone.now()
        return super().form_valid(form)


class AnnualTrustComplianceRecordUpdateView(StaffRequiredMixin, UpdateView):
    model = AnnualTrustComplianceRecord
    form_class = AnnualTrustComplianceRecordForm
    template_name = "trust/annual_trust_compliance_form.html"
    success_url = reverse_lazy("trust:annual_compliance_list")

    def get_queryset(self):
        return AnnualTrustComplianceRecord.objects.filter(firm=self.request.user.firm)

    def form_valid(self, form):
        form.instance.reviewed_by = self.request.user
        form.instance.reviewed_on = timezone.now()
        return super().form_valid(form)


class ComplianceReportView(StaffRequiredMixin, TemplateView):
    template_name = "trust/compliance_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        status = ComplianceService(self.request.user.firm).get_status()
        alerts = status["alerts"]

        alert_keys = [alert.alert_key for alert in alerts if getattr(alert, "alert_key", "")]
        latest_reviews = {}

        if alert_keys:
            logs = (
                ComplianceReviewLog.objects
                .filter(firm=self.request.user.firm, alert_key__in=alert_keys)
                .select_related("matter", "reviewed_by")
                .order_by("alert_key", "-reviewed_on", "-created_at")
            )

            for log in logs:
                if log.alert_key not in latest_reviews:
                    latest_reviews[log.alert_key] = log

        for alert in alerts:
            alert.latest_review = latest_reviews.get(getattr(alert, "alert_key", ""))

        context["compliance_status"] = status
        context["alerts"] = alerts
        context["review_logs"] = (
            ComplianceReviewLog.objects
            .filter(firm=self.request.user.firm)
            .select_related("matter", "reviewed_by")
            .order_by("-reviewed_on", "-created_at")[:100]
        )
        context["periodic_reviews"] = (
            Section19ComplianceReview.objects
            .filter(firm=self.request.user.firm)
            .select_related("reviewed_by")
            .order_by("-review_period_end", "-created_at")[:20]
        )
        context["annual_records"] = (
            AnnualTrustComplianceRecord.objects
            .filter(firm=self.request.user.firm)
            .select_related("reviewed_by")
            .order_by("-trust_year_end", "-created_at")[:20]
        )
        context["generated_on"] = timezone.now()
        return context


class ComplianceCentreView(StaffRequiredMixin, TemplateView):
    template_name = "trust/compliance_centre.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = ComplianceService(self.request.user.firm)
        status = service.get_status()
        alerts = status["alerts"]

        alert_keys = [alert.alert_key for alert in alerts if getattr(alert, "alert_key", "")]
        latest_reviews = {}

        if alert_keys:
            logs = (
                ComplianceReviewLog.objects
                .filter(firm=self.request.user.firm, alert_key__in=alert_keys)
                .select_related("matter", "reviewed_by")
                .order_by("alert_key", "-reviewed_on", "-created_at")
            )

            for log in logs:
                if log.alert_key not in latest_reviews:
                    latest_reviews[log.alert_key] = log

        for alert in alerts:
            alert.latest_review = latest_reviews.get(getattr(alert, "alert_key", ""))

        context["compliance_status"] = status
        context["alerts"] = alerts
        context["review_logs"] = (
            ComplianceReviewLog.objects
            .filter(firm=self.request.user.firm)
            .select_related("matter", "reviewed_by")
            .order_by("-reviewed_on", "-created_at")[:5]
        )
        return context
