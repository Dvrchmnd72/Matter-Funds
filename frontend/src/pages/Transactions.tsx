import { useState, useCallback, useEffect } from 'react';
import { api } from '../utils/api';
import { Transaction, AustralianState } from '../types';
import { formatCurrency, formatDate, getTransactionTypeLabel } from '../utils/format';

const STATES: AustralianState[] = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];

export default function Transactions() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedState, setSelectedState] = useState<AustralianState | 'all'>('all');
  const [filterType, setFilterType] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [search, setSearch] = useState('');

  const fetchTransactions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getTransactions();
      setTransactions(data as Transaction[]);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchTransactions(); }, [fetchTransactions]);

  const handleReverse = async (txn: Transaction) => {
    const reason = window.prompt(`Reverse "${txn.description}"\nEnter reason:`);
    if (!reason) return;
    try {
      await api.reverseTransaction(txn.id, reason);
      await fetchTransactions();
    } catch (e: unknown) {
      alert((e as Error).message);
    }
  };

  const filtered = transactions.filter((t) => {
    if (selectedState !== 'all' && !t.matterNumber.startsWith(selectedState + '-')) return false;
    if (filterType !== 'all' && t.type !== filterType) return false;
    if (filterStatus !== 'all' && t.status !== filterStatus) return false;
    if (
      search !== '' &&
      !t.matterNumber.toLowerCase().includes(search.toLowerCase()) &&
      !t.description.toLowerCase().includes(search.toLowerCase()) &&
      !t.payerPayee.toLowerCase().includes(search.toLowerCase())
    )
      return false;
    return true;
  });

  const totalDeposits = filtered
    .filter((t) => t.type === 'deposit' || t.type === 'interest')
    .reduce((s, t) => s + t.amount, 0);

  const totalWithdrawals = filtered
    .filter((t) => t.type === 'withdrawal' || t.type === 'bank_fee')
    .reduce((s, t) => s + t.amount, 0);

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Transactions</div>
          <div className="page-subtitle">All trust account transactions</div>
        </div>
      </div>

      {error && <div className="alert alert-error">⚠️ {error}</div>}

      <div className="stats-grid" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-label">Total Transactions</div>
          <div className="stat-value blue">{filtered.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Deposits</div>
          <div className="stat-value green">{formatCurrency(totalDeposits)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Withdrawals</div>
          <div className="stat-value amber">{formatCurrency(totalWithdrawals)}</div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <div className="search-box">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            className="form-input"
            placeholder="Search transactions..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          className="form-select"
          style={{ width: 'auto' }}
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
        >
          <option value="all">All Types</option>
          <option value="deposit">Deposit</option>
          <option value="withdrawal">Withdrawal</option>
          <option value="transfer">Transfer</option>
          <option value="bank_fee">Bank Fee</option>
          <option value="interest">Interest</option>
        </select>
        <select
          className="form-select"
          style={{ width: 'auto' }}
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
        >
          <option value="all">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="cleared">Cleared</option>
          <option value="reconciled">Reconciled</option>
          <option value="reversed">Reversed</option>
        </select>
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
        <div className="loading"><div className="spinner" />Loading transactions...</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">💸</div>
          <div className="empty-state-text">No transactions found</div>
        </div>
      ) : (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Matter</th>
                <th>Type</th>
                <th>Description</th>
                <th>Reference</th>
                <th>Payer/Payee</th>
                <th style={{ textAlign: 'right' }}>Amount</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.id} style={{ opacity: t.status === 'reversed' ? 0.5 : 1 }}>
                  <td style={{ whiteSpace: 'nowrap' }}>{formatDate(t.date)}</td>
                  <td>
                    <span className="state-tag">{t.matterNumber}</span>
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        t.type === 'deposit' || t.type === 'interest'
                          ? 'badge-green'
                          : 'badge-red'
                      }`}
                    >
                      {getTransactionTypeLabel(t.type)}
                    </span>
                  </td>
                  <td style={{ color: 'var(--gray-700)' }}>{t.description}</td>
                  <td style={{ color: 'var(--gray-500)', fontSize: 12 }}>{t.reference}</td>
                  <td style={{ color: 'var(--gray-600)' }}>{t.payerPayee}</td>
                  <td
                    style={{ textAlign: 'right' }}
                    className={
                      t.status === 'reversed'
                        ? 'amount-zero'
                        : t.type === 'deposit' || t.type === 'interest'
                        ? 'amount-positive'
                        : 'amount-negative'
                    }
                  >
                    {t.type === 'deposit' || t.type === 'interest' ? '+' : '-'}
                    {formatCurrency(t.amount)}
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        t.status === 'cleared' || t.status === 'reconciled'
                          ? 'badge-green'
                          : t.status === 'pending'
                          ? 'badge-amber'
                          : 'badge-red'
                      }`}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td>
                    {t.status !== 'reversed' && (
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleReverse(t)}
                      >
                        Reverse
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
