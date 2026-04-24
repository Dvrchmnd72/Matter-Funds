import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../utils/api';
import { Matter, AustralianState, MatterType } from '../types';
import { formatCurrency, formatDate, getMatterTypeLabel } from '../utils/format';

const STATES: AustralianState[] = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];
const MATTER_TYPES: MatterType[] = [
  'conveyancing', 'family_law', 'commercial', 'litigation',
  'estate', 'criminal', 'immigration', 'employment', 'other',
];

interface MatterFormData {
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

const emptyForm: MatterFormData = {
  matterNumber: '',
  description: '',
  clientName: '',
  clientEmail: '',
  clientPhone: '',
  matterType: 'conveyancing',
  state: 'NSW',
  responsibleSolicitor: '',
  openedDate: new Date().toISOString().split('T')[0],
};

export default function Matters() {
  const navigate = useNavigate();
  const [matters, setMatters] = useState<Matter[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedState, setSelectedState] = useState<AustralianState | 'all'>('all');
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState<MatterFormData>(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [search, setSearch] = useState('');

  const fetchMatters = async () => {
    try {
      const state = selectedState === 'all' ? undefined : selectedState;
      const data = await api.getMatters(state);
      setMatters(data as Matter[]);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMatters();
  }, [selectedState]);

  const filteredMatters = matters.filter((m) =>
    search === '' ||
    m.matterNumber.toLowerCase().includes(search.toLowerCase()) ||
    m.clientName.toLowerCase().includes(search.toLowerCase()) ||
    m.description.toLowerCase().includes(search.toLowerCase())
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    setSubmitting(true);
    try {
      await api.createMatter(form);
      setShowModal(false);
      setForm(emptyForm);
      await fetchMatters();
    } catch (e: unknown) {
      setFormError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = (id: string) => {
    api.updateMatter(id, { status: 'closed', closedDate: new Date().toISOString().split('T')[0] })
      .then(() => fetchMatters())
      .catch(() => {});
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Matters</div>
          <div className="page-subtitle">Manage legal matters and trust ledgers</div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          + New Matter
        </button>
      </div>

      {error && (
        <div className="alert alert-error">
          <span>⚠️</span> {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <div className="search-box">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            className="form-input"
            placeholder="Search matters..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="state-selector" style={{ margin: 0 }}>
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
      </div>

      {loading ? (
        <div className="loading"><div className="spinner" />Loading matters...</div>
      ) : filteredMatters.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📁</div>
          <div className="empty-state-text">No matters found</div>
          <div className="empty-state-sub">Create a new matter to get started</div>
        </div>
      ) : (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Matter No.</th>
                <th>Client</th>
                <th>Description</th>
                <th>Type</th>
                <th>State</th>
                <th>Solicitor</th>
                <th>Opened</th>
                <th style={{ textAlign: 'right' }}>Trust Balance</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredMatters.map((m) => (
                <tr key={m.id}>
                  <td>
                    <strong
                      style={{ cursor: 'pointer', color: 'var(--primary-light)' }}
                      onClick={() => navigate(`/matters/${m.id}`)}
                    >
                      {m.matterNumber}
                    </strong>
                  </td>
                  <td>{m.clientName}</td>
                  <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {m.description}
                  </td>
                  <td>
                    <span className="badge badge-blue">{getMatterTypeLabel(m.matterType)}</span>
                  </td>
                  <td>
                    <span className="state-tag">{m.state}</span>
                  </td>
                  <td style={{ color: 'var(--gray-600)' }}>{m.responsibleSolicitor}</td>
                  <td style={{ whiteSpace: 'nowrap', color: 'var(--gray-500)' }}>
                    {formatDate(m.openedDate)}
                  </td>
                  <td
                    style={{ textAlign: 'right' }}
                    className={m.trustBalance > 0 ? 'amount-positive' : m.trustBalance < 0 ? 'amount-negative' : 'amount-zero'}
                  >
                    {formatCurrency(m.trustBalance)}
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        m.status === 'active' ? 'badge-green' : m.status === 'closed' ? 'badge-gray' : 'badge-amber'
                      }`}
                    >
                      {m.status}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => navigate(`/matters/${m.id}`)}
                      >
                        Ledger
                      </button>
                      {m.status === 'active' && (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleClose(m.id)}
                        >
                          Close
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">New Matter</div>
              <button className="modal-close" onClick={() => setShowModal(false)}>×</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="modal-body">
                {formError && (
                  <div className="alert alert-error" style={{ marginBottom: 16 }}>
                    <span>⚠️</span> {formError}
                  </div>
                )}
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">
                      Matter Number <span className="required">*</span>
                    </label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="e.g. NSW-2024-001"
                      value={form.matterNumber}
                      onChange={(e) => setForm({ ...form, matterNumber: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">
                      State <span className="required">*</span>
                    </label>
                    <select
                      className="form-select"
                      value={form.state}
                      onChange={(e) => setForm({ ...form, state: e.target.value as AustralianState })}
                      required
                    >
                      {STATES.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">
                    Description <span className="required">*</span>
                  </label>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="Brief description of matter"
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    required
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">
                      Client Name <span className="required">*</span>
                    </label>
                    <input
                      type="text"
                      className="form-input"
                      value={form.clientName}
                      onChange={(e) => setForm({ ...form, clientName: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Client Email</label>
                    <input
                      type="email"
                      className="form-input"
                      value={form.clientEmail}
                      onChange={(e) => setForm({ ...form, clientEmail: e.target.value })}
                    />
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Client Phone</label>
                    <input
                      type="text"
                      className="form-input"
                      value={form.clientPhone}
                      onChange={(e) => setForm({ ...form, clientPhone: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Matter Type</label>
                    <select
                      className="form-select"
                      value={form.matterType}
                      onChange={(e) => setForm({ ...form, matterType: e.target.value as MatterType })}
                    >
                      {MATTER_TYPES.map((t) => (
                        <option key={t} value={t}>{getMatterTypeLabel(t)}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">
                      Responsible Solicitor <span className="required">*</span>
                    </label>
                    <input
                      type="text"
                      className="form-input"
                      value={form.responsibleSolicitor}
                      onChange={(e) => setForm({ ...form, responsibleSolicitor: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Opened Date</label>
                    <input
                      type="date"
                      className="form-input"
                      value={form.openedDate}
                      onChange={(e) => setForm({ ...form, openedDate: e.target.value })}
                    />
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? 'Creating...' : 'Create Matter'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
