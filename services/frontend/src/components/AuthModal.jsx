import React, { useState } from 'react'
import { Network, Eye, EyeOff, Loader2 } from 'lucide-react'
import useStore from '../store/useStore'
import './AuthModal.css'

export default function AuthModal() {
  const { login, register, authLoading, authError } = useStore()
  const [tab, setTab]             = useState('login')  // 'login' | 'register'
  const [username, setUsername]   = useState('')
  const [password, setPassword]   = useState('')
  const [email, setEmail]         = useState('')
  const [showPass, setShowPass]   = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (tab === 'login') {
      await login(username, password)
    } else {
      await register(username, password, email)
    }
  }

  return (
    <div className="auth-overlay">
      <div className="auth-modal animate-fade-in">
        {/* Logo */}
        <div className="auth-logo">
          <div className="auth-logo-icon">
            <Network size={24} />
          </div>
          <div>
            <div className="auth-logo-name">MIND<span>MAP</span> AI</div>
            <div className="auth-logo-sub font-mono">Distributed Knowledge Graph Engine</div>
          </div>
        </div>

        {/* Tabs */}
        <div className="auth-tabs">
          <button
            className={`auth-tab ${tab === 'login' ? 'active' : ''}`}
            onClick={() => setTab('login')}
            type="button"
          >
            Sign In
          </button>
          <button
            className={`auth-tab ${tab === 'register' ? 'active' : ''}`}
            onClick={() => setTab('register')}
            type="button"
          >
            Create Account
          </button>
        </div>

        {/* Form */}
        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="auth-field">
            <label className="auth-label font-mono">USERNAME</label>
            <input
              className="auth-input"
              type="text"
              placeholder="Enter your username"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoComplete="username"
              required
              minLength={3}
            />
          </div>

          {tab === 'register' && (
            <div className="auth-field">
              <label className="auth-label font-mono">EMAIL <span className="auth-optional">(optional)</span></label>
              <input
                className="auth-input"
                type="email"
                placeholder="your@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                autoComplete="email"
              />
            </div>
          )}

          <div className="auth-field">
            <label className="auth-label font-mono">PASSWORD</label>
            <div className="auth-pass-wrap">
              <input
                className="auth-input"
                type={showPass ? 'text' : 'password'}
                placeholder={tab === 'register' ? 'Min 6 characters' : 'Enter your password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete={tab === 'register' ? 'new-password' : 'current-password'}
                required
                minLength={6}
              />
              <button
                type="button"
                className="auth-pass-toggle"
                onClick={() => setShowPass(!showPass)}
                tabIndex={-1}
              >
                {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          {authError && (
            <div className="auth-error animate-fade-in">{authError}</div>
          )}

          <button
            className="auth-submit"
            type="submit"
            disabled={authLoading}
          >
            {authLoading ? (
              <><Loader2 size={14} className="animate-spin" /> {tab === 'login' ? 'Signing in…' : 'Creating account…'}</>
            ) : (
              tab === 'login' ? 'Sign In' : 'Create Account'
            )}
          </button>
        </form>

        {/* Ambient feature bullets */}
        <div className="auth-features">
          <div className="auth-feature-item font-mono">⬡ Distributed multi-agent pipeline</div>
          <div className="auth-feature-item font-mono">⬡ ReAct + Critic knowledge extraction</div>
          <div className="auth-feature-item font-mono">⬡ 10 graphs stored per account</div>
        </div>
      </div>
    </div>
  )
}
