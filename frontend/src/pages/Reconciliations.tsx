import { useState, useEffect } from 'react';
import { api } from '../utils/api';
import { Reconciliation, TrustAccount, AustralianState } from '../types';
import { formatCurrency, formatDate } from '../utils/format';

interface ReconciliationFormData {
  trustAccountId: string;
  state: AustralianState;
  periodStart: string;
  periodEnd: string;
  bankStatementBalance: string;
  notes: string;
  preparedBy: string;
}

export default function Reconciliations() {
  const [reconciliations, setReconciliations] = useState<Reconciliation[]>([]);
  const [accounts, setAccounts] = useState<TrustAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState<ReconciliationFormData>({
    trustAccountId: '',
    state: 'NSW',
    periodStart: '',
    periodEnd: '',
    bankStatementBalance: '',
    notes: '',
    preparedBy: '',
  });
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [recs, accts] = await Promise.all([
        api.getReconciliations() as Promise<Reconciliation[]>,
        api.getTrustAccounts() as Promise<TrustAccount[]>,
      ]);
      setReconciliations(recs);
      setAccounts(accts);
      if (accts.length > 0) {
        setForm((f) => ({ ...f, trustAccountId: accts[0].id, state: accts[0].state }));
      }
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    setSubmitting(true);
    try {
      await api.createReconciliation({
        ...form,
        bankStatementBalance: parseFloat(form.bankStatementBalance),
      });
      setShowModal(false);
      await fetchData();
    } catch (e: unknown) {
      setFormError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleApprove = async (id: string) => {
    const approvedBy = window.prompt('Enter approver name:');
    if (!approvedBy) return;
    try {
      await api.approveReconciliation(id, approvedBy);
      await fetchData();
    } catch (e: unknown) {
      alert((e as Error).message);
    }
  };

  const handleAccountChange = (accountId: string) => {
    const account = accounts.find((a) => a.id === accountId);
    setForm((f) => ({
      ...f,
      trustAccountId: accountId,
      state: account?.state ?? f.state,
    }));
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Reconciliations</div>
          <div className="page-subtitle">Monthly trust account reconciliations</div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          + New Reconciliation
        </button>
      </div>

      {error && <div className="alert alert-error">⚠️ {error}</div>}

      <div className="alert alert-info" style={{ marginBottom: 20 }}>
        <span>ℹ️</span>
        <div>
          Australian law requires trust accounts to be reconciled at least <strong>monthly</strong>.
          The reconciliation compares the trust ledger balance with the bank statement balance.
          Any difference must be investigated and resolved promptly.
        </div>
      </div>

      {loading ? (
        <div className="loading"><div className="spinner" />Loading...</div>
      ) : reconciliations.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">✅</div>
          <div className="empty-state-text">No reconciliations found</div>
          <div className="empty-state-sub">Create your first monthly reconciliation</div>
        </div>
      ) : (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Period</th>
                <th>Trust Account</th>
                <th>State</th>
                <th style={{ textAlign: 'right' }}>Bank Balance</th>
                <th style={{ textAlign: 'right' }}>Ledger Balance</th>
                <th style={{ textAlign: 'right' }}>Difference</th>
                <th>Status</th>
                <th>Prepared By</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {reconciliations.map((r) => {
                const account = accounts.find((a) => a.id === r.trustAccountId);
                return (
                  <tr key={r.id}>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {formatDate(r.periodStart)} – {formatDate(r.periodEnd)}
                    </td>
                    <td style={{ color: 'var(--gray-700)' }}>{account?.accountName ?? '—'}</td>
                    <td><span className="state-tag">{r.state}</span></td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>
                      {formatCurrency(r.bankStatementBalance)}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>
                      {formatCurrency(r.trustLedgerBalance)}
                    </td>
                    <td
                      style={{ textAlign: 'right', fontFamily: 'monospace' }}
                      className={
                        r.difference === 0
                          ? 'amount-positive'
                          : 'amount-negative'
                      }
                    >
                      {r.difference === 0 ? '✓ Balanced' : formatCurrency(r.difference)}
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          r.status === 'approved'
                            ? 'badge-green'
                            : r.status === 'completed'
                            ? 'badge-blue'
                            : 'badge-amber'
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td style={{ color: 'var(--gray-600)' }}>{r.preparedBy}</td>
                    <td>
                      {r.status === 'draft' && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => handleApprove(r.id)}
                        >
                          Approve
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">New Reconciliation</div>
              <button className="modal-close" onClick={() => setShowModal(false)}>×</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="modal-body">
                {formError && <div className="alert alert-error">⚠️ {formError}</div>}
                <div className="form-group">
                  <label className="form-label">Trust Account <span className="required">*</span></label>
                  <select
                    className="form-select"
                    value={form.trustAccountId}
                    onChange={(e) => handleAccountChange(e.target.value)}
                    required
                  >
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.state} — {a.accountName} ({a.bankName})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Period Start <span className="required">*</span></label>
                    <input
                      type="date"
                      className="form-input"
                      value={form.periodStart}
                      onChange={(e) => setForm({ ...form, periodStart: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Period End <span className="required">*</span></label>
                    <input
                      type="date"
                      className="form-input"
                      value={form.periodEnd}
                      onChange={(e) => setForm({ ...form, periodEnd: e.target.value })}
                      required
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">
                    Bank Statement Closing Balance <span className="required">*</span>
                  </label>
                  <input
                    type="number"
                    className="form-input"
                    step="0.01"
                    placeholder="0.00"
                    value={form.bankStatementBalance}
                    onChange={(e) => setForm({ ...form, bankStatementBalance: e.target.value })}
                    required
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Prepared By <span className="required">*</span></label>
                    <input
                      type="text"
                      className="form-input"
                      value={form.preparedBy}
                      onChange={(e) => setForm({ ...form, preparedBy: e.target.value })}
                      required
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Notes</label>
                  <textarea
                    className="form-textarea"
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    placeholder="Any reconciling items or notes..."
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? 'Saving...' : 'Create Reconciliation'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
