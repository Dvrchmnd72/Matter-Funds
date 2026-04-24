import { useState, useEffect } from 'react';
import { api } from '../utils/api';
import { TrustAccount, AustralianState } from '../types';
import { formatCurrency, formatDate } from '../utils/format';

const STATES: AustralianState[] = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];

interface TrustAccountFormData {
  accountName: string;
  bsb: string;
  accountNumber: string;
  bankName: string;
  state: AustralianState;
}

const emptyForm: TrustAccountFormData = {
  accountName: '',
  bsb: '',
  accountNumber: '',
  bankName: '',
  state: 'NSW',
};

export default function TrustAccounts() {
  const [accounts, setAccounts] = useState<TrustAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedState, setSelectedState] = useState<AustralianState | 'all'>('all');
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState<TrustAccountFormData>(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  const fetchAccounts = async () => {
    try {
      const state = selectedState === 'all' ? undefined : selectedState;
      const data = await api.getTrustAccounts(state);
      setAccounts(data as TrustAccount[]);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAccounts(); }, [selectedState]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    setSubmitting(true);
    try {
      await api.createTrustAccount(form);
      setShowModal(false);
      setForm(emptyForm);
      await fetchAccounts();
    } catch (e: unknown) {
      setFormError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const totalBalance = accounts.reduce((s, a) => s + a.currentBalance, 0);

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Trust Accounts</div>
          <div className="page-subtitle">Manage trust accounts across all Australian states</div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          + New Trust Account
        </button>
      </div>

      {error && <div className="alert alert-error">⚠️ {error}</div>}

      <div className="stats-grid" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-label">Total Accounts</div>
          <div className="stat-value blue">{accounts.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Balance</div>
          <div className="stat-value green">{formatCurrency(totalBalance)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Active Accounts</div>
          <div className="stat-value">{accounts.filter((a) => a.status === 'active').length}</div>
        </div>
      </div>

      <div className="state-selector">
        <button
          className={`state-btn ${selectedState === 'all' ? 'active' : ''}`}
          onClick={() => setSelectedState('all')}
        >
          All States
        </button>
        {STATES.map((s) => (
          <button
            key={s}
            className={`state-btn ${selectedState === s ? 'active' : ''}`}
            onClick={() => setSelectedState(s)}
          >
            {s}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading"><div className="spinner" />Loading trust accounts...</div>
      ) : accounts.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🏦</div>
          <div className="empty-state-text">No trust accounts found</div>
        </div>
      ) : (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Account Name</th>
                <th>Bank</th>
                <th>BSB</th>
                <th>Account Number</th>
                <th>State</th>
                <th style={{ textAlign: 'right' }}>Balance</th>
                <th>Last Reconciled</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id}>
                  <td>
                    <strong>{a.accountName}</strong>
                  </td>
                  <td>{a.bankName}</td>
                  <td style={{ fontFamily: 'monospace' }}>{a.bsb}</td>
                  <td style={{ fontFamily: 'monospace' }}>{a.accountNumber}</td>
                  <td><span className="state-tag">{a.state}</span></td>
                  <td
                    style={{ textAlign: 'right' }}
                    className={a.currentBalance > 0 ? 'amount-positive' : 'amount-zero'}
                  >
                    {formatCurrency(a.currentBalance)}
                  </td>
                  <td style={{ color: 'var(--gray-500)', fontSize: 13 }}>
                    {a.lastReconciliationDate ? formatDate(a.lastReconciliationDate) : '—'}
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        a.status === 'active' ? 'badge-green' : a.status === 'suspended' ? 'badge-amber' : 'badge-gray'
                      }`}
                    >
                      {a.status}
                    </span>
                  </td>
                </tr>
              ))}
              <tr className="summary-row">
                <td colSpan={5} style={{ textAlign: 'right', fontWeight: 600 }}>Total</td>
                <td style={{ textAlign: 'right', fontWeight: 700 }} className="amount-positive">
                  {formatCurrency(totalBalance)}
                </td>
                <td colSpan={2} />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">New Trust Account</div>
              <button className="modal-close" onClick={() => setShowModal(false)}>×</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="modal-body">
                {formError && <div className="alert alert-error">⚠️ {formError}</div>}
                <div className="alert alert-warning">
                  <span>⚠️</span>
                  <div>
                    Trust accounts must be opened at an approved ADI (Authorised Deposit-taking
                    Institution) and registered with the relevant state regulatory body before use.
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Account Name <span className="required">*</span></label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="e.g. NSW General Trust Account"
                      value={form.accountName}
                      onChange={(e) => setForm({ ...form, accountName: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">State <span className="required">*</span></label>
                    <select
                      className="form-select"
                      value={form.state}
                      onChange={(e) => setForm({ ...form, state: e.target.value as AustralianState })}
                    >
                      {STATES.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Bank Name <span className="required">*</span></label>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="e.g. Commonwealth Bank"
                    value={form.bankName}
                    onChange={(e) => setForm({ ...form, bankName: e.target.value })}
                    required
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">BSB <span className="required">*</span></label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="000-000"
                      value={form.bsb}
                      onChange={(e) => setForm({ ...form, bsb: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Account Number <span className="required">*</span></label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="12345678"
                      value={form.accountNumber}
                      onChange={(e) => setForm({ ...form, accountNumber: e.target.value })}
                      required
                    />
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? 'Creating...' : 'Create Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
