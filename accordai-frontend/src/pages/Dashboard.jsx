import { useEffect, useState } from 'react'
import {
  PhoneCall, Clock, Users, ThumbsUp,
  CheckCircle, XCircle, MessageSquare, TrendingUp
} from 'lucide-react'
import {
  AreaChart, Area, BarChart , Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts'
import StatCard from '../components/dashboard/StatCard'
import { fetchDashboard } from '../services/api'
import './Dashboard.css'

const COLORS = ['#0ea5e9', '#10b981', '#ef4444', '#f59e0b']

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="chart-tooltip__row">
          <span style={{ color: p.color }}>{p.name}</span>
          <span>{p.value}</span>
        </div>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchDashboard()
      .then(setData)
      .catch(() => setError('Failed to load analytics. Is the backend running?'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="page center">
      <div className="spinner" />
      <p style={{ marginTop: 12, color: 'var(--text-secondary)' }}>Loading analytics...</p>
    </div>
  )

  if (error) return (
    <div className="page center">
      <XCircle size={32} color="var(--danger)" />
      <p style={{ marginTop: 12, color: 'var(--text-secondary)' }}>{error}</p>
    </div>
  )

  const callsPerDay = [...(data.calls_per_day || [])].reverse()

  const statusData = [
    { name: 'Completed', value: data.completed_calls },
    { name: 'Resolved',  value: data.resolved_calls },
    { name: 'Failed',    value: data.failed_calls },
    { name: 'Other',     value: Math.max(0, data.total_calls - data.completed_calls - data.failed_calls) },
  ].filter(d => d.value > 0)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Real-time overview of your AI voice agent performance</p>
        </div>
        <div className="live-badge">
          <span className="live-dot" />
          Live
        </div>
      </div>

      {/* Stat grid */}
      <div className="stats-grid">
        <StatCard
          icon={PhoneCall}
          label="Total Calls"
          value={data.total_calls.toLocaleString()}
          sub={`${data.completed_calls} completed`}
          color="blue"
        />
        <StatCard
          icon={Users}
          label="Unique Customers"
          value={data.total_customers.toLocaleString()}
          sub="Distinct callers"
          color="green"
        />
        <StatCard
          icon={Clock}
          label="Avg Duration"
          value={`${Math.floor(data.avg_duration_seconds / 60)}m ${Math.round(data.avg_duration_seconds % 60)}s`}
          sub="Per completed call"
          color="yellow"
        />
        <StatCard
          icon={ThumbsUp}
          label="Satisfaction"
          value={`${data.satisfaction_rate ?? 0}%`}
          sub={`${data.total_rated_calls} rated calls`}
          color="green"
        />
        <StatCard
          icon={CheckCircle}
          label="Resolution Rate"
          value={`${data.resolution_rate}%`}
          sub={`${data.resolved_calls} resolved`}
          color="blue"
        />
        <StatCard
          icon={MessageSquare}
          label="Avg Messages"
          value={data.avg_messages_per_call}
          sub="Exchanges per call"
          color="yellow"
        />
      </div>

      {/* Charts row */}
      <div className="charts-grid">
        {/* Calls per day area chart */}
        <div className="card chart-card">
          <div className="chart-header">
            <div>
              <h3 className="chart-title">Call Volume</h3>
              <p className="chart-sub">Last 7 days</p>
            </div>
            <TrendingUp size={16} color="var(--accent)" />
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={callsPerDay} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="callGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#0ea5e9" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(59,130,246,0.08)" />
              <XAxis dataKey="date" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="calls" name="Calls" stroke="#0ea5e9" strokeWidth={2} fill="url(#callGrad)" dot={{ fill: '#0ea5e9', r: 3 }} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Status breakdown pie */}
        <div className="card chart-card chart-card--sm">
          <div className="chart-header">
            <div>
              <h3 className="chart-title">Call Outcomes</h3>
              <p className="chart-sub">Status breakdown</p>
            </div>
          </div>
          {statusData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie
                    data={statusData}
                    cx="50%" cy="50%"
                    innerRadius={50} outerRadius={80}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {statusData.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="pie-legend">
                {statusData.map((d, i) => (
                  <div key={i} className="pie-legend__item">
                    <span className="pie-legend__dot" style={{ background: COLORS[i % COLORS.length] }} />
                    <span className="pie-legend__label">{d.name}</span>
                    <span className="pie-legend__value">{d.value}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-chart">No data yet</div>
          )}
        </div>
      </div>
    </div>
  )
}
