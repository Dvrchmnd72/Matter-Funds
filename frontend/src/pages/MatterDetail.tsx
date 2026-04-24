import { useState, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../utils/api';
import { Matter, TrustLedger, Transaction, TrustAccount, TransactionType } from '../types';
import { formatCurrency, formatDate, getMatterTypeLabel, getTransactionTypeLabel } from '../utils/format';

interface TxnFormData {
  trustAccountId: string;
  type: TransactionType;
  amount: string;
  description: string;
  reference: string;
  payerPayee: string;
  date: string;
}

export default function MatterDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [matter, setMatter] = useState<Matter | null>(null);
  const [ledger, setLedger] = useState<TrustLedger | null>(null);
  const [accounts, setAccounts] = useState<TrustAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showTxnModal, setShowTxnModal] = useState(false);
  const [txnForm, setTxnForm] = useState<TxnFormData>({
    trustAccountId: '',
    type: 'deposit',
    amount: '',
    description: '',
    reference: '',
    payerPayee: '',
    date: new Date().toISOString().split('T')[0],
  });
  const [txnError, setTxnError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [m, l] = await Promise.all([
        api.getMatter(id) as Promise<Matter>,
        api.getMatterLedger(id) as Promise<TrustLedger>,
      ]);
      setMatter(m);
      setLedger(l);
      const accts = await api.getTrustAccounts(m.state) as TrustAccount[];
      setAccounts(accts);
      if (accts.length > 0) {
        setTxnForm((f) => ({ ...f, trustAccountId: accts[0].id }));
      }
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const handleTxnSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTxnError('');
    setSubmitting(true);
    try {
      await api.createTransaction({
        matterId: id,
        trustAccountId: txnForm.trustAccountId,
        type: txnForm.type,
        amount: parseFloat(txnForm.amount),
        description: txnForm.description,
        reference: txnForm.reference,
        payerPayee: txnForm.payerPayee,
        date: txnForm.date,
      });
      setShowTxnModal(false);
      await load();
    } catch (e: unknown) {
      setTxnError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleReverse = async (txn: Transaction) => {
    const reason = window.prompt(`Enter reason for reversing transaction "${txn.description}":`);
    if (!reason) return;
    try {
      await api.reverseTransaction(txn.id, reason);
      await load();
    } catch (e: unknown) {
      alert((e as Error).message);
    }
  };

  if (loading) return <div className="loading"><div className="spinner" />Loading matter...</div>;
  if (error) return <div className="alert alert-error">⚠️ {error}</div>;
  if (!matter || !ledger) return null;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/matters')}>
          ← Back
        </button>
        <div>
          <div className="page-title">{matter.matterNumber}</div>
          <div className="page-subtitle">{matter.description}</div>
        </div>
        {matter.status === 'active' && (
          <button
            className="btn btn-primary"
            style={{ marginLeft: 'auto' }}
            onClick={() => setShowTxnModal(true)}
          >
            + New Transaction
          </button>
        )}
      </div>

      {/* Matter info */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16 }}>
          <div>
            <div className="stat-label">Client</div>
            <div style={{ fontWeight: 600 }}>{matter.clientName}</div>
            <div style={{ fontSize: 12, color: 'var(--gray-500)' }}>{matter.clientEmail}</div>
          </div>
          <div>
            <div className="stat-label">Type</div>
            <div>
              <span className="badge badge-blue">{getMatterTypeLabel(matter.matterType)}</span>
            </div>
          </div>
          <div>
            <div className="stat-label">State</div>
            <span className="state-tag">{matter.state}</span>
          </div>
          <div>
            <div className="stat-label">Solicitor</div>
            <div style={{ fontWeight: 500 }}>{matter.responsibleSolicitor}</div>
          </div>
          <div>
            <div className="stat-label">Opened</div>
            <div>{formatDate(matter.openedDate)}</div>
          </div>
          <div>
            <div className="stat-label">Status</div>
            <span
              className={`badge ${matter.status === 'active' ? 'badge-green' : 'badge-gray'}`}
            >
              {matter.status}
            </span>
          </div>
          <div>
            <div className="stat-label">Trust Balance</div>
            <div
              style={{ fontSize: 20, fontWeight: 700 }}
              className={matter.trustBalance > 0 ? 'amount-positive' : 'amount-zero'}
            >
              {formatCurrency(matter.trustBalance)}
            </div>
          </div>
        </div>
      </div>

      {/* Trust Ledger */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Trust Ledger</div>
          <div style={{ fontSize: 13, color: 'var(--gray-500)' }}>
            {ledger.entries.length} transaction{ledger.entries.length !== 1 ? 's' : ''}
          </div>
        </div>

        {ledger.entries.length === 0 ? (
          <div className="empty-state" style={{ padding: '40px 20px' }}>
            <div className="empty-state-icon">📋</div>
            <div className="empty-state-text">No transactions yet</div>
            <div className="empty-state-sub">Record a trust deposit to get started</div>
          </div>
        ) : (
          <div className="table-container">
            <table className="ledger-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Type</th>
                  <th>Description</th>
                  <th>Reference</th>
                  <th>Payer/Payee</th>
                  <th>Debit</th>
                  <th>Credit</th>
                  <th>Balance</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {ledger.entries.map((e) => (
                  <tr key={e.transactionId}>
                    <td style={{ whiteSpace: 'nowrap' }}>{e.date}</td>
                    <td>
                      <span className={`badge ${e.credit > 0 ? 'badge-green' : 'badge-red'}`}>
                        {getTransactionTypeLabel(e.type)}
                      </span>
                    </td>
                    <td style={{ color: 'var(--gray-700)' }}>{e.description}</td>
                    <td style={{ color: 'var(--gray-500)', fontSize: 12 }}>{e.reference}</td>
                    <td style={{ color: 'var(--gray-600)' }}>{e.payerPayee}</td>
                    <td className={e.debit > 0 ? 'amount-negative' : 'amount-zero'}>
                      {e.debit > 0 ? formatCurrency(e.debit) : '—'}
                    </td>
                    <td className={e.credit > 0 ? 'amount-positive' : 'amount-zero'}>
                      {e.credit > 0 ? formatCurrency(e.credit) : '—'}
                    </td>
                    <td style={{ fontWeight: 600 }}>{formatCurrency(e.balance)}</td>
                    <td>
                      <span
                        className={`badge ${
                          e.status === 'cleared' || e.status === 'reconciled'
                            ? 'badge-green'
                            : e.status === 'pending'
                            ? 'badge-amber'
                            : 'badge-red'
                        }`}
                      >
                        {e.status}
                      </span>
                    </td>
                    <td>
                      {e.status !== 'reversed' && (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() =>
                            handleReverse({ id: e.transactionId } as Transaction)
                          }
                        >
                          Reverse
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                <tr className="summary-row">
                  <td colSpan={5} style={{ textAlign: 'right', paddingRight: 14 }}>
                    <strong>Totals</strong>
                  </td>
                  <td className="amount-negative">
                    {formatCurrency(ledger.entries.reduce((s, e) => s + e.debit, 0))}
                  </td>
                  <td className="amount-positive">
                    {formatCurrency(ledger.entries.reduce((s, e) => s + e.credit, 0))}
                  </td>
                  <td style={{ fontWeight: 700 }}>{formatCurrency(matter.trustBalance)}</td>
                  <td colSpan={2} />
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* New Transaction Modal */}
      {showTxnModal && (
        <div className="modal-overlay" onClick={() => setShowTxnModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">New Transaction</div>
              <button className="modal-close" onClick={() => setShowTxnModal(false)}>×</button>
            </div>
            <form onSubmit={handleTxnSubmit}>
              <div className="modal-body">
                {txnError && (
                  <div className="alert alert-error">⚠️ {txnError}</div>
                )}
                <div className="alert alert-info" style={{ marginBottom: 16 }}>
                  <span>ℹ️</span>
                  <div>
                    All trust transactions are recorded in the trust ledger and subject to{' '}
                    <strong>{matter.state} trust accounting regulations</strong>.
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Transaction Type <span className="required">*</span></label>
                    <select
                      className="form-select"
                      value={txnForm.type}
                      onChange={(e) => setTxnForm({ ...txnForm, type: e.target.value as TransactionType })}
                    >
                      <option value="deposit">Deposit (Credit)</option>
                      <option value="withdrawal">Withdrawal (Debit)</option>
                      <option value="transfer">Transfer</option>
                      <option value="bank_fee">Bank Fee</option>
                      <option value="interest">Interest</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Trust Account <span className="required">*</span></label>
                    <select
                      className="form-select"
                      value={txnForm.trustAccountId}
                      onChange={(e) => setTxnForm({ ...txnForm, trustAccountId: e.target.value })}
                    >
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.accountName} ({a.bankName})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Amount (AUD) <span className="required">*</span></label>
                    <input
                      type="number"
                      className="form-input"
                      min="0.01"
                      step="0.01"
                      placeholder="0.00"
                      value={txnForm.amount}
                      onChange={(e) => setTxnForm({ ...txnForm, amount: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Date <span className="required">*</span></label>
                    <input
                      type="date"
                      className="form-input"
                      value={txnForm.date}
                      onChange={(e) => setTxnForm({ ...txnForm, date: e.target.value })}
                      required
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Description <span className="required">*</span></label>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="Brief description"
                    value={txnForm.description}
                    onChange={(e) => setTxnForm({ ...txnForm, description: e.target.value })}
                    required
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Reference</label>
                    <input
                      type="text"
                      className="form-input"
                      value={txnForm.reference}
                      onChange={(e) => setTxnForm({ ...txnForm, reference: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Payer / Payee</label>
                    <input
                      type="text"
                      className="form-input"
                      value={txnForm.payerPayee}
                      onChange={(e) => setTxnForm({ ...txnForm, payerPayee: e.target.value })}
                    />
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowTxnModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? 'Saving...' : 'Record Transaction'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
