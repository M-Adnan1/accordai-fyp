import { Link } from 'react-router-dom'
import {
  Zap, PhoneCall, BookOpen, Wrench, BarChart3, ShieldCheck, ArrowRight,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import './Landing.css'

const FEATURES = [
  {
    icon: PhoneCall,
    title: '24/7 AI Voice Agent',
    text: 'An AI receptionist answers every call to your business number — natural conversation, instant answers, no hold music.',
  },
  {
    icon: BookOpen,
    title: 'Your Knowledge, Its Answers',
    text: 'Upload your policies, FAQs, and menus. The agent answers from your documents, not generic guesses.',
  },
  {
    icon: Wrench,
    title: 'Real Actions, Not Just Talk',
    text: 'Connect your booking or ordering API and the agent takes reservations and checks availability mid-call — with spoken confirmation.',
  },
  {
    icon: BarChart3,
    title: 'Every Call, Measured',
    text: 'Transcripts, satisfaction ratings, resolution tracking, and response-time analytics in one dashboard.',
  },
]

export default function Landing() {
  const { user } = useAuth()

  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="landing-nav-inner">
          <div className="landing-logo">
            <div className="logo-icon"><Zap size={18} /></div>
            <span className="logo-name">AccordAI</span>
          </div>
          <nav className="landing-nav-actions">
            {user ? (
              <Link className="btn btn-primary" to="/dashboard">
                Open Dashboard <ArrowRight size={15} />
              </Link>
            ) : (
              <>
                <Link className="btn btn-ghost" to="/login">Sign in</Link>
                <Link className="btn btn-primary" to="/signup">Get started</Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="hero-badge">
            <ShieldCheck size={14} />
            <span>Multi-tenant voice AI for small businesses</span>
          </div>
          <h1>
            Your phone line,<br />
            <span className="hero-accent">answered by AI.</span>
          </h1>
          <p className="hero-sub">
            AccordAI turns your business number into an intelligent voice agent that
            answers questions from your own knowledge base, books appointments through
            your systems, and reports on every conversation.
          </p>
          <div className="hero-ctas">
            <Link className="btn btn-primary btn-lg" to={user ? '/dashboard' : '/signup'}>
              {user ? 'Open Dashboard' : 'Create your agent'} <ArrowRight size={16} />
            </Link>
            {!user && (
              <Link className="btn btn-ghost btn-lg" to="/login">
                I already have an account
              </Link>
            )}
          </div>
        </section>

        <section className="landing-features">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div className="feature-card" key={title}>
              <div className="feature-icon"><Icon size={20} /></div>
              <h3>{title}</h3>
              <p>{text}</p>
            </div>
          ))}
        </section>

        <section className="landing-cta">
          <h2>Set up your AI receptionist in minutes.</h2>
          <p>Create an account, upload your documents, connect your tools — done.</p>
          <Link className="btn btn-primary btn-lg" to={user ? '/dashboard' : '/signup'}>
            {user ? 'Open Dashboard' : 'Get started free'} <ArrowRight size={16} />
          </Link>
        </section>
      </main>

      <footer className="landing-footer">
        <span>AccordAI — Final Year Project</span>
      </footer>
    </div>
  )
}