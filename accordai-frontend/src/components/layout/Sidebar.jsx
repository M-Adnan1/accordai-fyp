import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, PhoneCall, BookOpen,
  Activity, Zap
} from 'lucide-react'
import './Sidebar.css'

const NAV = [
  { to: '/',          icon: LayoutDashboard, label: 'Dashboard'      },
  { to: '/calls',     icon: PhoneCall,       label: 'Call History'   },
  { to: '/knowledge', icon: BookOpen,        label: 'Knowledge Base' },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-icon">
          <Zap size={18} />
        </div>
        <div className="logo-text">
          <span className="logo-name">AccordAI</span>
          <span className="logo-sub">Voice Intelligence</span>
        </div>
      </div>

      <div className="sidebar-section-label">Navigation</div>

      <nav className="sidebar-nav">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? 'active' : ''}`
            }
          >
            <Icon size={16} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="status-dot" />
        <span>System Online</span>
      </div>
    </aside>
  )
}
