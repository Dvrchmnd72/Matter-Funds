import request from 'supertest';
import app from '../app';

describe('Matter Funds API', () => {
  describe('GET /api/health', () => {
    it('returns health status', async () => {
      const res = await request(app).get('/api/health');
      expect(res.status).toBe(200);
      expect(res.body.status).toBe('ok');
      expect(res.body.service).toBe('Matter Funds API');
    });
  });

  describe('GET /api/states', () => {
    it('returns all 8 Australian states', async () => {
      const res = await request(app).get('/api/states');
      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      const states = Object.keys(res.body.data);
      expect(states).toHaveLength(8);
      expect(states).toEqual(expect.arrayContaining(['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT']));
    });

    it('returns state details for NSW', async () => {
      const res = await request(app).get('/api/states/NSW');
      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.data.code).toBe('NSW');
      expect(res.body.data.name).toBe('New South Wales');
      expect(res.body.data.regulatoryBody).toBe('NSW Law Society');
    });

    it('returns 404 for unknown state', async () => {
      const res = await request(app).get('/api/states/XYZ');
      expect(res.status).toBe(404);
      expect(res.body.success).toBe(false);
    });
  });

  describe('GET /api/matters', () => {
    it('returns list of matters', async () => {
      const res = await request(app).get('/api/matters');
      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(Array.isArray(res.body.data)).toBe(true);
    });

    it('filters matters by state', async () => {
      const res = await request(app).get('/api/matters?state=NSW');
      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      const matters = res.body.data;
      matters.forEach((m: { state: string }) => expect(m.state).toBe('NSW'));
    });
  });

  describe('POST /api/matters', () => {
    it('creates a new matter', async () => {
      const res = await request(app).post('/api/matters').send({
        matterNumber: 'TEST-001',
        description: 'Test Matter',
        clientName: 'Test Client',
        clientEmail: 'test@example.com',
        clientPhone: '0400 000 000',
        matterType: 'commercial',
        state: 'VIC',
        responsibleSolicitor: 'Jane Doe',
        openedDate: '2024-01-01',
      });
      expect(res.status).toBe(201);
      expect(res.body.success).toBe(true);
      expect(res.body.data.matterNumber).toBe('TEST-001');
      expect(res.body.data.state).toBe('VIC');
      expect(res.body.data.trustBalance).toBe(0);
    });

    it('rejects matter with missing required fields', async () => {
      const res = await request(app).post('/api/matters').send({
        matterNumber: 'TEST-002',
      });
      expect(res.status).toBe(400);
      expect(res.body.success).toBe(false);
    });

    it('rejects matter with invalid state', async () => {
      const res = await request(app).post('/api/matters').send({
        matterNumber: 'TEST-003',
        description: 'Test',
        clientName: 'Test',
        state: 'INVALID',
      });
      expect(res.status).toBe(400);
      expect(res.body.success).toBe(false);
    });
  });

  describe('GET /api/trust-accounts', () => {
    it('returns list of trust accounts', async () => {
      const res = await request(app).get('/api/trust-accounts');
      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(Array.isArray(res.body.data)).toBe(true);
    });

    it('returns trust accounts for each state', async () => {
      const states = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];
      for (const state of states) {
        const res = await request(app).get(`/api/trust-accounts?state=${state}`);
        expect(res.status).toBe(200);
        expect(res.body.success).toBe(true);
        expect(res.body.data.length).toBeGreaterThanOrEqual(1);
      }
    });
  });

  describe('POST /api/trust-accounts', () => {
    it('creates a new trust account', async () => {
      const res = await request(app).post('/api/trust-accounts').send({
        accountName: 'QLD Trust Account 2',
        bsb: '124-999',
        accountNumber: '99999999',
        bankName: 'ANZ',
        state: 'QLD',
      });
      expect(res.status).toBe(201);
      expect(res.body.success).toBe(true);
      expect(res.body.data.state).toBe('QLD');
      expect(res.body.data.currentBalance).toBe(0);
      expect(res.body.data.status).toBe('active');
    });
  });

  describe('POST /api/transactions', () => {
    let matterId: string;
    let trustAccountId: string;

    beforeAll(async () => {
      // Create a matter
      const matterRes = await request(app).post('/api/matters').send({
        matterNumber: 'TXN-TEST-001',
        description: 'Transaction Test Matter',
        clientName: 'Transaction Test Client',
        clientEmail: 'txn@example.com',
        clientPhone: '0400 111 222',
        matterType: 'conveyancing',
        state: 'NSW',
        responsibleSolicitor: 'Test Solicitor',
        openedDate: '2024-01-01',
      });
      matterId = matterRes.body.data.id;

      // Get NSW trust account
      const accountRes = await request(app).get('/api/trust-accounts?state=NSW');
      trustAccountId = accountRes.body.data[0].id;
    });

    it('creates a deposit transaction', async () => {
      const res = await request(app).post('/api/transactions').send({
        matterId,
        trustAccountId,
        type: 'deposit',
        amount: 5000,
        description: 'Client deposit',
        reference: 'REF-001',
        payerPayee: 'Transaction Test Client',
        date: '2024-02-01',
      });
      expect(res.status).toBe(201);
      expect(res.body.success).toBe(true);
      expect(res.body.data.type).toBe('deposit');
      expect(res.body.data.amount).toBe(5000);
    });

    it('creates a withdrawal from funded matter', async () => {
      const res = await request(app).post('/api/transactions').send({
        matterId,
        trustAccountId,
        type: 'withdrawal',
        amount: 1000,
        description: 'Disbursement',
        reference: 'REF-002',
        payerPayee: 'Court Registry',
        date: '2024-02-05',
      });
      expect(res.status).toBe(201);
      expect(res.body.success).toBe(true);
      expect(res.body.data.type).toBe('withdrawal');
    });

    it('rejects withdrawal exceeding trust balance', async () => {
      const res = await request(app).post('/api/transactions').send({
        matterId,
        trustAccountId,
        type: 'withdrawal',
        amount: 999999,
        description: 'Excessive withdrawal',
        reference: 'REF-003',
        payerPayee: 'Test',
        date: '2024-02-06',
      });
      expect(res.status).toBe(400);
      expect(res.body.success).toBe(false);
      expect(res.body.error).toContain('Insufficient trust funds');
    });

    it('rejects zero amount transactions', async () => {
      const res = await request(app).post('/api/transactions').send({
        matterId,
        trustAccountId,
        type: 'deposit',
        amount: 0,
        description: 'Zero deposit',
        reference: 'REF-004',
        payerPayee: 'Test',
        date: '2024-02-07',
      });
      expect(res.status).toBe(400);
      expect(res.body.success).toBe(false);
    });
  });

  describe('GET /api/matters/:id/ledger', () => {
    it('returns trust ledger for a matter', async () => {
      const mattersRes = await request(app).get('/api/matters');
      const matter = mattersRes.body.data[0];

      const res = await request(app).get(`/api/matters/${matter.id}/ledger`);
      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.data.matterId).toBe(matter.id);
      expect(Array.isArray(res.body.data.entries)).toBe(true);
    });

    it('returns 404 for non-existent matter', async () => {
      const res = await request(app).get('/api/matters/non-existent-id/ledger');
      expect(res.status).toBe(404);
    });
  });

  describe('POST /api/reconciliations', () => {
    it('creates a reconciliation', async () => {
      const accountsRes = await request(app).get('/api/trust-accounts?state=VIC');
      const trustAccountId = accountsRes.body.data[0].id;

      const res = await request(app).post('/api/reconciliations').send({
        trustAccountId,
        state: 'VIC',
        periodStart: '2024-01-01',
        periodEnd: '2024-01-31',
        bankStatementBalance: accountsRes.body.data[0].currentBalance,
        notes: 'Monthly reconciliation January 2024',
        preparedBy: 'Jane Smith',
      });
      expect(res.status).toBe(201);
      expect(res.body.success).toBe(true);
      expect(res.body.data.state).toBe('VIC');
      expect(res.body.data.status).toBe('draft');
    });
  });

  describe('GET /api/states/dashboard/summary', () => {
    it('returns dashboard data', async () => {
      const res = await request(app).get('/api/states/dashboard/summary');
      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(typeof res.body.data.totalTrustFunds).toBe('number');
      expect(typeof res.body.data.totalMatters).toBe('number');
      expect(typeof res.body.data.activeMatters).toBe('number');
      expect(res.body.data.byState).toHaveProperty('NSW');
      expect(res.body.data.byState).toHaveProperty('VIC');
      expect(res.body.data.byState).toHaveProperty('QLD');
    });
  });
});
