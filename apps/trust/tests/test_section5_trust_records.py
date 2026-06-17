import datetime
import io
import zipfile
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from apps.clients.models import Client
from apps.firms.models import Firm
from apps.matters.models import Matter
from apps.trust import reports as trust_reports
from apps.trust.models import (
    ControlledMoneyAccount, ControlledMoneyMonthlyStatement, ControlledMoneyReceipt,
    ControlledMoneyWithdrawal, MatterLedger, MonthlyReconciliation, TrustAccount,
    TrustAccountingPeriod, TrustMonthlyRecord,
)
from apps.trust.services import create_payment, create_receipt

User = get_user_model()


class Section5TrustRecordCompletenessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass', role='admin')
        self.other = User.objects.create_user(username='other', password='pass', role='admin')
        self.firm = Firm.objects.create(name='Example Law', abn='12345678901', address='1 Street', principal_solicitor=self.admin)
        self.other_firm = Firm.objects.create(name='Other Law', abn='12345678902', address='2 Street', principal_solicitor=self.other)
        self.client = Client.objects.create(firm=self.firm, client_type='individual', name='Jane Client', address='3 Street')
        self.matter = Matter.objects.create(firm=self.firm, client=self.client, description='Purchase of land', responsible_lawyer=self.admin, file_number='M-1')
        self.trust = TrustAccount.objects.create(firm=self.firm, name='General Trust', bank='Bank', bsb='012-345', account_number='123456')
        self.ledger = MatterLedger.objects.create(matter=self.matter, trust_account=self.trust)

    def test_trust_account_statement_rows_filter_and_running_balances(self):
        create_receipt(matter_ledger=self.ledger, amount=Decimal('100.00'), date_received=datetime.date(2024, 1, 10), payor_name='Jane', payment_method='eft', purpose='Initial', created_by=self.admin)
        create_receipt(matter_ledger=self.ledger, amount=Decimal('50.00'), date_received=datetime.date(2024, 2, 10), payor_name='Jane', payment_method='eft', purpose='Top up', created_by=self.admin)
        create_payment(matter_ledger=self.ledger, amount=Decimal('20.00'), date_paid=datetime.date(2024, 2, 20), payee_name='Vendor', payment_method='eft', purpose='Settlement', authorised_by=self.admin, created_by=self.admin)

        _from, _to, opening, receipts, payments, journals, closing, rows = trust_reports.trust_account_statement_rows(
            self.ledger, datetime.date(2024, 2, 1), datetime.date(2024, 2, 29)
        )

        self.assertEqual(opening, Decimal('100.00'))
        self.assertEqual(receipts, Decimal('50.00'))
        self.assertEqual(payments, Decimal('20.00'))
        self.assertEqual(journals, Decimal('0.00'))
        self.assertEqual(closing, Decimal('130.00'))
        self.assertEqual([r[-1] for r in rows], ['150.00', '130.00'])

    def test_trust_account_statement_pdf_generated(self):
        with patch.object(trust_reports, '_build_pdf_document', side_effect=lambda buffer, *args, **kwargs: buffer.write(b'pdf')):
            self.assertEqual(trust_reports.trust_account_statement_pdf_bytes(self.ledger, datetime.date(2024, 1, 1), datetime.date(2024, 1, 31)), b'pdf')

    def test_export_pack_uses_retained_monthly_records_without_duplicate_generated_reports(self):
        period = TrustAccountingPeriod.objects.create(
            trust_account=self.trust,
            period_start=datetime.date(2024, 3, 1),
            period_end=datetime.date(2024, 3, 31),
            status=TrustAccountingPeriod.STATUS_LOCKED,
            locked_by=self.admin,
            locked_on=timezone.now(),
        )
        reconciliation = MonthlyReconciliation.objects.create(
            trust_account=self.trust,
            accounting_period=period,
            period_end=datetime.date(2024, 3, 31),
            cash_book_balance=Decimal('0.00'),
            ledger_total_balance=Decimal('0.00'),
            bank_statement_balance=Decimal('0.00'),
            is_reconciled=True,
        )
        for record_type in (
            TrustMonthlyRecord.RECORD_RECONCILIATION_STATEMENT,
            TrustMonthlyRecord.RECORD_TRIAL_BALANCE,
        ):
            record = TrustMonthlyRecord.objects.create(
                accounting_period=period,
                reconciliation=reconciliation,
                trust_account=self.trust,
                record_type=record_type,
                generated_by=self.admin,
                sha256_hash='0' * 64,
            )
            record.pdf.save(f'{record_type}_2024-03-31.pdf', ContentFile(b'%PDF retained'), save=True)

        with patch.object(trust_reports, 'trial_balance_pdf_bytes', side_effect=AssertionError('must not regenerate trial balance')), \
             patch.object(trust_reports, 'reconciliation_statement_pdf_bytes', side_effect=AssertionError('must not regenerate reconciliation')), \
             patch.object(trust_reports, '_build_pdf_document', side_effect=lambda buffer, *args, **kwargs: buffer.write(b'pdf')):
            response = trust_reports.trust_records_export_pack_zip(self.trust, datetime.date(2024, 3, 1), datetime.date(2024, 3, 31))

        names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
        self.assertIn('retained-monthly-records/2024-03-31/reconciliation_statement.pdf', names)
        self.assertIn('retained-monthly-records/2024-03-31/trial_balance.pdf', names)
        self.assertNotIn('generated-reports/reconciliations/reconciliation_2024-03-31.pdf', names)
        self.assertNotIn('generated-reports/trial_balance.pdf', names)

    def test_cma_validation_receipt_sequence_and_withdrawal_controls(self):
        with self.assertRaises(ValidationError):
            ControlledMoneyAccount.objects.create(firm=self.firm, client=self.client, account_name='Jane savings', bank='Bank', bsb='012-345', account_number='1', purpose='Land')
        cma = ControlledMoneyAccount.objects.create(firm=self.firm, client=self.client, matter=self.matter, account_name='Example Law CMA/c Jane Client', bank='Bank', bsb='012-345', account_number='2', purpose='Purchase settlement funds')
        r1 = ControlledMoneyReceipt.objects.create(firm=self.firm, controlled_money_account=cma, amount=Decimal('75.00'), payment_method='eft', person_from_whom_received='Jane', person_on_behalf='Jane Client', matter_description='Purchase of land', matter_reference='M-1', reason='Deposit', made_out_by=self.admin)
        r2 = ControlledMoneyReceipt.objects.create(firm=self.firm, controlled_money_account=cma, amount=Decimal('25.00'), payment_method='eft', person_from_whom_received='Jane', person_on_behalf='Jane Client', matter_description='Purchase of land', matter_reference='M-1', reason='Deposit', made_out_by=self.admin)
        self.assertEqual((r1.receipt_number, r2.receipt_number), (1, 2))
        with self.assertRaises(PermissionError):
            r1.delete()
        cma.refresh_from_db()
        with self.assertRaises(ValidationError):
            ControlledMoneyWithdrawal.objects.create(controlled_money_account=cma, date=datetime.date(2024, 2, 1), transaction_number='W1', amount=Decimal('200.00'), withdrawal_method='eft', destination_account_name='Vendor', destination_account_number='9', destination_bsb='012-345', person_on_behalf='Jane Client', matter_reference='M-1', reason='Settlement', authorised_by='Principal')
        withdrawal = ControlledMoneyWithdrawal.objects.create(controlled_money_account=cma, date=datetime.date(2024, 2, 1), transaction_number='W2', amount=Decimal('20.00'), withdrawal_method='eft', destination_account_name='Vendor', destination_account_number='9', destination_bsb='012-345', person_on_behalf='Jane Client', matter_reference='M-1', reason='Settlement', authorised_by='Principal')
        self.assertEqual(withdrawal.withdrawal_method, 'eft')

    def test_controlled_money_monthly_statement_due_date_and_export_pack(self):
        ControlledMoneyMonthlyStatement.objects.create(firm=self.firm, period_end=datetime.date(2024, 3, 31), reviewed_by=self.admin, reviewed_on=datetime.date(2024, 4, 10), reviewer_role_confirmation='principal')
        with patch.object(trust_reports, '_build_pdf_document', side_effect=lambda buffer, *args, **kwargs: buffer.write(b'pdf')):
            response = trust_reports.trust_records_export_pack_zip(self.trust, datetime.date(2024, 3, 1), datetime.date(2024, 3, 31))
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        names = zf.namelist()
        self.assertIn('README.txt', names)
        self.assertNotIn('manifest.json', names)
        self.assertNotIn('SHA256SUMS.txt', names)
        self.assertIn('controlled-money/monthly-statements/2024-03-31.pdf', names)
        self.assertIn('exports/trust_transactions.csv', names)
