import { useEffect, useState } from 'react'
import {
  User, Phone, Webhook, ShieldCheck, Copy, Check,
  Save, AlertTriangle, KeyRound,
} from 'lucide-react'
import { fetchTenant, updateTwilioNumber, changePassword } from '../services/api'
import { useAuth } from '../context/AuthContext'
import './Settings.css'

function Row({ label, children }) {
  return (
    <div className="settings-row">
      <span className="settings-row__label">{label}</span>
      <span className="settings-row__value">{children}</span>
    </div>
  )
}

export default function Settings() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'  // server enforces too; this is just UI

  const [tenant, setTenant] = useState(null)
  const [loading, setLoading] = useState(true)

  // Twilio number form
  const [numberInput, setNumberInput] = useState('')
  const [numberBusy, setNumberBusy] = useState(false)
  const [numberError, setNumberError] = useState('')
  const [numberSaved, setNumberSaved] = useState(false)

  // Webhook copy
  const [copied, setCopied] = useState(false)

  // Change password form
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' })
  const [pwBusy, setPwBusy] = useState(false)
  const [pwError, setPwError] = useState('')
  const [pwSuccess, setPwSuccess] = useState('')

  useEffect(() => {
    fetchTenant()
      .then((t) => {
        setTenant(t)
        setNumberInput(t.twilio_number || '')
      })
      .finally(() => setLoading(false))
  }, [])

  const saveNumber = async (e) => {
    e.preventDefault()
    setNumberError('')
    setNumberSaved(false)
    setNumberBusy(true)
    try {
      const t = await updateTwilioNumber(numberInput.trim() || null)
      setTenant(t)
      setNumberInput(t.twilio_number || '')
      setNumberSaved(true)
      setTimeout(() => setNumberSaved(false), 3000)
    } catch (err) {
      setNumberError(err.response?.data?.detail || 'Could not save the number.')
    } finally {
      setNumberBusy(false)
    }
  }

  const copyWebhook = async () => {
    try {
      await navigator.clipboard.writeText(tenant.webhook_url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard unavailable (non-secure context) — user can select manually */
    }
  }

  const submitPassword = async (e) => {
    e.preventDefault()
    setPwError('')
    setPwSuccess('')
    if (pwForm.next.length < 8) {
      setPwError('New password must be at least 8 characters.')
      return
    }
    if (pwForm.next !== pwForm.confirm) {
      setPwError('New passwords do not match.')
      return
    }
    setPwBusy(true)
    try {
      await changePassword(pwForm.current, pwForm.next)
      setPwSuccess('Password updated successfully.')
      setPwForm({ current: '', next: '', confirm: '' })
    } catch (err) {
      const detail = err.response?.data?.detail
      setPwError(typeof detail === 'string' ? detail : 'Could not update password.')
    } finally {
      setPwBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="settings-loading"><div className="spinner" /></div>
      </div>
    )
  }

  return (
    <div className="page settings-page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Your account, phone number, and Twilio configuration</p>
        </div>
      </div>

      {/* ── Account information ── */}
      <div className="card settings-card">
        <div className="settings-card__title"><User size={16} /> Account Information</div>
        <Row label="Full name">{user?.full_name || <span className="settings-muted">Not set</span>}</Row>
        <Row label="Email">{user?.email}</Row>
        <Row label="Business">{user?.client_name}</Row>
        <Row label="Role">
          <span className={`role-badge role-${user?.role}`}>{user?.role}</span>
        </Row>
      </div>

      {/* ── Twilio number ── */}
      <div className="card settings-card">
        <div className="settings-card__title"><Phone size={16} /> Twilio Phone Number</div>

        {tenant?.twilio_number ? (
          <Row label="Current number">
            <span className="mono">{tenant.twilio_number}</span>
          </Row>
        ) : (
          <div className="settings-notice">
            <AlertTriangle size={15} />
            <span>
              No Twilio number configured yet — your AI agent can't receive calls until
              one is set and pointed at the webhook below.
            </span>
          </div>
        )}

        {isAdmin ? (
          <form className="settings-inline-form" onSubmit={saveNumber}>
            <input
              type="tel"
              value={numberInput}
              onChange={(e) => setNumberInput(e.target.value)}
              placeholder="+13526236826"
              aria-label="Twilio phone number"
            />
            <button className="btn btn-primary" type="submit" disabled={numberBusy}>
              {numberSaved ? <Check size={14} /> : <Save size={14} />}
              {numberBusy ? 'Saving…' : numberSaved ? 'Saved' : 'Save number'}
            </button>
          </form>
        ) : (
          <p className="settings-muted">Only the account admin can change the Twilio number.</p>
        )}
        {numberError && <div className="settings-error">{numberError}</div>}
        <p className="settings-hint">
          E.164 format required: <span className="mono">+</span> then country code and digits,
          e.g. <span className="mono">+13526236826</span>. Formatting characters are stripped
          automatically. Leave empty and save to remove the number.
        </p>
      </div>

      {/* ── Webhook ── */}
      <div className="card settings-card">
        <div className="settings-card__title"><Webhook size={16} /> Voice Webhook</div>
        <div className="settings-webhook">
          <span className="mono settings-webhook__url">{tenant?.webhook_url}</span>
          <button className="btn btn-ghost" onClick={copyWebhook}>
            {copied ? <Check size={14} color="var(--success)" /> : <Copy size={14} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <ol className="settings-steps">
          <li>Open the <strong>Twilio Console</strong> → Phone Numbers → Manage → Active Numbers.</li>
          <li>Select the number you entered above.</li>
          <li>Under <strong>Voice Configuration</strong>, set "A call comes in" to
            <strong> Webhook</strong>, paste the URL above, and choose <strong>HTTP POST</strong>.</li>
          <li>Save. Calls to your number will now reach your AI agent — routing to your
            account happens automatically based on the dialed number.</li>
        </ol>
        <p className="settings-hint">
          This URL is the same for every AccordAI account; your saved Twilio number is what
          links incoming calls to your business.
        </p>
      </div>

      {/* ── Security ── */}
      <div className="card settings-card">
        <div className="settings-card__title"><ShieldCheck size={16} /> Security</div>
        <Row label="Sign-in email">{user?.email}</Row>

        <div className="settings-subtitle"><KeyRound size={14} /> Change password</div>
        <form className="settings-pw-form" onSubmit={submitPassword}>
          {pwError && <div className="settings-error">{pwError}</div>}
          {pwSuccess && <div className="settings-success">{pwSuccess}</div>}
          <input
            type="password" placeholder="Current password" autoComplete="current-password"
            value={pwForm.current} required
            onChange={(e) => setPwForm({ ...pwForm, current: e.target.value })}
          />
          <input
            type="password" placeholder="New password (min 8 characters)" autoComplete="new-password"
            value={pwForm.next} required minLength={8} maxLength={72}
            onChange={(e) => setPwForm({ ...pwForm, next: e.target.value })}
          />
          <input
            type="password" placeholder="Confirm new password" autoComplete="new-password"
            value={pwForm.confirm} required
            onChange={(e) => setPwForm({ ...pwForm, confirm: e.target.value })}
          />
          <button className="btn btn-primary" type="submit" disabled={pwBusy}>
            {pwBusy ? 'Updating…' : 'Update password'}
          </button>
        </form>
      </div>
    </div>
  )
}