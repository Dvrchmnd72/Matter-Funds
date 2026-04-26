from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model with role and contact fields."""

    ROLE_CHOICES = [
        ('admin', 'Administrator'),
        ('solicitor', 'Solicitor'),
        ('accountant', 'Accountant'),
        ('client', 'Client'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='client')
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.email or self.username
