# Generated manually for Section 3 NSW costs-transfer evidence fields.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trust', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='authority_or_agreement_file',
            field=models.FileField(blank=True, null=True, upload_to='trust/costs/authorities/'),
        ),
        migrations.AddField(
            model_name='payment',
            name='costs_evidence_file',
            field=models.FileField(blank=True, null=True, upload_to='trust/costs/evidence/'),
        ),
        migrations.AddField(
            model_name='payment',
            name='costs_withdrawal_method',
            field=models.CharField(blank=True, default='', choices=[('method_1_bill_issued', 'Method 1 - Bill issued'), ('method_2_authority', 'Method 2 - Authority'), ('method_3_reimbursement', 'Method 3 - Reimbursement'), ('method_4_commercial_government', 'Method 4 - Commercial/Government client')], max_length=40),
        ),
        migrations.AddField(
            model_name='payment',
            name='costs_withdrawal_notes',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='payment',
            name='key_evidence_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='notice_or_request_file',
            field=models.FileField(blank=True, null=True, upload_to='trust/costs/notices/'),
        ),
        migrations.AddField(
            model_name='payment',
            name='reimbursement_evidence_file',
            field=models.FileField(blank=True, null=True, upload_to='trust/costs/reimbursements/'),
        ),
    ]
