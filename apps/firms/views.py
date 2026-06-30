from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, UpdateView

from apps.accounts.permissions import AdminRequiredMixin
from .models import Firm
from .forms import FirmForm


class FirmListView(AdminRequiredMixin, ListView):
    model = Firm
    template_name = 'firms/firm_list.html'
    context_object_name = 'firms'


class FirmCreateView(AdminRequiredMixin, CreateView):
    model = Firm
    form_class = FirmForm
    template_name = 'firms/firm_form.html'
    success_url = reverse_lazy('firms:firm_list')

    def form_valid(self, form):
        messages.success(self.request, 'Firm created successfully.')
        return super().form_valid(form)


class FirmDetailView(AdminRequiredMixin, DetailView):
    model = Firm
    template_name = 'firms/firm_detail.html'
    context_object_name = 'firm'


class FirmUpdateView(AdminRequiredMixin, UpdateView):
    model = Firm
    form_class = FirmForm
    template_name = 'firms/firm_form.html'

    def get_success_url(self):
        messages.success(self.request, 'Firm details updated successfully.')
        return reverse_lazy('firms:firm_detail', kwargs={'pk': self.object.pk})
