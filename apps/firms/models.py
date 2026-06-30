from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


abn_validator = RegexValidator(r'^\d{11}$', 'ABN must be exactly 11 digits.')

JURISDICTION_CHOICES = [
    ('NSW', 'New South Wales'),
    ('VIC', 'Victoria'),
    ('QLD', 'Queensland'),
    ('WA', 'Western Australia'),
    ('SA', 'South Australia'),
    ('TAS', 'Tasmania'),
    ('ACT', 'Australian Capital Territory'),
    ('NT', 'Northern Territory'),
]


class Firm(models.Model):
    ACCESS_MODEL_SAAS = 'saas'
    ACCESS_MODEL_PERPETUAL = 'perpetual'

    ACCESS_MODEL_CHOICES = [
        (ACCESS_MODEL_SAAS, 'Monthly SaaS subscription'),
        (ACCESS_MODEL_PERPETUAL, 'Perpetual licence'),
    ]

    SUBSCRIPTION_ACTIVE = 'active'
    SUBSCRIPTION_TRIAL = 'trial'
    SUBSCRIPTION_GRACE = 'grace'
    SUBSCRIPTION_READ_ONLY = 'read_only'
    SUBSCRIPTION_SUSPENDED = 'suspended'

    SUBSCRIPTION_STATUS_CHOICES = [
        (SUBSCRIPTION_ACTIVE, 'Active'),
        (SUBSCRIPTION_TRIAL, 'Trial'),
        (SUBSCRIPTION_GRACE, 'Grace period'),
        (SUBSCRIPTION_READ_ONLY, 'Read-only compliance access'),
        (SUBSCRIPTION_SUSPENDED, 'Suspended'),
    ]

    name = models.CharField(max_length=255)
    abn = models.CharField(max_length=11, validators=[abn_validator])
    address = models.TextField()
    principal_solicitor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='principal_of',
    )
    is_sole_practitioner = models.BooleanField(default=False)
    jurisdiction = models.CharField(max_length=3, choices=JURISDICTION_CHOICES, default='NSW')

    access_model = models.CharField(
        max_length=20,
        choices=ACCESS_MODEL_CHOICES,
        default=ACCESS_MODEL_SAAS,
        help_text='Commercial access model for the law practice.'
    )
    subscription_status = models.CharField(
        max_length=20,
        choices=SUBSCRIPTION_STATUS_CHOICES,
        default=SUBSCRIPTION_TRIAL,
        help_text='Current Matter Funds access status for this law practice.'
    )
    subscription_started_on = models.DateField(null=True, blank=True)
    subscription_renews_on = models.DateField(null=True, blank=True)

    licence_key = models.CharField(max_length=80, blank=True)
    licence_issued_on = models.DateField(null=True, blank=True)
    licence_maintenance_expires_on = models.DateField(null=True, blank=True)

    read_only_reason = models.TextField(blank=True)

    mf2fa_mandatory = models.BooleanField(
        default=True,
        help_text='Firm-level requirement that all production users must use Matter Funds 2FA.'
    )
    allow_self_registration = models.BooleanField(
        default=False,
        help_text='If enabled, users may request access to this firm. Approval is still required.'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Firm'
        verbose_name_plural = 'Firms'

    def __str__(self):
        return self.name
