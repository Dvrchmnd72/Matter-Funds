# Generated manually for simplified Phase A monthly close.

import calendar
import datetime
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def month_start(date_value):
    return datetime.date(date_value.year, date_value.month, 1)


def month_end(date_value):
    return datetime.date(
        date_value.year,
        date_value.month,
        calendar.monthrange(date_value.year, date_value.month)[1],
    )


def backfill_accounting_periods(apps, schema_editor):
    MonthlyReconciliation = apps.get_model('trust', 'MonthlyReconciliation')
    TrustAccountingPeriod = apps.get_model('trust', 'TrustAccountingPeriod')
    for reconciliation in MonthlyReconciliation.objects.all():
        period_start = month_start(reconciliation.period_end)
        period_end = month_end(reconciliation.period_end)
        period, _ = TrustAccountingPeriod.objects.get_or_create(
            trust_account_id=reconciliation.trust_account_id,
            period_start=period_start,
            period_end=period_end,
            defaults={'status': 'open'},
        )
        reconciliation.accounting_period_id = period.pk
        reconciliation.save(update_fields=['accounting_period'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('trust', '0002_payment_costs_transfer_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='TrustAccountingPeriod',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('status', models.CharField(choices=[('open', 'Open'), ('locked', 'Locked')], default='open', max_length=10)),
                ('locked_on', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('locked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='trust_periods_locked', to=settings.AUTH_USER_MODEL)),
                ('trust_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='accounting_periods', to='trust.trustaccount')),
            ],
            options={
                'verbose_name': 'Trust Accounting Period',
                'verbose_name_plural': 'Trust Accounting Periods',
                'ordering': ['-period_end'],
            },
        ),
        migrations.AddField(
            model_name='monthlyreconciliation',
            name='accounting_period',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reconciliation', to='trust.trustaccountingperiod'),
        ),
        migrations.AddField(
            model_name='monthlyreconciliation',
            name='finalised_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='trust_reconciliations_finalised', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='monthlyreconciliation',
            name='finalised_on',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='monthlyreconciliation',
            name='is_finalised',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='TrustMonthlyRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('record_type', models.CharField(choices=[('receipts_cash_book', 'Receipts Cash Book'), ('payments_cash_book', 'Payments Cash Book'), ('trust_transfer_journal', 'Trust Transfer Journal'), ('trial_balance', 'Trial Balance'), ('reconciliation_statement', 'Reconciliation Statement')], max_length=40)),
                ('pdf', models.FileField(upload_to='trust/monthly-records/')),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('sha256_hash', models.CharField(max_length=64)),
                ('accounting_period', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='monthly_records', to='trust.trustaccountingperiod')),
                ('generated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='trust_monthly_records_generated', to=settings.AUTH_USER_MODEL)),
                ('reconciliation', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='monthly_records', to='trust.monthlyreconciliation')),
                ('trust_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='monthly_records', to='trust.trustaccount')),
            ],
            options={
                'verbose_name': 'Trust Monthly Record',
                'verbose_name_plural': 'Trust Monthly Records',
                'ordering': ['-generated_at'],
            },
        ),
        migrations.RunPython(backfill_accounting_periods, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='trustaccountingperiod',
            constraint=models.UniqueConstraint(fields=('trust_account', 'period_start', 'period_end'), name='unique_trust_accounting_period'),
        ),
        migrations.AddConstraint(
            model_name='trustaccountingperiod',
            constraint=models.CheckConstraint(check=models.Q(period_start__lte=models.F('period_end')), name='trust_period_start_lte_end'),
        ),
        migrations.AddIndex(
            model_name='trustaccountingperiod',
            index=models.Index(fields=['trust_account', 'period_start', 'period_end'], name='trust_trust_trust_a_7e3252_idx'),
        ),
        migrations.AddIndex(
            model_name='trustaccountingperiod',
            index=models.Index(fields=['trust_account', 'status'], name='trust_trust_trust_a_35b8b4_idx'),
        ),
        migrations.AddConstraint(
            model_name='trustmonthlyrecord',
            constraint=models.UniqueConstraint(fields=('accounting_period', 'record_type'), name='unique_monthly_record_type_per_period'),
        ),
        migrations.AddIndex(
            model_name='trustmonthlyrecord',
            index=models.Index(fields=['trust_account', 'record_type'], name='trust_trust_trust_a_8acced_idx'),
        ),
        migrations.AddIndex(
            model_name='trustmonthlyrecord',
            index=models.Index(fields=['trust_account', 'generated_at'], name='trust_trust_trust_a_8764ca_idx'),
        ),
    ]
