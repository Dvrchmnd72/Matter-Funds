import { v4 as uuidv4 } from 'uuid';
import {
  Matter,
  TrustAccount,
  Transaction,
  Reconciliation,
  CreateMatterRequest,
  CreateTransactionRequest,
  CreateTrustAccountRequest,
  CreateReconciliationRequest,
  AustralianState,
  TrustLedger,
  TrustLedgerEntry,
  TransactionType,
} from '../models/types';

// In-memory data stores
const matters: Map<string, Matter> = new Map();
const trustAccounts: Map<string, TrustAccount> = new Map();
const transactions: Map<string, Transaction> = new Map();
const reconciliations: Map<string, Reconciliation> = new Map();

// Seed some sample data for demonstration
function seedData(): void {
  // Create trust accounts for each state
  const stateAccounts: Partial<Record<AustralianState, string>> = {};

  const states: AustralianState[] = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];
  const banks = ['Commonwealth Bank', 'ANZ', 'Westpac', 'NAB', 'Bendigo Bank'];
  const bsbPrefixes: Record<AustralianState, string> = {
    NSW: '062',
    VIC: '013',
    QLD: '124',
    SA: '105',
    WA: '306',
    TAS: '037',
    ACT: '062',
    NT: '085',
  };

  states.forEach((state, idx) => {
    const accountId = uuidv4();
    const account: TrustAccount = {
      id: accountId,
      accountName: `${state} General Trust Account`,
      bsb: `${bsbPrefixes[state]}-${String(100 + idx).padStart(3, '0')}`,
      accountNumber: String(10000000 + idx * 1000000),
      bankName: banks[idx % banks.length],
      state,
      status: 'active',
      currentBalance: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    trustAccounts.set(accountId, account);
    stateAccounts[state] = accountId;
  });

  // Create sample matters
  const sampleMatters = [
    {
      state: 'NSW' as AustralianState,
      matterNumber: 'NSW-2024-001',
      description: 'Property Purchase - 42 Harbour View, Sydney',
      clientName: 'James & Sarah Mitchell',
      matterType: 'conveyancing' as const,
      solicitor: 'Emma Thompson',
    },
    {
      state: 'VIC' as AustralianState,
      matterNumber: 'VIC-2024-001',
      description: 'Divorce Settlement - Mitchell v Mitchell',
      clientName: 'Robert Mitchell',
      matterType: 'family_law' as const,
      solicitor: 'David Clarke',
    },
    {
      state: 'QLD' as AustralianState,
      matterNumber: 'QLD-2024-001',
      description: 'Business Sale - Gold Coast Café',
      clientName: 'Sunrise Holdings Pty Ltd',
      matterType: 'commercial' as const,
      solicitor: 'Lisa Johnson',
    },
    {
      state: 'SA' as AustralianState,
      matterNumber: 'SA-2024-001',
      description: 'Estate Administration - Estate of Margaret White',
      clientName: 'Thomas White (Executor)',
      matterType: 'estate' as const,
      solicitor: 'Michael Brown',
    },
    {
      state: 'WA' as AustralianState,
      matterNumber: 'WA-2024-001',
      description: 'Mining Lease Dispute',
      clientName: 'Pilbara Resources Ltd',
      matterType: 'litigation' as const,
      solicitor: 'Catherine Davis',
    },
  ];

  sampleMatters.forEach(({ state, matterNumber, description, clientName, matterType, solicitor }) => {
    const matterId = uuidv4();
    const matter: Matter = {
      id: matterId,
      matterNumber,
      description,
      clientName,
      clientEmail: `${clientName.toLowerCase().replace(/[^a-z]/g, '.')}@example.com`,
      clientPhone: '0400 000 000',
      matterType,
      status: 'active',
      state,
      responsibleSolicitor: solicitor,
      openedDate: '2024-01-15',
      trustBalance: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    matters.set(matterId, matter);

    // Add sample transactions for each matter
    const accountId = stateAccounts[state]!;
    const depositId = uuidv4();
    const depositAmount = Math.floor(Math.random() * 50000) + 10000;

    const deposit: Transaction = {
      id: depositId,
      matterId,
      matterNumber,
      trustAccountId: accountId,
      type: 'deposit',
      amount: depositAmount,
      description: 'Initial trust deposit',
      reference: `DEP-${matterNumber}`,
      payerPayee: clientName,
      date: '2024-01-16',
      clearedDate: '2024-01-17',
      status: 'cleared',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    transactions.set(depositId, deposit);

    // Update matter and account balances
    matter.trustBalance += depositAmount;
    const account = trustAccounts.get(accountId)!;
    account.currentBalance += depositAmount;
  });
}

seedData();

// Matter service
export const matterService = {
  getAll(): Matter[] {
    return Array.from(matters.values()).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    );
  },

  getByState(state: AustralianState): Matter[] {
    return Array.from(matters.values())
      .filter((m) => m.state === state)
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  },

  getById(id: string): Matter | undefined {
    return matters.get(id);
  },

  create(req: CreateMatterRequest): Matter {
    const id = uuidv4();
    const now = new Date().toISOString();
    const matter: Matter = {
      id,
      matterNumber: req.matterNumber,
      description: req.description,
      clientName: req.clientName,
      clientEmail: req.clientEmail,
      clientPhone: req.clientPhone,
      matterType: req.matterType,
      status: 'active',
      state: req.state,
      responsibleSolicitor: req.responsibleSolicitor,
      openedDate: req.openedDate,
      trustBalance: 0,
      createdAt: now,
      updatedAt: now,
    };
    matters.set(id, matter);
    return matter;
  },

  update(id: string, updates: Partial<Matter>): Matter | undefined {
    const matter = matters.get(id);
    if (!matter) return undefined;
    const updated = { ...matter, ...updates, id, updatedAt: new Date().toISOString() };
    matters.set(id, updated);
    return updated;
  },

  delete(id: string): boolean {
    return matters.delete(id);
  },

  getTrustLedger(matterId: string): TrustLedger | undefined {
    const matter = matters.get(matterId);
    if (!matter) return undefined;

    const matterTransactions = Array.from(transactions.values())
      .filter((t) => t.matterId === matterId)
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

    let runningBalance = 0;
    const entries: TrustLedgerEntry[] = matterTransactions.map((t) => {
      const isCredit = t.type === 'deposit' || t.type === 'interest';
      const debit = isCredit ? 0 : t.amount;
      const credit = isCredit ? t.amount : 0;
      runningBalance += credit - debit;

      return {
        transactionId: t.id,
        date: t.date,
        type: t.type,
        description: t.description,
        reference: t.reference,
        payerPayee: t.payerPayee,
        debit,
        credit,
        balance: runningBalance,
        status: t.status,
      };
    });

    return {
      matterId,
      matterNumber: matter.matterNumber,
      clientName: matter.clientName,
      state: matter.state,
      entries,
      openingBalance: 0,
      closingBalance: matter.trustBalance,
    };
  },
};

// Trust account service
export const trustAccountService = {
  getAll(): TrustAccount[] {
    return Array.from(trustAccounts.values()).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    );
  },

  getByState(state: AustralianState): TrustAccount[] {
    return Array.from(trustAccounts.values()).filter((a) => a.state === state);
  },

  getById(id: string): TrustAccount | undefined {
    return trustAccounts.get(id);
  },

  create(req: CreateTrustAccountRequest): TrustAccount {
    const id = uuidv4();
    const now = new Date().toISOString();
    const account: TrustAccount = {
      id,
      accountName: req.accountName,
      bsb: req.bsb,
      accountNumber: req.accountNumber,
      bankName: req.bankName,
      state: req.state,
      status: 'active',
      currentBalance: 0,
      createdAt: now,
      updatedAt: now,
    };
    trustAccounts.set(id, account);
    return account;
  },

  update(id: string, updates: Partial<TrustAccount>): TrustAccount | undefined {
    const account = trustAccounts.get(id);
    if (!account) return undefined;
    const updated = { ...account, ...updates, id, updatedAt: new Date().toISOString() };
    trustAccounts.set(id, updated);
    return updated;
  },
};

// Transaction service
export const transactionService = {
  getAll(): Transaction[] {
    return Array.from(transactions.values()).sort(
      (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
    );
  },

  getByMatter(matterId: string): Transaction[] {
    return Array.from(transactions.values())
      .filter((t) => t.matterId === matterId)
      .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  },

  getByTrustAccount(trustAccountId: string): Transaction[] {
    return Array.from(transactions.values())
      .filter((t) => t.trustAccountId === trustAccountId)
      .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  },

  getById(id: string): Transaction | undefined {
    return transactions.get(id);
  },

  create(req: CreateTransactionRequest): Transaction | { error: string } {
    const matter = matters.get(req.matterId);
    if (!matter) return { error: 'Matter not found' };

    const account = trustAccounts.get(req.trustAccountId);
    if (!account) return { error: 'Trust account not found' };

    if (account.status !== 'active') return { error: 'Trust account is not active' };

    const isDebit = req.type === 'withdrawal' || req.type === 'bank_fee';

    // Validate sufficient funds for withdrawals
    if (isDebit && matter.trustBalance < req.amount) {
      return { error: `Insufficient trust funds. Available: $${matter.trustBalance.toFixed(2)}` };
    }

    const id = uuidv4();
    const now = new Date().toISOString();
    const transaction: Transaction = {
      id,
      matterId: req.matterId,
      matterNumber: matter.matterNumber,
      trustAccountId: req.trustAccountId,
      type: req.type,
      amount: req.amount,
      description: req.description,
      reference: req.reference,
      payerPayee: req.payerPayee,
      date: req.date,
      status: 'pending',
      createdAt: now,
      updatedAt: now,
    };

    transactions.set(id, transaction);

    // Update balances
    const delta = isDebit ? -req.amount : req.amount;
    matter.trustBalance += delta;
    matter.updatedAt = now;
    account.currentBalance += delta;
    account.updatedAt = now;

    return transaction;
  },

  updateStatus(
    id: string,
    status: Transaction['status']
  ): Transaction | undefined {
    const transaction = transactions.get(id);
    if (!transaction) return undefined;
    const now = new Date().toISOString();
    const updated: Transaction = {
      ...transaction,
      status,
      clearedDate: status === 'cleared' || status === 'reconciled' ? transaction.clearedDate ?? now : transaction.clearedDate,
      updatedAt: now,
    };
    transactions.set(id, updated);
    return updated;
  },

  reverse(id: string, reason: string): Transaction | { error: string } {
    const original = transactions.get(id);
    if (!original) return { error: 'Transaction not found' };
    if (original.status === 'reversed') return { error: 'Transaction already reversed' };

    const matter = matters.get(original.matterId);
    if (!matter) return { error: 'Matter not found' };

    const account = trustAccounts.get(original.trustAccountId);
    if (!account) return { error: 'Trust account not found' };

    const isDebit = original.type === 'withdrawal' || original.type === 'bank_fee';

    // Reversal goes opposite direction
    if (!isDebit && matter.trustBalance < original.amount) {
      return { error: `Insufficient funds to reverse deposit` };
    }

    const reversalId = uuidv4();
    const now = new Date().toISOString();
    const reversalType: TransactionType = isDebit ? 'deposit' : 'withdrawal';

    const reversal: Transaction = {
      id: reversalId,
      matterId: original.matterId,
      matterNumber: original.matterNumber,
      trustAccountId: original.trustAccountId,
      type: reversalType,
      amount: original.amount,
      description: `REVERSAL: ${original.description} - ${reason}`,
      reference: `REV-${original.reference}`,
      payerPayee: original.payerPayee,
      date: new Date().toISOString().split('T')[0],
      status: 'cleared',
      reversalId: id,
      createdAt: now,
      updatedAt: now,
    };

    transactions.set(reversalId, reversal);

    // Update original as reversed
    const updatedOriginal = { ...original, status: 'reversed' as const, reversalId: reversalId, updatedAt: now };
    transactions.set(id, updatedOriginal);

    // Update balances
    const delta = isDebit ? original.amount : -original.amount;
    matter.trustBalance += delta;
    account.currentBalance += delta;

    return reversal;
  },
};

// Reconciliation service
export const reconciliationService = {
  getAll(): Reconciliation[] {
    return Array.from(reconciliations.values()).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    );
  },

  getByTrustAccount(trustAccountId: string): Reconciliation[] {
    return Array.from(reconciliations.values())
      .filter((r) => r.trustAccountId === trustAccountId)
      .sort((a, b) => new Date(b.periodEnd).getTime() - new Date(a.periodEnd).getTime());
  },

  getById(id: string): Reconciliation | undefined {
    return reconciliations.get(id);
  },

  create(req: CreateReconciliationRequest): Reconciliation | { error: string } {
    const account = trustAccounts.get(req.trustAccountId);
    if (!account) return { error: 'Trust account not found' };

    const trustLedgerBalance = account.currentBalance;
    const difference = req.bankStatementBalance - trustLedgerBalance;

    const id = uuidv4();
    const now = new Date().toISOString();
    const reconciliation: Reconciliation = {
      id,
      trustAccountId: req.trustAccountId,
      state: req.state,
      periodStart: req.periodStart,
      periodEnd: req.periodEnd,
      openingBalance: account.lastReconciliationBalance ?? 0,
      closingBalance: trustLedgerBalance,
      bankStatementBalance: req.bankStatementBalance,
      trustLedgerBalance,
      difference,
      status: 'draft',
      notes: req.notes,
      preparedBy: req.preparedBy,
      createdAt: now,
      updatedAt: now,
    };

    reconciliations.set(id, reconciliation);
    return reconciliation;
  },

  approve(id: string, approvedBy: string): Reconciliation | undefined {
    const reconciliation = reconciliations.get(id);
    if (!reconciliation) return undefined;

    const now = new Date().toISOString();
    const updated: Reconciliation = {
      ...reconciliation,
      status: 'approved',
      approvedBy,
      completedAt: now,
      updatedAt: now,
    };
    reconciliations.set(id, updated);

    // Update the trust account last reconciliation info
    const account = trustAccounts.get(reconciliation.trustAccountId);
    if (account) {
      account.lastReconciliationDate = reconciliation.periodEnd;
      account.lastReconciliationBalance = reconciliation.closingBalance;
      account.updatedAt = now;
    }

    return updated;
  },
};

// Dashboard/statistics service
export const statsService = {
  getDashboard() {
    const allMatters = Array.from(matters.values());
    const allAccounts = Array.from(trustAccounts.values());
    const allTransactions = Array.from(transactions.values());

    const totalTrustFunds = allAccounts.reduce((sum, a) => sum + a.currentBalance, 0);
    const activeMatters = allMatters.filter((m) => m.status === 'active').length;
    const pendingTransactions = allTransactions.filter((t) => t.status === 'pending').length;
    const recentTransactions = allTransactions
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
      .slice(0, 10);

    const byState = Object.fromEntries(
      (['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'] as AustralianState[]).map((state) => [
        state,
        {
          matters: allMatters.filter((m) => m.state === state).length,
          trustBalance: allAccounts
            .filter((a) => a.state === state)
            .reduce((sum, a) => sum + a.currentBalance, 0),
        },
      ])
    );

    return {
      totalTrustFunds,
      totalMatters: allMatters.length,
      activeMatters,
      totalTrustAccounts: allAccounts.length,
      pendingTransactions,
      recentTransactions,
      byState,
    };
  },
};
