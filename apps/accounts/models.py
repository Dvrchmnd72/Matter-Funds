from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model with Matter Funds access roles and MF2FA readiness."""

    ROLE_PLATFORM_ADMIN = 'platform_admin'
    ROLE_FIRM_ADMIN = 'firm_admin'
    ROLE_PRINCIPAL = 'principal'
    ROLE_AUTHORISED_TRUST_USER = 'authorised_trust_user'
    ROLE_ACCOUNTANT = 'accountant'
    ROLE_STAFF = 'staff'
    ROLE_EXTERNAL_EXAMINER = 'external_examiner'
    ROLE_CLIENT = 'client'

    # Legacy roles retained during Phase 22 migration.
    ROLE_ADMIN = 'admin'
    ROLE_SOLICITOR = 'solicitor'

    ROLE_CHOICES = [
        (ROLE_PLATFORM_ADMIN, 'Matter Funds platform admin'),
        (ROLE_FIRM_ADMIN, 'Firm admin'),
        (ROLE_PRINCIPAL, 'Principal / trust compliance owner'),
        (ROLE_AUTHORISED_TRUST_USER, 'Authorised trust user'),
        (ROLE_ACCOUNTANT, 'Accountant / bookkeeper'),
        (ROLE_STAFF, 'Staff'),
        (ROLE_EXTERNAL_EXAMINER, 'External examiner / read-only reviewer'),
        (ROLE_CLIENT, 'Client'),
        (ROLE_ADMIN, 'Legacy administrator'),
        (ROLE_SOLICITOR, 'Legacy solicitor'),
    ]

    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=ROLE_STAFF)
    phone = models.CharField(max_length=20, blank=True)
    firm = models.ForeignKey(
        'firms.Firm',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='members',
    )

    is_firm_approved = models.BooleanField(
        default=False,
        help_text='Whether the user has been approved by the firm principal/admin to access this firm.'
    )
    mf2fa_required = models.BooleanField(
        default=True,
        help_text='Matter Funds 2FA requirement. Production users should not access Matter Funds without MF2FA.'
    )
    mf2fa_enabled = models.BooleanField(
        default=False,
        help_text='Whether the user has completed Matter Funds 2FA setup.'
    )

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.email or self.username

    @property
    def is_platform_admin_role(self):
        return self.is_superuser or self.role in {self.ROLE_PLATFORM_ADMIN, self.ROLE_ADMIN}

    @property
    def is_firm_admin_role(self):
        return self.role in {self.ROLE_FIRM_ADMIN, self.ROLE_PRINCIPAL, self.ROLE_ADMIN}

    @property
    def can_prepare_trust_records(self):
        return self.role in {
            self.ROLE_PLATFORM_ADMIN,
            self.ROLE_FIRM_ADMIN,
            self.ROLE_PRINCIPAL,
            self.ROLE_AUTHORISED_TRUST_USER,
            self.ROLE_ACCOUNTANT,
            self.ROLE_ADMIN,
            self.ROLE_SOLICITOR,
        }

    @property
    def is_external_examiner_role(self):
        return self.role == self.ROLE_EXTERNAL_EXAMINER

