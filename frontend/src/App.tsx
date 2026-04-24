import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Matters from './pages/Matters';
import MatterDetail from './pages/MatterDetail';
import TrustAccounts from './pages/TrustAccounts';
import Transactions from './pages/Transactions';
import Reconciliations from './pages/Reconciliations';
import States from './pages/States';

const PAGE_TITLES: Record<string, { title: string; subtitle: string }> = {
  '/': { title: 'Dashboard', subtitle: 'Overview of trust accounts across all states' },
  '/matters': { title: 'Matters', subtitle: 'Legal matters and trust ledgers' },
  '/trust-accounts': { title: 'Trust Accounts', subtitle: 'Trust bank accounts by state' },
  '/transactions': { title: 'Transactions', subtitle: 'Trust account transactions' },
  '/reconciliations': { title: 'Reconciliations', subtitle: 'Monthly bank reconciliations' },
  '/states': { title: 'States & Compliance', subtitle: 'Australian state trust regulations' },
};

function Header() {
  const location = useLocation();
  const pathKey = Object.keys(PAGE_TITLES)
    .sort((a, b) => b.length - a.length)
    .find((k) => location.pathname === k || (k !== '/' && location.pathname.startsWith(k)));
  const info = pathKey ? PAGE_TITLES[pathKey] : { title: 'MatterFunds', subtitle: '' };

  return (
    <header className="header">
      <div>
        <div className="header-title">{info.title}</div>
        {info.subtitle && <div className="header-subtitle">{info.subtitle}</div>}
      </div>
      <div className="header-actions">
        <span
          style={{
            fontSize: 13,
            color: 'var(--gray-500)',
            background: 'var(--gray-100)',
            padding: '4px 10px',
            borderRadius: 6,
          }}
        >
          🇦🇺 All States
        </span>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <Sidebar />
        <div className="main">
          <Header />
          <main className="content">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/matters" element={<Matters />} />
              <Route path="/matters/:id" element={<MatterDetail />} />
              <Route path="/trust-accounts" element={<TrustAccounts />} />
              <Route path="/transactions" element={<Transactions />} />
              <Route path="/reconciliations" element={<Reconciliations />} />
              <Route path="/states" element={<States />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
