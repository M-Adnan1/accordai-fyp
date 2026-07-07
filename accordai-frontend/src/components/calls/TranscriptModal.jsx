import { useEffect, useState } from 'react'
import { X, User, Bot, Clock, Phone } from 'lucide-react'
import { fetchTranscript } from '../../services/api'
import './TranscriptModal.css'

export default function TranscriptModal({ callSid, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchTranscript(callSid)
      .then(setData)
      .finally(() => setLoading(false))

    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [callSid])

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title-group">
            <h2 className="modal-title">Call Transcript</h2>
            <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 11 }}>{callSid}</span>
          </div>
          <button className="modal-close" onClick={onClose}><X size={18} /></button>
        </div>

        {loading ? (
          <div className="modal-loading"><div className="spinner" /></div>
        ) : data?.error ? (
          <div className="modal-loading" style={{ color: 'var(--danger)' }}>Call not found</div>
        ) : (
          <>
            <div className="modal-meta">
              <div className="meta-item">
                <Phone size={13} />
                <span>{data.from_number}</span>
              </div>
              <div className="meta-item">
                <Clock size={13} />
                <span>{data.duration ? `${data.duration}s` : 'N/A'}</span>
              </div>
              <div className="meta-item">
                <span className={`badge ${data.resolved ? 'badge-success' : 'badge-warning'}`}>
                  {data.resolved ? 'Resolved' : 'Unresolved'}
                </span>
              </div>
              {data.satisfaction_rating !== null && data.satisfaction_rating !== undefined && (
                <div className="meta-item">
                  <span className={`badge ${data.satisfaction_rating === 1 ? 'badge-success' : 'badge-danger'}`}>
                    {data.satisfaction_rating === 1 ? '👍 Satisfied' : '👎 Not Satisfied'}
                  </span>
                </div>
              )}
            </div>

            {data.summary && (
              <div className="modal-summary">
                <div className="summary-label">AI Summary</div>
                <p>{data.summary}</p>
              </div>
            )}

            <div className="transcript">
              {data.messages?.length === 0 && (
                <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 32 }}>
                  No messages recorded
                </div>
              )}
              {data.messages?.map((msg, i) => (
                <div key={i} className={`transcript-msg transcript-msg--${msg.role}`}>
                  <div className="transcript-msg__avatar">
                    {msg.role === 'user' ? <User size={13} /> : <Bot size={13} />}
                  </div>
                  <div className="transcript-msg__body">
                    <div className="transcript-msg__header">
                      <span className="transcript-msg__name">
                        {msg.role === 'user' ? 'Caller' : 'AccordAI'}
                      </span>
                      {msg.response_time_ms && (
                        <span className="transcript-msg__time">{msg.response_time_ms}ms</span>
                      )}
                    </div>
                    <p className="transcript-msg__content">{msg.content}</p>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
