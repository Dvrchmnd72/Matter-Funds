import { useState, useEffect } from 'react';
import { api } from '../utils/api';
import { DashboardData, AustralianState } from '../types';
import { formatCurrency } from '../utils/format';

const STATE_COLORS: Record<AustralianState, string> = {
  NSW: '#1d4ed8',
  VIC: '#0f766e',
  QLD: '#7c3aed',
  SA: '#dc2626',
  WA: '#d97706',
  TAS: '#059669',
  ACT: '#0369a1',
  NT: '#b45309',
};

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .getDashboard()
      .then((d) => setData(d as DashboardData))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner" />
        Loading dashboard...
      </div>
    );
  }

  if (error) {
    return (
      <div className="alert alert-error">
        <span>⚠️</span> {error}
      </div>
    );
  }

  if (!data) return null;

  const states: AustralianState[] = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];

  return (
    <div>
      <div className="alert alert-info" style={{ marginBottom: 20 }}>
        <span>🇦🇺</span>
        <div>
          <strong>Australian Legal Trust Account Platform</strong> — Compliant with trust accounting
          requirements for all 8 Australian states and territories (NSW, VIC, QLD, SA, WA, TAS, ACT, NT).
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Total Trust Funds</div>
          <div className="stat-value green">{formatCurrency(data.totalTrustFunds)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Matters</div>
          <div className="stat-value blue">{data.totalMatters}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Active Matters</div>
          <div className="stat-value">{data.activeMatters}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Trust Accounts</div>
          <div className="stat-value">{data.totalTrustAccounts}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Pending Transactions</div>
          <div className="stat-value amber">{data.pendingTransactions}</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Trust Funds by State</div>
        </div>
        <div className="compliance-grid">
          {states.map((state) => {
            const stateData = data.byState[state];
            return (
              <div
                key={state}
                style={{
                  padding: '14px 16px',
                  borderRadius: 10,
                  border: '1px solid var(--gray-200)',
                  background: 'var(--gray-50)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                  <span
                    style={{
                      background: STATE_COLORS[state],
                      color: 'white',
                      borderRadius: 6,
                      padding: '2px 8px',
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  >
                    {state}
                  </span>
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--gray-900)' }}>
                  {formatCurrency(stateData.trustBalance)}
                </div>
                <div style={{ fontSize: 12, color: 'var(--gray-500)', marginTop: 4 }}>
                  {stateData.matters} matter{stateData.matters !== 1 ? 's' : ''}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {data.recentTransactions.length > 0 && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">Recent Transactions</div>
          </div>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Matter</th>
                  <th>Type</th>
                  <th>Description</th>
                  <th style={{ textAlign: 'right' }}>Amount</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.recentTransactions.map((t) => (
                  <tr key={t.id}>
                    <td style={{ whiteSpace: 'nowrap' }}>{t.date}</td>
                    <td>
                      <span className="state-tag" style={{ marginRight: 6 }}>
                        {t.matterNumber}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`badge ${t.type === 'deposit' || t.type === 'interest' ? 'badge-green' : 'badge-red'}`}
                      >
                        {t.type}
                      </span>
                    </td>
                    <td style={{ color: 'var(--gray-600)' }}>{t.description}</td>
                    <td
                      style={{ textAlign: 'right' }}
                      className={
                        t.type === 'deposit' || t.type === 'interest'
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
