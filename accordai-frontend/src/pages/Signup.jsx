import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Zap } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import './Auth.css'

export default function Signup() {
  const { signup } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({
    business_name: '', full_name: '', email: '', password: '',
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setBusy(true)
    try {
      await signup({ ...form, full_name: form.full_name || null })
      navigate('/dashboard')
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Signup failed. Please check your details.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-logo">
          <div className="logo-icon"><Zap size={18} /></div>
          <span className="logo-name">AccordAI</span>
        </div>
        <h1 className="auth-title">Create your account</h1>
        <p className="auth-subtitle">One account per business — you'll be the admin</p>

        <form className="auth-form" onSubmit={onSubmit}>
          {error && <div className="auth-error">{error}</div>}
          <div className="auth-field">
            <label htmlFor="business_name">Business name</label>
            <input
              id="business_name" type="text" required minLength={2}
              value={form.business_name} onChange={set('business_name')}
              placeholder="Sunshine Car Rentals"
            />
          </div>
          <div className="auth-field">
            <label htmlFor="full_name">Your name (optional)</label>
            <input
              id="full_name" type="text"
              value={form.full_name} onChange={set('full_name')}
              placeholder="Alex Smith"
            />
          </div>
          <div className="auth-field">
            <label htmlFor="email">Email</label>
            <input
              id="email" type="email" required autoComplete="email"
              value={form.email} onChange={set('email')}
              placeholder="you@business.com"
            />
          </div>
          <div className="auth-field">
            <label htmlFor="password">Password</label>
            <input
              id="password" type="password" required minLength={8} maxLength={72}
              autoComplete="new-password"
              value={form.password} onChange={set('password')}
              placeholder="At least 8 characters"
            />
          </div>
          <button className="auth-submit" type="submit" disabled={busy}>
            {busy ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
        <div style={{ textAlign: 'center' }}>
          <Link className="auth-back" to="/">← Back to home</Link>
        </div>
      </div>
    </div>
  )
}