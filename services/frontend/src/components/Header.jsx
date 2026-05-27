import React from 'react'
import { Network, RotateCcw, Clock, LogOut, User, Download } from 'lucide-react'
import useStore from '../store/useStore'
import ExportPanel from './ExportPanel'
import './Header.css'

export default function Header() {
  const {
    activeView, resetToUpload, fileName, graph,
    user, isAuthenticated, logout,
    setHistoryOpen, isHistoryOpen, fetchHistory,
  } = useStore()

  const handleHistoryClick = () => {
    fetchHistory()
    setHistoryOpen(true)
  }

  return (
    <header className="header">
      <div className="header-left">
        <div className="header-logo">
          <Network size={20} className="logo-icon" />
          <span className="logo-text">MIND<span className="logo-accent">MAP</span></span>
          <span className="logo-tag">AI</span>
        </div>
        <div className="header-subtitle">Distributed Multi-Agent Knowledge Graph Generator</div>
      </div>

      <div className="header-center">
        {activeView !== 'upload' && (
          <div className="pipeline-indicator">
            <PipelineStep label="INGEST"    active={true} />
            <div className="pipe-line" />
            <PipelineStep label="CHUNK"     active={activeView !== 'upload'} />
            <div className="pipe-line" />
            <PipelineStep label="AGENT"     active={activeView === 'graph'} />
            <div className="pipe-line" />
            <PipelineStep label="CONSENSUS" active={activeView === 'graph'} />
            <div className="pipe-line" />
            <PipelineStep label="GRAPH"     active={activeView === 'graph'} done />
          </div>
        )}
      </div>

      <div className="header-right">
        {fileName && (
          <span className="header-filename font-mono">{fileName}</span>
        )}
        {graph && (
          <div className="header-stats">
            <span className="stat-chip">{graph.nodes?.length ?? 0} nodes</span>
            <span className="stat-chip">{graph.edges?.length ?? 0} edges</span>
          </div>
        )}

        {/* Export button — only when graph is loaded */}
        {graph && <ExportPanel />}

        {/* History button */}
        {isAuthenticated && (
          <button
            className="header-icon-btn"
            onClick={handleHistoryClick}
            title="Document History"
          >
            <Clock size={15} />
          </button>
        )}

        {/* New document button */}
        {activeView !== 'upload' && (
          <button className="btn-reset" onClick={resetToUpload} title="New document">
            <RotateCcw size={15} />
            <span>New</span>
          </button>
        )}

        {/* User info + logout */}
        {isAuthenticated && (
          <div className="header-user">
            <div className="user-avatar">
              <User size={12} />
            </div>
            <span className="user-name font-mono">{user?.username}</span>
            <button className="header-icon-btn logout-btn" onClick={logout} title="Sign out">
              <LogOut size={13} />
            </button>
          </div>
        )}
      </div>
    </header>
  )
}

function PipelineStep({ label, active, done }) {
  return (
    <div className={`pipe-step ${active ? 'active' : ''} ${done ? 'done' : ''}`}>
      <div className="pipe-dot" />
      <span className="pipe-label">{label}</span>
    </div>
  )
}
