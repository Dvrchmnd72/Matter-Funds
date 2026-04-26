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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Firm'
        verbose_name_plural = 'Firms'

    def __str__(self):
        return self.name
