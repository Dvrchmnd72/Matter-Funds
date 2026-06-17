import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client as TestClient
from django.urls import reverse
from django.utils import timezone

from apps.firms.models import Firm
from apps.clients.models import Client
from apps.matters.models import Matter
from apps.trust.models import TrustAccount, MatterLedger, Receipt, Payment, Irregularity
from unittest.mock import patch

User = get_user_model()


class TrustViewTestCase(TestCase):
    def setUp(self):
        self.tc = TestClient()
        self.admin = User.objects.create_user(
            username='admin_view', email='admin@example.com',
            password='testpass123', role='admin'
        )
        self.solicitor = User.objects.create_user(
            username='solicitor_view', email='solicitor@example.com',
            password='testpass123', role='solicitor'
        )
        self.client_user = User.objects.create_user(
            username='client_view', email='client@example.com',
            password='testpass123', role='client'
        )
        self.firm = Firm.objects.create(
            name='View Test Firm', abn='12345678901', address='1 Test St',
            principal_solicitor=self.admin, jurisdiction='NSW',
            is_sole_practitioner=True,
        )
        self.admin.firm = self.firm
        self.admin.save()
        self.solicitor.firm = self.firm
        self.solicitor.save()
        self.client_obj = Client.objects.create(
            firm=self.firm, client_type='individual', name='View Test Client'
        )
        self.matter = Matter.objects.create(
            firm=self.firm, description='View Test Matter',
            client=self.client_obj, responsible_lawyer=self.solicitor,
            file_number='VT001',
        )
        self.trust_account = TrustAccount.objects.create(
            firm=self.firm, name='View Trust', bank='CBA',
            bsb='062-000', account_number='987654321',
        )
        self.ledger = MatterLedger.objects.create(
            matter=self.matter, trust_account=self.trust_account,
        )

    def test_unauthenticated_redirects_to_login(self):
        url = reverse('trust:account_list')
        response = self.tc.get(url)
        self.assertIn(response.status_code, [302, 301])
        self.assertIn('/accounts/login/', response['Location'])

    def test_client_role_forbidden_from_trust_account_list(self):
        self.tc.login(username='client_view', password='testpass123')
        url = reverse('trust:account_list')
        response = self.tc.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_receipt_create_page_displays_system_made_out_date_from_localdate(self):
        self.tc.login(username='admin_view', password='testpass123')
        url = reverse('trust:receipt_create', kwargs={'ledger_pk': self.ledger.pk})
        local_date = datetime.date(2024, 2, 1)
        with patch('apps.trust.views.timezone.localdate', return_value=local_date):
            response = self.tc.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Date receipt made out')
        self.assertContains(response, 'readonly')
        self.assertContains(response, 'Automatically recorded when this receipt is saved.')
        self.assertContains(response, str(local_date))
        self.assertEqual(response.context['date_receipt_made_out'], local_date)
        self.assertContains(response, 'Date received / confirmed in trust account')

    def test_future_dated_receipt_create_is_rejected(self):
        self.tc.login(username='admin_view', password='testpass123')
        url = reverse('trust:receipt_create', kwargs={'ledger_pk': self.ledger.pk})
        future_date = timezone.localdate() + datetime.timedelta(days=1)
        response = self.tc.post(url, {
            'amount': '500.00',
            'date_received': str(future_date),
            'date_banked': '',
            'payor_name': 'Test Payor',
            'payment_method': 'eft',
            'cheque_number': '',
            'purpose': 'Test receipt',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Receipt.objects.filter(transaction__matter_ledger=self.ledger).exists())
        self.assertContains(response, 'cannot be future-dated')

    def test_eft_receipt_create_defaults_deposit_date_to_received_date(self):
        self.tc.login(username='admin_view', password='testpass123')
        url = reverse('trust:receipt_create', kwargs={'ledger_pk': self.ledger.pk})
        received = datetime.date(2024, 1, 10)
        response = self.tc.post(url, {
            'amount': '500.00',
            'date_received': str(received),
            'date_banked': '',
            'payor_name': 'Test Payor',
            'payment_method': 'eft',
            'cheque_number': '',
            'purpose': 'Test receipt',
        })

        self.assertEqual(response.status_code, 302)
        receipt = Receipt.objects.get(transaction__matter_ledger=self.ledger)
        self.assertEqual(receipt.transaction.date_received_or_paid, received)
        self.assertEqual(receipt.transaction.date_banked, received)

    def test_cash_receipt_create_can_record_separate_deposit_date(self):
        self.tc.login(username='admin_view', password='testpass123')
        url = reverse('trust:receipt_create', kwargs={'ledger_pk': self.ledger.pk})
        received = datetime.date(2024, 1, 10)
        deposited = datetime.date(2024, 1, 11)
        response = self.tc.post(url, {
            'amount': '500.00',
            'date_received': str(received),
            'date_banked': str(deposited),
            'payor_name': 'Test Payor',
            'payment_method': 'cash',
            'cheque_number': '',
            'purpose': 'Test receipt',
        })

        self.assertEqual(response.status_code, 302)
        receipt = Receipt.objects.get(transaction__matter_ledger=self.ledger)
        self.assertEqual(receipt.transaction.date_received_or_paid, received)
        self.assertEqual(receipt.transaction.date_banked, deposited)

    def test_receipt_create_updates_balance(self):
        self.tc.login(username='admin_view', password='testpass123')
        url = reverse('trust:receipt_create', kwargs={'ledger_pk': self.ledger.pk})
        data = {
            'amount': '500.00',
            'date_received': str(datetime.date.today()),
            'date_banked': '',
            'payor_name': 'Test Payor',
            'payment_method': 'eft',
            'cheque_number': '',
            'purpose': 'Test receipt',
        }
        response = self.tc.post(url, data)
        self.assertIn(response.status_code, [302, 200])
        self.ledger.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('500.00'))
        receipt = Receipt.objects.get(transaction__matter_ledger=self.ledger)
        self.assertEqual(receipt.transaction.date_banked, receipt.transaction.date_received_or_paid)

    def test_dashboard_accessible_after_login(self):
        self.tc.login(username='admin_view', password='testpass123')
        response = self.tc.get('/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')


    def test_manual_irregularity_create_authorised_get(self):
        self.tc.login(username='admin_view', password='testpass123')
        response = self.tc.get(reverse('trust:irregularity_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'New Irregularity')

    def test_manual_irregularity_create_client_denied(self):
        self.tc.login(username='client_view', password='testpass123')
        response = self.tc.get(reverse('trust:irregularity_create'))
        self.assertIn(response.status_code, [403, 302])

    def test_manual_irregularity_valid_post_and_list_visibility(self):
        self.tc.login(username='admin_view', password='testpass123')
        response = self.tc.post(reverse('trust:irregularity_create'), {
            'trust_account': self.trust_account.pk,
            'discovered_on': str(datetime.date.today()),
            'description': 'Manual deficiency report',
            'amount': '123.45',
            'reported_to_law_society_on': '',
            'resolution': 'Rectified and reported.',
        })
        self.assertEqual(response.status_code, 302)
        irregularity = Irregularity.objects.get(description='Manual deficiency report')
        self.assertEqual(irregularity.amount, Decimal('123.45'))
        list_response = self.tc.get(reverse('trust:irregularity_list'))
        self.assertContains(list_response, 'Manual deficiency report')

    def test_reports_page_exposes_trust_records_export_pack_separately(self):
        self.tc.login(username='admin_view', password='testpass123')
        response = self.tc.get(reverse('trust:reports'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Examiner Pack (select year)')
        self.assertContains(response, 'Existing limited examiner-style pack')
        self.assertContains(response, 'Trust Records Export Pack')
        self.assertContains(response, 'Download a complete trust-record pack')
        self.assertContains(response, 'Download Trust Records ZIP')
        self.assertContains(response, reverse('trust:examiner_pack', kwargs={'pk': self.trust_account.pk}))
        self.assertContains(response, reverse('trust:trust_records_export_pack', kwargs={'pk': self.trust_account.pk}))

    def test_trust_records_export_pack_download_contains_required_evidence_files(self):
        import io
        import zipfile
        from apps.trust import reports as trust_reports

        self.tc.login(username='admin_view', password='testpass123')
        url = reverse('trust:trust_records_export_pack', kwargs={'pk': self.trust_account.pk})
        with patch.object(trust_reports, 'receipts_cash_book_pdf_bytes', return_value=b'receipts'), \
             patch.object(trust_reports, 'payments_cash_book_pdf_bytes', return_value=b'payments'), \
             patch.object(trust_reports, 'trust_transfer_journal_pdf_bytes', return_value=b'journals'), \
             patch.object(trust_reports, 'trial_balance_pdf_bytes', return_value=b'trial'), \
             patch.object(trust_reports, 'matter_ledger_statement_pdf') as ledger_pdf, \
             patch.object(trust_reports, 'trust_account_statement_pdf_bytes', return_value=b'trust statement'):
            ledger_pdf.return_value.content = b'ledger statement'
            response = self.tc.get(url, {'year': '2024'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        names = zf.namelist()
        self.assertIn('README.txt', names)
        self.assertNotIn('manifest.json', names)
        self.assertNotIn('SHA256SUMS.txt', names)
        self.assertFalse(any(name.lower().endswith('.xlsx') for name in names))
        self.assertIn('exports/trust_transactions.csv', names)
        self.assertIn('exports/matter_ledgers.csv', names)
        self.assertIn('exports/reconciliations.csv', names)

    def test_trust_records_export_pack_requires_admin_or_accountant(self):
        self.tc.login(username='solicitor_view', password='testpass123')
        response = self.tc.get(reverse('trust:trust_records_export_pack', kwargs={'pk': self.trust_account.pk}))
        self.assertIn(response.status_code, [302, 403])

    def test_account_detail_shows_distinct_ledger_statement_actions(self):
        self.tc.login(username='admin_view', password='testpass123')
        response = self.tc.get(reverse('trust:account_detail', kwargs={'pk': self.trust_account.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Matter Ledger Statement')
        self.assertContains(response, 'Trust Account Statement')
        self.assertNotContains(response, 'Statement PDF')
        self.assertContains(response, reverse('trust:ledger_statement_pdf', kwargs={'pk': self.ledger.pk}))
        self.assertContains(response, reverse('trust:trust_account_statement_pdf', kwargs={'pk': self.ledger.pk}))

    def test_trust_account_statement_pdf_uses_required_title_and_fields(self):
        from apps.trust import reports as trust_reports
        captured = []

        class FakeDoc:
            def __init__(self, *args, **kwargs):
                pass
            def build(self, elements):
                captured.extend(elements)

        class FakeTable:
            def __init__(self, data, *args, **kwargs):
                self.data = data
            def setStyle(self, style):
                pass
            def __repr__(self):
                return repr(self.data)

        def fake_paragraph(text, style):
            return text

        with patch.object(trust_reports, 'SimpleDocTemplate', FakeDoc), \
             patch.object(trust_reports, 'Paragraph', side_effect=fake_paragraph), \
             patch.object(trust_reports, 'Spacer', side_effect=lambda *args, **kwargs: ''), \
             patch.object(trust_reports, 'Table', FakeTable), \
             patch.object(trust_reports, 'TableStyle', side_effect=lambda *args, **kwargs: None):
            trust_reports.trust_account_statement_pdf_bytes(
                self.ledger, datetime.date(2024, 1, 1), datetime.date(2024, 1, 31)
            )

        flattened = repr(captured)
        self.assertIn('Trust Account Statement', flattened)
        self.assertIn('Opening balance', flattened)
        self.assertIn('Closing balance', flattened)
        self.assertIn('Statement period: 2024-01-01 to 2024-01-31', flattened)
        self.assertIn('Date statement prepared/generated', flattened)

    def test_trust_account_statement_access_scoped_to_firm(self):
        other_admin = User.objects.create_user(username='other_admin_view', password='testpass123', role='admin')
        other_firm = Firm.objects.create(name='Other Firm', abn='12345678902', address='2 Other St', principal_solicitor=other_admin)
        other_admin.firm = other_firm
        other_admin.save()
        self.tc.login(username='other_admin_view', password='testpass123')
        response = self.tc.get(reverse('trust:trust_account_statement_pdf', kwargs={'pk': self.ledger.pk}))
        self.assertEqual(response.status_code, 404)

    def test_transfer_costs_to_office_authorised_get(self):
        self.tc.login(username='admin_view', password='testpass123')
        response = self.tc.get(reverse('trust:transfer_costs_to_office_create', kwargs={'ledger_pk': self.ledger.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Transfer Costs to Office')

    def test_transfer_costs_to_office_client_denied(self):
        self.tc.login(username='client_view', password='testpass123')
        response = self.tc.get(reverse('trust:transfer_costs_to_office_create', kwargs={'ledger_pk': self.ledger.pk}))
        self.assertIn(response.status_code, [403, 302])

    def test_transfer_costs_to_office_valid_post(self):
        self.tc.login(username='admin_view', password='testpass123')
        self.ledger.balance = Decimal('1000.00')
        self.ledger.save(update_fields=['balance'])
        url = reverse('trust:transfer_costs_to_office_create', kwargs={'ledger_pk': self.ledger.pk})
        response = self.tc.post(url, {
            'amount': '250.00',
            'date_paid': str(datetime.date.today()),
            'payee_name': 'Office Account',
            'payee_bsb': '062-000',
            'payee_account': '123456789',
            'payment_method': 'eft',
            'cheque_number': '',
            'purpose': 'Legal costs transfer',
            'costs_withdrawal_method': 'method_1_bill_issued',
            'key_evidence_date': str(datetime.date.today()),
            'costs_evidence_file': SimpleUploadedFile('bill.pdf', b'bill evidence'),
            'costs_withdrawal_notes': 'Evidence retained.',
        })
        self.assertEqual(response.status_code, 302)
        self.ledger.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('750.00'))
        self.assertEqual(Payment.objects.filter(transaction__transaction_type='transfer_to_office').count(), 1)
