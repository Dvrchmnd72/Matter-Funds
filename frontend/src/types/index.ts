export type AustralianState = 'NSW' | 'VIC' | 'QLD' | 'SA' | 'WA' | 'TAS' | 'ACT' | 'NT';

export interface StateInfo {
  code: AustralianState;
  name: string;
  fullName: string;
  regulatoryBody: string;
  legislativeAct: string;
  trustAccountRules: string;
  interestRate: string;
  annualAuditRequired: boolean;
  reconciliationFrequency: 'monthly' | 'quarterly';
  minimumRetentionYears: number;
}

export type MatterStatus = 'active' | 'closed' | 'archived';
export type MatterType =
  | 'conveyancing'
  | 'family_law'
  | 'commercial'
  | 'litigation'
  | 'estate'
  | 'criminal'
  | 'immigration'
  | 'employment'
  | 'other';

export interface Matter {
  id: string;
  matterNumber: string;
  description: string;
  clientName: string;
  clientEmail: string;
  clientPhone: string;
  matterType: MatterType;
  status: MatterStatus;
  state: AustralianState;
  responsibleSolicitor: string;
  openedDate: string;
  closedDate?: string;
  trustBalance: number;
  createdAt: string;
  updatedAt: string;
}

export type TransactionType = 'deposit' | 'withdrawal' | 'transfer' | 'bank_fee' | 'interest';
export type TransactionStatus = 'pending' | 'cleared' | 'reconciled' | 'reversed';

export interface Transaction {
  id: string;
  matterId: string;
  matterNumber: string;
  trustAccountId: string;
  type: TransactionType;
  amount: number;
  description: string;
  reference: string;
  payerPayee: string;
  date: string;
  clearedDate?: string;
  reconciledDate?: string;
  status: TransactionStatus;
  reversalId?: string;
  createdAt: string;
  updatedAt: string;
}

export type TrustAccountStatus = 'active' | 'closed' | 'suspended';

export interface TrustAccount {
  id: string;
  accountName: string;
  bsb: string;
  accountNumber: string;
  bankName: string;
  state: AustralianState;
  status: TrustAccountStatus;
  currentBalance: number;
  lastReconciliationDate?: string;
  lastReconciliationBalance?: number;
  createdAt: string;
  updatedAt: string;
}

export interface Reconciliation {
  id: string;
  trustAccountId: string;
  state: AustralianState;
  periodStart: string;
  periodEnd: string;
  openingBalance: number;
  closingBalance: number;
  bankStatementBalance: number;
  trustLedgerBalance: number;
  difference: number;
  status: 'draft' | 'completed' | 'approved';
  notes: string;
  preparedBy: string;
  approvedBy?: string;
  completedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface TrustLedgerEntry {
  transactionId: string;
  date: string;
  type: TransactionType;
  description: string;
  reference: string;
  payerPayee: string;
  debit: number;
  credit: number;
  balance: number;
  status: TransactionStatus;
}

export interface TrustLedger {
  matterId: string;
  matterNumber: string;
  clientName: string;
  state: AustralianState;
  entries: TrustLedgerEntry[];
  openingBalance: number;
  closingBalance: number;
}

export interface DashboardData {
  totalTrustFunds: number;
  totalMatters: number;
  activeMatters: number;
  totalTrustAccounts: number;
  pendingTransactions: number;
  recentTransactions: Transaction[];
  byState: Record<AustralianState, { matters: number; trustBalance: number }>;
}

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}
