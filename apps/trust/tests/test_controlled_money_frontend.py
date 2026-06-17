import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client as TestClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.firms.models import Firm
from apps.matters.models import Matter
from apps.trust.models import ControlledMoneyAccount, ControlledMoneyReceipt, TrustAccount, TrustTransaction

User = get_user_model()


class ControlledMoneyFrontendTests(TestCase):
    def setUp(self):
        self.tc = TestClient()
        self.admin = User.objects.create_user('cm_admin', password='testpass123', role='admin')
        self.accountant = User.objects.create_user('cm_accountant', password='testpass123', role='accountant')
        self.solicitor = User.objects.create_user('cm_solicitor', password='testpass123', role='solicitor')
        self.firm = Firm.objects.create(name='CMA Test Firm', abn='12345678901', address='1 Test St', principal_solicitor=self.admin, jurisdiction='NSW')
        for user in (self.admin, self.accountant, self.solicitor):
            user.firm = self.firm
            user.save()
        self.client_obj = Client.objects.create(firm=self.firm, client_type='individual', name='Jane Client', address='1 Client St')
        self.matter = Matter.objects.create(firm=self.firm, client=self.client_obj, responsible_lawyer=self.admin, file_number='CMA001', description='Purchase matter')
        self.trust = TrustAccount.objects.create(firm=self.firm, name='General Trust', bank='Bank', bsb='012-345', account_number='123456')

    def account_payload(self, **overrides):
        data = {
            'client': self.client_obj.pk,
            'matter': self.matter.pk,
            'account_name': 'CMA Test Firm Controlled Money Account - Jane Client',
            'bank': 'ADI Bank',
            'bsb': '012-345',
            'account_number': '987654',
            'purpose': 'Settlement funds for CMA001 purchase matter',
            'person_on_behalf': 'Jane Client',
            'person_address': '1 Client St',
            'matter_reference': 'CMA001',
            'matter_description': 'Purchase matter',
            'opened_on': '2024-05-01',
            'is_active': 'on',
        }
        data.update(overrides)
        return data

    def create_cma(self):
        return ControlledMoneyAccount.objects.create(
            firm=self.firm, client=self.client_obj, matter=self.matter,
            account_name='CMA Test Firm Controlled Money Account - Jane Client',
            bank='ADI Bank', bsb='012-345', account_number='987654',
            purpose='Settlement funds for CMA001 purchase matter', person_on_behalf='Jane Client',
            person_address='1 Client St', matter_reference='CMA001', matter_description='Purchase matter',
        )

    def test_navigation_and_list_visible_to_authorised_user(self):
        self.tc.login(username='cm_accountant', password='testpass123')
        response = self.tc.get(reverse('trust:controlled_money_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Controlled Money')
        base = self.tc.get(reverse('trust:account_list'))
        self.assertContains(base, '/trust/controlled-money/')

    def test_unauthorised_user_blocked(self):
        self.tc.login(username='cm_solicitor', password='testpass123')
        response = self.tc.get(reverse('trust:controlled_money_list'))
        self.assertIn(response.status_code, (302, 403))

    def test_invalid_account_name_blocked_and_valid_account_created(self):
        self.tc.login(username='cm_admin', password='testpass123')
        response = self.tc.post(reverse('trust:controlled_money_create'), self.account_payload(account_name='Jane Client Savings'))
        self.assertContains(response, 'Controlled money account name must include', status_code=200)
        response = self.tc.post(reverse('trust:controlled_money_create'), self.account_payload())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ControlledMoneyAccount.objects.filter(firm=self.firm, account_number='987654').exists())

    def test_receipt_sequence_pdf_withdrawal_balance_and_no_general_trust_txn(self):
        self.tc.login(username='cm_admin', password='testpass123')
        cma = self.create_cma()
        receipt_data = {
            'controlled_money_account': cma.pk, 'amount': '100.00', 'payment_method': 'eft',
            'person_from_whom_received': 'Jane Client', 'person_on_behalf': 'Jane Client',
            'matter_reference': 'CMA001', 'matter_description': 'Purchase matter', 'reason': 'Settlement deposit',
        }
        self.assertEqual(self.tc.post(reverse('trust:controlled_money_receipt_create'), receipt_data).status_code, 302)
        self.assertEqual(self.tc.post(reverse('trust:controlled_money_receipt_create'), receipt_data).status_code, 302)
        self.assertEqual(list(ControlledMoneyReceipt.objects.values_list('receipt_number', flat=True)), [1, 2])
        pdf = self.tc.get(reverse('trust:controlled_money_receipt_pdf', kwargs={'pk': ControlledMoneyReceipt.objects.first().pk}))
        self.assertEqual(pdf.status_code, 200)
        overdraft = {'controlled_money_account': cma.pk, 'date': '2024-05-02', 'transaction_number': 'W1', 'amount': '999.00', 'withdrawal_method': 'eft', 'destination_account_name': 'Payee', 'destination_bsb': '012-345', 'destination_account_number': '111', 'person_on_behalf': 'Jane Client', 'matter_reference': 'CMA001', 'reason': 'Payment', 'authorised_by': 'Jane Client'}
        self.assertContains(self.tc.post(reverse('trust:controlled_money_withdrawal_create'), overdraft), 'Withdrawal cannot overdraw', status_code=200)
        ok = dict(overdraft, amount='40.00')
        self.assertEqual(self.tc.post(reverse('trust:controlled_money_withdrawal_create'), ok).status_code, 302)
        cma.refresh_from_db()
        self.assertEqual(cma.current_balance, Decimal('160.00'))
        self.assertEqual(TrustTransaction.objects.count(), 0)

    def test_monthly_statement_early_due_status_review_and_export_pack(self):
        self.tc.login(username='cm_admin', password='testpass123')
        self.create_cma()
        early = self.tc.post(reverse('trust:controlled_money_statements'), {'period_end': str(timezone.localdate())})
        self.assertContains(early, 'cannot be prepared before the month has ended', status_code=200)
        with patch('django.utils.timezone.localdate', return_value=datetime.date(2024, 6, 10)):
            response = self.tc.post(reverse('trust:controlled_money_statements'), {'period_end': '2024-05-31'})
        self.assertEqual(response.status_code, 302)
        detail = self.tc.get(response['Location'])
        self.assertContains(detail, 'Due')
        self.assertContains(detail, 'on-time')
        review = self.tc.post(response['Location'], {'confirm': 'on', 'reviewer_role_confirmation': 'Principal/admin review confirmed', 'review_note': 'Reviewed'})
        self.assertEqual(review.status_code, 302)
        export = self.tc.get(reverse('trust:trust_records_export_pack', kwargs={'pk': self.trust.pk}), {'date_from': '2024-05-01', 'date_to': '2024-05-31'})
        self.assertEqual(export.status_code, 200)
        self.assertIn(b'controlled-money/exports/accounts.csv', export.content)
