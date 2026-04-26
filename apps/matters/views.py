from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, CreateView, DetailView

from apps.accounts.permissions import StaffRequiredMixin
from apps.trust.models import MatterLedger
from .models import Matter
from .forms import MatterForm, MatterLedgerForm


class MatterListView(StaffRequiredMixin, ListView):
    model = Matter
    template_name = 'matters/matter_list.html'
    context_object_name = 'matters'

    def get_queryset(self):
        qs = super().get_queryset().select_related('firm', 'client', 'responsible_lawyer')
        user = self.request.user
        if user.role != 'admin' and user.firm:
            qs = qs.filter(firm=user.firm)
        return qs


class MatterCreateView(StaffRequiredMixin, CreateView):
    model = Matter
    form_class = MatterForm
    template_name = 'matters/matter_form.html'
    success_url = reverse_lazy('matters:matter_list')

    def form_valid(self, form):
        messages.success(self.request, 'Matter created successfully.')
        return super().form_valid(form)


class MatterDetailView(StaffRequiredMixin, DetailView):
    model = Matter
    template_name = 'matters/matter_detail.html'
    context_object_name = 'matter'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['ledgers'] = self.object.ledgers.select_related('trust_account').prefetch_related('transactions')
        return ctx


class MatterLedgerCreateView(StaffRequiredMixin, CreateView):
    model = MatterLedger
    form_class = MatterLedgerForm
    template_name = 'matters/ledger_form.html'

    def get_matter(self):
        return get_object_or_404(Matter, pk=self.kwargs['matter_pk'])

    def form_valid(self, form):
        form.instance.matter = self.get_matter()
        messages.success(self.request, 'Ledger created successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('matters:matter_detail', kwargs={'pk': self.kwargs['matter_pk']})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['matter'] = self.get_matter()
        return ctx
