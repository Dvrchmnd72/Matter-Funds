import datetime

from django.conf import settings
from django.db import models, transaction


class Matter(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('closed', 'Closed'),
    ]

    firm = models.ForeignKey('firms.Firm', on_delete=models.PROTECT)
    file_number = models.CharField(max_length=20, blank=True)
    description = models.CharField(max_length=500)
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT)
    responsible_lawyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    opened_on = models.DateField(default=datetime.date.today)
    closed_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('firm', 'file_number')]
        verbose_name = 'Matter'
        verbose_name_plural = 'Matters'

    def __str__(self):
        return f"{self.file_number} \u2013 {self.description}"

    def save(self, *args, **kwargs):
        if not self.file_number:
            from apps.firms.models import Firm
            with transaction.atomic():
                # Lock the firm row to serialise concurrent file-number generation.
                Firm.objects.select_for_update().get(pk=self.firm_id)
                year = datetime.date.today().year
                sequence = Matter.objects.filter(firm_id=self.firm_id).count() + 1
                self.file_number = f"{year}-{sequence:06d}"
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

        self.ensure_default_trust_ledger()

    def ensure_default_trust_ledger(self):
        """Create the matter's trust ledger under the firm's active general trust account.

        The trust bank account remains one general trust account. This creates the
        required matter-level sub-ledger used for receipts, payments, journals,
        ledger statements and trial balance reporting.
        """
        from apps.trust.models import MatterLedger, TrustAccount

        trust_account = (
            TrustAccount.objects
            .filter(firm_id=self.firm_id, is_general=True, is_active=True)
            .order_by("pk")
            .first()
        )
        if trust_account:
            MatterLedger.objects.get_or_create(
                matter=self,
                trust_account=trust_account,
            )
