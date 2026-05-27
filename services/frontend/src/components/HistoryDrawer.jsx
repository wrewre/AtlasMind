import React from 'react'
import { X, Clock, FileText, Trash2, ExternalLink, Loader2, GitBranch, Network } from 'lucide-react'
import useStore from '../store/useStore'
import './HistoryDrawer.css'

const MAX_DOCS = 10

export default function HistoryDrawer() {
  const {
    isHistoryOpen, setHistoryOpen,
    history, isLoadingHistory,
    loadFromHistory, deleteFromHistory,
  } = useStore()

  if (!isHistoryOpen) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="drawer-backdrop"
        onClick={() => setHistoryOpen(false)}
      />

      {/* Drawer panel */}
      <aside className="history-drawer animate-slide-in-right">
        <div className="drawer-header">
          <div className="drawer-title">
            <Clock size={16} />
            <span>Document History</span>
          </div>
          <div className="drawer-subtitle font-mono">
            {history.length}/{MAX_DOCS} graphs stored
          </div>
          <button
            className="drawer-close"
            onClick={() => setHistoryOpen(false)}
          >
            <X size={16} />
          </button>
        </div>

        {/* Progress bar showing history usage */}
        <div className="history-usage">
          <div
            className="history-usage-bar"
            style={{ width: `${(history.length / MAX_DOCS) * 100}%` }}
          />
        </div>

        <div className="drawer-body">
          {isLoadingHistory ? (
            <div className="drawer-loading">
              <Loader2 size={20} className="animate-spin" />
              <span>Loading history…</span>
            </div>
          ) : history.length === 0 ? (
            <div className="drawer-empty">
              <div className="drawer-empty-icon">
                <GitBranch size={28} />
              </div>
              <div className="drawer-empty-title">No documents yet</div>
              <div className="drawer-empty-sub font-mono">
                Upload a document to start building knowledge graphs
              </div>
            </div>
          ) : (
            <div className="history-list">
              {history.map((doc, i) => (
                <HistoryItem
                  key={doc.document_id}
                  doc={doc}
                  index={i}
                  onLoad={() => loadFromHistory(doc.document_id, doc.filename)}
                  onDelete={() => deleteFromHistory(doc.document_id)}
                />
              ))}
            </div>
          )}
        </div>

        <div className="drawer-footer font-mono">
          Oldest graph auto-deleted when limit reached
        </div>
      </aside>
    </>
  )
}

function HistoryItem({ doc, index, onLoad, onDelete }) {
  const [deleting, setDeleting] = React.useState(false)
  const date = doc.processed_at || doc.created_at
  const displayDate = date ? new Date(date).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }) : 'Processing…'

  const handleDelete = async (e) => {
    e.stopPropagation()
    setDeleting(true)
    await onDelete()
    setDeleting(false)
  }

  return (
    <div
      className="history-item"
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <div className="history-item-icon">
        <FileText size={14} />
      </div>

      <div className="history-item-body">
        <div className="history-item-name">{doc.filename}</div>
        <div className="history-item-date font-mono">{displayDate}</div>
        {(doc.node_count > 0 || doc.edge_count > 0) && (
          <div className="history-item-stats font-mono">
            <span className="hist-stat nodes">{doc.node_count} nodes</span>
            <span className="hist-stat edges">{doc.edge_count} edges</span>
          </div>
        )}
        {doc.summary_snippet && (
          <div className="history-item-summary">{doc.summary_snippet}</div>
        )}
      </div>

      <div className="history-item-actions">
        <button
          className="hist-btn open-btn"
          onClick={onLoad}
          title="Open graph"
        >
          <ExternalLink size={13} />
        </button>
        <button
          className="hist-btn delete-btn"
          onClick={handleDelete}
          disabled={deleting}
          title="Remove from history"
        >
          {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
        </button>
      </div>
    </div>
  )
}
