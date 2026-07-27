import { useEffect, useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  Upload, FileText, Trash2, CheckCircle,
  AlertCircle, BookOpen, Layers, RefreshCw
} from 'lucide-react'
import { fetchDocuments, uploadDocument, deleteDocument } from '../services/api'
import { useAuth } from '../context/AuthContext'
import './Knowledge.css'

function FileIcon({ type }) {
  return (
    <div className="file-icon">
      <FileText size={18} />
      <span className="file-ext">{type?.replace('.', '').toUpperCase()}</span>
    </div>
  )
}

export default function Knowledge() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'  // server enforces too; this is just UI
  const [docs, setDocs] = useState([])
  const [totalChunks, setTotalChunks] = useState(0)
  const [loading, setLoading] = useState(true)
  const [uploads, setUploads] = useState([])  // { name, progress, status, error }
  const [deleting, setDeleting] = useState(null)

  const loadDocs = () => {
    setLoading(true)
    fetchDocuments()
      .then(data => {
        setDocs(data.files || [])
        setTotalChunks(data.total_chunks || 0)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadDocs() }, [])

  const onDrop = useCallback((acceptedFiles) => {
    acceptedFiles.forEach(file => {
      const entry = { name: file.name, progress: 0, status: 'uploading', error: null }
      setUploads(prev => [...prev, entry])

      uploadDocument(file, (progress) => {
        setUploads(prev => prev.map(u =>
          u.name === file.name ? { ...u, progress } : u
        ))
      })
        .then(() => {
          setUploads(prev => prev.map(u =>
            u.name === file.name ? { ...u, status: 'done', progress: 100 } : u
          ))
          loadDocs()
          // Clear done entries after 3s
          setTimeout(() => {
            setUploads(prev => prev.filter(u => u.name !== file.name))
          }, 3000)
        })
        .catch(err => {
          setUploads(prev => prev.map(u =>
            u.name === file.name
              ? { ...u, status: 'error', error: err.response?.data?.detail || 'Upload failed' }
              : u
          ))
        })
    })
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
    },
    multiple: true,
  })

  const handleDelete = async (filename) => {
    if (!confirm(`Delete "${filename}" from the knowledge base?`)) return
    setDeleting(filename)
    try {
      await deleteDocument(filename)
      loadDocs()
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Knowledge Base</h1>
          <p className="page-subtitle">Upload documents to power your AI agent's responses</p>
        </div>
        <button className="btn btn-ghost" onClick={loadDocs}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Stats strip */}
      <div className="kb-stats">
        <div className="kb-stat">
          <BookOpen size={16} color="var(--accent)" />
          <span><strong>{docs.length}</strong> Documents</span>
        </div>
        <div className="kb-stat-divider" />
        <div className="kb-stat">
          <Layers size={16} color="var(--accent)" />
          <span><strong>{totalChunks.toLocaleString()}</strong> Vector Chunks</span>
        </div>
      </div>

      {/* Dropzone — admins only; members have read-only access */}
      {isAdmin && (
        <div
          {...getRootProps()}
          className={`dropzone ${isDragActive ? 'dropzone--active' : ''}`}
        >
          <input {...getInputProps()} />
          <div className="dropzone-icon">
            <Upload size={24} />
          </div>
          <div className="dropzone-text">
            {isDragActive
              ? 'Drop files here...'
              : 'Drag & drop files here, or click to browse'}
          </div>
          <div className="dropzone-hint">Supports PDF, TXT, and Markdown files</div>
        </div>
      )}

      {/* Upload queue */}
      {uploads.length > 0 && (
        <div className="upload-queue">
          {uploads.map((u, i) => (
            <div key={i} className={`upload-item upload-item--${u.status}`}>
              <FileText size={14} />
              <div className="upload-item__info">
                <span className="upload-item__name">{u.name}</span>
                {u.status === 'uploading' && (
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${u.progress}%` }} />
                  </div>
                )}
                {u.status === 'error' && (
                  <span className="upload-item__error">{u.error}</span>
                )}
              </div>
              {u.status === 'done' && <CheckCircle size={15} color="var(--success)" />}
              {u.status === 'error' && <AlertCircle size={15} color="var(--danger)" />}
              {u.status === 'uploading' && (
                <span className="upload-item__pct">{u.progress}%</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Document list */}
      <div className="card" style={{ padding: 0, marginTop: 24 }}>
        <div className="doc-list-header">
          <span>Uploaded Documents</span>
        </div>

        {loading ? (
          <div className="doc-empty"><div className="spinner" /></div>
        ) : docs.length === 0 ? (
          <div className="doc-empty">
            <BookOpen size={32} color="var(--text-muted)" />
            <p>No documents uploaded yet.</p>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              Upload a PDF or text file to get started.
            </p>
          </div>
        ) : (
          <div className="doc-list">
            {docs.map((filename, i) => {
              const ext = '.' + filename.split('.').pop()
              return (
                <div key={i} className="doc-item">
                  <FileIcon type={ext} />
                  <div className="doc-item__info">
                    <span className="doc-item__name">{filename}</span>
                    <span className="doc-item__ext badge badge-blue">{ext.replace('.', '').toUpperCase()}</span>
                  </div>
                  {isAdmin && (
                    <button
                      className="btn btn-danger"
                      onClick={() => handleDelete(filename)}
                      disabled={deleting === filename}
                    >
                      {deleting === filename
                        ? <div className="spinner" style={{ width: 14, height: 14 }} />
                        : <Trash2 size={14} />}
                      Delete
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
