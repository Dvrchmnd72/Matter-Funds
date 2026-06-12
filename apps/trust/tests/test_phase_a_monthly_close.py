import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.firms.models import Firm
from apps.matters.models import Matter
from apps.trust import reports as trust_reports
from apps.trust.models import (
    MatterLedger,
    MonthlyReconciliation,
    TrustAccount,
    TrustAccountingPeriod,
    TrustMonthlyRecord,
)
from apps.trust.services import (
    create_payment,
    create_receipt,
    create_transfer_to_office,
    create_trust_journal,
    finalise_reconciliation,
    get_or_create_accounting_period,
    lock_accounting_period,
    required_monthly_record_types,
    reverse_transaction,
)

User = get_user_model()


class PhaseAMonthlyCloseTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='phase_admin', password='pass', role='admin')
        self.solicitor = User.objects.create_user(username='phase_solicitor', password='pass', role='solicitor')
        self.firm = Firm.objects.create(
            name='Phase Firm', abn='12345678901', address='1 Phase St',
            principal_solicitor=self.admin, jurisdiction='NSW', is_sole_practitioner=True,
        )
        self.admin.firm = self.firm
        self.admin.save(update_fields=['firm'])
        self.solicitor.firm = self.firm
        self.solicitor.save(update_fields=['firm'])
        self.client_obj = Client.objects.create(firm=self.firm, client_type='individual', name='Phase Client')
        self.matter = Matter.objects.create(
            firm=self.firm, description='Phase Matter', client=self.client_obj,
            responsible_lawyer=self.solicitor, file_number='P001',
        )
        self.matter2 = Matter.objects.create(
            firm=self.firm, description='Phase Matter 2', client=self.client_obj,
            responsible_lawyer=self.solicitor, file_number='P002',
        )
        self.trust_account = TrustAccount.objects.create(
            firm=self.firm, name='Phase Trust', bank='CBA', bsb='062-000', account_number='123456789',
        )
        self.ledger = MatterLedger.objects.create(matter=self.matter, trust_account=self.trust_account)
        self.ledger2 = MatterLedger.objects.create(matter=self.matter2, trust_account=self.trust_account)
        self.period_end = datetime.date(2024, 1, 31)
        self.txn_date = datetime.date(2024, 1, 15)

    def create_balanced_reconciliation(self):
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'), date_received=self.txn_date,
            payor_name='Client', payment_method='eft', purpose='Retainer', created_by=self.admin,
        )
        period = get_or_create_accounting_period(self.trust_account, self.period_end)
        return MonthlyReconciliation.objects.create(
            trust_account=self.trust_account,
            accounting_period=period,
            period_end=self.period_end,
            cash_book_balance=Decimal('1000.00'),
            ledger_total_balance=Decimal('1000.00'),
            bank_statement_balance=Decimal('1000.00'),
            unpresented_cheques_total=Decimal('0.00'),
            outstanding_deposits_total=Decimal('0.00'),
            bank_statement_pdf=SimpleUploadedFile('statement.pdf', b'bank statement', content_type='application/pdf'),
        )

    def finalise_and_lock_period(self):
        reconciliation = self.create_balanced_reconciliation()
        finalise_reconciliation(reconciliation, self.admin)
        reconciliation.refresh_from_db()
        period = lock_accounting_period(reconciliation.accounting_period, self.admin)
        return reconciliation, period

    def test_period_validation_and_duplicate_periods(self):
        period = TrustAccountingPeriod(
            trust_account=self.trust_account,
            period_start=datetime.date(2024, 1, 1),
            period_end=datetime.date(2024, 1, 31),
        )
        period.full_clean()
        period.save()

        invalid_start = TrustAccountingPeriod(
            trust_account=self.trust_account,
            period_start=datetime.date(2024, 1, 2),
            period_end=datetime.date(2024, 1, 31),
        )
        with self.assertRaises(ValidationError):
            invalid_start.full_clean()

        invalid_end = TrustAccountingPeriod(
            trust_account=self.trust_account,
            period_start=datetime.date(2024, 2, 1),
            period_end=datetime.date(2024, 2, 27),
        )
        with self.assertRaises(ValidationError):
            invalid_end.full_clean()

        with self.assertRaises(IntegrityError):
            TrustAccountingPeriod.objects.create(
                trust_account=self.trust_account,
                period_start=datetime.date(2024, 1, 1),
                period_end=datetime.date(2024, 1, 31),
            )

    def test_finalisation_requires_balanced_reconciliation(self):
        period = get_or_create_accounting_period(self.trust_account, self.period_end)
        reconciliation = MonthlyReconciliation.objects.create(
            trust_account=self.trust_account,
            accounting_period=period,
            period_end=self.period_end,
            cash_book_balance=Decimal('1000.00'),
            ledger_total_balance=Decimal('900.00'),
            bank_statement_balance=Decimal('1000.00'),
            bank_statement_pdf=SimpleUploadedFile('statement.pdf', b'bank statement', content_type='application/pdf'),
        )
        self.assertFalse(reconciliation.is_reconciled)
        with self.assertRaises(ValidationError):
            finalise_reconciliation(reconciliation, self.admin)

    def test_finalisation_creates_all_monthly_records_with_hashes(self):
        reconciliation = self.create_balanced_reconciliation()
        finalised = finalise_reconciliation(reconciliation, self.admin)
        finalised.refresh_from_db()
        self.assertTrue(finalised.is_finalised)
        self.assertEqual(finalised.finalised_by, self.admin)
        self.assertIsNotNone(finalised.finalised_on)
        self.assertEqual(finalised.monthly_records.count(), 5)
        self.assertEqual(
            set(finalised.monthly_records.values_list('record_type', flat=True)),
            set(required_monthly_record_types()),
        )
        for record in finalised.monthly_records.all():
            self.assertTrue(record.pdf)
            self.assertEqual(len(record.sha256_hash), 64)
            self.assertEqual(record.generated_by, self.admin)

    def test_finalised_reconciliation_and_monthly_records_are_immutable(self):
        reconciliation = self.create_balanced_reconciliation()
        finalise_reconciliation(reconciliation, self.admin)
        reconciliation.refresh_from_db()
        reconciliation.cash_book_balance = Decimal('1.00')
        with self.assertRaises(PermissionError):
            reconciliation.save()
        with self.assertRaises(PermissionError):
            reconciliation.delete()

        record = reconciliation.monthly_records.first()
        record.sha256_hash = '0' * 64
        with self.assertRaises(PermissionError):
            record.save()
        with self.assertRaises(PermissionError):
            record.delete()

    def test_locked_period_cannot_be_deleted_and_blocks_transactions(self):
        reconciliation, period = self.finalise_and_lock_period()
        with self.assertRaises(PermissionError):
            period.delete()

        with self.assertRaises(ValidationError):
            create_receipt(
                matter_ledger=self.ledger, amount=Decimal('10.00'), date_received=self.txn_date,
                payor_name='Client', payment_method='eft', purpose='Locked receipt', created_by=self.admin,
            )

        current_receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('100.00'), date_received=datetime.date.today(),
            payor_name='Client', payment_method='eft', purpose='Current receipt', created_by=self.admin,
        )
        current_period = get_or_create_accounting_period(self.trust_account, datetime.date.today())
        current_period.status = TrustAccountingPeriod.STATUS_LOCKED
        current_period.locked_by = self.admin
        current_period.locked_on = timezone.now()
        current_period.full_clean()
        current_period.save()

        with self.assertRaises(ValidationError):
            create_trust_journal(
                from_ledger=self.ledger, to_ledger=self.ledger2, amount=Decimal('10.00'),
                description='Locked journal', written_authority_file='authority.pdf',
                authority_date=datetime.date.today(), authority_signed_by='Client', created_by=self.admin,
            )
        with self.assertRaises(ValidationError):
            reverse_transaction(transaction_obj=current_receipt.transaction, reason='Locked reversal', created_by=self.admin)
        with self.assertRaises(ValidationError):
            create_payment(
                matter_ledger=self.ledger, amount=Decimal('10.00'), date_paid=self.txn_date,
                payee_name='Payee', payment_method='eft', purpose='Locked payment',
                authorised_by=self.admin, created_by=self.admin,
            )
        with self.assertRaises(ValidationError):
            create_transfer_to_office(
                matter_ledger=self.ledger, amount=Decimal('10.00'), date_paid=self.txn_date,
                payee_name='Office', payee_bsb='062-000', payee_account='123456789',
                payment_method='eft', purpose='Locked transfer', authorised_by=self.admin,
                created_by=self.admin, costs_withdrawal_method='method_1_bill_issued',
                costs_evidence_file=SimpleUploadedFile('bill.pdf', b'bill evidence'),
            )

    def test_open_period_workflows_and_report_endpoints_still_work(self):
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('500.00'), date_received=datetime.date(2024, 2, 1),
            payor_name='Client', payment_method='eft', purpose='Open receipt', created_by=self.admin,
        )
        payment = create_payment(
            matter_ledger=self.ledger, amount=Decimal('100.00'), date_paid=datetime.date(2024, 2, 2),
            payee_name='Payee', payment_method='eft', purpose='Open payment',
            authorised_by=self.admin, created_by=self.admin,
        )
        self.assertIsNotNone(payment.pk)
        self.assertEqual(MatterLedger.objects.get(pk=self.ledger.pk).balance, Decimal('400.00'))

        transfer = create_transfer_to_office(
            matter_ledger=self.ledger, amount=Decimal('50.00'), date_paid=datetime.date(2024, 2, 3),
            payee_name='Office', payee_bsb='062-000', payee_account='123456789',
            payment_method='eft', purpose='Open transfer', authorised_by=self.admin,
            created_by=self.admin, costs_withdrawal_method='method_1_bill_issued',
            costs_evidence_file=SimpleUploadedFile('bill.pdf', b'bill evidence'),
        )
        self.assertIsNotNone(transfer.pk)

        journal = create_trust_journal(
            from_ledger=self.ledger, to_ledger=self.ledger2, amount=Decimal('50.00'),
            description='Open journal', written_authority_file='authority.pdf',
            authority_date=datetime.date.today(), authority_signed_by='Client', created_by=self.admin,
        )
        self.assertIsNotNone(journal.pk)
        reversal = reverse_transaction(transaction_obj=receipt.transaction, reason='Correction', created_by=self.admin)
        self.assertIsNotNone(reversal.pk)

        self.client.login(username='phase_admin', password='pass')
        for url in [
            reverse('trust:receipts_journal_pdf', kwargs={'pk': self.trust_account.pk}),
            reverse('trust:payments_journal_pdf', kwargs={'pk': self.trust_account.pk}),
            reverse('trust:trust_transfer_journal_pdf', kwargs={'pk': self.trust_account.pk}),
            reverse('trust:trial_balance_pdf', kwargs={'pk': self.trust_account.pk}),
        ]:
            response = self.client.get(url, {'date_from': '2024-02-01', 'date_to': '2024-02-29'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_monthly_record_views_and_download(self):
        reconciliation = self.create_balanced_reconciliation()
        finalise_reconciliation(reconciliation, self.admin)
        record = TrustMonthlyRecord.objects.first()
        self.client.login(username='phase_admin', password='pass')
        self.assertEqual(self.client.get(reverse('trust:period_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('trust:period_detail', kwargs={'pk': reconciliation.accounting_period.pk})).status_code, 200)
        self.assertEqual(self.client.get(reverse('trust:monthly_record_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('trust:monthly_record_detail', kwargs={'pk': record.pk})).status_code, 200)
        self.assertEqual(self.client.get(reverse('trust:monthly_record_download', kwargs={'pk': record.pk})).status_code, 200)

    def test_report_byte_builders_return_pdf_bytes(self):
        reconciliation = self.create_balanced_reconciliation()
        finalise_reconciliation(reconciliation, self.admin)
        self.assertTrue(trust_reports.receipts_cash_book_pdf_bytes(self.trust_account, datetime.date(2024, 1, 1), self.period_end).startswith(b'%PDF'))
        self.assertTrue(trust_reports.payments_cash_book_pdf_bytes(self.trust_account, datetime.date(2024, 1, 1), self.period_end).startswith(b'%PDF'))
        self.assertTrue(trust_reports.trust_transfer_journal_pdf_bytes(self.trust_account, datetime.date(2024, 1, 1), self.period_end).startswith(b'%PDF'))
        self.assertTrue(trust_reports.trial_balance_pdf_bytes(self.trust_account, self.period_end).startswith(b'%PDF'))
        self.assertTrue(trust_reports.reconciliation_statement_pdf_bytes(reconciliation).startswith(b'%PDF'))
