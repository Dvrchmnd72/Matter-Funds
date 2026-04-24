export type AustralianState = 'NSW' | 'VIC' | 'QLD' | 'SA' | 'WA' | 'TAS' | 'ACT' | 'NT';

export const AUSTRALIAN_STATES: Record<AustralianState, StateInfo> = {
  NSW: {
    code: 'NSW',
    name: 'New South Wales',
    fullName: 'New South Wales',
    regulatoryBody: 'NSW Law Society',
    legislativeAct: 'Legal Profession Uniform Law 2014',
    trustAccountRules: 'Legal Profession Uniform General Rules 2015',
    interestRate: 'Refer to State Supervision Authority',
    annualAuditRequired: true,
    reconciliationFrequency: 'monthly',
    minimumRetentionYears: 7,
  },
  VIC: {
    code: 'VIC',
    name: 'Victoria',
    fullName: 'Victoria',
    regulatoryBody: 'Victorian Legal Services Board',
    legislativeAct: 'Legal Profession Uniform Law Application Act 2014',
    trustAccountRules: 'Legal Profession Uniform General Rules 2015',
    interestRate: 'Refer to State Supervision Authority',
    annualAuditRequired: true,
    reconciliationFrequency: 'monthly',
    minimumRetentionYears: 7,
  },
  QLD: {
    code: 'QLD',
    name: 'Queensland',
    fullName: 'Queensland',
    regulatoryBody: 'Queensland Law Society',
    legislativeAct: 'Legal Profession Act 2007 (Qld)',
    trustAccountRules: 'Legal Profession Regulation 2017 (Qld)',
    interestRate: 'Prescribed by regulation',
    annualAuditRequired: true,
    reconciliationFrequency: 'monthly',
    minimumRetentionYears: 7,
  },
  SA: {
    code: 'SA',
    name: 'South Australia',
    fullName: 'South Australia',
    regulatoryBody: 'Law Society of South Australia',
    legislativeAct: 'Legal Practitioners Act 1981 (SA)',
    trustAccountRules: 'Legal Practitioners Regulations 2014',
    interestRate: 'Prescribed by regulation',
    annualAuditRequired: true,
    reconciliationFrequency: 'monthly',
    minimumRetentionYears: 7,
  },
  WA: {
    code: 'WA',
    name: 'Western Australia',
    fullName: 'Western Australia',
    regulatoryBody: 'Legal Practice Board of Western Australia',
    legislativeAct: 'Legal Profession Act 2008 (WA)',
    trustAccountRules: 'Legal Profession Regulations 2009',
    interestRate: 'Prescribed by regulation',
    annualAuditRequired: true,
    reconciliationFrequency: 'monthly',
    minimumRetentionYears: 7,
  },
  TAS: {
    code: 'TAS',
    name: 'Tasmania',
    fullName: 'Tasmania',
    regulatoryBody: 'Law Society of Tasmania',
    legislativeAct: 'Legal Profession Act 2007 (Tas)',
    trustAccountRules: 'Legal Profession Regulations 2008',
    interestRate: 'Prescribed by regulation',
    annualAuditRequired: true,
    reconciliationFrequency: 'monthly',
    minimumRetentionYears: 7,
  },
  ACT: {
    code: 'ACT',
    name: 'Australian Capital Territory',
    fullName: 'Australian Capital Territory',
    regulatoryBody: 'ACT Law Society',
    legislativeAct: 'Legal Profession Uniform Law Application Act 2014 (ACT)',
    trustAccountRules: 'Legal Profession Uniform General Rules 2015',
    interestRate: 'Refer to State Supervision Authority',
    annualAuditRequired: true,
    reconciliationFrequency: 'monthly',
    minimumRetentionYears: 7,
  },
  NT: {
    code: 'NT',
    name: 'Northern Territory',
    fullName: 'Northern Territory',
    regulatoryBody: 'Law Society Northern Territory',
    legislativeAct: 'Legal Profession Act 2006 (NT)',
    trustAccountRules: 'Legal Profession Regulations 2007',
    interestRate: 'Prescribed by regulation',
    annualAuditRequired: true,
    reconciliationFrequency: 'monthly',
    minimumRetentionYears: 7,
  },
};

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

export interface CreateMatterRequest {
  matterNumber: string;
  description: string;
  clientName: string;
  clientEmail: string;
  clientPhone: string;
  matterType: MatterType;
  state: AustralianState;
  responsibleSolicitor: string;
  openedDate: string;
}

export interface CreateTransactionRequest {
  matterId: string;
  trustAccountId: string;
  type: TransactionType;
  amount: number;
  description: string;
  reference: string;
  payerPayee: string;
  date: string;
}

export interface CreateTrustAccountRequest {
  accountName: string;
  bsb: string;
  accountNumber: string;
  bankName: string;
  state: AustralianState;
}

export interface CreateReconciliationRequest {
  trustAccountId: string;
  state: AustralianState;
  periodStart: string;
  periodEnd: string;
  bankStatementBalance: number;
  notes: string;
  preparedBy: string;
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

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}
