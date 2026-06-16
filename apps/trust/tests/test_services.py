import datetime
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from apps.firms.models import Firm
from apps.clients.models import Client
from apps.matters.models import Matter
from apps.trust.models import (
    TrustAccount, MatterLedger, TrustTransaction, Receipt, Payment, TrustJournal,
    MonthlyReconciliation, Irregularity,
)
from apps.trust.services import create_receipt, create_payment, create_transfer_to_office, create_trust_journal, reverse_transaction
from apps.trust import reports as trust_reports

User = get_user_model()


class TrustServiceTestCase(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(username='admin', password='pass', role='admin')
        self.solicitor = User.objects.create_user(username='solicitor', password='pass', role='solicitor')
        self.firm = Firm.objects.create(
            name='Test Firm', abn='12345678901', address='123 Test St',
            principal_solicitor=self.admin_user, jurisdiction='NSW'
        )
        self.client_obj = Client.objects.create(
            firm=self.firm, client_type='individual', name='Test Client'
        )
        self.matter = Matter.objects.create(
            firm=self.firm, description='Test Matter', client=self.client_obj,
            responsible_lawyer=self.solicitor
        )
        self.trust_account = TrustAccount.objects.create(
            firm=self.firm, name='General Trust', bank='ANZ',
            bsb='012-345', account_number='123456789'
        )
        self.ledger = MatterLedger.objects.create(
            matter=self.matter, trust_account=self.trust_account
        )

    def test_eft_receipt_deposited_same_day_is_not_late(self):
        received = datetime.date(2024, 1, 10)
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('250.00'),
            date_received=received, date_banked=received, payor_name='Client A',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        self.assertFalse(receipt.late_banking)

    def test_receipt_late_deposit_uses_five_working_day_window(self):
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('250.00'),
            date_received=datetime.date(2024, 1, 8),
            date_banked=datetime.date(2024, 1, 16),
            payor_name='Client A', payment_method='cash', purpose='Retainer',
            created_by=self.admin_user
        )
        self.assertTrue(receipt.late_banking)

    def test_receipts_cash_book_includes_nsw_receipt_dates(self):
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('250.00'),
            date_received=datetime.date(2024, 1, 9),
            date_banked=datetime.date(2024, 1, 9), payor_name='Client A',
            payment_method='direct_deposit', purpose='Retainer', created_by=self.admin_user
        )
        made_out = timezone.make_aware(datetime.datetime(2024, 1, 10, 9, 0))
        TrustTransaction.objects.filter(pk=receipt.transaction_id).update(created_at=made_out)

        captured = {}

        def fake_build(buffer, trust_account, title, subtitle, rows, col_headers):
            captured['rows'] = rows
            captured['headers'] = col_headers
            buffer.write(b'pdf')

        with patch.object(trust_reports, '_build_pdf_document', side_effect=fake_build):
            trust_reports.receipts_cash_book_pdf_bytes(
                self.trust_account, datetime.date(2024, 1, 1), datetime.date(2024, 1, 31)
            )

        self.assertIn('Date receipt made out', captured['headers'])
        self.assertIn('Date received (if different)', captured['headers'])
        self.assertIn('Date deposited to trust account', captured['headers'])
        self.assertEqual(captured['rows'][0][0], '2024-01-10')
        self.assertEqual(captured['rows'][0][1], '2024-01-09')
        self.assertEqual(captured['rows'][0][2], '2024-01-09')

    def test_receipt_pdf_includes_nsw_receipt_dates(self):
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('250.00'),
            date_received=datetime.date(2024, 1, 9),
            date_banked=datetime.date(2024, 1, 9), payor_name='Client A',
            payment_method='direct_deposit', purpose='Retainer', created_by=self.admin_user
        )
        TrustTransaction.objects.filter(pk=receipt.transaction_id).update(
            created_at=timezone.make_aware(datetime.datetime(2024, 1, 10, 9, 0))
        )
        receipt = Receipt.objects.select_related('transaction__matter_ledger__trust_account').get(pk=receipt.pk)
        captured = {}

        class FakeTable:
            def __init__(self, data):
                captured['details'] = data
            def setStyle(self, style):
                pass

        class FakeDoc:
            def __init__(self, *args, **kwargs):
                pass
            def build(self, elements):
                pass

        with patch.object(trust_reports, 'Table', FakeTable), patch.object(trust_reports, 'SimpleDocTemplate', FakeDoc):
            response = trust_reports.receipt_pdf(receipt)

        self.assertEqual(response.status_code, 200)
        self.assertIn(['Date receipt made out', '2024-01-10'], captured['details'])
        self.assertIn(['Date received', '2024-01-09'], captured['details'])
        self.assertIn(['Date deposited to trust account', '2024-01-09'], captured['details'])

    def test_receipt_increments_balance(self):
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client A',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        self.ledger.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('1000.00'))
        self.assertEqual(receipt.receipt_number, 1)

    def test_receipt_sequential_numbers(self):
        for i in range(5):
            create_receipt(
                matter_ledger=self.ledger, amount=Decimal('100.00'),
                date_received=datetime.date.today(), payor_name='Client',
                payment_method='eft', purpose='Test', created_by=self.admin_user
            )
        receipts = Receipt.objects.order_by('receipt_number')
        numbers = list(receipts.values_list('receipt_number', flat=True))
        self.assertEqual(numbers, [1, 2, 3, 4, 5])

    def test_payment_decrements_balance(self):
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        self.firm.is_sole_practitioner = True
        self.firm.save()
        payment = create_payment(
            matter_ledger=self.ledger, amount=Decimal('500.00'),
            date_paid=datetime.date.today(), payee_name='Expert',
            payment_method='eft', purpose='Expert fee', authorised_by=self.admin_user,
            created_by=self.admin_user
        )
        self.ledger.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('500.00'))
        self.assertEqual(payment.payment_number, 1)

    def test_payment_eft_allows_single_authoriser_for_non_sole_practitioner(self):
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        payment = create_payment(
            matter_ledger=self.ledger, amount=Decimal('500.00'),
            date_paid=datetime.date.today(), payee_name='Expert',
            payment_method='eft', purpose='Expert fee', authorised_by=self.admin_user,
            created_by=self.admin_user
        )
        self.assertIsNotNone(payment.pk)
        self.assertEqual(payment.authorised_by, self.admin_user)
        self.assertIsNone(payment.second_authoriser)

    def test_payment_eft_allowed_for_sole_practitioner(self):
        self.firm.is_sole_practitioner = True
        self.firm.save()
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        payment = create_payment(
            matter_ledger=self.ledger, amount=Decimal('500.00'),
            date_paid=datetime.date.today(), payee_name='Expert',
            payment_method='eft', purpose='Expert fee', authorised_by=self.admin_user,
            created_by=self.admin_user
        )
        self.assertIsNotNone(payment.pk)

    def test_transfer_to_office_creates_transaction_and_payment_and_decrements_balance(self):
        self.firm.is_sole_practitioner = True
        self.firm.save()
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        payment = create_transfer_to_office(
            matter_ledger=self.ledger, amount=Decimal('300.00'),
            date_paid=datetime.date.today(), payee_name='Office Account',
            payment_method='eft', purpose='Costs transfer',
            authorised_by=self.admin_user, created_by=self.admin_user,
            costs_withdrawal_method='method_1_bill_issued',
            costs_evidence_file=SimpleUploadedFile('bill.pdf', b'bill evidence'),
            costs_withdrawal_notes='Bill issued and evidence retained.',
        )
        self.ledger.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('700.00'))
        self.assertEqual(payment.transaction.transaction_type, 'transfer_to_office')
        self.assertEqual(payment.payment_number, 1)
        self.assertEqual(payment.costs_withdrawal_method, 'method_1_bill_issued')
        self.assertTrue(Payment.objects.filter(transaction__transaction_type='transfer_to_office').exists())

    def test_transfer_to_office_rejects_insufficient_funds(self):
        self.firm.is_sole_practitioner = True
        self.firm.save()
        with self.assertRaises(ValidationError):
            create_transfer_to_office(
                matter_ledger=self.ledger, amount=Decimal('300.00'),
                date_paid=datetime.date.today(), payee_name='Office Account',
                payment_method='eft', purpose='Costs transfer',
                authorised_by=self.admin_user, created_by=self.admin_user,
                costs_withdrawal_method='method_1_bill_issued',
                costs_evidence_file=SimpleUploadedFile('bill.pdf', b'bill evidence'),
            )

    def test_transfer_to_office_requires_evidence(self):
        self.firm.is_sole_practitioner = True
        self.firm.save()
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        with self.assertRaises(ValidationError):
            create_transfer_to_office(
                matter_ledger=self.ledger, amount=Decimal('300.00'),
                date_paid=datetime.date.today(), payee_name='Office Account',
                payment_method='eft', purpose='Costs transfer',
                authorised_by=self.admin_user, created_by=self.admin_user,
                costs_withdrawal_method='method_1_bill_issued',
            )
        with self.assertRaises(ValidationError):
            create_transfer_to_office(
                matter_ledger=self.ledger, amount=Decimal('300.00'),
                date_paid=datetime.date.today(), payee_name='Office Account',
                payment_method='eft', purpose='Costs transfer',
                authorised_by=self.admin_user, created_by=self.admin_user,
                costs_withdrawal_method='method_2_authority',
                costs_evidence_file=SimpleUploadedFile('notes.pdf', b'notes'),
            )

    def test_transfer_to_office_eft_allows_single_authoriser_for_non_sole_practitioner(self):
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        payment = create_transfer_to_office(
            matter_ledger=self.ledger, amount=Decimal('300.00'),
            date_paid=datetime.date.today(), payee_name='Office Account',
            payment_method='eft', purpose='Costs transfer',
            authorised_by=self.admin_user, created_by=self.admin_user,
            costs_withdrawal_method='method_1_bill_issued',
            costs_evidence_file=SimpleUploadedFile('bill.pdf', b'bill evidence'),
        )
        self.assertIsNotNone(payment.pk)
        self.assertEqual(payment.authorised_by, self.admin_user)
        self.assertIsNone(payment.second_authoriser)

    def test_payments_journal_includes_transfer_to_office_rows(self):
        self.firm.is_sole_practitioner = True
        self.firm.save()
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        create_transfer_to_office(
            matter_ledger=self.ledger, amount=Decimal('300.00'),
            date_paid=datetime.date.today(), payee_name='Office Account',
            payment_method='eft', purpose='Costs transfer',
            authorised_by=self.admin_user, created_by=self.admin_user,
            costs_withdrawal_method='method_1_bill_issued',
            costs_evidence_file=SimpleUploadedFile('bill.pdf', b'bill evidence'),
        )
        captured = {}

        def fake_build(buffer, trust_account, title, subtitle, rows, col_headers):
            captured['rows'] = rows
            captured['headers'] = col_headers
            buffer.write(b'pdf')

        with patch.object(trust_reports, '_build_pdf_document', side_effect=fake_build):
            trust_reports.payments_journal_pdf(
                self.trust_account, datetime.date.today(), datetime.date.today()
            )
        self.assertIn('Type', captured['headers'])
        self.assertTrue(any(row[1] == 'Transfer to Office' for row in captured['rows']))

    def test_trust_journal_double_entry(self):
        matter2 = Matter.objects.create(
            firm=self.firm, description='Matter 2', client=self.client_obj,
            responsible_lawyer=self.solicitor
        )
        ledger2 = MatterLedger.objects.create(matter=matter2, trust_account=self.trust_account)
        create_receipt(
            matter_ledger=self.ledger, amount=Decimal('1000.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Retainer', created_by=self.admin_user
        )
        journal = create_trust_journal(
            from_ledger=self.ledger, to_ledger=ledger2, amount=Decimal('300.00'),
            description='Transfer', written_authority_file='test_authority.pdf',
            authority_date=datetime.date.today(), authority_signed_by='Client A',
            created_by=self.admin_user
        )
        self.ledger.refresh_from_db()
        ledger2.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('700.00'))
        self.assertEqual(ledger2.balance, Decimal('300.00'))
        self.assertIsNotNone(journal.pk)

    def test_trust_journal_atomic_rollback_if_negative(self):
        matter2 = Matter.objects.create(
            firm=self.firm, description='Matter 2', client=self.client_obj,
            responsible_lawyer=self.solicitor
        )
        ledger2 = MatterLedger.objects.create(matter=matter2, trust_account=self.trust_account)
        with self.assertRaises(ValidationError):
            create_trust_journal(
                from_ledger=self.ledger, to_ledger=ledger2, amount=Decimal('500.00'),
                description='Transfer', written_authority_file='test_authority.pdf',
                authority_date=datetime.date.today(), authority_signed_by='Client A',
                created_by=self.admin_user
            )
        self.ledger.refresh_from_db()
        ledger2.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('0.00'))
        self.assertEqual(ledger2.balance, Decimal('0.00'))

    def test_update_trust_transaction_raises(self):
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('100.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Test', created_by=self.admin_user
        )
        txn = receipt.transaction
        with self.assertRaises(PermissionError):
            txn.save()

    def test_delete_trust_transaction_raises(self):
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('100.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Test', created_by=self.admin_user
        )
        txn = receipt.transaction
        with self.assertRaises(PermissionError):
            txn.delete()

    def test_reverse_transaction(self):
        receipt = create_receipt(
            matter_ledger=self.ledger, amount=Decimal('500.00'),
            date_received=datetime.date.today(), payor_name='Client',
            payment_method='eft', purpose='Test', created_by=self.admin_user
        )
        reversal = reverse_transaction(
            transaction_obj=receipt.transaction, reason='Error', created_by=self.admin_user
        )
        self.ledger.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('0.00'))
        receipt.transaction.refresh_from_db()
        self.assertTrue(receipt.transaction.is_reversed)
        self.assertEqual(reversal.transaction_type, 'reversal')
        self.assertEqual(reversal.reverses_id, receipt.transaction.pk)

    def test_monthly_reconciliation_mismatch_creates_irregularity(self):
        recon = MonthlyReconciliation.objects.create(
            trust_account=self.trust_account,
            period_end=datetime.date(2024, 1, 31),
            cash_book_balance=Decimal('1000.00'),
            ledger_total_balance=Decimal('1000.00'),
            bank_statement_balance=Decimal('900.00'),
            unpresented_cheques_total=Decimal('0.00'),
            outstanding_deposits_total=Decimal('0.00'),
        )
        self.assertFalse(recon.is_reconciled)
        self.assertTrue(Irregularity.objects.filter(trust_account=self.trust_account).exists())

    def test_gapless_sequencing(self):
        for _ in range(10):
            create_receipt(
                matter_ledger=self.ledger, amount=Decimal('10.00'),
                date_received=datetime.date.today(), payor_name='Client',
                payment_method='cash', purpose='Test', created_by=self.admin_user
            )
        numbers = list(Receipt.objects.order_by('receipt_number').values_list('receipt_number', flat=True))
        self.assertEqual(numbers, list(range(1, 11)))
