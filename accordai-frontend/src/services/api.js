import axios from 'axios'

// JWT session token. Tenant context is derived server-side from this token —
// the old hardcoded client_id query param is gone.
const TOKEN_KEY = 'accordai_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

// Backend location. In dev this stays '/api' and the Vite proxy forwards it
// to localhost:8000. In production (Vercel) there is no proxy — set
// VITE_API_BASE_URL to the backend's public origin (e.g. the ngrok URL),
// with no trailing slash and no /api suffix (backend routes are unprefixed).
const API_BASE = import.meta.env?.VITE_API_BASE_URL || '/api'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  // ngrok's free tier intercepts browser-looking requests with an HTML warning
  // page unless this header is present. Harmless for non-ngrok backends.
  config.headers['ngrok-skip-browser-warning'] = 'true'
  return config
})

// Expired or invalid session → clear it and return to login, unless we're
// already on a public page (landing/login/signup handle their own state).
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      clearToken()
      const path = window.location.pathname
      if (!['/', '/login', '/signup'].includes(path)) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

// ── Auth ──────────────────────────────────────────────────
export const apiSignup = (payload) =>
  api.post('/auth/signup', payload).then(r => r.data)

export const apiLogin = (email, password) =>
  api.post('/auth/login', { email, password }).then(r => r.data)

export const fetchMe = () =>
  api.get('/auth/me').then(r => r.data)

// ── Account / Settings ────────────────────────────────────
export const fetchTenant = () =>
  api.get('/account/tenant').then(r => r.data)

export const updateTwilioNumber = (twilioNumber) =>
  api.patch('/account/twilio-number', { twilio_number: twilioNumber }).then(r => r.data)

export const changePassword = (currentPassword, newPassword) =>
  api.post('/account/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  }).then(r => r.data)

// ── Analytics ─────────────────────────────────────────────
export const fetchDashboard = () =>
  api.get('/analytics/dashboard').then(r => r.data)

export const fetchCalls = (skip = 0, limit = 20) =>
  api.get(`/analytics/calls?skip=${skip}&limit=${limit}`).then(r => r.data)

export const fetchTranscript = (callSid) =>
  api.get(`/analytics/calls/${callSid}/transcript`).then(r => r.data)

// ── Documents ─────────────────────────────────────────────
export const fetchDocuments = () =>
  api.get('/documents/list').then(r => r.data)

export const uploadDocument = (file, onProgress) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
    }
  }).then(r => r.data)
}

export const deleteDocument = (filename) =>
  api.delete(`/documents/delete/${encodeURIComponent(filename)}`).then(r => r.data)

// ── Tools ─────────────────────────────────────────────────
export const generateToolSchema = (description) =>
  api.post('/tools/generate-schema', { description }).then(r => r.data)

export const createTool = (payload) =>
  api.post('/tools/create', payload).then(r => r.data)

export const updateTool = (toolId, payload) =>
  api.patch('/tools/update', payload, { params: { tool_id: toolId } }).then(r => r.data)

export const deleteTool = (toolId) =>
  api.delete(`/tools/delete/${toolId}`).then(r => r.data)

export const fetchTools = () =>
  api.get('/tools/list').then(r => r.data)

export default api
