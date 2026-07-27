import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()

  // Don't bounce to /login while the session restore is still in flight.
  if (loading) {
    return (
      <div style={{
        height: '100vh', display: 'flex',
        alignItems: 'center', justifyContent: 'center',
        color: 'var(--text-secondary)',
      }}>
        Loading…
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return children
}