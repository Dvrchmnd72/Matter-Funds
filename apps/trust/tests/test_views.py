import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client as TestClient
from django.urls import reverse

from apps.firms.models import Firm
from apps.clients.models import Client
from apps.matters.models import Matter
from apps.trust.models import TrustAccount, MatterLedger, Receipt, Payment, Irregularity

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
        self.assertEqual(Receipt.objects.filter(transaction__matter_ledger=self.ledger).count(), 1)

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
            'second_authoriser': '',
            'costs_withdrawal_method': 'method_1_bill_issued',
            'key_evidence_date': str(datetime.date.today()),
            'costs_evidence_file': SimpleUploadedFile('bill.pdf', b'bill evidence'),
            'costs_withdrawal_notes': 'Evidence retained.',
        })
        self.assertEqual(response.status_code, 302)
        self.ledger.refresh_from_db()
        self.assertEqual(self.ledger.balance, Decimal('750.00'))
        self.assertEqual(Payment.objects.filter(transaction__transaction_type='transfer_to_office').count(), 1)
