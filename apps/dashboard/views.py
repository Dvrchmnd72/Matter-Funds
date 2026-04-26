from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.db.models import Sum

from apps.matters.models import Matter
from apps.trust.models import TrustAccount, MatterLedger, MonthlyReconciliation, Irregularity


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/index.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        if user.role == 'admin':
            open_matters = Matter.objects.filter(status='open').count()
            trust_accounts = TrustAccount.objects.filter(is_active=True).count()
            total_balance = MatterLedger.objects.aggregate(t=Sum('balance'))['t'] or Decimal('0.00')
            unreconciled = MonthlyReconciliation.objects.filter(is_reconciled=False).count()
            open_irregularities = Irregularity.objects.filter(resolution='').count()
        else:
            firm = user.firm
            if firm:
                open_matters = Matter.objects.filter(status='open', firm=firm).count()
                trust_accounts = TrustAccount.objects.filter(is_active=True, firm=firm).count()
                total_balance = MatterLedger.objects.filter(
                    trust_account__firm=firm
                ).aggregate(t=Sum('balance'))['t'] or Decimal('0.00')
                unreconciled = MonthlyReconciliation.objects.filter(
                    is_reconciled=False, trust_account__firm=firm
                ).count()
                open_irregularities = Irregularity.objects.filter(
                    resolution='', trust_account__firm=firm
                ).count()
            else:
                open_matters = trust_accounts = unreconciled = open_irregularities = 0
                total_balance = Decimal('0.00')
        ctx.update({
            'open_matters': open_matters,
            'trust_accounts': trust_accounts,
            'total_balance': total_balance,
            'unreconciled': unreconciled,
            'open_irregularities': open_irregularities,
        })
        return ctx
