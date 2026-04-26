from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView

from apps.accounts.permissions import StaffRequiredMixin
from .models import Client
from .forms import ClientForm


class ClientListView(StaffRequiredMixin, ListView):
    model = Client
    template_name = 'clients/client_list.html'
    context_object_name = 'clients'

    def get_queryset(self):
        qs = super().get_queryset().select_related('firm')
        user = self.request.user
        if user.role != 'admin' and user.firm:
            qs = qs.filter(firm=user.firm)
        return qs


class ClientCreateView(StaffRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = 'clients/client_form.html'
    success_url = reverse_lazy('clients:client_list')

    def form_valid(self, form):
        messages.success(self.request, 'Client created successfully.')
        return super().form_valid(form)


class ClientDetailView(StaffRequiredMixin, DetailView):
    model = Client
    template_name = 'clients/client_detail.html'
    context_object_name = 'client'
