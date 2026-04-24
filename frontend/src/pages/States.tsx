import { useState, useEffect } from 'react';
import { api } from '../utils/api';
import { StateInfo } from '../types';

export default function States() {
  const [states, setStates] = useState<Record<string, StateInfo>>({});
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<StateInfo | null>(null);

  useEffect(() => {
    api
      .getStates()
      .then((data) => setStates(data as Record<string, StateInfo>))
      .finally(() => setLoading(false));
  }, []);

  const stateList = Object.values(states);

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">States &amp; Compliance</div>
          <div className="page-subtitle">
            Trust accounting regulations for all Australian states and territories
          </div>
        </div>
      </div>

      <div className="alert alert-info" style={{ marginBottom: 20 }}>
        <span>🇦🇺</span>
        <div>
          MatterFunds supports trust accounting compliance for all <strong>8 Australian states and territories</strong>.
          Each jurisdiction has its own legislation, regulatory body, and trust accounting requirements.
        </div>
      </div>

      {loading ? (
        <div className="loading"><div className="spinner" />Loading states...</div>
      ) : (
        <div className="compliance-grid">
          {stateList.map((s) => (
            <div
              key={s.code}
              className="state-card"
              onClick={() => setSelected(selected?.code === s.code ? null : s)}
            >
              <div className="state-card-code">{s.code}</div>
              <div className="state-card-name">{s.fullName}</div>
              <div className="state-card-info">
                <strong>Regulator:</strong> {s.regulatoryBody}
              </div>
              <div className="state-card-info">
                <strong>Act:</strong> {s.legislativeAct}
              </div>
              <div className="state-card-info">
                <strong>Reconciliation:</strong>{' '}
                {s.reconciliationFrequency.charAt(0).toUpperCase() + s.reconciliationFrequency.slice(1)}
              </div>
              <div className="state-card-info">
                <strong>Annual Audit:</strong> {s.annualAuditRequired ? '✅ Required' : '❌ Not required'}
              </div>
              <div className="state-card-info">
                <strong>Retention:</strong> {s.minimumRetentionYears} years minimum
              </div>

              {selected?.code === s.code && (
                <div
                  style={{ marginTop: 12, borderTop: '1px solid var(--gray-200)', paddingTop: 12 }}
                >
                  <div style={{ fontSize: 12, color: 'var(--gray-600)', marginBottom: 6 }}>
                    <strong>Trust Account Rules:</strong>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--gray-600)', marginBottom: 6 }}>
                    {s.trustAccountRules}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--gray-600)' }}>
                    <strong>Interest:</strong> {s.interestRate}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-title" style={{ marginBottom: 16 }}>
          General Trust Accounting Requirements (All States)
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {[
            {
              icon: '🏦',
              title: 'Separate Account',
              desc: "Client funds must be kept in a separate trust account, not mixed with the firm's general funds.",
            },
            {
              icon: '📋',
              title: 'Trust Ledger',
              desc: 'A separate trust ledger must be maintained for each matter, recording all receipts and payments.',
            },
            {
              icon: '🔄',
              title: 'Monthly Reconciliation',
              desc: "The trust account bank balance must be reconciled with the trust ledger each month.",
            },
            {
              icon: '📊',
              title: 'Annual Audit',
              desc: 'An independent external audit of trust records is required each year in most jurisdictions.',
            },
            {
              icon: '📅',
              title: 'Record Retention',
              desc: 'Trust account records must be retained for a minimum of 7 years after the matter closes.',
            },
            {
              icon: '🚫',
              title: 'No Unauthorised Withdrawals',
              desc: "Withdrawals from trust can only be made when entitled and with proper authorisation.",
            },
            {
              icon: '💰',
              title: 'Interest',
              desc: "Interest on trust accounts is generally paid to the state law society's public purposes fund.",
            },
            {
              icon: '📝',
              title: 'Trust Receipts',
              desc: 'A trust receipt must be issued for every amount received and recorded in the trust ledger.',
            },
          ].map(({ icon, title, desc }) => (
            <div
              key={title}
              style={{
                padding: '14px',
                borderRadius: 8,
                border: '1px solid var(--gray-200)',
                background: 'var(--gray-50)',
              }}
            >
              <div style={{ fontSize: 20, marginBottom: 6 }}>{icon}</div>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{title}</div>
              <div style={{ fontSize: 13, color: 'var(--gray-500)', lineHeight: 1.5 }}>{desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
