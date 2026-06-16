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
    Payment,
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
        self.accountant = User.objects.create_user(username='phase_accountant', password='pass', role='accountant')
        self.firm = Firm.objects.create(
            name='Phase Firm', abn='12345678901', address='1 Phase St',
            principal_solicitor=self.admin, jurisdiction='NSW', is_sole_practitioner=True,
        )
        self.admin.firm = self.firm
        self.admin.save(update_fields=['firm'])
        self.solicitor.firm = self.firm
        self.solicitor.save(update_fields=['firm'])
        self.accountant.firm = self.firm
        self.accountant.save(update_fields=['firm'])
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

    def create_other_firm_records(self):
        other_admin = User.objects.create_user(username='phase_other_admin', password='pass', role='admin')
        other_solicitor = User.objects.create_user(username='phase_other_solicitor', password='pass', role='solicitor')
        other_firm = Firm.objects.create(
            name='Other Phase Firm', abn='10987654321', address='2 Phase St',
            principal_solicitor=other_admin, jurisdiction='NSW', is_sole_practitioner=True,
        )
        other_admin.firm = other_firm
        other_admin.save(update_fields=['firm'])
        other_solicitor.firm = other_firm
        other_solicitor.save(update_fields=['firm'])
        other_client = Client.objects.create(firm=other_firm, client_type='individual', name='Other Phase Client')
        other_matter = Matter.objects.create(
            firm=other_firm, description='Other Phase Matter', client=other_client,
            responsible_lawyer=other_solicitor, file_number='OP001',
        )
        other_trust_account = TrustAccount.objects.create(
            firm=other_firm, name='Other Phase Trust', bank='CBA', bsb='062-001', account_number='223456789',
        )
        other_ledger = MatterLedger.objects.create(matter=other_matter, trust_account=other_trust_account)
        create_receipt(
            matter_ledger=other_ledger, amount=Decimal('1000.00'), date_received=datetime.date(2024, 1, 15),
            payor_name='Other Client', payment_method='eft', purpose='Other retainer', created_by=other_admin,
        )
        finalised_period = get_or_create_accounting_period(other_trust_account, datetime.date(2024, 1, 31))
        finalised_reconciliation = MonthlyReconciliation.objects.create(
            trust_account=other_trust_account,
            accounting_period=finalised_period,
            period_end=datetime.date(2024, 1, 31),
            cash_book_balance=Decimal('1000.00'),
            ledger_total_balance=Decimal('1000.00'),
            bank_statement_balance=Decimal('1000.00'),
            unpresented_cheques_total=Decimal('0.00'),
            outstanding_deposits_total=Decimal('0.00'),
            bank_statement_pdf=SimpleUploadedFile('other-statement.pdf', b'bank statement', content_type='application/pdf'),
        )
        finalise_reconciliation(finalised_reconciliation, other_admin)
        finalised_reconciliation.refresh_from_db()

        create_receipt(
            matter_ledger=other_ledger, amount=Decimal('500.00'), date_received=datetime.date(2024, 2, 15),
            payor_name='Other Client', payment_method='eft', purpose='Other second retainer', created_by=other_admin,
        )
        open_period = get_or_create_accounting_period(other_trust_account, datetime.date(2024, 2, 29))
        open_reconciliation = MonthlyReconciliation.objects.create(
            trust_account=other_trust_account,
            accounting_period=open_period,
            period_end=datetime.date(2024, 2, 29),
            cash_book_balance=Decimal('1500.00'),
            ledger_total_balance=Decimal('1500.00'),
            bank_statement_balance=Decimal('1500.00'),
            unpresented_cheques_total=Decimal('0.00'),
            outstanding_deposits_total=Decimal('0.00'),
            bank_statement_pdf=SimpleUploadedFile('other-feb-statement.pdf', b'bank statement', content_type='application/pdf'),
        )
        return {
            'account': other_trust_account,
            'ledger': other_ledger,
            'finalised_reconciliation': finalised_reconciliation,
            'open_reconciliation': open_reconciliation,
            'finalised_period': finalised_period,
            'open_period': open_period,
            'record': finalised_reconciliation.monthly_records.first(),
        }

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

    def create_balanced_reconciliation_without_bank_statement(self):
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

    def test_balanced_reconciliation_can_be_finalised_without_bank_statement_pdf(self):
        reconciliation = self.create_balanced_reconciliation_without_bank_statement()
        finalised = finalise_reconciliation(reconciliation, self.admin)
        finalised.refresh_from_db()
        self.assertTrue(finalised.is_finalised)
        self.assertFalse(bool(finalised.bank_statement_pdf))
        self.assertEqual(finalised.monthly_records.count(), 5)

    def test_finalised_reconciliation_without_bank_statement_shows_evidence_outstanding(self):
        reconciliation = self.create_balanced_reconciliation_without_bank_statement()
        finalise_reconciliation(reconciliation, self.admin)
        self.client.login(username='phase_admin', password='pass')

        response = self.client.get(reverse('trust:reconciliation_detail', kwargs={'pk': reconciliation.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bank statement evidence')
        self.assertContains(response, 'Outstanding')
        self.assertNotContains(response, 'Upload Bank Statement')

    def test_bank_statement_can_be_uploaded_before_finalisation(self):
        reconciliation = self.create_balanced_reconciliation_without_bank_statement()
        self.client.login(username='phase_admin', password='pass')

        response = self.client.post(
            reverse('trust:reconciliation_bank_statement', kwargs={'pk': reconciliation.pk}),
            {'bank_statement_pdf': SimpleUploadedFile('statement.pdf', b'first statement', content_type='application/pdf')},
        )

        self.assertRedirects(response, reverse('trust:reconciliation_detail', kwargs={'pk': reconciliation.pk}))
        reconciliation.refresh_from_db()
        self.assertTrue(reconciliation.bank_statement_pdf.name.endswith('statement.pdf'))

    def test_bank_statement_can_be_replaced_before_finalisation(self):
        reconciliation = self.create_balanced_reconciliation()
        original_name = reconciliation.bank_statement_pdf.name
        self.client.login(username='phase_admin', password='pass')

        response = self.client.post(
            reverse('trust:reconciliation_bank_statement', kwargs={'pk': reconciliation.pk}),
            {'bank_statement_pdf': SimpleUploadedFile('replacement.pdf', b'replacement statement', content_type='application/pdf')},
        )

        self.assertRedirects(response, reverse('trust:reconciliation_detail', kwargs={'pk': reconciliation.pk}))
        reconciliation.refresh_from_db()
        self.assertNotEqual(reconciliation.bank_statement_pdf.name, original_name)
        self.assertTrue(reconciliation.bank_statement_pdf.name.endswith('replacement.pdf'))

    def test_bank_statement_can_be_downloaded_when_uploaded(self):
        reconciliation = self.create_balanced_reconciliation()
        self.client.login(username='phase_admin', password='pass')

        response = self.client.get(
            reverse('trust:reconciliation_bank_statement', kwargs={'pk': reconciliation.pk}),
            {'download': '1'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'bank statement')
        self.assertIn('attachment;', response['Content-Disposition'])

    def test_bank_statement_cannot_be_replaced_after_finalisation(self):
        reconciliation = self.create_balanced_reconciliation()
        original_name = reconciliation.bank_statement_pdf.name
        finalise_reconciliation(reconciliation, self.admin)
        self.client.login(username='phase_admin', password='pass')

        response = self.client.post(
            reverse('trust:reconciliation_bank_statement', kwargs={'pk': reconciliation.pk}),
            {'bank_statement_pdf': SimpleUploadedFile('replacement.pdf', b'replacement statement', content_type='application/pdf')},
        )

        self.assertRedirects(response, reverse('trust:reconciliation_detail', kwargs={'pk': reconciliation.pk}))
        reconciliation.refresh_from_db()
        self.assertEqual(reconciliation.bank_statement_pdf.name, original_name)

    def test_existing_reconciliation_pdf_download_still_works(self):
        reconciliation = self.create_balanced_reconciliation_without_bank_statement()
        finalise_reconciliation(reconciliation, self.admin)
        self.client.login(username='phase_admin', password='pass')

        response = self.client.get(reverse('trust:reconciliation_pdf', kwargs={'pk': reconciliation.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

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

    def test_accountant_cannot_guess_other_firm_phase_a_or_transfer_ids(self):
        other = self.create_other_firm_records()
        self.client.login(username='phase_accountant', password='pass')

        self.assertEqual(
            self.client.get(reverse('trust:period_detail', kwargs={'pk': other['finalised_period'].pk})).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse('trust:period_lock', kwargs={'pk': other['finalised_period'].pk}), {'confirm': 'on'}).status_code,
            404,
        )
        other['finalised_period'].refresh_from_db()
        self.assertEqual(other['finalised_period'].status, TrustAccountingPeriod.STATUS_OPEN)

        self.assertEqual(
            self.client.get(reverse('trust:monthly_record_detail', kwargs={'pk': other['record'].pk})).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('trust:monthly_record_download', kwargs={'pk': other['record'].pk})).status_code,
            404,
        )

        self.assertEqual(
            self.client.post(reverse('trust:reconciliation_finalise', kwargs={'pk': other['open_reconciliation'].pk}), {'confirm': 'on'}).status_code,
            404,
        )
        other['open_reconciliation'].refresh_from_db()
        self.assertFalse(other['open_reconciliation'].is_finalised)

        transfer_count = Payment.objects.filter(transaction__transaction_type='transfer_to_office').count()
        response = self.client.post(reverse('trust:transfer_costs_to_office_create', kwargs={'ledger_pk': other['ledger'].pk}), {
            'amount': '250.00',
            'date_paid': '2024-03-01',
            'payee_name': 'Office Account',
            'payee_bsb': '062-000',
            'payee_account': '123456789',
            'payment_method': 'eft',
            'cheque_number': '',
            'purpose': 'Guessed costs transfer',
            'costs_withdrawal_method': 'method_1_bill_issued',
            'key_evidence_date': '2024-03-01',
            'costs_evidence_file': SimpleUploadedFile('bill.pdf', b'bill evidence'),
            'costs_withdrawal_notes': 'Evidence retained.',
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Payment.objects.filter(transaction__transaction_type='transfer_to_office').count(), transfer_count)

    def test_report_byte_builders_return_pdf_bytes(self):
        reconciliation = self.create_balanced_reconciliation()
        finalise_reconciliation(reconciliation, self.admin)
        self.assertTrue(trust_reports.receipts_cash_book_pdf_bytes(self.trust_account, datetime.date(2024, 1, 1), self.period_end).startswith(b'%PDF'))
        self.assertTrue(trust_reports.payments_cash_book_pdf_bytes(self.trust_account, datetime.date(2024, 1, 1), self.period_end).startswith(b'%PDF'))
        self.assertTrue(trust_reports.trust_transfer_journal_pdf_bytes(self.trust_account, datetime.date(2024, 1, 1), self.period_end).startswith(b'%PDF'))
        self.assertTrue(trust_reports.trial_balance_pdf_bytes(self.trust_account, self.period_end).startswith(b'%PDF'))
        self.assertTrue(trust_reports.reconciliation_statement_pdf_bytes(reconciliation).startswith(b'%PDF'))
