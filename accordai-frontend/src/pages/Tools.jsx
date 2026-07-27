import { useEffect, useState } from 'react'
import {
  Wrench, Plus, Sparkles, Trash2, X, Save, Pencil,
  ShieldCheck, ShieldAlert, Link2, RefreshCw, AlertCircle
} from 'lucide-react'
import { generateToolSchema, createTool, updateTool, deleteTool, fetchTools } from '../services/api'
import { useAuth } from '../context/AuthContext'
import './Tools.css'

const PARAM_TYPES = ['string', 'integer', 'number', 'boolean']
const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const AUTH_TYPES = [
  { value: 'none', label: 'None' },
  { value: 'bearer', label: 'Bearer token' },
  { value: 'api_key_header', label: 'API key header' },
]

// FastAPI errors come in two shapes: a plain string `detail` (our custom 422/409
// HTTPExceptions — SSRF, duplicate name, bad schema) or Pydantic's structured
// array of {loc, msg}. Surface the real message either way, never fail silently.
function extractError(err) {
  const detail = err?.response?.data?.detail
  if (!detail) return err?.message || 'Request failed. Is the backend running?'
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map(d => {
        const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : ''
        return field ? `${field}: ${d.msg}` : d.msg
      })
      .join('; ')
  }
  return JSON.stringify(detail)
}

// generate-schema returns a JSON Schema object; flatten it into editable rows.
function schemaToRows(parameters) {
  const props = parameters?.properties || {}
  const required = parameters?.required || []
  return Object.entries(props).map(([name, def]) => ({
    name,
    type: PARAM_TYPES.includes(def?.type) ? def.type : 'string',
    description: def?.description || '',
    required: required.includes(name),
  }))
}

// ...and rebuild a JSON Schema from the (possibly edited) rows for /tools/create.
function rowsToSchema(rows) {
  const properties = {}
  const required = []
  for (const p of rows) {
    const name = p.name.trim()
    if (!name) continue
    properties[name] = { type: p.type, description: p.description }
    if (p.required) required.push(name)
  }
  return { type: 'object', properties, required }
}

const emptyParam = () => ({ name: '', type: 'string', description: '', required: false })

export default function Tools() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'  // server enforces too; this is just UI
  const [tools, setTools] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingTool, setEditingTool] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  // Step 1 — plain-English description → generate-schema
  const [description, setDescription] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState(null)
  const [schemaReady, setSchemaReady] = useState(false)

  // Step 2 — editable generated schema
  const [toolName, setToolName] = useState('')
  const [toolDescription, setToolDescription] = useState('')
  const [params, setParams] = useState([])

  // Step 3 — endpoint + auth
  const [endpointUrl, setEndpointUrl] = useState('')
  const [httpMethod, setHttpMethod] = useState('POST')
  const [authType, setAuthType] = useState('none')
  const [authCredential, setAuthCredential] = useState('')
  const [authHeaderName, setAuthHeaderName] = useState('')
  const [requiresConfirmation, setRequiresConfirmation] = useState(true)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  const loadTools = () => {
    setLoading(true)
    fetchTools()
      .then(data => setTools(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadTools() }, [])

  const resetForm = () => {
    setEditingTool(null)
    setDescription('')
    setGenError(null)
    setSchemaReady(false)
    setToolName('')
    setToolDescription('')
    setParams([])
    setEndpointUrl('')
    setHttpMethod('POST')
    setAuthType('none')
    setAuthCredential('')
    setAuthHeaderName('')
    setRequiresConfirmation(true)
    setSaveError(null)
  }

  const closeForm = () => {
    setShowForm(false)
    resetForm()
  }

  // Populate the form (steps 2 & 3 only — the schema already exists) from an
  // existing tool and open it in edit mode. auth_credential is never returned
  // by the API, so that field starts blank; leaving it blank on save keeps
  // the stored secret untouched (matches the PATCH /update partial-update contract).
  const startEdit = (tool) => {
    setSaveError(null)
    setEditingTool(tool)
    setDescription('')
    setGenError(null)
    setSchemaReady(true)
    setToolName(tool.name)
    setToolDescription(tool.description)
    setParams(schemaToRows(tool.parameters_schema))
    setEndpointUrl(tool.endpoint_url)
    setHttpMethod(tool.http_method)
    setAuthType(tool.auth_type)
    setAuthCredential('')
    setAuthHeaderName(tool.auth_header_name || '')
    setRequiresConfirmation(tool.requires_confirmation)
    setShowForm(true)
  }

  const handleDelete = async (tool) => {
    if (!confirm(`Deactivate "${tool.name}"? The agent will stop offering it on calls.`)) return
    setDeletingId(tool.id)
    try {
      await deleteTool(tool.id)
      loadTools()
    } catch (err) {
      alert(extractError(err))
    } finally {
      setDeletingId(null)
    }
  }

  const handleGenerate = async () => {
    setGenError(null)
    setSaveError(null)
    setGenerating(true)
    try {
      const schema = await generateToolSchema(description.trim())
      setToolName(schema.name || '')
      setToolDescription(schema.description || '')
      setParams(schemaToRows(schema.parameters))
      setSchemaReady(true)
    } catch (err) {
      setGenError(extractError(err))
    } finally {
      setGenerating(false)
    }
  }

  const updateParam = (i, patch) =>
    setParams(prev => prev.map((p, idx) => (idx === i ? { ...p, ...patch } : p)))
  const removeParam = (i) => setParams(prev => prev.filter((_, idx) => idx !== i))
  const addParam = () => setParams(prev => [...prev, emptyParam()])

  const handleSave = async () => {
    setSaveError(null)
    setSaving(true)
    try {
      if (editingTool) {
        // Partial update: only send auth_credential if the owner typed a new
        // one, otherwise the backend leaves the stored secret untouched.
        const payload = {
          name: toolName.trim(),
          description: toolDescription.trim(),
          parameters: rowsToSchema(params),
          endpoint_url: endpointUrl.trim(),
          http_method: httpMethod,
          auth_type: authType,
          auth_header_name:
            authType === 'api_key_header' ? authHeaderName.trim() || null : null,
          requires_confirmation: requiresConfirmation,
        }
        if (authType !== 'none' && authCredential.trim()) {
          payload.auth_credential = authCredential.trim()
        }
        await updateTool(editingTool.id, payload)
      } else {
        const payload = {
          name: toolName.trim(),
          description: toolDescription.trim(),
          parameters: rowsToSchema(params),
          endpoint_url: endpointUrl.trim(),
          http_method: httpMethod,
          auth_type: authType,
          auth_credential: authType === 'none' ? null : authCredential.trim() || null,
          auth_header_name:
            authType === 'api_key_header' ? authHeaderName.trim() || null : null,
          requires_confirmation: requiresConfirmation,
        }
        await createTool(payload)
      }
      closeForm()
      loadTools()
    } catch (err) {
      setSaveError(extractError(err))
    } finally {
      setSaving(false)
    }
  }

  const descTooShort = description.trim().length < 10
  // On edit, a blank credential means "keep the existing one" — the backend
  // rejects the save if that's not actually valid (e.g. switching auth_type
  // with no prior credential), so only block client-side for create.
  const saveDisabled =
    saving ||
    !toolName.trim() ||
    !toolDescription.trim() ||
    !endpointUrl.trim() ||
    (!editingTool && authType !== 'none' && !authCredential.trim())

  return (
    <div className="page">
      <div className="page-header tools-header">
        <div>
          <h1 className="page-title">Tools</h1>
          <p className="page-subtitle">
            Give your AI agent actions it can perform mid-call — bookings, lookups, and more
          </p>
        </div>
        {!showForm && isAdmin && (
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            <Plus size={15} /> Create Tool
          </button>
        )}
      </div>

      {/* ── Create/Edit panel ────────────────────────── */}
      {showForm && (
        <div className="card tool-form">
          <div className="tool-form__top">
            <div className="tool-form__title">
              <Wrench size={16} color="var(--accent)" /> {editingTool ? `Edit "${editingTool.name}"` : 'New Tool'}
            </div>
            <button className="icon-btn" onClick={closeForm} aria-label="Close">
              <X size={16} />
            </button>
          </div>

          {/* Step 1 — describe (create only; editing already has a schema) */}
          {!editingTool && (
          <div className="tool-section">
            <div className="tool-section-label">1 · Describe the tool</div>
            <textarea
              className="tool-textarea"
              placeholder="e.g. Book a table. Caller must give party size, time, and their name; drop-off optional."
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
            <div className="tool-row-between">
              <span className="tool-hint">
                Plain English, at least 10 characters. The AI drafts a schema you can edit.
              </span>
              <button
                className="btn btn-ghost"
                onClick={handleGenerate}
                disabled={descTooShort || generating}
              >
                {generating
                  ? <><div className="spinner" style={{ width: 14, height: 14 }} /> Generating…</>
                  : <><Sparkles size={14} /> Generate</>}
              </button>
            </div>
            {genError && (
              <div className="form-error">
                <AlertCircle size={14} /> {genError}
              </div>
            )}
          </div>
          )}

          {/* Steps 2 & 3 appear once a schema exists */}
          {schemaReady && (
            <>
              {/* Step 2 — edit schema */}
              <div className="tool-section">
                <div className="tool-section-label">2 · Review &amp; edit schema</div>

                <div className="field-grid">
                  <div className="field">
                    <label className="field-label">Tool name</label>
                    <input
                      className="tool-input mono"
                      value={toolName}
                      onChange={e => setToolName(e.target.value)}
                      placeholder="reserve_table"
                    />
                    <span className="tool-hint">lowercase snake_case</span>
                  </div>
                  <div className="field">
                    <label className="field-label">When to call it</label>
                    <textarea
                      className="tool-textarea tool-textarea--sm"
                      value={toolDescription}
                      onChange={e => setToolDescription(e.target.value)}
                      placeholder="when the caller wants to book a table"
                    />
                  </div>
                </div>

                <div className="field-label" style={{ marginTop: 14 }}>Parameters</div>
                {params.length === 0 && (
                  <div className="tool-hint" style={{ marginBottom: 8 }}>
                    No parameters — this tool takes no inputs. Add one if it needs any.
                  </div>
                )}
                <div className="param-list">
                  {params.map((p, i) => (
                    <div className="param-row" key={i}>
                      <input
                        className="tool-input mono"
                        placeholder="param_name"
                        value={p.name}
                        onChange={e => updateParam(i, { name: e.target.value })}
                      />
                      <select
                        className="tool-select"
                        value={p.type}
                        onChange={e => updateParam(i, { type: e.target.value })}
                      >
                        {PARAM_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                      <input
                        className="tool-input"
                        placeholder="description"
                        value={p.description}
                        onChange={e => updateParam(i, { description: e.target.value })}
                      />
                      <label className="param-required">
                        <input
                          type="checkbox"
                          checked={p.required}
                          onChange={e => updateParam(i, { required: e.target.checked })}
                        />
                        required
                      </label>
                      <button
                        className="icon-btn"
                        onClick={() => removeParam(i)}
                        aria-label="Remove parameter"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
                <button className="btn btn-ghost btn-sm" onClick={addParam}>
                  <Plus size={14} /> Add parameter
                </button>
              </div>

              {/* Step 3 — endpoint + auth */}
              <div className="tool-section">
                <div className="tool-section-label">3 · Endpoint &amp; authentication</div>

                <div className="field-grid">
                  <div className="field field--wide">
                    <label className="field-label">Endpoint URL</label>
                    <div className="input-with-icon">
                      <Link2 size={14} />
                      <input
                        className="tool-input"
                        placeholder="https://api.example.com/bookings"
                        value={endpointUrl}
                        onChange={e => setEndpointUrl(e.target.value)}
                      />
                    </div>
                    <span className="tool-hint">Public http/https host only</span>
                  </div>
                  <div className="field">
                    <label className="field-label">Method</label>
                    <select
                      className="tool-select"
                      value={httpMethod}
                      onChange={e => setHttpMethod(e.target.value)}
                    >
                      {HTTP_METHODS.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </div>
                </div>

                <div className="field-grid" style={{ marginTop: 14 }}>
                  <div className="field">
                    <label className="field-label">Auth type</label>
                    <select
                      className="tool-select"
                      value={authType}
                      onChange={e => setAuthType(e.target.value)}
                    >
                      {AUTH_TYPES.map(a => (
                        <option key={a.value} value={a.value}>{a.label}</option>
                      ))}
                    </select>
                  </div>
                  {authType !== 'none' && (
                    <div className="field">
                      <label className="field-label">
                        {authType === 'bearer' ? 'Bearer token' : 'API key'}
                      </label>
                      <input
                        className="tool-input"
                        type="password"
                        placeholder={
                          editingTool
                            ? 'Leave blank to keep the existing one'
                            : 'Stored encrypted, never returned'
                        }
                        value={authCredential}
                        onChange={e => setAuthCredential(e.target.value)}
                      />
                    </div>
                  )}
                  {authType === 'api_key_header' && (
                    <div className="field">
                      <label className="field-label">Header name</label>
                      <input
                        className="tool-input mono"
                        placeholder="X-API-Key"
                        value={authHeaderName}
                        onChange={e => setAuthHeaderName(e.target.value)}
                      />
                      <span className="tool-hint">Defaults to X-API-Key</span>
                    </div>
                  )}
                </div>

                <label className="confirm-toggle">
                  <input
                    type="checkbox"
                    checked={requiresConfirmation}
                    onChange={e => setRequiresConfirmation(e.target.checked)}
                  />
                  <span>
                    <strong>Require spoken confirmation</strong>
                    <span className="tool-hint">
                      Agent reads the details back and waits for the caller to confirm before running
                    </span>
                  </span>
                </label>
              </div>

              {saveError && (
                <div className="form-error">
                  <AlertCircle size={14} /> {saveError}
                </div>
              )}

              <div className="form-actions">
                <button className="btn btn-ghost" onClick={closeForm}>Cancel</button>
                <button className="btn btn-primary" onClick={handleSave} disabled={saveDisabled}>
                  {saving
                    ? <><div className="spinner" style={{ width: 14, height: 14 }} /> Saving…</>
                    : <><Save size={14} /> Save Tool</>}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Configured tools list ────────────────────── */}
      <div className="card" style={{ padding: 0, marginTop: 24 }}>
        <div className="doc-list-header tool-list-header">
          <span>Configured Tools</span>
          <button className="btn btn-ghost btn-sm" onClick={loadTools}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>

        {loading ? (
          <div className="tool-empty"><div className="spinner" /></div>
        ) : tools.length === 0 ? (
          <div className="tool-empty">
            <Wrench size={32} color="var(--text-muted)" />
            <p>No tools configured yet.</p>
            <p className="tool-hint">Create one above to let your agent take actions on calls.</p>
          </div>
        ) : (
          <div className="tool-list">
            {tools.map(t => (
              <div key={t.id} className="tool-item">
                <div className="tool-item__icon"><Wrench size={16} /></div>
                <div className="tool-item__info">
                  <div className="tool-item__top">
                    <span className="tool-item__name mono">{t.name}</span>
                    <span className={`badge ${t.requires_confirmation ? 'badge-warning' : 'badge-success'}`}>
                      {t.requires_confirmation
                        ? <><ShieldAlert size={11} /> Confirmation</>
                        : <><ShieldCheck size={11} /> Auto-run</>}
                    </span>
                  </div>
                  <span className="tool-item__desc">{t.description}</span>
                  <span className="tool-item__endpoint mono">
                    <span className="badge badge-blue">{t.http_method}</span>
                    {t.endpoint_url}
                  </span>
                </div>
                {isAdmin && (
                  <div className="tool-item__actions">
                    <button
                      className="icon-btn"
                      onClick={() => startEdit(t)}
                      aria-label={`Edit ${t.name}`}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      className="icon-btn"
                      onClick={() => handleDelete(t)}
                      disabled={deletingId === t.id}
                      aria-label={`Deactivate ${t.name}`}
                    >
                      {deletingId === t.id
                        ? <div className="spinner" style={{ width: 14, height: 14 }} />
                        : <Trash2 size={14} />}
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
