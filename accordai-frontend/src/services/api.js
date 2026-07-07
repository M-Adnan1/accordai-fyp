import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

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

export default api
