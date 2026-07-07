import { useEffect, useState } from 'react'
import { PhoneIncoming, ChevronLeft, ChevronRight, ThumbsUp, ThumbsDown, Minus } from 'lucide-react'
import { fetchCalls } from '../services/api'
import TranscriptModal from '../components/calls/TranscriptModal'
import { format } from 'date-fns'
import './Calls.css'

const STATUS_BADGE = {
  completed:   'badge-success',
  in_progress: 'badge-blue',
  initiated:   'badge-warning',
  failed:      'badge-danger',
}

function RatingIcon({ rating }) {
  if (rating === 1) return <ThumbsUp size={13} color="var(--success)" />
  if (rating === 0) return <ThumbsDown size={13} color="var(--danger)" />
  return <Minus size={13} color="var(--text-muted)" />
}

export default function Calls() {
  const [calls, setCalls] = useState([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  const [selectedSid, setSelectedSid] = useState(null)
  const limit = 20

  useEffect(() => {
    setLoading(true)
    fetchCalls(page * limit, limit)
      .then(setCalls)
      .finally(() => setLoading(false))
  }, [page])

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Call History</h1>
          <p className="page-subtitle">Browse and review all customer interactions</p>
        </div>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Caller</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Messages</th>
                <th>Rating</th>
                <th>Resolved</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="table-empty"><div className="spinner" /></td></tr>
              ) : calls.length === 0 ? (
                <tr><td colSpan={7} className="table-empty">No calls recorded yet</td></tr>
              ) : calls.map(call => (
                <tr key={call.call_sid} onClick={() => setSelectedSid(call.call_sid)}>
                  <td>
                    <div className="caller-cell">
                      <div className="caller-avatar">
                        <PhoneIncoming size={13} />
                      </div>
                      <div>
                        <div className="caller-number mono">{call.from_number}</div>
                        {call.customer_name && (
                          <div className="caller-name">{call.customer_name}</div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className={`badge ${STATUS_BADGE[call.status] || 'badge-blue'}`}>
                      {call.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="mono">
                    {call.duration ? `${call.duration}s` : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                  </td>
                  <td className="mono">{call.total_messages}</td>
                  <td><RatingIcon rating={call.satisfaction_rating} /></td>
                  <td>
                    <span className={`badge ${call.resolved ? 'badge-success' : 'badge-warning'}`}>
                      {call.resolved ? 'Yes' : 'No'}
                    </span>
                  </td>
                  <td style={{ color: 'var(--text-secondary)' }}>
                    {call.created_at
                      ? format(new Date(call.created_at), 'MMM d, HH:mm')
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="pagination">
          <span className="pagination-info">
            Showing {page * limit + 1}–{page * limit + calls.length}
          </span>
          <div className="pagination-btns">
            <button
              className="btn btn-ghost"
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              <ChevronLeft size={15} /> Prev
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => setPage(p => p + 1)}
              disabled={calls.length < limit}
            >
              Next <ChevronRight size={15} />
            </button>
          </div>
        </div>
      </div>

      {selectedSid && (
        <TranscriptModal
          callSid={selectedSid}
          onClose={() => setSelectedSid(null)}
        />
      )}
    </div>
  )
}
