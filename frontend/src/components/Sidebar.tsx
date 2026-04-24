import { NavLink, useLocation } from 'react-router-dom';

const navItems = [
  { path: '/', icon: '📊', label: 'Dashboard' },
  { path: '/matters', icon: '📁', label: 'Matters' },
  { path: '/trust-accounts', icon: '🏦', label: 'Trust Accounts' },
  { path: '/transactions', icon: '💸', label: 'Transactions' },
  { path: '/reconciliations', icon: '✅', label: 'Reconciliations' },
  { path: '/states', icon: '🗺️', label: 'States & Compliance' },
];

export default function Sidebar() {
  const location = useLocation();

  return (
    <nav className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">M</div>
          <div>
            <div className="sidebar-logo-text">MatterFunds</div>
            <div className="sidebar-logo-sub">Legal Trust Platform</div>
          </div>
        </div>
      </div>

      <div className="sidebar-nav">
        <div className="sidebar-section">
          <div className="sidebar-section-title">Navigation</div>
          {navItems.map(({ path, icon, label }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                `sidebar-link${isActive || (path !== '/' && location.pathname.startsWith(path)) ? ' active' : ''}`
              }
              end={path === '/'}
            >
              <span className="sidebar-link-icon">{icon}</span>
              {label}
            </NavLink>
          ))}
        </div>
      </div>

      <div className="sidebar-footer">
        <div>🇦🇺 Australian Trust Account Platform</div>
        <div style={{ marginTop: 4 }}>All 8 States &amp; Territories</div>
      </div>
    </nav>
  );
}
