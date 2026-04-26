from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.trust.models import TrustTransaction, MatterLedger
from .models import AuditLog


@receiver(post_save, sender=TrustTransaction)
def log_trust_transaction(sender, instance, created, **kwargs):
    if not created:
        return
    content_type = ContentType.objects.get_for_model(instance)
    AuditLog.objects.create(
        action='create',
        content_type=content_type,
        object_id=instance.pk,
        object_repr=str(instance)[:200],
        after_json={
            'transaction_type': instance.transaction_type,
            'amount': str(instance.amount),
            'date': str(instance.date_received_or_paid),
            'description': instance.description,
        },
    )


@receiver(post_save, sender=MatterLedger)
def log_matter_ledger(sender, instance, created, **kwargs):
    if not created:
        return
    content_type = ContentType.objects.get_for_model(instance)
    AuditLog.objects.create(
        action='create',
        content_type=content_type,
        object_id=instance.pk,
        object_repr=str(instance)[:200],
        after_json={
            'matter': str(instance.matter),
            'trust_account': str(instance.trust_account),
            'balance': str(instance.balance),
        },
    )
