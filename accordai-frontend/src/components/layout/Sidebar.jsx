import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, PhoneCall, BookOpen,
  Wrench, Zap, LogOut, Settings,
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import './Sidebar.css'

const NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard'      },
  { to: '/calls',     icon: PhoneCall,       label: 'Call History'   },
  { to: '/knowledge', icon: BookOpen,        label: 'Knowledge Base' },
  { to: '/tools',     icon: Wrench,          label: 'Tools'          },
  { to: '/settings',  icon: Settings,        label: 'Settings'       },
]

export default function Sidebar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const onLogout = () => {
    logout()
    navigate('/')
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-icon">
          <Zap size={18} />
        </div>
        <div className="logo-text">
          <span className="logo-name">AccordAI</span>
          <span className="logo-sub">{user?.client_name || 'Voice Intelligence'}</span>
        </div>
      </div>

      <div className="sidebar-section-label">Navigation</div>

      <nav className="sidebar-nav">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? 'active' : ''}`
            }
          >
            <Icon size={16} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-user">
        <div className="sidebar-user-info">
          <span className="sidebar-user-email" title={user?.email}>{user?.email}</span>
          <span className={`role-badge role-${user?.role}`}>{user?.role}</span>
        </div>
        <button className="sidebar-logout" onClick={onLogout} title="Sign out">
          <LogOut size={15} />
          <span>Sign out</span>
        </button>
      </div>

      <div className="sidebar-footer">
        <div className="status-dot" />
        <span>System Online</span>
      </div>
    </aside>
  )
}