const API_BASE = '/api';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.error || 'Request failed');
  return data.data as T;
}

export const api = {
  // Dashboard
  getDashboard: () => fetchJson('/states/dashboard/summary'),

  // States
  getStates: () => fetchJson('/states'),
  getState: (code: string) => fetchJson(`/states/${code}`),

  // Matters
  getMatters: (state?: string) =>
    fetchJson(`/matters${state ? `?state=${state}` : ''}`),
  getMatter: (id: string) => fetchJson(`/matters/${id}`),
  createMatter: (data: unknown) =>
    fetchJson('/matters', { method: 'POST', body: JSON.stringify(data) }),
  updateMatter: (id: string, data: unknown) =>
    fetchJson(`/matters/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  getMatterLedger: (id: string) => fetchJson(`/matters/${id}/ledger`),

  // Trust Accounts
  getTrustAccounts: (state?: string) =>
    fetchJson(`/trust-accounts${state ? `?state=${state}` : ''}`),
  getTrustAccount: (id: string) => fetchJson(`/trust-accounts/${id}`),
  createTrustAccount: (data: unknown) =>
    fetchJson('/trust-accounts', { method: 'POST', body: JSON.stringify(data) }),

  // Transactions
  getTransactions: (params?: { matterId?: string; trustAccountId?: string }) => {
    const qs = params?.matterId
      ? `?matterId=${params.matterId}`
      : params?.trustAccountId
      ? `?trustAccountId=${params.trustAccountId}`
      : '';
    return fetchJson(`/transactions${qs}`);
  },
  createTransaction: (data: unknown) =>
    fetchJson('/transactions', { method: 'POST', body: JSON.stringify(data) }),
  reverseTransaction: (id: string, reason: string) =>
    fetchJson(`/transactions/${id}/reverse`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  // Reconciliations
  getReconciliations: (trustAccountId?: string) =>
    fetchJson(`/reconciliations${trustAccountId ? `?trustAccountId=${trustAccountId}` : ''}`),
  createReconciliation: (data: unknown) =>
    fetchJson('/reconciliations', { method: 'POST', body: JSON.stringify(data) }),
  approveReconciliation: (id: string, approvedBy: string) =>
    fetchJson(`/reconciliations/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approvedBy }),
    }),
};
