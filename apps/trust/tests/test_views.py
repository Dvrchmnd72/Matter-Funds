import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client as TestClient
from django.urls import reverse

from apps.firms.models import Firm
from apps.clients.models import Client
from apps.matters.models import Matter
from apps.trust.models import TrustAccount, MatterLedger, Receipt

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
